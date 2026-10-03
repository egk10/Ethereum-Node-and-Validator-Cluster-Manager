#!/usr/bin/env python3
"""Explicit, single-source 1.39.3 -> 2.1.0 Patricia pilot; never resyncs."""
from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import re
import shlex
import sys
import time
from pathlib import Path

from gestaobot_client import Client

spec = importlib.util.spec_from_file_location(
    "cluster_maintenance", Path(__file__).with_name("cluster-maintenance.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

FROM_VERSION = "1.39.3"
TO_VERSION = "2.1.0"
# Official 2.1.0 Linux/amd64 manifest, checked against Docker Hub before the pilot.
BASE_DIGEST = "sha256:7c9312419b9cd7596b9c687ad06f1b7435b321cc0c80719909bc5a3c78876ae2"

AUDIT = r'''
import hashlib, json, pathlib, re, shlex, subprocess, sys
def run(args):
    return subprocess.check_output(args, text=True, timeout=60)
def require(value, reason):
    if not value: raise RuntimeError(reason)
require(not run(['git','status','--porcelain']).strip(), 'eth-docker worktree is dirty')
require(run(['uname','-m']).strip() == 'x86_64', 'pilot manifest is only for amd64')
c=json.loads(run(['docker','inspect','eth-docker-execution-1']))[0]
env=dict(x.split('=',1) for x in c['Config']['Env'] if '=' in x)
require(env.get('NETWORK') == 'mainnet', 'only stock mainnet config is reviewed')
require(env.get('NODE_TYPE') == 'pre-prague-expiry', 'node type is outside reviewed recipe')
require(not env.get('NM_FLATDB','').strip(), 'explicit FlatDB configuration needs review')
require(not env.get('ERE_URL','').strip(), 'EraE import is outside reviewed recipe')
require('grandine-plugin' not in env.get('COMPOSE_FILE',''), 'embedded plugin is outside recipe')
require(not any(k.upper().startswith('NETHERMIND_') for k in env), 'custom Nethermind env needs review')
require(not c['Config']['Cmd'], 'custom container command needs review')
allowed={'--HealthChecks.Enabled','--HealthChecks.UIEnabled','--LogIndex.Enabled','true','false'}
require(all(x in allowed for x in shlex.split(env.get('EL_EXTRAS',''))),
        'custom EL flags are outside reviewed recipe')
require(c['Config']['Entrypoint'][:2] == ['docker-entrypoint.sh','/nethermind/nethermind'],
        'non-stock entrypoint needs review')
require(all(x['Source'] == '/etc/localtime' for x in c['Mounts'] if x['Type']=='bind'),
        'custom bind-mounted configuration needs review')
mounts={x['Destination']:x for x in c['Mounts'] if x['Type']=='volume'}
require('/var/lib/nethermind' in mounts and '/var/lib/nethermind-og' in mounts,
        'expected Nethermind volumes are missing')
old=pathlib.Path(mounts['/var/lib/nethermind-og']['Source'])
selected=mounts['/var/lib/nethermind-og'] if (old/'nethermind_db').is_dir() else mounts['/var/lib/nethermind']
db=pathlib.Path(selected['Source'])/'nethermind_db/mainnet'
require(any((db/'state').rglob('*.sst')), 'existing Patricia state SST files not found')
if sys.argv[1] == 'before':
    require(not any((db/x).exists() for x in ('flat','flatHistory','persistedSnapshot')),
            'flat state detected; this recipe must not change its backend')
else:
    # 2.x probes the flat DB and may create unused empty column families. The
    # running process must explicitly confirm that the existing Patricia wins.
    logs=subprocess.run(['docker','logs','--since',c['State']['StartedAt'],'--tail','100000',c['Id']],
                        text=True,capture_output=True,timeout=60,check=True)
    text=re.sub(r'\x1b\[[0-9;]*m','',logs.stdout+logs.stderr)
    require('State backend: patricia (existing patricia state detected)' in text,
            'running 2.1.0 did not confirm preservation of existing Patricia state')
settings={}
for line in pathlib.Path('.env').read_text().splitlines():
    key,sep,value=line.partition('=')
    if sep: settings[key]=value.strip().strip('"').strip("'")
require(settings.get('NM_DOCKERFILE') == 'Dockerfile.binary', 'source build needs separate review')
require(settings.get('NM_DOCKER_REPO','nethermind/nethermind') in ('','nethermind/nethermind'),
        'custom Nethermind image repository needs review')
require(settings.get('NM_DOCKER_TAG') == 'latest', 'existing explicit image pin must be preserved')
print(json.dumps({'database_backend':'patricia','data_volume':selected['Name'],
                  'env_sha256':hashlib.sha256(pathlib.Path('.env').read_bytes()).hexdigest(),
                  'entrypoint_sha256':hashlib.sha256(pathlib.Path('nethermind/docker-entrypoint.sh').read_bytes()).hexdigest(),
                  'old_image_id':c['Image'],'old_container_id':c['Id'],
                  'database_path':str(db),'stock_mainnet':True,'custom_flags_reviewed':True}))
'''


def assert_version(probe: dict, version: str) -> None:
    raw = probe.get("ethd_version", "")
    found = re.search(m.CLIENT_PATTERNS["nethermind"], raw) if isinstance(raw, str) else None
    if found is None or found.group(1) != version:
        raise m.MaintenanceError("unexpected Nethermind version; expected " + version)


def candidate_id(candidate: dict) -> str:
    item = candidate.get("nethermind", {}) if isinstance(candidate, dict) else {}
    raw = item.get("version_output", "")
    found = re.search(r"(?m)^Version:\s*v?(\d+\.\d+\.\d+)", raw) if isinstance(raw, str) else None
    image_id = item.get("image_id", "")
    if found is None or found.group(1) != TO_VERSION or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise m.MaintenanceError("candidate is not exactly Nethermind " + TO_VERSION)
    return image_id


def assert_preserved(before: dict, after: dict, target: str) -> None:
    for name in m.NODES:
        required = ("eth-docker-execution-1", "eth-docker-consensus-1") if name in m.SOURCES else (
            "eth-docker-validator-1", "eth-docker-web3signer-1", "hyperdrive_sw_vc",
            "hyperdrive_sw_daemon", "hyperdrive_daemon")
        for container in required:
            if name == target and container == "eth-docker-execution-1":
                continue
            old = before[name]["containers"][container].get("image_id")
            new = after[name]["containers"][container].get("image_id")
            if not isinstance(old, str) or old != new:
                raise m.MaintenanceError(f"{name}/{container}: non-target image changed during pilot")
    for name, item in before["cloudvero"]["containers"].items():
        if name == "hyperdrive_sw_operator" or name.startswith("eth-lido-"):
            was_up = str(item.get("status", "")).startswith("Up")
            is_up = str(after["cloudvero"]["containers"].get(name, {}).get("status", "")).startswith("Up")
            if was_up != is_up:
                raise m.MaintenanceError(name + ": operator stop/start state changed")


class Pilot:
    def __init__(self, config, backend, bot, state, report, sleeper=time.sleep):
        self.config, self.backend, self.bot = config, backend, bot
        self.state, self.report, self.sleep = state, report, sleeper
        self.engine = m.Engine(config, backend, bot, state, sleeper)

    def phase(self, value: str, **details):
        self.report.value.update(phase=value, updated_at=m.now(), **details)
        self.report.save()
        self.state.value.update(phase="nethermind-pilot/" + value,
                                current={"node":self.report.value["node"], "kind":"nethermind-pilot",
                                         "report":str(self.report.path)})
        self.state.save()
        print(json.dumps({"phase":value,"node":self.report.value["node"]}), flush=True)

    def audit(self, node, after=False):
        script = "cd " + shlex.quote(node["workdir"]) + "\npython3 - " + ("after" if after else "before") + " <<'PY'\n" + AUDIT + "\nPY\n"
        return json.loads(self.backend._command(node, script, 180).stdout)

    def run(self, target: str):
        if self.state.value.get("status") in ("running", "blocked"):
            raise m.MaintenanceError("reconcile previous maintenance before pilot")
        node = self.config["nodes"][target]
        if target not in m.SOURCES or node["el"] != "nethermind":
            raise m.MaintenanceError("pilot requires one Nethermind source")
        before = self.engine.probe_all()
        issues = m.health(before, self.config)
        if issues or not m.source_quorum(before, self.config, target):
            raise m.MaintenanceError("pilot preflight health: " + "; ".join(issues))
        assert_version(before[target], FROM_VERSION)
        audited = self.audit(node)
        self.report.value = {"status":"running","node":target,"from":FROM_VERSION,"to":TO_VERSION,
                             "recipe":"stock-mainnet-patricia-inplace-v1","started_at":m.now(),
                             "base_digest":BASE_DIGEST,"audit":audited,"preflight":before}
        self.state.value.update(status="running", started_at=m.now())
        self.phase("preflight")
        applied = False
        try:
            self.engine.alert("Piloto Nethermind iniciando", target,
                "Atualização autorizada de 1.39.3 para 2.1.0. Somente execução neste nó; banco Patricia existente. "
                "Os outros quatro sources devem permanecer sincronizados e não otimistas.")
            prefix = "cd " + shlex.quote(node["workdir"]) + "\n"
            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            backup = ".env.bak.nethermind-pilot." + stamp
            old_tag = "nethermind:pilot-before-2.1.0-" + stamp
            self.phase("building", env_backup=backup, old_image_tag=old_tag)
            preparation = ("test -z \"$(git status --porcelain)\"\n"
                           + "cp -p .env " + shlex.quote(backup) + "\nchmod 600 " + shlex.quote(backup) + "\n"
                           + "docker tag " + shlex.quote(audited["old_image_id"]) + " " + shlex.quote(old_tag) + "\n"
                           + "ETHD_FRONTEND=noninteractive ./ethd cmd build --pull --build-arg "
                           + shlex.quote("DOCKER_TAG=" + TO_VERSION + "@" + BASE_DIGEST) + " execution\n")
            built = self.backend._command(node, prefix + preparation, 7200)
            self.report.value["build_output_tail"] = built.stdout[-2500:]
            self.phase("candidate-check")
            probe = "python3 - '[\"nethermind\"]' 0 <<'PY'\n" + m.CANDIDATE_PROBE + "\nPY\n"
            candidate = json.loads(self.backend._command(node, probe, 300).stdout)
            image_id = candidate_id(candidate)
            self.phase("before-apply", candidate_image_id=image_id)
            current = self.engine.probe_all()
            issues = m.health(current, self.config)
            if issues or not m.source_quorum(current, self.config, target):
                raise m.MaintenanceError("health changed before apply: " + "; ".join(issues))
            assert_preserved(before, current, target)
            if self.audit(node) != audited:
                raise m.MaintenanceError("live node/configuration changed after preflight")
            ids = {"nethermind":image_id}
            script = "python3 - " + shlex.quote(json.dumps(ids)) + " 0 <<'PY'\n" + m.TAG_ID_CHECK + "\nPY\n"
            self.phase("applying")
            self.backend._command(node, prefix + script
                                  + "ETHD_FRONTEND=noninteractive ./ethd cmd up -d --no-deps --no-build --pull never execution\n", 900)
            applied = True
            since = time.time()
            self.phase("postcheck", applied_epoch=since)
            after = self.engine.postcheck(target, since)
            assert_version(after[target], TO_VERSION)
            assert_preserved(before, after, target)
            if after[target]["containers"]["eth-docker-execution-1"].get("image_id") != image_id:
                raise m.MaintenanceError("running execution image differs from checked candidate")
            self.phase("observing", health_issues=[])
            # Catch a restart/optimism regression after the first recovered sample.
            for _ in range(3):
                self.sleep(60)
                after = self.engine.probe_all()
                issues = m.health(after, self.config, attestation_since=since)
                if issues:
                    raise m.MaintenanceError("pilot observation health: " + "; ".join(issues))
                assert_version(after[target], TO_VERSION)
                assert_preserved(before, after, target)
                self.phase("observing", last_sync={n:after[n]["sync"] for n in m.SOURCES})
            # The same data volume and unchanged .env are required; do not force a DB backend.
            audited_after = self.audit(node, after=True)
            for key in ("env_sha256", "entrypoint_sha256", "data_volume", "database_path", "database_backend"):
                if audited_after[key] != audited[key]:
                    raise m.MaintenanceError("pilot invariant changed: " + key)
            if int(after[target]['sync']['head_slot']) <= int(before[target]['sync']['head_slot']):
                raise m.MaintenanceError("pilot chain head did not advance during observation")
            self.report.value.update(status="complete", phase="complete", finished_at=m.now(),
                                     health_issues=[], inventory_after=after, audit_after=audited_after,
                                     fresh_attestations={x:m.published_after(after['cloudvero'],x,since) for x in
                                                         ('eth-docker-validator-1','hyperdrive_sw_vc')})
            self.report.save()
            self.state.value.update(status="pilot_complete", phase="nethermind-pilot/complete", finished_at=m.now(),
                                    last_pilot={"node":target,"from":FROM_VERSION,"to":TO_VERSION,"report":str(self.report.path)})
            self.state.value.pop("current", None)
            self.state.save()
            outcome = self.engine.alert("Piloto Nethermind concluído", target,
                "Nethermind 2.1.0 confirmado. Cinco sources sincronizados, não otimistas e com EL online; "
                "Vero e Hyperdrive publicaram novas atestações após a atualização. "
                "Banco e configuração preservados; nenhum outro cliente foi atualizado. "
                "O bloqueio de major deste nó foi resolvido pela versão observada. "
                "Hyperdrive e código eth-docker continuam exigindo seus próprios pilotos.")
            self.report.value["notification"] = outcome
            self.report.save()
            return {"status":"complete","node":target,"version":TO_VERSION,"report":str(self.report.path)}
        except Exception as exc:
            if self.report.value.get("status") == "complete":
                self.report.value["notification_error"] = str(exc)
            else:
                self.report.value.update(status="blocked", error=str(exc), applied=applied, failed_at=m.now())
                self.state.value.update(status="blocked", error=str(exc))
                self.state.save()
                try:
                    self.engine.alert("Piloto Nethermind interrompido", target, str(exc))
                except Exception as alert_error:
                    self.report.value["alert_error"] = str(alert_error)
            self.report.save()
            raise


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--node", choices=("minipcamd", "minipcamd3"), required=True)
    ap.add_argument("--run", action="store_true", help="execute the explicitly authorized one-node pilot")
    args = ap.parse_args(argv)
    try:
        config = m.checked_config(args.config)
        backend = m.Backend(config)
        state = m.State(Path(config["state_file"]))
        report = m.State(state.path.with_name("nethermind-pilot-" + args.node + ".json"))
        pilot = Pilot(config, backend, Client(), state, report)
        if not args.run:
            inventory = pilot.engine.probe_all()
            assert_version(inventory[args.node], FROM_VERSION)
            print(json.dumps({"health_issues":m.health(inventory, config),"audit":pilot.audit(config['nodes'][args.node]),
                              "target_version":TO_VERSION}))
            return 0 if not m.health(inventory, config) else 2
        lock = Path(config["lock_file"])
        lock.parent.mkdir(parents=True, exist_ok=True)
        with lock.open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Reload under the shared lock: the weekly worker may have changed
            # its durable status between process startup and lock acquisition.
            state = m.State(Path(config["state_file"]))
            report = m.State(state.path.with_name("nethermind-pilot-" + args.node + ".json"))
            pilot = Pilot(config, backend, Client(), state, report)
            print(json.dumps(pilot.run(args.node)), flush=True)
        return 0
    except Exception as exc:
        print("nethermind pilot: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

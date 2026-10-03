"""Stage official Eth Docker in a private worktree and preserve local overlays."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

MIN_ENV = 67
MAX_ENV = 72
UPSTREAM = "https://github.com/ethstaker/eth-docker.git"


def env_values(text):
    values = {}
    for line in text.splitlines():
        found = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", line)
        if found:
            key, value = found.groups()
            if key in values:
                raise ValueError("source review required: duplicate env key " + key)
            values[key] = value
    return values


def unquote(value):
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def migrate_env(original, defaults):
    old, new = env_values(original), env_values(defaults)
    before, after = int(unquote(old.get("ENV_VERSION", "0"))), int(new["ENV_VERSION"])
    if not MIN_ENV <= before <= after <= MAX_ENV:
        raise ValueError("source review required: unsupported env schema")
    if unquote(old.get("NETHERMIND_FLATDB", "")):
        raise ValueError("source review required: explicit FlatDB layout")
    if unquote(old.get("COMPOSE_PROFILES", "")):
        raise ValueError("source review required: enabled Compose profiles")
    replacements = {"ENV_VERSION": str(after)}
    # The official schema 72 migration preserves the former 'always' behavior.
    if before < 72 and re.fullmatch(r"0*100", unquote(old.get("EPBS_BUILD_FACTOR", ""))):
        replacements["EPBS_BUILD_FACTOR"] = "always"
    if unquote(old.get("NODE_EXPORTER_COLLECTOR_MOUNT_PATH", "")) == "/dev/null":
        replacements["NODE_EXPORTER_COLLECTOR_MOUNT_PATH"] = ""
    lines = []
    for line in original.splitlines():
        key = line.partition("=")[0]
        lines.append(key + "=" + replacements[key] if key in replacements else line)
    added = []
    for key, value in new.items():
        if key not in old:
            lines.append(key + "=" + value)
            added.append(key)
    result = "\n".join(lines) + "\n"
    final = env_values(result)
    if any(final.get(k) != v for k, v in old.items() if k not in replacements):
        raise ValueError("source review required: original settings changed")
    return result, {"schema_before": before, "schema_after": after,
                    "added_keys": added, "changed_keys": [k for k in replacements if old.get(k) != final[k]],
                    "original_settings_preserved": True}


def validate_compose(before, after, active):
    critical = {"execution", "consensus", "validator", "web3signer", "postgres"}
    for name in critical & set(active):
        a, b = before["services"][name], after["services"].get(name)
        if not b:
            raise ValueError("source review required: missing active service " + name)
        # No data, key, slashing-protection, networking or PostgreSQL migration.
        for key in ("volumes", "ports", "networks", "image", "user"):
            if a.get(key) != b.get(key):
                raise ValueError("source review required: " + name + "/" + key + " changed")
        ae, be = a.get("environment", {}), b.get("environment", {})
        protected = {k for k in set(ae) | set(be)
                     if any(word in k.upper() for word in ("SECRET", "PASSWORD", "TOKEN", "FEE", "KEY", "NODE", "JWT"))}
        for key in protected:
            if ae.get(key) != be.get(key):
                raise ValueError("source review required: " + name + "/protected setting " + key)
    if set(active) - set(after["services"]):
        raise ValueError("source review required: active service removed")


def prepare(workdir, revision, use_sudo=False, apply=True):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("invalid official revision")
    root = Path(workdir)
    docker = ["sudo", "-n", "docker"] if use_sudo else ["docker"]

    def run(args, cwd=root, timeout=180):
        p = subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=timeout,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        if p.returncode:
            raise RuntimeError(args[0] + " failed with exit " + str(p.returncode))
        return p.stdout.strip()

    if run(["git", "status", "--porcelain"]):
        raise ValueError("source review required: worktree dirty")
    env_stat = (root / ".env").stat()
    original = (root / ".env").read_text()
    old_env = env_values(original)
    if unquote(old_env.get("NETWORK", "")) != "mainnet":
        raise ValueError("source review required: network outside mainnet")
    if unquote(old_env.get("COMPOSE_FILE", "")) != "${CORE_FILES}${CUSTOM_FILES:+:${CUSTOM_FILES}}":
        raise ValueError("source review required: custom Compose indirection")
    if unquote(old_env.get("COMPOSE_PROJECT_NAME", "")) not in ("", "eth-docker"):
        raise ValueError("source review required: custom project name")
    files = (unquote(old_env.get("CORE_FILES", "")) + ":" + unquote(old_env.get("CUSTOM_FILES", ""))).strip(":").split(":")
    if not all(re.fullmatch(r"[a-z0-9._-]+\.yml", f) for f in files):
        raise ValueError("source review required: unsupported Compose files")
    old_head = run(["git", "rev-parse", "HEAD"])
    run(["git", "fetch", "--no-tags", UPSTREAM, revision], timeout=300)
    defaults = run(["git", "show", revision + ":default.env"])
    updated, migration = migrate_env(original, defaults)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    archive_base = root.parent / "eth-docker-local-backups"
    archive_base.mkdir(parents=True, mode=0o700, exist_ok=True)
    archive = Path(tempfile.mkdtemp(prefix="source-" + stamp + "-", dir=archive_base))
    os.chmod(archive, 0o700)

    def private(path, data):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(data)

    private(archive / "env-before", original)
    run(["git", "bundle", "create", str(archive / "source-before.bundle"), "HEAD"], timeout=300)
    os.chmod(archive / "source-before.bundle", 0o600)
    preview = archive / "preview"
    run(["git", "worktree", "add", "--detach", str(preview), old_head])
    # Merge in isolation: local commits remain ancestors; conflicts never touch live code.
    run(["git", "-c", "user.name=egkcluster maintenance", "-c", "user.email=egkcluster@localhost",
         "merge", "--no-edit", revision], cwd=preview)
    merged = run(["git", "rev-parse", "HEAD"], cwd=preview)
    for name in files:
        if not (preview / name).exists():
            source = root / name
            if not source.is_file():
                raise ValueError("source review required: Compose file missing " + name)
            shutil.copy2(source, preview / name)
    private(preview / ".env", updated)

    def compose(directory, envfile):
        argv = docker + ["compose", "--project-name", "eth-docker", "--project-directory", str(root),
                         "--env-file", str(envfile)]
        for name in files:
            argv += ["-f", str(directory / name)]
        return json.loads(run(argv + ["config", "--format", "json"]))

    before, after = compose(root, root / ".env"), compose(preview, preview / ".env")
    rows = run(docker + ["ps", "--filter", "label=com.docker.compose.project=eth-docker", "--format", "{{.Names}}"])
    active = set()
    for name in rows.splitlines():
        service = run(docker + ["inspect", "--format", '{{index .Config.Labels "com.docker.compose.service"}}', name])
        if not re.fullmatch(r"[a-z0-9_-]+", service):
            raise ValueError("invalid active service identity")
        active.add(service)
    if not active:
        raise ValueError("source review required: no active services")
    validate_compose(before, after, active)
    for service in active:
        if after['services'][service].get('profiles'):
            raise ValueError("source review required: active service uses a tools profile")
    helpers = set()
    for service in active:
        deps = set(after['services'][service].get('depends_on', {}))
        for dep in deps - active:
            if dep == 'prom-init':
                helpers.add(dep)
            elif dep not in before['services']:
                raise ValueError("source review required: new dependency " + dep)
    private(archive / "compose-before.json", json.dumps(before, indent=2))
    private(archive / "compose-after.json", json.dumps(after, indent=2))
    result = {"old_head": old_head, "new_head": merged, "upstream_revision": revision,
              "env_before_sha256": hashlib.sha256(original.encode()).hexdigest(),
              "env_after_sha256": hashlib.sha256(updated.encode()).hexdigest(),
              "backup": str(archive), "compose_files": files,
              "active_services": sorted(active), "helpers": sorted(helpers),
              "local_history_preserved": True, "compose_checked": True, "applied": False, **migration}
    # Signing/storage containers keep their current binaries and running state.
    result['apply_services'] = sorted(active - {'postgres','web3signer'})
    if apply:
        # Recheck the live tree/env before the fast-forward and atomic configuration swap.
        if run(["git", "rev-parse", "HEAD"]) != old_head or (root / '.env').read_text() != original or run(["git", "status", "--porcelain"]):
            raise ValueError("live checkout changed during source preview")
        run(["git", "merge", "--ff-only", merged])
        tmp = root / (".env.source-stage-" + stamp)
        private(tmp, updated)
        # SSH runs as root on the sources; retain access for the original operator.
        if os.geteuid() == 0:
            os.chown(tmp, env_stat.st_uid, env_stat.st_gid)
        os.replace(tmp, root / ".env")
        if run(["git", "status", "--porcelain"]):
            raise ValueError("source worktree became dirty after configuration swap")
        result['applied'] = True
    private(archive / "result.json", json.dumps(result, indent=2))
    return result


def remote_script(workdir, revision, use_sudo, apply=True):
    code = Path(__file__).read_text()
    argv = json.dumps([workdir, revision, use_sudo, apply])
    return "python3 - " + shlex.quote(argv) + " <<'SOURCEPY'\n" + code + "\nprint(json.dumps(prepare(*json.loads(sys.argv[1]))))\nSOURCEPY\n"

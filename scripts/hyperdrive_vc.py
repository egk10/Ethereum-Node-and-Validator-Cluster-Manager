"""Lodestar-only Hyperdrive maintenance; preserve signing data and other services."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

VC = "hyperdrive_sw_vc"
ROOT = Path("/home/egk/.hyperdrive")
IMAGE = "chainsafe/lodestar:latest"
FILES = tuple(ROOT / p for p in (
    "runtime/daemon.yml", "override/daemon.yml",
    "runtime/modules/stakewise/sw_daemon.yml", "override/modules/stakewise/sw_daemon.yml",
    "runtime/modules/stakewise/sw_operator.yml", "override/modules/stakewise/sw_operator.yml",
    "runtime/modules/stakewise/sw_vc.yml", "override/modules/stakewise/sw_vc.yml"))
VERSION_PATTERN = r"(?m)^\s*\* Version:\s*v?(\d+\.\d+\.\d+)"


def command(args, timeout=60):
    p = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        # Compose errors can contain interpolated environment values. Keep them private.
        raise RuntimeError(f"Hyperdrive command failed (exit {p.returncode})")
    return p.stdout


def docker(*args, timeout=60):
    return command(["sudo", "-n", "docker", *args], timeout)


def compose():
    return ["sudo", "-n", "docker", "compose", "--project-name", "hyperdrive",
            "--project-directory", str(ROOT), *[a for p in FILES for a in ("-f", str(p))]]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def settings_hashes():
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (ROOT / "user-settings.yml", *FILES)}


def inspect_all():
    ids = docker("ps", "-a", "-q").split()
    return {c["Name"].lstrip("/"): c for c in json.loads(docker("inspect", *ids))
            if c['Name'].lstrip('/').startswith(('eth-docker-','eth-lido-','hyperdrive_'))}


def identity(c):
    return {"id": c["Id"], "image_id": c["Image"], "status": c["State"]["Status"],
            "started_at": c["State"]["StartedAt"],
            "restart": c["HostConfig"]["RestartPolicy"]}


def signing_context(c):
    return {"mounts": sorted((m["Type"], m["Source"], m["Destination"], m["RW"])
                             for m in c["Mounts"]),
            "entrypoint": c["Config"]["Entrypoint"], "command": c["Config"]["Cmd"],
            "user": c["Config"]["User"]}


def validate_render(render, live):
    service = render.get("services", {}).get("sw_vc", {})
    if service.get("image") != IMAGE or live["Config"]["Image"] != IMAGE:
        raise RuntimeError("Hyperdrive VC must already use the reviewed Lodestar repository/tag")
    for rendered, actual in (("entrypoint", "Entrypoint"), ("command", "Cmd"), ("user", "User")):
        if service.get(rendered, "" if rendered == "user" else None) != live["Config"].get(actual):
            raise RuntimeError("Hyperdrive VC runtime differs from Compose: " + rendered)
    env = dict(x.split("=", 1) for x in live["Config"]["Env"] if "=" in x)
    if any(env.get(k) != str(v) for k, v in service.get("environment", {}).items()):
        raise RuntimeError("Hyperdrive VC environment differs from Compose")
    mounts = sorted((v["type"], v.get("source"), v["target"], not v.get("read_only", False))
                    for v in service.get("volumes", []))
    if mounts != signing_context(live)["mounts"]:
        raise RuntimeError("Hyperdrive VC signing/slashing mounts differ from Compose")
    if len(mounts) != 2 or any(m[0] != "bind" for m in mounts) or not any(
            m[2] == "/validators" and m[3] is True and Path(m[1]).is_dir() for m in mounts):
        raise RuntimeError("Hyperdrive VC requires the existing validators bind directory")
    labels = live["Config"]["Labels"]
    if (labels.get("com.docker.compose.project") != "hyperdrive"
            or labels.get("com.docker.compose.service") != "sw_vc"
            or labels.get("com.docker.compose.project.working_dir") != str(ROOT)
            or labels.get("com.docker.compose.project.config_files") != ",".join(map(str, FILES))):
        raise RuntimeError("Hyperdrive VC Compose provenance differs from reviewed recipe")
    return service


def assert_preserved(before, after):
    if set(before) != set(after):
        raise RuntimeError("Cloudvero container inventory changed during Hyperdrive maintenance")
    for name in before:
        if name != VC and identity(before[name]) != identity(after[name]):
            raise RuntimeError("Non-target container changed during Hyperdrive maintenance: " + name)
    if signing_context(before[VC]) != signing_context(after[VC]):
        raise RuntimeError("Hyperdrive signing context changed")


def version_output():
    return docker("exec", VC, "/usr/app/node_modules/.bin/lodestar", "--version")


def version(raw):
    match = re.search(VERSION_PATTERN, raw)
    if not match:
        raise RuntimeError("Hyperdrive Lodestar version unknown")
    return match.group(1)


def parts(value):
    if not isinstance(value, str) or not re.fullmatch(r"v?\d+\.\d+\.\d+", value):
        raise RuntimeError("Hyperdrive version target unknown")
    return tuple(map(int, value.lstrip("v").split(".")))


def check_candidate(raw, prior):
    new = version(raw)
    old, latest, candidate = parts(prior["installed"]), parts(prior["latest"]), parts(new)
    if old[0] != candidate[0] or candidate != latest or candidate < old:
        raise RuntimeError("Hyperdrive Lodestar candidate requires review; live VC retained")
    return new


def update(prior, before_apply, backup_parent):
    before = inspect_all()
    render = json.loads(command(compose() + ["config", "--format", "json"]))
    validate_render(render, before[VC])
    if version(version_output()) != prior["installed"]:
        raise RuntimeError("Hyperdrive VC version changed after inventory")
    hashes = settings_hashes()
    backup = Path(tempfile.mkdtemp(prefix="hyperdrive-vc-", dir=backup_parent))
    backup.chmod(0o700)
    # Full Docker/Compose data can contain credentials: private backups only.
    for name, value in (("containers.json", before), ("compose.json", render)):
        p = backup / name
        p.write_text(json.dumps(value))
        p.chmod(0o600)
    for i, p in enumerate((ROOT / "user-settings.yml", *FILES)):
        saved = backup / str(i)
        saved.write_bytes(p.read_bytes())
        saved.chmod(0o600)
    docker("tag", before[VC]["Image"], "chainsafe/lodestar:maintenance-before-" + backup.name)
    docker("pull", IMAGE, timeout=900)
    image_id = docker("image", "inspect", "--format", "{{.Id}}", IMAGE).strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise RuntimeError("Hyperdrive candidate image identity unknown")
    declared = json.loads(docker("image", "inspect", "--format", "{{json .Config.Volumes}}", image_id)) or {}
    tmpfs = []
    for path in declared:
        if not re.fullmatch(r"/[A-Za-z0-9_./-]+", path) or ".." in path:
            raise RuntimeError("Hyperdrive candidate declares unsafe volume")
        tmpfs += ["--tmpfs", path + ":rw,nosuid,nodev,noexec,size=1048576"]
    candidate = check_candidate(docker("run", "--rm", "--network", "none", "--read-only", *tmpfs,
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--entrypoint",
        "/usr/app/node_modules/.bin/lodestar", image_id, "--version", timeout=90), prior)
    before_apply("cloudvero")
    assert_preserved(before, inspect_all())
    if hashes != settings_hashes() or digest(render) != digest(json.loads(
            command(compose() + ["config", "--format", "json"]))):
        raise RuntimeError("Hyperdrive configuration changed before apply")
    if docker("image", "inspect", "--format", "{{.Id}}", IMAGE).strip() != image_id:
        raise RuntimeError("Hyperdrive candidate tag changed before apply")
    command(compose() + ["up", "-d", "--no-deps", "--no-build", "--pull", "never",
                         "--force-recreate", "sw_vc"], timeout=900)
    after = inspect_all()
    assert_preserved(before, after)
    if (after[VC]["Image"] != image_id or version(version_output()) != candidate
            or hashes != settings_hashes()):
        raise RuntimeError("Hyperdrive running image/version/configuration differs from validated candidate")
    service_env = render["services"]["sw_vc"].get("environment", {})
    new_env = dict(x.split("=", 1) for x in after[VC]["Config"]["Env"] if "=" in x)
    if any(new_env.get(k) != str(v) for k, v in service_env.items()):
        raise RuntimeError("Hyperdrive configured environment changed after apply")
    return {"candidate_versions": {"lodestar": {**prior, "candidate": candidate, "image_id": image_id}},
            "backup": str(backup), "settings_hashes": hashes,
            "protected_containers": {name: identity(c) for name, c in after.items() if name != VC},
            "vc": identity(after[VC]), "signing_context_sha256": digest(signing_context(after[VC]))}

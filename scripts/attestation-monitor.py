#!/usr/bin/env python3
"""Monitor de atestações do egkcluster — vero VC e hyperdrive_sw_vc (Layer 1).

Roda a cada 3 min (systemd timer) no cloudvero. Duas perguntas por validador:

1. Erros de atestação no log (últimos 7 min): "Failed to produce attestation",
   "missed", timeouts. HTTP 500 de beacon execution-optimistic
   (HeadBlockNotFullyVerified) é ruído se houver atestação publicada na mesma
   janela — o Vero tenta o próximo beacon e publica.
2. Silêncio anormal: validadores atestam 1x/época (6,4 min); 7 min sem NENHUMA
   linha de atestação com o container Up é alerta.

Alerta passa pelo GestãoBot local; o monitor não lê credenciais Meta. Dedupe de 30 min por (VC, tipo) — não pela linha
de log, que muda a cada slot e furava o dedupe. Estado em
/opt/egkcluster/state/attest-alerts.json.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import tempfile
from pathlib import Path
from gestaobot_client import Client, BotError

ESTADO = Path("/opt/egkcluster/state/attest-alerts.json")
JANELA_MIN = 7
DEDUPE_MIN = 30

VCS = [
    ("vero", "eth-docker-validator-1"),
    ("hyperdrive_vc", "hyperdrive_sw_vc"),
]
RE_ERRO = re.compile(
    r"(?i)(failed|missed|timeout)[^\n]{0,80}attest|attest[^\n]{0,80}(failed|missed|timeout)")
RE_ATIVIDADE = re.compile(r"(?i)attest")
RE_PUBLICADA = re.compile(r"(?i)published attest")
RE_SLOT = re.compile(r"(?i)\bslot[\s=:]+[\"']?([0-9]+)")
# 500 do Lighthouse/outros quando o EL está em resync — não é miss.
RE_RUIDO = re.compile(
    r"(?i)headblocknotfullyverified|execution_status:\s*optimistic|"
    r"failed to produce attestation data")


def _docker() -> list[str]:
    return (["sudo", "-n"] if os.environ.get("EGK_DOCKER_SUDO") == "1" else []) + ["docker"]


def docker_logs(cont: str) -> list[str]:
    r = subprocess.run(_docker() + ["logs", "--since", f"{JANELA_MIN}m", cont],
                       capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise RuntimeError(f"não foi possível ler logs de {cont}")
    return (r.stdout + r.stderr).splitlines()


def container_up(cont: str) -> bool:
    r = subprocess.run(_docker() + ["ps", "--filter", f"name=^{cont}$",
                        "--format", "{{.Status}}"], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"não foi possível consultar Docker: {cont}")
    return r.stdout.strip().startswith("Up")


def mandar(texto: str) -> bool:
    try:
        Client().alert("Atestações", "cloudvero", texto[:1800])
        print("alerta aceito pelo GestãoBot")
        return True
    except BotError as exc:
        print(str(exc), file=sys.stderr)
        return False


def main() -> int:
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    try:
        visto = json.loads(ESTADO.read_text())
    except Exception:
        visto = {}
    agora = time.time()
    # (chave estável, texto do alerta)
    incidentes: list[tuple[str, str]] = []

    for nome, cont in VCS:
        try:
            up = container_up(cont)
            linhas = docker_logs(cont) if up else []
        except Exception as exc:
            incidentes.append((f"{nome}:coleta", f"❌ {nome}: falha ao verificar atestações ({type(exc).__name__})"))
            continue
        if not up:
            incidentes.append((f"{nome}:down", f"❌ {nome}: container {cont} NÃO está Up"))
            continue
        publicadas = any(RE_PUBLICADA.search(ln) for ln in linhas)
        slots_publicados = {match.group(1) for ln in linhas
                            if RE_PUBLICADA.search(ln) and (match := RE_SLOT.search(ln))}
        erros_all = [ln.strip() for ln in linhas if RE_ERRO.search(ln)]
        erros = [ln for ln in erros_all if not
                 (RE_RUIDO.search(ln) and (match := RE_SLOT.search(ln))
                  and match.group(1) in slots_publicados)]
        if erros:
            incidentes.append(
                (f"{nome}:erro",
                 f"❌ {nome}: erro de atestação — {erros[-1][:150]} "
                 f"({len(erros)} na janela)"))
        elif erros_all and publicadas:
            print(f"ok: {nome}: {len(erros_all)} 500 optimistic ignorados "
                  f"(há atestação publicada na janela)")
        elif not publicadas:
            incidentes.append(
                (f"{nome}:silencio",
                 f"⚠️ {nome}: nenhuma atestação publicada em "
                 f"{JANELA_MIN} min (container Up)"))

    falha_envio = False
    for chave, msg in incidentes:
        if agora - float(visto.get(chave, 0)) < DEDUPE_MIN * 60:
            continue
        if mandar(f"egkcluster ATESTAÇÕES\n{msg}\n"
                  f"(próximos avisos desta chave em {DEDUPE_MIN} min)"):
            visto[chave] = agora
        else:
            falha_envio = True
    visto = {k: v for k, v in visto.items() if agora - float(v) < 24 * 3600}
    fd, tmp = tempfile.mkstemp(prefix=".attest-", dir=ESTADO.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(visto, f)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, ESTADO)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    if falha_envio:
        return 20

    if incidentes:
        print("\n".join(m for _, m in incidentes))
        return 2
    print(f"ok: {len(VCS)} VCs sem erros de atestação na janela de {JANELA_MIN} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())

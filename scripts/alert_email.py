"""Canal de e-mail para alertas do egkcluster (sem aprovação).

Ativo quando /opt/egkcluster/alert-channel.json existe com "channel": "email"
(ou ALERT_CHANNEL=email). Envia pela API do Gmail já usada pela Integra,
rodando como o usuário integra; este script nunca lê o token.
Reverter: renomeie/apague alert-channel.json — tudo volta para o GestãoBot.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

CONFIG = Path(os.environ.get("ALERT_CHANNEL_CONFIG", "/opt/egkcluster/alert-channel.json"))

_SENDER = r'''
import json, sys
sys.path.insert(0, "/opt/integra/scripts")
import google_cliente
d = json.load(sys.stdin)
r = google_cliente.gmail_enviar(d["conta"], d["to"], d["subject"], d["body"])
print(r.get("id", ""))
'''


def config() -> dict:
    cfg = {}
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    if os.environ.get("ALERT_CHANNEL"):
        cfg["channel"] = os.environ["ALERT_CHANNEL"]
    if os.environ.get("ALERT_EMAIL_TO"):
        cfg["to"] = os.environ["ALERT_EMAIL_TO"]
    return cfg if isinstance(cfg, dict) else {}


def enabled() -> bool:
    cfg = config()
    return cfg.get("channel") == "email" and "@" in str(cfg.get("to", ""))


def send(titulo: str, node: str, detalhe: str = "") -> dict:
    cfg = config()
    payload = {
        "conta": cfg.get("conta", "elie@integratechgestao.com.br"),
        "to": cfg["to"],
        "subject": f"[egkcluster] {titulo} — {node}"[:200],
        "body": f"{titulo}\nServidor: {node}\n\n{detalhe}\n\n-- egkcluster (cloudvero)\n",
    }
    done = subprocess.run(
        ["sudo", "-n", "-u", "integra", "/opt/integra/.venv/bin/python", "-c", _SENDER],
        input=json.dumps(payload, ensure_ascii=False), capture_output=True, text=True,
        timeout=60, cwd="/tmp", check=False)
    if done.returncode != 0:
        last = (done.stderr.strip().splitlines() or ["erro"])[-1]
        raise RuntimeError(f"email falhou: {last[:180]}")
    return {"ok": True, "canal": "email", "id": done.stdout.strip()}

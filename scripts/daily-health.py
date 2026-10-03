#!/usr/bin/env python3
"""Saúde diária do egkcluster — CAMADA 1, determinística (systemd timer).

Roda o coletor para os seis nós ativos, aplica regras e envia o resumo pelo
GestãoBot local. Não lê credenciais Meta. Falha de coleta/envio é falha
operacional, distinta dos códigos 10 (aviso) e 11 (crítico) de saúde.

Saída: exit 0 = saudável, 10 = aviso, 11 = crítico, 20 = falha operacional.
"""
from __future__ import annotations

import json
import subprocess
import sys
import re
from pathlib import Path
from gestaobot_client import Client, BotError

ROOT = Path(__file__).resolve().parent.parent
# Coletor: irmão deste arquivo quando instalado no cloudvero (/opt/egkcluster),
# ou no skill quando rodando do repo na estação.
_CANDIDATOS = [
    Path(__file__).resolve().parent / "collect-cluster-state.sh",
    ROOT / ".grok/skills/eth-cluster-ops/scripts/collect-cluster-state.sh",
]
COLLECTOR = next((c for c in _CANDIDATOS if c.exists()), _CANDIDATOS[-1])
ESPERADOS = {"minipcamd", "minipcamd2", "minipcamd3", "minitx",
             "orangepi5-plus", "cloudvero"}

WARN_DISK, CRIT_DISK = 80, 90
# cloudvero: eth-lido é desligado de propósito; o resto precisa estar Up
VC_PRECISAM = ("eth-docker-validator-1", "eth-docker-web3signer-1",
               "hyperdrive_daemon", "hyperdrive_sw_daemon", "hyperdrive_sw_vc")


def coletar() -> dict[str, dict]:
    saida = subprocess.run(["bash", str(COLLECTOR)], capture_output=True,
                           text=True, timeout=900).stdout
    nos: dict[str, dict] = {}
    for bloco in saida.split("===== ")[1:]:
        nome, _, corpo = bloco.partition("=====")
        no: dict = {"discos": [], "sync": None, "vc": [], "reachable": False}
        secao = None
        for ln in (corpo or "").splitlines():
            ln = ln.strip()
            if ln.startswith("--"):
                secao = ln.strip("-")
            elif secao == "probe-status" and re.fullmatch(r"[0-9]+", ln):
                no["reachable"] = ln == "0"
            elif secao == "disk" and ln.startswith("/dev"):
                p = ln.split()
                if len(p) >= 6:
                    no["discos"].append((p[0], p[1], p[4], p[5]))
            elif secao == "beacon-sync" and ln.startswith("{"):
                try:
                    no["sync"] = json.loads(ln)["data"]
                except Exception:
                    pass
            elif secao == "vc-containers" and ln and ln != "none":
                no["vc"].append(ln)
        nos[nome.strip()] = no
    return nos


def analisar(nos: dict) -> tuple[int, list[str]]:
    criticos, avisos = [], []
    for nome in sorted(ESPERADOS - set(nos)):
        criticos.append(f"{nome}: coleta ausente")
    for nome, no in nos.items():
        if nome not in ESPERADOS:
            criticos.append(f"{nome}: nó inesperado na coleta")
        if not no.get("reachable"):
            criticos.append(f"{nome}: falha na coleta")
        if not no["discos"]:
            criticos.append(f"{nome}: disco sem medição")
        for fs, tam, uso, ponto in no["discos"]:
            try:
                pct = int(uso.rstrip("%"))
                m = re.fullmatch(r"([0-9.,]+)([KMGT]?)i?B?", tam)
                if not m:
                    raise ValueError("invalid disk size")
                unit = m.group(2)
                tam_g = float(m.group(1).replace(",", ".")) * {
                    "": 1 / 1024**2, "K": 1 / 1024**2,
                    "M": 1 / 1024, "G": 1, "T": 1024}[unit]
            except ValueError:
                criticos.append(f"{nome}: medição de disco inválida")
                continue
            if tam_g < 1:  # /boot e afins
                continue
            if pct >= CRIT_DISK:
                criticos.append(f"{nome}: disco {pct}% em {ponto}")
            elif pct >= WARN_DISK:
                avisos.append(f"{nome}: disco {pct}% em {ponto}")
        s = no["sync"]
        if nome != "cloudvero" and not s:
            criticos.append(f"{nome}: beacon sem resposta válida")
        elif nome != "cloudvero":
            if any(not isinstance(s.get(k), bool) for k in
                   ("is_syncing", "is_optimistic", "el_offline")):
                criticos.append(f"{nome}: estado de sync incompleto")
            if s.get("is_syncing"):
                avisos.append(f"{nome}: sincronizando")
            if s.get("el_offline"):
                criticos.append(f"{nome}: EL offline")
            if s.get("is_optimistic"):
                avisos.append(f"{nome}: otimístico (resync em curso ou EL atrasado)")
        if nome == "cloudvero":
            for vc in VC_PRECISAM:
                if not any(v.split(" ", 1)[0] == vc and " Up" in v for v in no["vc"]):
                    criticos.append(f"cloudvero: {vc} não está Up")
        else:
            for vc in ("eth-docker-execution-1", "eth-docker-consensus-1"):
                if not any(v.split(" ", 1)[0] == vc and " Up" in v for v in no["vc"]):
                    criticos.append(f"{nome}: {vc} não está Up")
    if criticos:
        return 2, criticos + avisos
    if avisos:
        return 1, avisos
    return 0, []


def mandar(resumo: str, critico: bool) -> bool:
    try:
        Client().alert("Saúde diária: " + ("crítico" if critico else "resumo"),
                       "cluster", resumo[:1800])
        return True
    except BotError as exc:
        print(str(exc), file=sys.stderr)
    return False


def main() -> int:
    try:
        nos = coletar()
    except Exception as exc:
        resumo = f"Falha operacional na coleta: {type(exc).__name__}"
        print(resumo, file=sys.stderr)
        mandar(resumo, True)
        return 20
    if len(nos) < 6:
        print(f"ALERTA: coletor só alcançou {len(nos)}/6 nós", file=sys.stderr)
        codigo, itens = 2, [f"coletor alcançou só {len(nos)}/6 nós"]
    else:
        codigo, itens = analisar(nos)
    estado = "✅ saudável" if codigo == 0 else ("⚠️ avisos" if codigo == 1 else "❌ críticos")
    linhas = [f"egkcluster diária {estado} ({len(nos)} nós)"] + [f"• {i}" for i in itens] or ["• nada a reportar"]
    resumo = "\n".join(linhas) if itens else linhas[0]
    print(resumo)
    if not mandar(resumo, codigo == 2):
        return 20
    return {0: 0, 1: 10, 2: 11}[codigo]


if __name__ == "__main__":
    sys.exit(main())

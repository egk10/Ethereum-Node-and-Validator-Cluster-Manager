#!/usr/bin/env python3
"""Envia alertas e pedidos de aprovação do egkcluster ao gestaobot (leadbot
interno, integratech) e aguarda a aprovação humana pelo WhatsApp do Elie.

Uso:
    notify-gestaobot.py --titulo "resync geth" --node minipcamd2 \
        --detalhe "libera ~1TB" [--aprovar] [--aguardar 15]

Requer GESTAOBOT_URL (padrão http://127.0.0.1:8101 — a rota /internal do bot é
só-localhost; de outra máquina, use túnel SSH ou rode na VM do bot).
A rota devolve o código; --aguardar faz polling de /internal/cluster/aprovacao
até aprovação, rejeição ou timeout (o TTL no bot é de 15 min).
"""
from __future__ import annotations

import argparse
import sys
import time

from gestaobot_client import Client, BotError

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--titulo")
    ap.add_argument("--node")
    ap.add_argument("--detalhe", default="")
    ap.add_argument("--aprovar", action="store_true",
                    help="pede aprovação humana (cria código com TTL de 15 min)")
    ap.add_argument("--aguardar", type=int, default=0, metavar="MIN",
                    help="minutos de polling pelo veredito (0 = só envia)")
    ap.add_argument("--concluir", metavar="CODIGO",
                    help="envia a conclusão da operação aprovada (use com --ok ou --erro)")
    ap.add_argument("--ok", action="store_true", help="conclusão de sucesso")
    ap.add_argument("--erro", action="store_true", help="conclusão de falha")
    ap.add_argument("--texto", default="", help="detalhe da conclusão")
    args = ap.parse_args()
    if args.concluir:
        if args.ok == args.erro:
            ap.error("--concluir requires exactly one of --ok or --erro")
    elif not (args.titulo and args.node):
        ap.error("--titulo and --node are required for alerts")
    bot = Client()

    if args.concluir:
        resp = bot.conclude(args.concluir, args.ok, args.texto)
        if resp.get("ok"):
            print("Conclusão enviada.")
            return 0
        print(f"ERRO: {resp.get('motivo', resp)}", file=sys.stderr)
        return 2

    resp = bot.alert(args.titulo, args.node, args.detalhe, args.aprovar)
    if not resp.get("ok"):
        print(f"ERRO: gestaobot não aceitou o aviso: {resp.get('motivo', resp)}", file=sys.stderr)
        return 2
    codigo = resp.get("codigo", "")
    if args.aprovar:
        print(f"Pedido de aprovação enviado. Código: {codigo} (expira {resp.get('expira_em')})")
    else:
        print("Alerta enviado.")
        return 0

    if args.aguardar <= 0:
        return 0
    prazo = time.time() + args.aguardar * 60
    while time.time() < prazo:
        st = bot.approval(codigo)
        estado = st.get("estado")
        if estado == "aprovada":
            print("APROVADA pelo WhatsApp.")
            return 0
        if estado in ("rejeitada", "expirada"):
            print(f"Operação NÃO autorizada: {estado}.", file=sys.stderr)
            return 1
        time.sleep(30)
    print("Timeout aguardando aprovação — operação NÃO autorizada.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BotError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(20)

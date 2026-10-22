#!/usr/bin/env python3
"""Monitor de atestações do egkcluster — vero VC e hyperdrive_sw_vc (Layer 1).

Roda a cada 3 min (systemd timer) no cloudvero. Três perguntas por validador:

1. Erros de atestação no log (últimos 15 min): "Failed to produce attestation"
   e "missed". Timeout de conexão com um beacon não é atestação perdida:
   o texto diz qual beacon não respondeu e se houve publicação por outro.
   HTTP 500 de beacon execution-optimistic (HeadBlockNotFullyVerified) é ruído
   se houver atestação publicada na mesma duty.
2. Timeout de produce_attestation_data. O Vero 1.4.1 corta cada beacon em
   0,5 s e dispara um por beacon no mesmo instante. Uma rajada no mesmo
   segundo, com publicação saudável, não é miss — e não é "bloco ainda não
   verificado". Só vira alerta se o event loop passou de 5 s, um job rodou
   fora do slot, as rajadas duraram 60 s ou mais, não houve publicação, ou
   o vão entre slots publicados passou de 63 (uma época ficou de fora).
3. Silêncio anormal: a posição da duty muda entre épocas (6,4 min cada),
   portanto o intervalo entre publicações pode alcançar quase duas épocas.
   Quinze minutos sem publicação com o container Up é alerta.

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
from datetime import datetime
from pathlib import Path
from gestaobot_client import Client, BotError

ESTADO = Path("/opt/egkcluster/state/attest-alerts.json")
JANELA_MIN = 15
DEDUPE_MIN = 30
# Uma época tem 32 slots. O vão normal entre duas duties cabe em 63 slots.
GAP_EPOCH_SLOTS = 63
LAG_ALERTA_S = 5.0
RAJADA_SPAN_S = 60

VCS = [
    ("vero", "eth-docker-validator-1"),
    ("hyperdrive_vc", "hyperdrive_sw_vc"),
]
RE_ERRO = re.compile(
    r"(?i)(failed|missed|timeout)[^\n]{0,80}attest|attest[^\n]{0,80}(failed|missed|timeout)")
RE_PUBLICADA = re.compile(r"(?i)published attest")
RE_SLOT = re.compile(r"(?i)\bslot[\s=:]+[\"']?([0-9]+)")
# 500 do Lighthouse/outros quando o EL está em resync — não é miss.
# "Failed to produce attestation data" sozinho fica de fora: no Vero isso
# também é TimeoutError de 0,5 s, e o texto antigo dizia "bloco não verificado".
RE_RUIDO = re.compile(
    r"(?i)headblocknotfullyverified|execution_status:\s*optimistic|"
    r"block not yet verified|not yet fully verified")
RE_PRODUCE_TIMEOUT = re.compile(
    r"(?i)failed to produce attestation data[^\n]*timeouterror|"
    r"produce_attestation_data\(\)[^\n]*timeouterror|"
    r"waiting for checkpoints:[^\n]*timeouterror")
RE_BEACON_TIMEOUT = re.compile(
    r"(?i)failed to get a response from beacon node|connectiontimeouterror|"
    r"connection timeout to host")
RE_HOST = re.compile(r"https?://([^/:\s]+):(\d+)")
RE_BEST = re.compile(r"Using\s+(\S+)\s+as\s+[`']best[`']\s+beacon", re.I)
RE_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
RE_LAG = re.compile(r"Event loop lag high:\s*([0-9]+(?:\.[0-9]+)?)")
RE_SLOT_INVALIDO = re.compile(r"(?i)invalid slot for (?:attestation|block proposal)")
RE_SIGNER = re.compile(r"(?i)mainnet-web3signer|remotesigner")


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


def mandar(titulo: str, texto: str) -> bool:
    try:
        Client().alert(titulo, "cloudvero", texto[:1800])
        print("alerta aceito pelo GestãoBot")
        return True
    except BotError as exc:
        print(str(exc), file=sys.stderr)
        return False


def _host_curto(host: str) -> str:
    return host.split(".", 1)[0]


def _vezes(n: int) -> str:
    return "1 vez" if n == 1 else f"{n} vezes"


def _aviso_de_novo() -> str:
    return f" Próximo aviso desta situação em {DEDUPE_MIN} min."


def beacons_em_timeout(linhas: list[str]) -> dict[tuple[str, str], int]:
    contagem: dict[tuple[str, str], int] = {}
    for ln in linhas:
        if not RE_BEACON_TIMEOUT.search(ln):
            continue
        found = RE_HOST.search(ln)
        chave = (_host_curto(found.group(1)), found.group(2)) if found else ("beacon sem nome no log", "")
        contagem[chave] = contagem.get(chave, 0) + 1
    return contagem


def beacon_escolhido(linhas: list[str]) -> str:
    escolhido = ""
    for ln in linhas:
        match = RE_BEST.search(ln)
        if match:
            escolhido = _host_curto(match.group(1))
    return escolhido


def texto_beacon(nome: str, host: str, porta: str, vezes: int,
                 publicadas: bool, escolhido: str) -> tuple[str, str]:
    destino = f"{host} na porta {porta}" if porta else host
    if publicadas:
        titulo = "Beacon sem resposta"
        frase = (f"{nome} publicou atestação nos últimos {JANELA_MIN} min. "
                 f"O beacon {destino} não respondeu {_vezes(vezes)} por timeout de conexão.")
        if escolhido and escolhido != host:
            frase += f" O beacon escolhido no lugar foi {escolhido}."
        else:
            frase += " O validador usou outro beacon."
    else:
        titulo = "Atestação não publicada"
        frase = (f"{nome} não publicou atestação nos últimos {JANELA_MIN} min. "
                 f"O beacon {destino} não respondeu {_vezes(vezes)} por timeout de conexão.")
    return titulo, frase + _aviso_de_novo()


def avaliar_produce_timeouts(linhas: list[str]) -> dict | None:
    """Rajada curta de TimeoutError com publicação saudável não é miss.

    O Vero pergunta a todos os beacons em paralelo e cada um estoura em 0,5 s.
    Cinco linhas no mesmo segundo são um round, não cinco duties.
    """
    carimbo = None
    vistos: list[datetime] = []
    n = 0
    lag = 0.0
    slot_invalido = False
    signer = False
    for ln in linhas:
        marca = RE_TS.match(ln)
        if marca:
            carimbo = datetime.strptime(marca.group(1), "%Y-%m-%d %H:%M:%S")
        if RE_PRODUCE_TIMEOUT.search(ln):
            n += 1
            if carimbo is not None:
                vistos.append(carimbo)
        atraso = RE_LAG.search(ln)
        if atraso:
            lag = max(lag, float(atraso.group(1)))
        if RE_SLOT_INVALIDO.search(ln):
            slot_invalido = True
        if RE_SIGNER.search(ln) and re.search(r"(?i)timeouterror|status=503|service unavailable", ln):
            signer = True
    slots = sorted({
        int(achado.group(1))
        for ln in linhas
        if RE_PUBLICADA.search(ln) and (achado := RE_SLOT.search(ln))
    })
    gap = max((b - a for a, b in zip(slots, slots[1:])), default=0)
    if n == 0 and lag < LAG_ALERTA_S and not slot_invalido:
        return None
    span = (max(vistos) - min(vistos)).total_seconds() if len(vistos) >= 2 else 0.0
    grave = (
        (lag >= LAG_ALERTA_S and (n > 0 or slot_invalido or not slots or gap > GAP_EPOCH_SLOTS))
        or slot_invalido
        or span >= RAJADA_SPAN_S
        or gap > GAP_EPOCH_SLOTS
        or (n > 0 and not slots)
    )
    if not grave:
        return None
    return {
        "linhas": n,
        "momentos": len({t.strftime("%Y-%m-%d %H:%M:%S") for t in vistos}) or (1 if n else 0),
        "lag": lag if lag >= LAG_ALERTA_S else None,
        "slot_invalido": slot_invalido,
        "signer": signer,
        "gap": gap,
    }


def texto_timeout(nome: str, info: dict, publicadas: bool) -> tuple[str, str]:
    n = info["linhas"]
    momentos = info["momentos"]
    if n:
        linha_txt = "1 linha" if n == 1 else f"{n} linhas"
        momento_txt = "1 momento" if momentos == 1 else f"{momentos} momentos"
        frase = (
            f"{nome}: timeout ao pedir dados de atestação aos beacons "
            f"({linha_txt} em {momento_txt}). "
            "Cada beacon tem 0,5 s; várias linhas no mesmo segundo são o mesmo "
            "pedido em paralelo, não várias duties perdidas."
        )
    else:
        frase = f"{nome}: a cadência de atestação quebrou."
    if info["lag"] is not None:
        frase += f" O event loop do Vero atrasou {info['lag']:.0f} s."
    if info["slot_invalido"]:
        frase += " Um job de duty rodou fora do slot."
    if info["signer"]:
        frase += " O web3signer local (mainnet-web3signer:9000) também falhou nesse intervalo."
    if info["gap"] > GAP_EPOCH_SLOTS:
        frase += (
            f" O maior vão entre atestações publicadas na janela foi de {info['gap']} slots; "
            "acima de 63 fica uma época de fora."
        )
    elif publicadas:
        frase += " Ainda houve publicação nesta janela."
    else:
        frase += f" Nenhuma atestação foi publicada nos últimos {JANELA_MIN} min."
    return "Atestação falhou", frase + _aviso_de_novo()


def texto_falha(nome: str, erros: list[str], publicadas: bool) -> tuple[str, str]:
    ultima = erros[-1]
    slot = RE_SLOT.search(ultima)
    slot_txt = f" do slot {slot.group(1)}" if slot else ""
    if RE_RUIDO.search(ultima):
        fato = "o beacon recusou os dados da atestação porque o bloco ainda não estava verificado" + (
            f" no slot {slot.group(1)}" if slot else "")
    elif re.search(r"missed", ultima, re.I):
        fato = "o validador perdeu a atestação" + slot_txt
    else:
        fato = "o validador não produziu a atestação" + slot_txt
    frase = f"{nome}: {fato}."
    if publicadas:
        frase += " Houve publicação em outro slot nesta janela."
    else:
        frase += f" Nenhuma atestação foi publicada nos últimos {JANELA_MIN} min."
    ocorrencias = "1 ocorrência" if len(erros) == 1 else f"{len(erros)} ocorrências"
    return "Atestação falhou", f"{frase} {ocorrencias} nesta janela.{_aviso_de_novo()}"


def main() -> int:
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    try:
        visto = json.loads(ESTADO.read_text())
    except Exception:
        visto = {}
    agora = time.time()
    # (chave estável, título, texto)
    incidentes: list[tuple[str, str, str]] = []

    for nome, cont in VCS:
        try:
            up = container_up(cont)
            linhas = docker_logs(cont) if up else []
        except Exception as exc:
            incidentes.append((
                f"{nome}:coleta", "Falha ao verificar",
                f"Não consegui verificar {nome}: {type(exc).__name__}.{_aviso_de_novo()}"))
            continue
        if not up:
            incidentes.append((
                f"{nome}:down", "Validador parado",
                f"{nome} está parado. O container {cont} não está Up.{_aviso_de_novo()}"))
            continue
        publicadas = any(RE_PUBLICADA.search(ln) for ln in linhas)
        slots_publicados = {match.group(1) for ln in linhas
                            if RE_PUBLICADA.search(ln) and (match := RE_SLOT.search(ln))}
        timeouts = beacons_em_timeout(linhas)
        escolhido = beacon_escolhido(linhas)
        erros_all = [ln.strip() for ln in linhas
                     if RE_ERRO.search(ln) and not RE_BEACON_TIMEOUT.search(ln)
                     and not RE_PRODUCE_TIMEOUT.search(ln)]
        erros = [ln for ln in erros_all if not
                 (RE_RUIDO.search(ln) and (match := RE_SLOT.search(ln))
                  and match.group(1) in slots_publicados)]
        grave = avaliar_produce_timeouts(linhas)
        for (host, porta), vezes in sorted(timeouts.items()):
            titulo, texto = texto_beacon(nome, host, porta, vezes, publicadas, escolhido)
            incidentes.append((f"{nome}:beacon:{host}:{porta}", titulo, texto))
        if grave:
            titulo, texto = texto_timeout(nome, grave, publicadas)
            incidentes.append((f"{nome}:timeout", titulo, texto))
        if erros:
            titulo, texto = texto_falha(nome, erros, publicadas)
            incidentes.append((f"{nome}:erro", titulo, texto))
        elif erros_all and publicadas:
            print(f"ok: {nome}: {len(erros_all)} 500 optimistic ignorados "
                  f"(há atestação publicada na janela)")
        elif not publicadas and not timeouts and not grave:
            incidentes.append((
                f"{nome}:silencio", "Atestação não publicada",
                f"{nome} não publicou nenhuma atestação nos últimos {JANELA_MIN} min. "
                f"O container {cont} está no ar.{_aviso_de_novo()}"))

    falha_envio = False
    for chave, titulo, msg in incidentes:
        if agora - float(visto.get(chave, 0)) < DEDUPE_MIN * 60:
            continue
        if mandar(titulo, msg):
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
        print("\n".join(m for _, _, m in incidentes))
        return 2
    print(f"ok: {len(VCS)} VCs sem erros de atestação na janela de {JANELA_MIN} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())

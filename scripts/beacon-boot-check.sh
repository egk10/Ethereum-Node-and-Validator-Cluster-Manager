#!/bin/bash
# Checagem do beacon (Lodestar) no minipcamd3.
# Caminho duro: CL "syncing" com head parado e EL sincronizado → reinicia consensus.
# Caminho lag: is_syncing=true e sync_distance>32 por >=30 min → reinicia consensus (sem veto EL).
# Estado persistente: cooldown 30 min e máx. 2 reinícios/dia (UTC), ambos os caminhos.
# Teste: DRY_RUN=1. Simulação: FAKE_CL1/FAKE_CL2/FAKE_EL, FAKE_NOW, BEACON_BOOT_CHECK_STATE_DIR.
set -u
CL=http://localhost:5052
EL=http://localhost:8545
DIR=/home/egk/eth-docker
STATE_DIR=${BEACON_BOOT_CHECK_STATE_DIR:-/var/lib/beacon-boot-check}
STATE_FILE="$STATE_DIR/state"
WAIT=${WAIT:-180}
MIN_ADVANCE=5
LAG_DISTANCE=32
LAG_PERSIST=1800
COOLDOWN=1800
MAX_PER_DAY=2
log() { echo "beacon-boot-check: $*"; }

now() { echo "${FAKE_NOW:-$(date +%s)}"; }
utc_day() { date -u -d "@$(now)" +%Y-%m-%d; }

state_get() {
  local key=$1 default=$2 val
  if [ -f "$STATE_FILE" ]; then
    val=$(grep -E "^${key}=" "$STATE_FILE" 2>/dev/null | tail -1 | cut -d= -f2-)
    echo "${val:-$default}"
  else
    echo "$default"
  fi
}

save_state() {
  mkdir -p "$STATE_DIR"
  cat >"$STATE_FILE" <<EOF
day=$day
count=$count
lag_since=$lag_since
last_restart=$last_restart
EOF
}

load_state() {
  day=$(state_get day "")
  count=$(state_get count 0)
  lag_since=$(state_get lag_since 0)
  last_restart=$(state_get last_restart 0)
  today=$(utc_day)
  if [ -z "$day" ] || [ "$day" != "$today" ]; then
    day=$today
    count=0
    save_state
  fi
}

cl() { curl -sf -m 10 "$CL/eth/v1/node/syncing"; }
el() {
  curl -sf -m 10 -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","method":"eth_syncing","params":[],"id":1}' "$EL"
}

try_restart() {
  local reason=$1
  local now_ts nxt
  now_ts=$(now)
  if [ "$count" -ge "$MAX_PER_DAY" ]; then
    log "já reiniciei $count vez(es) hoje (UTC), desisto (verificar manualmente)"
    return 0
  fi
  if [ "$last_restart" -gt 0 ] && [ $((now_ts - last_restart)) -lt "$COOLDOWN" ]; then
    log "cooldown ativo ($((COOLDOWN - (now_ts - last_restart)))s restantes), não reinicio"
    return 0
  fi
  nxt=$((count + 1))
  log "$reason — reiniciando consensus ($nxt/$MAX_PER_DAY)"
  if [ -n "${DRY_RUN:-}" ]; then
    log "DRY_RUN: não reiniciei"
    return 0
  fi
  count=$nxt
  last_restart=$now_ts
  lag_since=0
  save_state
  cd "$DIR" && docker compose restart consensus && log "consensus reiniciado"
}

load_state
now_ts=$(now)
if [ "$count" -ge "$MAX_PER_DAY" ]; then
  log "já reiniciei $count vez(es) hoje (UTC), desisto (verificar manualmente)"
  exit 0
fi
if [ "$last_restart" -gt 0 ] && [ $((now_ts - last_restart)) -lt "$COOLDOWN" ]; then
  log "cooldown ativo ($((COOLDOWN - (now_ts - last_restart)))s restantes), nada a fazer"
  exit 0
fi

s1=${FAKE_CL1:-$(cl)} || true
[ -z "$s1" ] && { log "beacon API sem resposta, tento na próxima"; exit 0; }

is_sync=$(jq -r .data.is_syncing <<<"$s1")
head1=$(jq -r .data.head_slot <<<"$s1")
sync_dist=$(jq -r '.data.sync_distance // 0' <<<"$s1")

if [ "$is_sync" != "true" ] || [ "$sync_dist" -le "$LAG_DISTANCE" ]; then
  if [ "$lag_since" != "0" ]; then
    lag_since=0
    save_state
  fi
else
  if [ "$lag_since" = "0" ]; then
    lag_since=$now_ts
    save_state
    log "sync_distance=$sync_dist > $LAG_DISTANCE, lag_since registrado"
  else
    lagged=$((now_ts - lag_since))
    log "sync_distance=$sync_dist, lag há ${lagged}s"
    if [ "$lagged" -ge "$LAG_PERSIST" ]; then
      try_restart "CL com lag persistente (sync_distance=$sync_dist, lag ${lagged}s)"
      exit 0
    fi
  fi
fi

if [ "$is_sync" != "true" ]; then
  log "OK: $(jq -c .data <<<"$s1")"
  exit 0
fi

[ -z "${FAKE_CL1:-}" ] && sleep "$WAIT"
s2=${FAKE_CL2:-$(cl)} || true
e=${FAKE_EL:-$(el)} || true
[ -z "$s2" ] && { log "beacon API sem resposta na 2a leitura"; exit 0; }
h1=$(jq -r .data.head_slot <<<"$s1")
h2=$(jq -r .data.head_slot <<<"$s2")
sync2=$(jq -r .data.is_syncing <<<"$s2")
eloff=$(jq -r .data.el_offline <<<"$s2")
elsync=$(jq -r .result <<<"$e" 2>/dev/null)
log "head $h1 -> $h2, is_syncing=$sync2, sync_distance=$sync_dist, el_offline=$eloff, EL eth_syncing=$elsync"
if [ "$sync2" != "true" ] || [ $((h2 - h1)) -ge "$MIN_ADVANCE" ]; then
  log "CL progredindo, sem ação"
  exit 0
fi
if [ "$elsync" != "false" ] || [ "$eloff" != "false" ]; then
  log "EL ainda sincronizando/offline, não reinicio o CL"
  exit 0
fi
try_restart "CL travado (avançou $((h2 - h1)) slots em ${WAIT}s)"
exit 0
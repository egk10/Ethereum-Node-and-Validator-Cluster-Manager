#!/usr/bin/env bash
# Quick Teku graffiti append-format checker for eth-docker managed nodes
# Usage:
#   ./scripts/check_teku_graffiti.sh <tailscale_or_host> [ssh_user]
#   Add --accept-new-hostkey to auto add unknown hosts.
# Example:
#   ./scripts/check_teku_graffiti.sh minitx
#   ./scripts/check_teku_graffiti.sh minitx myuser

set -euo pipefail

HOST=""
SSH_USER="$USER"
ACCEPT_NEW=false

for arg in "$@"; do
  case "$arg" in
    --accept-new-hostkey)
      ACCEPT_NEW=true
      shift
      ;;
    *)
      if [[ -z "$HOST" ]]; then
        HOST="$arg"
      elif [[ "$SSH_USER" == "$USER" ]]; then
        SSH_USER="$arg"
      fi
      shift || true
      ;;
  esac

done

if [[ -z "${HOST}" ]]; then
  echo "Usage: $0 <host> [ssh_user] [--accept-new-hostkey]" >&2
  exit 1
fi

SSH_TARGET="${SSH_USER}@${HOST}"

cyan="\033[36m"; green="\033[32m"; yellow="\033[33m"; red="\033[31m"; reset="\033[0m"
info(){ echo -e "${cyan}[INFO]${reset} $*"; }
ok(){ echo -e "${green}[OK]${reset}  $*"; }
warn(){ echo -e "${yellow}[WARN]${reset} $*"; }
err(){ echo -e "${red}[ERR]${reset}  $*"; }

info "Target: $SSH_TARGET"

# Function: attempt simple SSH command capturing stderr
ssh_try(){
  local out
  set +e
  if $ACCEPT_NEW; then
    out=$(ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=6 "$SSH_TARGET" 'echo ok' 2>&1)
  else
    out=$(ssh -o BatchMode=yes -o ConnectTimeout=6 "$SSH_TARGET" 'echo ok' 2>&1)
  fi
  local rc=$?
  set -e
  echo "$out" | grep -q "Host key verification failed" && {
    err "Host key verification failed."
    echo "$out" | sed 's/^/  /'
    echo ""
    echo "Remedies:" >&2
    echo "  1) Manually trust host: ssh $SSH_TARGET" >&2
    echo "  2) Re-run with: $0 $HOST $SSH_USER --accept-new-hostkey" >&2
    echo "  3) If using Tailscale MagicDNS, try FQDN (e.g. minitx.<tailnet>.ts.net)" >&2
    exit 10
  }
  if [[ $rc -ne 0 ]]; then
    err "SSH connection failed (rc=$rc). Output:"; echo "$out" | sed 's/^/  /'
    exit 11
  fi
}

ssh_try
ok "SSH connectivity established"

# 1. Identify Teku container name (support different naming patterns)
TEKU_CONTAINER=$(ssh "$SSH_TARGET" 'docker ps --format "{{.Names}}" | grep -E "teku|consensus" | grep -i teku | head -n1' || true)
if [[ -z "$TEKU_CONTAINER" ]]; then
  warn "No container name explicitly containing 'teku'; trying generic consensus match..."
  TEKU_CONTAINER=$(ssh "$SSH_TARGET" 'docker ps --format "{{.Names}}" | grep -E "teku|consensus" | head -n1' || true)
fi
if [[ -z "$TEKU_CONTAINER" ]]; then
  err "No running Teku/consensus container found"
  echo "Diagnostics to run manually:" >&2
  echo "  ssh $SSH_TARGET 'docker ps'" >&2
  exit 2
fi
ok "Found candidate container: $TEKU_CONTAINER"

# 2. Extract full command / args
CMD_JSON=$(ssh "$SSH_TARGET" "docker inspect $TEKU_CONTAINER --format '{{json .Config.Cmd}}'" || true)
ENTRYPOINT_JSON=$(ssh "$SSH_TARGET" "docker inspect $TEKU_CONTAINER --format '{{json .Config.Entrypoint}}'" || true)

# 3. Search for the flag
FLAG_REGEX='validators-graffiti-client-append-format'
HAS_FLAG_CMD=$(echo "$CMD_JSON $ENTRYPOINT_JSON" | grep -i "$FLAG_REGEX" || true)
if [[ -z "$HAS_FLAG_CMD" ]]; then
  PROC_LINE=$(ssh "$SSH_TARGET" "docker exec $TEKU_CONTAINER ps -eo cmd" | grep -i teku | grep -i "$FLAG_REGEX" || true)
else
  PROC_LINE="$HAS_FLAG_CMD"
fi

if [[ -n "$PROC_LINE" ]]; then
  ok "Flag present in command line"
  VALUE=$(echo "$PROC_LINE" | tr ' ' '\n' | grep -i "$FLAG_REGEX" | tail -n1 | cut -d'=' -f2- || true)
  if [[ -n "$VALUE" ]]; then
    echo "Flag value: $VALUE"
    if [[ "$VALUE" == "DISABLED" ]]; then
      ok "Append format is DISABLED (no client suffix)."
    else
      warn "Append format active: $VALUE"
    fi
  else
    warn "Flag detected but value parse failed."
  fi
else
  warn "Flag NOT present in running args"
fi

# 4. Check env files
info "Scanning eth-docker env files for flag..."
ENV_HITS=$(ssh "$SSH_TARGET" 'grep -R "validators-graffiti-client-append-format" -n ~/eth-docker 2>/dev/null || true')
if [[ -n "$ENV_HITS" ]]; then
  ok "Found in env files:"; echo "$ENV_HITS"
else
  warn "Not present in env files"
fi

# 5. Explicit graffiti
GRAFFITI_ARG=$(echo "$CMD_JSON $ENTRYPOINT_JSON" | tr '"' ' ' | tr ' ' '\n' | grep -i '^--validators-graffiti=' || true)
[[ -n "$GRAFFITI_ARG" ]] && info "Explicit graffiti arg: $GRAFFITI_ARG"

cat <<"SUMMARY"
------------------------------------------------------------------------
Next Steps:
- To disable append: add to teku env (e.g. teku.env or consensus-client.env):
    TEKU_OPTS="--validators-graffiti-client-append-format=DISABLED $TEKU_OPTS"
  then: docker compose up -d --force-recreate consensus
- To set format explicitly (examples): CLIENT | VERSION | CLIENT_VERSION
- To revert: remove the flag and optionally set --validators-graffiti=YOURTAG
------------------------------------------------------------------------
SUMMARY

exit 0

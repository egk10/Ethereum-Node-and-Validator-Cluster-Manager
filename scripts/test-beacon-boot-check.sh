#!/bin/bash
# Testes locais de beacon-boot-check.sh (FAKE_* + diretório de estado temporário).
set -u
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
CHECK="$SCRIPT_DIR/beacon-boot-check.sh"
export DRY_RUN=1
export WAIT=0
fail=0
pass=0

now=$(date +%s)
today=$(date -u +%Y-%m-%d)

assert() {
  local name=$1 expect=$2 out=$3
  if echo "$out" | grep -q "$expect"; then
    echo "PASS: $name"
    pass=$((pass + 1))
  else
    echo "FAIL: $name (esperava '$expect')"
    echo "$out"
    fail=$((fail + 1))
  fi
}

# healthy: não sincronizando
tmp=$(mktemp -d)
out=$(BEACON_BOOT_CHECK_STATE_DIR=$tmp FAKE_CL1='{"data":{"is_syncing":false,"head_slot":"100","sync_distance":"0"}}' "$CHECK" 2>&1) || true
assert healthy "OK:" "$out"
rm -rf "$tmp"

# lag < 30 min: registra mas sem reinício
tmp=$(mktemp -d)
lag_start=$((now - 600))
cat >"$tmp/state" <<EOF
day=$today
count=0
lag_since=$lag_start
last_restart=0
EOF
out=$(BEACON_BOOT_CHECK_STATE_DIR=$tmp FAKE_NOW=$now \
  FAKE_CL1='{"data":{"is_syncing":true,"head_slot":"100","sync_distance":"50","el_offline":false}}' \
  "$CHECK" 2>&1) || true
if echo "$out" | grep -q "lag há" && ! echo "$out" | grep -q "reiniciando consensus"; then
  echo "PASS: lag_under_30min"
  pass=$((pass + 1))
else
  echo "FAIL: lag_under_30min"
  echo "$out"
  fail=$((fail + 1))
fi
rm -rf "$tmp"

# lag >= 30 min: DRY_RUN reinício
tmp=$(mktemp -d)
lag_start=$((now - 1900))
cat >"$tmp/state" <<EOF
day=$today
count=0
lag_since=$lag_start
last_restart=0
EOF
out=$(BEACON_BOOT_CHECK_STATE_DIR=$tmp FAKE_NOW=$now \
  FAKE_CL1='{"data":{"is_syncing":true,"head_slot":"100","sync_distance":"50","el_offline":false}}' \
  "$CHECK" 2>&1) || true
if echo "$out" | grep -q "lag persistente" && echo "$out" | grep -q "DRY_RUN"; then
  echo "PASS: lag_over_30min_dry_run"
  pass=$((pass + 1))
else
  echo "FAIL: lag_over_30min_dry_run"
  echo "$out"
  fail=$((fail + 1))
fi
rm -rf "$tmp"

# cooldown
tmp=$(mktemp -d)
cat >"$tmp/state" <<EOF
day=$today
count=1
lag_since=0
last_restart=$((now - 300))
EOF
out=$(BEACON_BOOT_CHECK_STATE_DIR=$tmp FAKE_NOW=$now \
  FAKE_CL1='{"data":{"is_syncing":true,"head_slot":"100","sync_distance":"50","el_offline":false}}' \
  "$CHECK" 2>&1) || true
assert cooldown "cooldown ativo" "$out"
rm -rf "$tmp"

# daily cap
tmp=$(mktemp -d)
cat >"$tmp/state" <<EOF
day=$today
count=2
lag_since=0
last_restart=$((now - 7200))
EOF
out=$(BEACON_BOOT_CHECK_STATE_DIR=$tmp FAKE_NOW=$now \
  FAKE_CL1='{"data":{"is_syncing":true,"head_slot":"100","sync_distance":"50","el_offline":false}}' \
  "$CHECK" 2>&1) || true
assert daily_cap "já reiniciei 2 vez" "$out"
rm -rf "$tmp"

# hard stall: head parado, EL ok (sync_distance baixo para não acionar lag)
tmp=$(mktemp -d)
out=$(BEACON_BOOT_CHECK_STATE_DIR=$tmp \
  FAKE_CL1='{"data":{"is_syncing":true,"head_slot":"100","sync_distance":"5","el_offline":false}}' \
  FAKE_CL2='{"data":{"is_syncing":true,"head_slot":"102","sync_distance":"5","el_offline":false}}' \
  FAKE_EL='{"result":false}' \
  "$CHECK" 2>&1) || true
if echo "$out" | grep -q "CL travado" && echo "$out" | grep -q "DRY_RUN"; then
  echo "PASS: hard_stall"
  pass=$((pass + 1))
else
  echo "FAIL: hard_stall"
  echo "$out"
  fail=$((fail + 1))
fi
rm -rf "$tmp"

echo "---"
echo "passed=$pass failed=$fail"
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "$CHECK" "$SCRIPT_DIR/test-beacon-boot-check.sh" && echo "shellcheck: OK"
else
  echo "shellcheck: não instalado (ignorado)"
fi
exit "$fail"
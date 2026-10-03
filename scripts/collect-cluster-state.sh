#!/usr/bin/env bash
# Read-only, buffered probes. A header is not proof that SSH or Docker worked.
set -u
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cat > "$TMP/probe.sh" <<'PROBE'
set -eu
name="$1"
docker_cmd=(docker)
if [[ "$name" == cloudvero ]]; then docker_cmd=(sudo -n docker); fi
data_root=$("${docker_cmd[@]}" info --format '{{.DockerRootDir}}')
echo '--disk--'
df -Pk / "$data_root" | sed 1d | sort -u
echo '--beacon-sync--'
if [[ "$name" != cloudvero ]]; then
  curl --fail --silent --show-error --max-time 8 http://127.0.0.1:5052/eth/v1/node/syncing
  echo
fi
echo '--vc-containers--'
"${docker_cmd[@]}" ps -a --format '{{.Names}} {{.Status}}'
PROBE

probe() {
  local name="$1" target="$2" port="$3" rc
  if [[ "$name" == cloudvero && "${EGK_LOCAL_CLOUDVERO:-0}" == 1 ]]; then
    if timeout 60 bash -s -- "$name" < "$TMP/probe.sh" > "$TMP/$name.txt" 2>&1; then rc=0; else rc=$?; fi
  else
    if timeout 60 ssh -p "$port" -o ConnectTimeout=12 -o BatchMode=yes "$target" \
        "bash -s -- $name" < "$TMP/probe.sh" > "$TMP/$name.txt" 2>&1; then rc=0; else rc=$?; fi
  fi
  printf '\n--probe-status--\n%s\n' "$rc" >> "$TMP/$name.txt"
}
for name in minipcamd minipcamd2 minipcamd3 minitx orangepi5-plus; do
  probe "$name" "root@$name.velociraptor-scylla.ts.net" "${EGK_NODE_SSH_PORT:-22}" &
done
probe cloudvero egk@100.120.33.16 22 &
wait
for name in minipcamd minipcamd2 minipcamd3 minitx orangepi5-plus cloudvero; do
  printf '===== %s =====\n' "$name"
  cat "$TMP/$name.txt"
done
echo COLLECT-DONE

#!/bin/bash
#
# Vero Container Monitor
# Monitors Vero validator containers for errors and auto-restarts them
#
# Detects:
#   - ConflictingIdError: APScheduler job conflict during beacon node reconnection
#   - Stale slot bug: Validator stuck requesting attestation data for old slots
#
# Usage: ./monitor-vero-containers.sh [--daemon]
#
# Install as systemd service:
#   sudo cp monitor-vero-containers.sh /usr/local/bin/
#   sudo chmod +x /usr/local/bin/monitor-vero-containers.sh
#   # Then install the systemd service (see below)

set -euo pipefail

# Configuration
CONTAINERS=("eth-lido-validator-1" "eth-docker-validator-1")  # Vero containers to monitor
CHECK_INTERVAL=60          # Check every 60 seconds
ERROR_THRESHOLD=5          # Number of ConflictingIdError in window to trigger restart
STALE_SLOT_THRESHOLD=50    # Number of "is not the current slot" errors to trigger restart
ERROR_WINDOW_SECONDS=120   # Time window to count errors
LOG_FILE="/var/log/vero-monitor.log"
COOLDOWN_SECONDS=300       # Minimum time between restarts for same container

# State tracking
declare -A LAST_RESTART_TIME

log() {
    local level="$1"
    shift
    local msg="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $msg" | tee -a "$LOG_FILE" 2>/dev/null || echo "[$timestamp] [$level] $msg"
}

check_container_errors() {
    local container="$1"
    local error_type="$2"  # "conflicting_id" or "stale_slot"

    # Check if container exists and is running
    if ! docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
        log "WARN" "Container $container is not running"
        return 1
    fi

    local logs
    logs=$(docker logs "$container" --since "${ERROR_WINDOW_SECONDS}s" 2>&1)

    local count=0
    case "$error_type" in
        conflicting_id)
            # Count ConflictingIdError occurrences
            count=$(echo "$logs" | grep -c "ConflictingIdError" || true)
            ;;
        stale_slot)
            # Count "is not the current slot" errors (stale slot bug)
            count=$(echo "$logs" | grep -c "is not the current slot" || true)
            ;;
    esac
    echo "${count:-0}"
}

should_restart() {
    local container="$1"
    local now=$(date +%s)
    local last_restart=${LAST_RESTART_TIME[$container]:-0}
    local elapsed=$((now - last_restart))

    if [ "$elapsed" -lt "$COOLDOWN_SECONDS" ]; then
        log "INFO" "Container $container in cooldown period ($elapsed/${COOLDOWN_SECONDS}s)"
        return 1
    fi
    return 0
}

restart_container() {
    local container="$1"
    local reason="$2"

    log "WARN" "Restarting $container due to: $reason"

    if docker restart "$container" 2>&1; then
        LAST_RESTART_TIME[$container]=$(date +%s)
        log "INFO" "Successfully restarted $container"

        # Wait a moment and verify it's running
        sleep 5
        if docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
            log "INFO" "Container $container is running after restart"
        else
            log "ERROR" "Container $container failed to start after restart"
        fi
    else
        log "ERROR" "Failed to restart $container"
    fi
}

check_all_containers() {
    for container in "${CONTAINERS[@]}"; do
        # Check for ConflictingIdError
        local conflicting_count
        conflicting_count=$(check_container_errors "$container" "conflicting_id")

        if [ "$conflicting_count" -ge "$ERROR_THRESHOLD" ]; then
            log "WARN" "Container $container has $conflicting_count ConflictingIdError in last ${ERROR_WINDOW_SECONDS}s (threshold: $ERROR_THRESHOLD)"
            if should_restart "$container"; then
                restart_container "$container" "$conflicting_count ConflictingIdError occurrences"
                continue  # Skip other checks after restart
            fi
        elif [ "$conflicting_count" -gt 0 ]; then
            log "DEBUG" "Container $container has $conflicting_count ConflictingIdError (below threshold)"
        fi

        # Check for stale slot bug (validator stuck on old slot)
        local stale_count
        stale_count=$(check_container_errors "$container" "stale_slot")

        if [ "$stale_count" -ge "$STALE_SLOT_THRESHOLD" ]; then
            log "WARN" "Container $container has $stale_count stale slot errors in last ${ERROR_WINDOW_SECONDS}s (threshold: $STALE_SLOT_THRESHOLD)"
            if should_restart "$container"; then
                restart_container "$container" "$stale_count stale slot errors (validator stuck on old slot)"
            fi
        elif [ "$stale_count" -gt 0 ]; then
            log "DEBUG" "Container $container has $stale_count stale slot errors (below threshold)"
        fi
    done
}

run_daemon() {
    log "INFO" "Starting Vero container monitor daemon"
    log "INFO" "Monitoring containers: ${CONTAINERS[*]}"
    log "INFO" "Check interval: ${CHECK_INTERVAL}s, ConflictingIdError threshold: ${ERROR_THRESHOLD}, Stale slot threshold: ${STALE_SLOT_THRESHOLD} in ${ERROR_WINDOW_SECONDS}s"

    while true; do
        check_all_containers
        sleep "$CHECK_INTERVAL"
    done
}

run_once() {
    log "INFO" "Running single check for Vero containers"
    check_all_containers
    log "INFO" "Check complete"
}

show_status() {
    echo "Vero Container Monitor Status"
    echo "=============================="
    echo ""
    for container in "${CONTAINERS[@]}"; do
        echo "Container: $container"
        if docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
            echo "  Status: Running"
            local conflicting_count=$(check_container_errors "$container" "conflicting_id")
            local stale_count=$(check_container_errors "$container" "stale_slot")
            echo "  ConflictingIdError count (last ${ERROR_WINDOW_SECONDS}s): $conflicting_count (threshold: $ERROR_THRESHOLD)"
            echo "  Stale slot error count (last ${ERROR_WINDOW_SECONDS}s): $stale_count (threshold: $STALE_SLOT_THRESHOLD)"
            local uptime=$(docker inspect --format='{{.State.StartedAt}}' "$container" 2>/dev/null || echo "unknown")
            echo "  Started at: $uptime"
        else
            echo "  Status: Not running"
        fi
        echo ""
    done
}

usage() {
    cat << EOF
Vero Container Monitor - Monitors for Vero bugs and auto-restarts

Detects:
  - ConflictingIdError: APScheduler job conflict during beacon node reconnection
  - Stale slot bug: Validator stuck requesting attestation data for old slots

Usage: $0 [OPTION]

Options:
  --daemon      Run as a background daemon
  --once        Run a single check and exit
  --status      Show current container status
  --help        Show this help message

Configuration (edit script to modify):
  CONTAINERS:           ${CONTAINERS[*]}
  CHECK_INTERVAL:       ${CHECK_INTERVAL}s
  ERROR_THRESHOLD:      ${ERROR_THRESHOLD} ConflictingIdError
  STALE_SLOT_THRESHOLD: ${STALE_SLOT_THRESHOLD} stale slot errors
  ERROR_WINDOW_SECONDS: ${ERROR_WINDOW_SECONDS}s
  COOLDOWN_SECONDS:     ${COOLDOWN_SECONDS}s

EOF
}

# Main
case "${1:-}" in
    --daemon)
        run_daemon
        ;;
    --once)
        run_once
        ;;
    --status)
        show_status
        ;;
    --help|-h)
        usage
        ;;
    "")
        usage
        ;;
    *)
        echo "Unknown option: $1"
        usage
        exit 1
        ;;
esac

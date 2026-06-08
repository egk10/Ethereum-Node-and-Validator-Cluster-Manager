# HAProxy Load Balancer for Hyperdrive

## Overview

This document describes the HAProxy setup on **cloudvero** that provides multi-node redundancy for the Hyperdrive validator client, exposed via tsdproxy (Tailscale Docker Proxy).

**Problem**: Hyperdrive benefits from fallback beacon/execution endpoints for resilience.

**Solution**: HAProxy load balancer aggregates multiple backend nodes, exposed via tsdproxy in a separate Docker stack (`/home/egk/eth-proxy`).

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         cloudvero (US East)                         │
│  ┌─────────────┐      ┌──────────────────────────────────────────┐ │
│  │  Hyperdrive │      │ HAProxy                                  │ │
│  │  Primary:   │      │   - Beacon:    localhost:15052           │ │
│  │   nodeset   │      │   - Execution: localhost:18545           │ │
│  │  Fallback:  │ ───► │   - Stats:     localhost:8404            │ │
│  │   HAProxy   │      └──────────────────────────────────────────┘ │
└──┴─────────────┴──────────────────┬─────────────────────────────────┘
                                    │
         ┌──────────────────────────┼──────────────────────────────┐
         │                          │                              │
         ▼                          ▼                              ▼
   ┌───────────┐            ┌───────────┐                  ┌───────────┐
   │ ~18ms     │            │ ~124ms    │                  │ ~148ms    │
   │ Canada    │            │ Brazil    │                  │ Brazil    │
   ├───────────┤            ├───────────┤                  ├───────────┤
   │ minipcamd4 (ryzen7) │   │ rocketpool│                  │ bropi     │
   │ minipcamd2 (lido188)│   │           │                  │           │
   │ minipcamd  (lido102)│   │           │                  │           │
   └─────────────────────┘   └───────────┘                  └───────────┘
```

## Backend Nodes (Fallback Pool)

Ordered by latency from cloudvero (US East). `balance first` mode uses the first healthy server.

| Priority | Node     | Tailscale Domain                        | Latency | Consensus     | Execution |
|----------|----------|-----------------------------------------|---------|---------------|-----------|
| 1 | minipcamd4 (ryzen7) | minipcamd4.velociraptor-scylla.ts.net | ~18ms | Grandine :5052 | Erigon :8545 |
| 2 | minipcamd2 (lido188) | minipcamd2.velociraptor-scylla.ts.net | ~18ms | Lighthouse :5052 | Geth :8545 |
| 3 | minipcamd (lido102) | minipcamd.velociraptor-scylla.ts.net | ~19ms | Prysm :5052 | Nethermind :8545 |
| 4 | minipcamd3 (nodeset) | minipcamd3.velociraptor-scylla.ts.net | ~19ms | Lodestar :5052 | Reth :8545 |
| 5 | minitx (rocketpool) | minitx.velociraptor-scylla.ts.net | ~124ms | Lodestar :5052 | Geth :8545 |
| 6 | opiplus (bropi) | orangepi5-plus.velociraptor-scylla.ts.net | ~148ms | Nimbus :5052 | Geth :8545 |

## Configuration Files

### HAProxy Config: `/etc/haproxy/haproxy.cfg`

```haproxy
global
    log /dev/log local0
    log /dev/log local1 notice
    chroot /var/lib/haproxy
    stats socket /run/haproxy/admin.sock mode 660 level admin
    stats timeout 30s
    user haproxy
    group haproxy
    daemon

# Runtime DNS resolution for Tailscale MagicDNS
# IMPORTANT: Required for HAProxy to resolve *.ts.net hostnames at runtime
# Without this, HAProxy fails to start if DNS isn't available at boot time
resolvers tailscale
    nameserver dns1 127.0.0.53:53
    resolve_retries 3
    timeout resolve 1s
    timeout retry 1s
    hold valid 10s
    hold nx 5s
    hold timeout 5s

defaults
    log     global
    mode    http
    option  httplog
    option  dontlog-normal
    timeout connect 5s
    timeout client  30s
    timeout server  30s
    errorfile 400 /etc/haproxy/errors/400.http
    errorfile 403 /etc/haproxy/errors/403.http
    errorfile 408 /etc/haproxy/errors/408.http
    errorfile 500 /etc/haproxy/errors/500.http
    errorfile 502 /etc/haproxy/errors/502.http
    errorfile 503 /etc/haproxy/errors/503.http
    errorfile 504 /etc/haproxy/errors/504.http

# Stats page for monitoring
listen stats
    bind *:8404
    stats enable
    stats uri /stats
    stats refresh 10s

# =============================================
# BEACON NODE (Consensus Client) LOAD BALANCER
# =============================================
# Health check: Verify node is synced AND not in optimistic mode
# Optimistic nodes return 503 for attestations, so we exclude them
frontend beacon_node_fallback
    bind *:15052
    default_backend beacon_nodes

backend beacon_nodes
    balance first
    option httpchk GET /eth/v1/node/syncing
    # Match response body: node must have is_optimistic:false AND is_syncing:false
    http-check expect rstring \"is_optimistic\":false.*\"is_syncing\":false|\"is_syncing\":false.*\"is_optimistic\":false

    # Ordered by latency from cloudvero (US East)
    # Canada nodes (~18ms) - lowest latency first
    # Note: 'resolvers tailscale init-addr none' enables runtime DNS resolution
    server minipcamd4     minipcamd4.velociraptor-scylla.ts.net:5052     check inter 5s fall 2 rise 2 resolvers tailscale init-addr none
    server minipcamd2     minipcamd2.velociraptor-scylla.ts.net:5052     check inter 5s fall 2 rise 2 resolvers tailscale init-addr none
    server minipcamd     minipcamd.velociraptor-scylla.ts.net:5052      check inter 5s fall 2 rise 2 resolvers tailscale init-addr none
    server minipcamd3     minipcamd3.velociraptor-scylla.ts.net:5052     check inter 5s fall 2 rise 2 resolvers tailscale init-addr none
    # Brazil nodes (~124-148ms) - higher latency last
    server minitx  minitx.velociraptor-scylla.ts.net:5052         check inter 5s fall 2 rise 2 resolvers tailscale init-addr none
    server opiplus       orangepi5-plus.velociraptor-scylla.ts.net:5052 check inter 5s fall 2 rise 2 resolvers tailscale init-addr none

# =============================================
# EXECUTION CLIENT LOAD BALANCER
# =============================================
# Health check: Verify node is fully synced (eth_syncing returns false)
frontend execution_client_fallback
    bind *:18545
    default_backend execution_clients

backend execution_clients
    balance first
    option httpchk POST /
    http-check send hdr Content-Type application/json body "{\"jsonrpc\":\"2.0\",\"method\":\"eth_syncing\",\"params\":[],\"id\":1}"
    # Match: result must be false (not an object with sync status)
    http-check expect rstring \"result\":false

    # Ordered by latency from cloudvero (US East)
    # Canada nodes (~18ms) - lowest latency first
    server minipcamd4     minipcamd4.velociraptor-scylla.ts.net:8545     check inter 5s fall 2 rise 2 resolvers tailscale init-addr none
    server minipcamd2     minipcamd2.velociraptor-scylla.ts.net:8545     check inter 5s fall 2 rise 2 resolvers tailscale init-addr none
    server minipcamd     minipcamd.velociraptor-scylla.ts.net:8545      check inter 5s fall 2 rise 2 resolvers tailscale init-addr none
    server minipcamd3     minipcamd3.velociraptor-scylla.ts.net:8545     check inter 5s fall 2 rise 2 resolvers tailscale init-addr none
    # Brazil nodes (~124-148ms) - higher latency last
    server minitx  minitx.velociraptor-scylla.ts.net:8545         check inter 5s fall 2 rise 2 resolvers tailscale init-addr none
    server opiplus       orangepi5-plus.velociraptor-scylla.ts.net:8545 check inter 5s fall 2 rise 2 resolvers tailscale init-addr none
```

### Hyperdrive Config: `~/.hyperdrive/user-settings.yml`

HAProxy is used as the **primary** beacon/execution endpoint (not fallback):

```yaml
hyperdrive:
    externalBeacon:
        httpUrl: https://beaconapi.velociraptor-scylla.ts.net
    externalExecution:
        httpUrl: https://ethereum-rpc.velociraptor-scylla.ts.net
    fallback:
        bnHttpUrl: http://orangepi5-plus.velociraptor-scylla.ts.net:5052
        ecHttpUrl: http://orangepi5-plus.velociraptor-scylla.ts.net:8545
        useFallbackClients: "true"
```

### tsdproxy Setup

The HAProxy endpoints are exposed via tsdproxy's **file-based proxy list** feature - no nginx containers needed.

**Config file**: `~/homelab/tsdproxy/config/tsdproxy.yaml`
```yaml
# TSDProxy configuration
tailscale:
  dataDir: /data/
  providers:
    default:
      authKeyFile: ""
      controlUrl: https://controlplane.tailscale.com

files:
  eth-proxies:
    filename: /config/eth-proxies.yaml
    defaultProxyProvider: default
```

**Proxy list file**: `~/homelab/tsdproxy/config/eth-proxies.yaml`
```yaml
# Ethereum HAProxy endpoints
beaconapi:
  url: http://172.26.0.1:15052
  tailscale:
    ephemeral: true

ethereum-rpc:
  url: http://172.26.0.1:18545
  tailscale:
    ephemeral: true
```

**Note**: The URL uses the Docker gateway IP (172.26.0.1). Check with: `docker inspect tsdproxy --format '{{range .NetworkSettings.Networks}}{{.Gateway}}{{end}}'`

**Auto-reload**: tsdproxy automatically reloads the proxy list when `eth-proxies.yaml` is updated - no restart needed.

### Why tsdproxy over Tailscale Serve?

| Factor | Tailscale Serve | tsdproxy |
|--------|-----------------|----------|
| Health check latency | ⚠️ Connection warmup delays | ✅ Always warm |
| Lodestar warnings | ⚠️ "Primary beacon unhealthy" | ✅ No warnings |
| Docker dependency | ✅ None | ⚠️ Requires Docker |

**Note**: tsdproxy was chosen over Tailscale Serve because Tailscale Serve causes periodic "Primary beacon node is unhealthy" warnings in Lodestar due to connection establishment latency after idle periods

## Health Check Settings

| Setting | Value | Description |
|---------|-------|-------------|
| `inter` | 5s | Check every 5 seconds |
| `fall` | 2 | Mark unhealthy after 2 failures (~10s) - faster failover |
| `rise` | 2 | Mark healthy after 2 successes (~10s) |

### Beacon Node Health Check
- **Endpoint**: `GET /eth/v1/node/syncing`
- **Validation**: Response body must contain `"is_optimistic":false` AND `"is_syncing":false`
- **Why**: Optimistic nodes return HTTP 503 for attestation requests, causing validator failures

### Execution Client Health Check
- **Endpoint**: `POST /` with `eth_syncing` JSON-RPC call
- **Validation**: Response must contain `"result":false` (fully synced)
- **Why**: Syncing nodes return a sync status object instead of `false`

## Ports

| Port | Service | Description |
|------|---------|-------------|
| 15052 | Beacon Node Fallback | HAProxy frontend for consensus clients |
| 18545 | Execution Client Fallback | HAProxy frontend for execution clients |
| 8404 | Stats Page | HAProxy monitoring dashboard |

## Common Commands

### Check HAProxy Status
```bash
sudo systemctl status haproxy
```

### View Backend Health
```bash
curl -s "http://127.0.0.1:8404/stats;csv" | grep -E "^beacon_nodes|^execution_clients" | awk -F',' '{print $1, $2, $18}'
```

### Reload Configuration (without downtime)
```bash
sudo haproxy -c -f /etc/haproxy/haproxy.cfg  # Validate first
sudo systemctl reload haproxy
```

### Restart HAProxy
```bash
sudo systemctl restart haproxy
```

### View Logs
```bash
sudo journalctl -u haproxy -f
```

### Test Fallback Endpoints
```bash
# Test beacon node
curl -s "http://localhost:15052/eth/v1/node/identity" | jq '.data.peer_id'

# Test execution client
curl -s -X POST -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' \
  "http://localhost:18545" | jq '.result'
```

### Check Which Backend is Active
```bash
curl -s "http://127.0.0.1:8404/stats;csv" | grep beacon_nodes | grep -v BACKEND | head -1 | awk -F',' '{print "Active: " $2}'
```

## Monitoring

### Web Dashboard
Access the HAProxy stats page at: `http://cloudvero:8404/stats`

Shows:
- Backend server status (UP/DOWN)
- Connection counts
- Response times
- Error rates

### CLI Monitoring
```bash
# Watch backend status in real-time
watch -n5 'curl -s "http://127.0.0.1:8404/stats;csv" | grep -E "beacon_nodes|execution_clients" | awk -F"," "{print \$1, \$2, \$18}"'
```

## Failover Behavior

1. **Normal operation**: All requests go to `minipcamd4` (ryzen7 - first healthy server, lowest latency)
2. **If minipcamd4 fails**: After 2 failed health checks (~10s), traffic shifts to `minipcamd2` (lido188)
3. **If minipcamd4 recovers**: After 2 successful health checks (~10s), traffic returns to `minipcamd4` (ryzen7)

This "first available" strategy minimizes latency while providing automatic failover.

## Troubleshooting

### HAProxy won't start
```bash
# Check for config errors
sudo haproxy -c -f /etc/haproxy/haproxy.cfg

# Check logs
sudo journalctl -u haproxy --no-pager -n 50
```

### HAProxy fails with "could not resolve address"
If you see errors like:
```
[ALERT] : 'server beacon_nodes/minipcamd4' : could not resolve address 'minipcamd4.velociraptor-scylla.ts.net'
```

**Cause**: HAProxy by default resolves DNS only at startup. If Tailscale MagicDNS isn't fully ready when HAProxy starts, resolution fails.

**Solution**: Ensure the config has:
1. A `resolvers` section pointing to the local DNS stub (127.0.0.53)
2. `resolvers tailscale init-addr none` on each server line

This allows HAProxy to:
- Start even if DNS isn't immediately available (`init-addr none`)
- Resolve DNS at runtime using the system resolver
- Automatically update IPs when they change

```bash
# Verify DNS resolution works
nslookup minipcamd4.velociraptor-scylla.ts.net

# If it fails, check Tailscale status
tailscale status
```

### All backends showing DOWN
- Check if nodes are reachable: `ping minipcamd4.velociraptor-scylla.ts.net`
- Check if beacon API is responding: `curl http://minipcamd4.velociraptor-scylla.ts.net:5052/eth/v1/node/health`
- (minipcamd4 = ryzen7)
- Check Tailscale connectivity: `tailscale status`

### Hyperdrive not using fallback
- Verify Hyperdrive config: `grep -A3 'fallback:' ~/.hyperdrive/user-settings.yml`
- Restart Hyperdrive: `hyperdrive service stop -y && hyperdrive service start -y`

### tsdproxy endpoints not working
```bash
# Check if eth-proxy containers are running
cd /home/egk/eth-proxy && docker compose ps

# Check tsdproxy logs
docker logs eth-tsdproxy

# Check if endpoints appear in Tailscale
tailscale status | grep -E 'beaconapi|ethereum-rpc'

# Test endpoints directly
curl -s https://beaconapi.velociraptor-scylla.ts.net/eth/v1/node/syncing
curl -s -X POST -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' \
  https://ethereum-rpc.velociraptor-scylla.ts.net

# If timeout, check if HAProxy is running
sudo systemctl status haproxy

# Check UFW firewall allows Docker networks to reach HAProxy
sudo ufw status | grep -E '15052|18545'
```

### Restart eth-proxy stack
```bash
cd /home/egk/eth-proxy
docker compose down
docker compose up -d
```

## Boot Order Configuration

To prevent HAProxy failures after VM reboots/upgrades, a systemd override ensures HAProxy waits for Tailscale:

### Systemd Override: `/etc/systemd/system/haproxy.service.d/tailscale.conf`

```ini
[Unit]
# Wait for Tailscale to be up before starting HAProxy
After=tailscaled.service
Wants=tailscaled.service

# Add extra delay to ensure MagicDNS is ready
ExecStartPre=/bin/sleep 5
```

### Create the override:
```bash
sudo mkdir -p /etc/systemd/system/haproxy.service.d
sudo tee /etc/systemd/system/haproxy.service.d/tailscale.conf > /dev/null << 'EOF'
[Unit]
After=tailscaled.service
Wants=tailscaled.service
ExecStartPre=/bin/sleep 5
EOF
sudo systemctl daemon-reload
```

This combined with the `resolvers` config and `init-addr none` provides robust protection against boot timing issues.

## Adding/Removing Backend Nodes

### Add a new node
1. Edit `/etc/haproxy/haproxy.cfg`
2. Add server line to both `beacon_nodes` and `execution_clients` backends
3. Position by latency (lower latency = higher in list)
4. Validate and reload:
   ```bash
   sudo haproxy -c -f /etc/haproxy/haproxy.cfg
   sudo systemctl reload haproxy
   ```

### Remove a node
1. Edit `/etc/haproxy/haproxy.cfg`
2. Remove or comment out the server lines
3. Validate and reload

## tsdproxy Proxy Management

### Config Location
```
~/homelab/tsdproxy/config/
├── tsdproxy.yaml        # Main config (defines file providers)
└── eth-proxies.yaml     # HAProxy endpoints (auto-reloads on change)
```

### Common commands
```bash
# Edit proxy list (auto-reloads)
nano ~/homelab/tsdproxy/config/eth-proxies.yaml

# Restart tsdproxy (only needed for tsdproxy.yaml changes)
docker restart tsdproxy

# Check Tailscale endpoints
tailscale status | grep -E 'beaconapi|ethereum-rpc'

# View tsdproxy logs
docker logs tsdproxy -f
```

**Note**: Changes to `eth-proxies.yaml` are auto-reloaded. Only restart tsdproxy when modifying `tsdproxy.yaml`.

## Setup Date
- Initial HAProxy setup: December 12, 2025
- Migrated to Tailscale Serve: December 19, 2025
- Switched to tsdproxy file-based proxy list: December 20, 2025

## Related Documentation
- [Hyperdrive Documentation](https://docs.nodeset.io/)
- [HAProxy Documentation](https://www.haproxy.org/documentation/)
- [tsdproxy Documentation](https://almeidapaulopt.github.io/tsdproxy/)
- [Ethereum Beacon API](https://ethereum.github.io/beacon-APIs/)

# HAProxy Load Balancer for Hyperdrive Fallback

## Overview

This document describes the HAProxy setup on **cloudvero** that provides multi-node fallback redundancy for the Hyperdrive validator client.

**Problem**: Hyperdrive only supports a single fallback URL for beacon and execution clients.

**Solution**: HAProxy load balancer that aggregates multiple backend nodes and presents a single endpoint to Hyperdrive.

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
   │ ryzen7    │            │ rocketpool│                  │ bropi     │
   │ lido188   │            │           │                  │           │
   │ lido102   │            │           │                  │           │
   └───────────┘            └───────────┘                  └───────────┘
```

## Backend Nodes (Fallback Pool)

Ordered by latency from cloudvero (US East). `balance first` mode uses the first healthy server.

| Priority | Node | Tailscale Domain | Latency | Consensus | Execution |
|----------|------|------------------|---------|-----------|-----------|
| 1 | ryzen7 | minipcamd4.velociraptor-scylla.ts.net | ~18ms | Nimbus :5052 | Erigon :8545 |
| 2 | lido188 | minipcamd2.velociraptor-scylla.ts.net | ~18ms | Teku :5052 | Geth :8545 |
| 3 | lido102 | minipcamd.velociraptor-scylla.ts.net | ~19ms | Lighthouse :5052 | Nethermind :8545 |
| 4 | rocketpool | minitx.velociraptor-scylla.ts.net | ~124ms | Teku :5052 | Geth :8545 |
| 5 | bropi | orangepi5-plus.velociraptor-scylla.ts.net | ~148ms | Grandine :5052 | Nethermind :8545 |

**Note**: `nodeset` is excluded from the fallback pool because it's the primary node. If nodeset fails, we don't want the fallback to try it too.

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
frontend beacon_node_fallback
    bind *:15052
    default_backend beacon_nodes

backend beacon_nodes
    balance first
    option httpchk GET /eth/v1/node/health
    http-check expect status 200-206
    
    # Ordered by latency from cloudvero (US East)
    # Canada nodes (~18ms) - lowest latency first
    server ryzen7      minipcamd4.velociraptor-scylla.ts.net:5052     check inter 5s fall 3 rise 2
    server lido188     minipcamd2.velociraptor-scylla.ts.net:5052     check inter 5s fall 3 rise 2
    server lido102     minipcamd.velociraptor-scylla.ts.net:5052      check inter 5s fall 3 rise 2
    # Brazil nodes (~124-148ms) - higher latency last
    server rocketpool  minitx.velociraptor-scylla.ts.net:5052         check inter 5s fall 3 rise 2
    server bropi       orangepi5-plus.velociraptor-scylla.ts.net:5052 check inter 5s fall 3 rise 2

# =============================================
# EXECUTION CLIENT LOAD BALANCER
# =============================================
frontend execution_client_fallback
    bind *:18545
    default_backend execution_clients

backend execution_clients
    balance first
    option httpchk POST /
    http-check send hdr Content-Type application/json body "{\"jsonrpc\":\"2.0\",\"method\":\"eth_syncing\",\"params\":[],\"id\":1}"
    http-check expect status 200
    
    # Ordered by latency from cloudvero (US East)
    # Canada nodes (~18ms) - lowest latency first
    server ryzen7      minipcamd4.velociraptor-scylla.ts.net:8545     check inter 5s fall 3 rise 2
    server lido188     minipcamd2.velociraptor-scylla.ts.net:8545     check inter 5s fall 3 rise 2
    server lido102     minipcamd.velociraptor-scylla.ts.net:8545      check inter 5s fall 3 rise 2
    # Brazil nodes (~124-148ms) - higher latency last
    server rocketpool  minitx.velociraptor-scylla.ts.net:8545         check inter 5s fall 3 rise 2
    server bropi       orangepi5-plus.velociraptor-scylla.ts.net:8545 check inter 5s fall 3 rise 2
```

### Hyperdrive Fallback Config: `~/.hyperdrive/user-settings.yml`

```yaml
fallback:
    bnHttpUrl: http://localhost:15052
    ecHttpUrl: http://localhost:18545
    prysmRpcUrl: ""
    useFallbackClients: "true"
```

## Health Check Settings

| Setting | Value | Description |
|---------|-------|-------------|
| `inter` | 5s | Check every 5 seconds |
| `fall` | 3 | Mark unhealthy after 3 failures (~15s) |
| `rise` | 2 | Mark healthy after 2 successes (~10s) |
| `status` | 200-206 | Accept both synced (200) and syncing (206) nodes |

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

1. **Normal operation**: All requests go to `ryzen7` (first healthy server)
2. **If ryzen7 fails**: After 3 failed health checks (~15s), traffic shifts to `lido188`
3. **If ryzen7 recovers**: After 2 successful health checks (~10s), traffic returns to `ryzen7`

This "first available" strategy minimizes latency while providing automatic failover.

## Troubleshooting

### HAProxy won't start
```bash
# Check for config errors
sudo haproxy -c -f /etc/haproxy/haproxy.cfg

# Check logs
sudo journalctl -u haproxy --no-pager -n 50
```

### All backends showing DOWN
- Check if nodes are reachable: `ping minipcamd4.velociraptor-scylla.ts.net`
- Check if beacon API is responding: `curl http://minipcamd4.velociraptor-scylla.ts.net:5052/eth/v1/node/health`
- Check Tailscale connectivity: `tailscale status`

### Hyperdrive not using fallback
- Verify Hyperdrive config: `grep -A3 'fallback:' ~/.hyperdrive/user-settings.yml`
- Restart Hyperdrive: `hyperdrive service stop && hyperdrive service start`

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

## Setup Date
December 12, 2025

## Related Documentation
- [Hyperdrive Documentation](https://docs.nodeset.io/)
- [HAProxy Documentation](https://www.haproxy.org/documentation/)
- [Ethereum Beacon API](https://ethereum.github.io/beacon-APIs/)

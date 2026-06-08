# GitHub Issue: ConflictingIdError in BeaconNode initialization

**Repository:** https://github.com/serenita-org/vero/issues/new

## Issue Title
ConflictingIdError causes cascading failures when beacon nodes become temporarily unreachable

## Issue Body

### Description

When running Vero v1.3.0 with multiple beacon nodes, if one or more beacon nodes become temporarily unreachable (network timeout, brief outage), Vero enters a failure loop where it repeatedly fails to re-initialize the beacon nodes due to APScheduler `ConflictingIdError`.

### Environment

- **Vero version:** v1.3.0 (commit 18a343041f7bee62d7909f1db6d0ec053ec47cbb)
- **Platform:** ARM64 (Orange Pi 5 Plus) / Linux
- **Network:** Ethereum Mainnet
- **Number of beacon nodes:** 6
- **Attestation consensus threshold:** 3

### Beacon Node Geographic Distribution

The 6 beacon nodes are geographically distributed across two regions. Vero runs on a node in São Paulo State, Brazil.

**Measured latencies from Vero host (bropi/orangepi5-plus):**

| Node | Client | Location | Avg Latency |
|------|--------|----------|-------------|
| 100.99.2.41 (local) | Nimbus | São Paulo, Brazil | **0.06ms** |
| minitx | Lodestar¹ | São Paulo, Brazil | **4.1ms** |
| minipcamd4 | Grandine | Toronto, Canada | **137ms** |
| minipcamd | Prysm | Toronto, Canada | **177ms** |
| minipcamd2 | Lighthouse | Toronto, Canada | **147ms** |
| minipcamd3 | Lodestar | Toronto, Canada | **151ms** |

> ¹ Corrected 2026-06-07: minitx runs **Geth + Lodestar** (verified via `web3_clientVersion` / node version API), not Teku. The original "Teku" label was stale.

**Summary:**
- **Brazil (local):** 2 nodes with <5ms latency
- **Toronto (remote):** 4 nodes with 137-177ms latency

This geographic distribution is intentional for redundancy and client diversity, but the ~150ms latency to Toronto nodes may contribute to transient timeouts that trigger the ConflictingIdError cascade. The issue appears more likely to start with timeout errors to the higher-latency Toronto nodes before cascading to all nodes.

### Steps to Reproduce

1. Run Vero with multiple beacon nodes (6 in my case)
2. Wait for a brief network interruption or beacon node timeout
3. Observe the cascade of `ConflictingIdError` messages

### Expected Behavior

Vero should gracefully handle beacon node reconnection by either:
- Removing existing jobs before re-adding them
- Using `replace_existing=True` when adding APScheduler jobs
- Catching `ConflictingIdError` and handling it gracefully

### Actual Behavior

Vero enters a failure loop with continuous error messages:

```
BeaconNode - ERROR: Failed to initialize beacon node at http://...:5052: ConflictingIdError('Job identifier (BeaconNode.update_node_version-http://...:5052) conflicts with an existing job')
```

This continues indefinitely until the container is manually restarted.

### Logs

```
2025-12-09 11:41:27,080 - BeaconNode           - ERROR: Failed to initialize beacon node at http://minipcamd4.velociraptor-scylla.ts.net:5052: ConflictingIdError('Job identifier (BeaconNode.update_node_version-http://minipcamd4.velociraptor-scylla.ts.net:5052) conflicts with an existing job')
2025-12-09 11:41:29,434 - BeaconNode           - ERROR: Failed to initialize beacon node at http://minipcamd4.velociraptor-scylla.ts.net:5052: ConflictingIdError('Job identifier (BeaconNode.update_node_version-http://minipcamd4.velociraptor-scylla.ts.net:5052) conflicts with an existing job')
2025-12-09 11:41:29,566 - BeaconNode           - ERROR: Failed to initialize beacon node at http://minitx.velociraptor-scylla.ts.net:5052: ConflictingIdError('Job identifier (BeaconNode.update_node_version-http://minitx.velociraptor-scylla.ts.net:5052) conflicts with an existing job')
... [continues for all beacon nodes]
```

After restart, the warning about unawaited coroutine appears:
```
/vero/tasks.py:-1: RuntimeWarning: coroutine 'BeaconNode.initialize_full' was never awaited
RuntimeWarning: Enable tracemalloc to get the object allocation traceback
```

After restart, initialization succeeds:
```
2025-12-09 11:42:13,375 - BeaconNode           - INFO : Initialized beacon node at http://100.99.2.41:5052
2025-12-09 11:42:13,391 - BeaconNode           - INFO : Initialized beacon node at http://minitx.velociraptor-scylla.ts.net:5052
... [all 6 nodes initialize successfully]
2025-12-09 11:42:13,816 - MultiBeaconNode      - INFO : Successfully initialized 6/6 beacon nodes
```

### Root Cause Analysis

The issue appears to be in the `BeaconNode` class where `update_node_version` jobs are scheduled. When a beacon node becomes temporarily unreachable:

1. Vero attempts to re-initialize the beacon node
2. The existing scheduled job with ID `BeaconNode.update_node_version-<url>` still exists
3. Adding a new job with the same ID raises `ConflictingIdError`
4. This prevents successful re-initialization

### Suggested Fix

In the beacon node initialization code, when adding the `update_node_version` job:

```python
# Option 1: Use replace_existing=True
scheduler.add_job(
    self.update_node_version,
    trigger='interval',
    ...,
    id=f'BeaconNode.update_node_version-{self.url}',
    replace_existing=True  # Add this
)

# Option 2: Remove existing job before adding
job_id = f'BeaconNode.update_node_version-{self.url}'
try:
    scheduler.remove_job(job_id)
except JobLookupError:
    pass
scheduler.add_job(...)

# Option 3: Catch ConflictingIdError
try:
    scheduler.add_job(...)
except ConflictingIdError:
    # Job already exists, this is fine for re-initialization
    pass
```

### Workaround

Currently using a monitoring script that detects the error pattern and auto-restarts the container:

```bash
# Monitor for ConflictingIdError and restart if threshold exceeded
docker logs eth-lido102-validator-1 --since "120s" 2>&1 | grep -c "ConflictingIdError"
```

### Impact

- **Severity:** Medium
- **Impact:** Validator stops attesting until manual restart
- **Workaround available:** Yes (auto-restart script)

### Additional Context

- The issue seems to occur more frequently with higher numbers of beacon nodes
- Brief network hiccups (even 1-2 seconds) can trigger this issue
- The RuntimeWarning about unawaited coroutine suggests there may be related async cleanup issues

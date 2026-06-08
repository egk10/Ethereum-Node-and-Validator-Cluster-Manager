# GitHub Issue: Validator stuck requesting attestation data for stale slot

**Repository:** https://github.com/serenita-org/vero/issues/new

## Issue Title
Validator gets stuck requesting attestation data for stale slot while continuing to attest

## Issue Body

### Description

Vero occasionally enters a state where it continuously requests attestation data for a stale slot (thousands of slots behind current) while still successfully publishing attestations for the current slot. This causes unnecessary load on beacon nodes and fills logs with warnings.

### Environment

- **Vero version:** fix-beacon-node-init branch (commit 38deed372214d352500bc045e8fdda388c78e01d)
- **Platform:** x86_64 Linux (Oracle Cloud)
- **Network:** Ethereum Mainnet
- **Number of beacon nodes:** 6

### Beacon Node Configuration

| Node | Client |
|------|--------|
| minipcamd | Prysm v7.1.0 |
| minipcamd2 | Lighthouse v8.0.1 |
| minipcamd3 | Lodestar v1.37.0 |
| minipcamd4 | Grandine 2.0.1 |
| minitx | Lodestar v1.43.0* |
| orangepi5-plus | Nimbus v25.11.1 |

> \* Corrected 2026-06-07: minitx runs **Geth + Lodestar** (verified via node version API), not Teku. The original "Teku v25.11.1" label was stale.

### Symptoms

Vero continuously requests attestation data for a very old slot while the network has moved on:

```
2025-12-14 21:06:36,340 - BeaconNode - WARNING: Failed to produce attestation data while waiting for checkpoints: BeaconNodeReturnedBadRequest(URL('http://minipcamd.velociraptor-scylla.ts.net:5052/eth/v1/validator/attestation_data?slot=13237984&committee_index=0'), '{"message":"invalid request: slot 13237984 is not the current slot 13243531","code":400}')
```

Key observations:
- **Requested slot:** 13237984
- **Current slot:** 13243531
- **Difference:** 5,547 slots (~18.5 hours behind)
- **Request frequency:** ~50ms between requests (extremely rapid)
- **Attestations still published:** Yes, current slot attestations succeed

### Logs

The warnings repeat every ~50ms:

```
2025-12-14 21:06:36,340 - BeaconNode           - WARNING: Failed to produce attestation data while waiting for checkpoints: BeaconNodeReturnedBadRequest(URL('http://minipcamd.velociraptor-scylla.ts.net:5052/eth/v1/validator/attestation_data?slot=13237984&committee_index=0'), '{"message":"invalid request: slot 13237984 is not the current slot 13243531","code":400}')
2025-12-14 21:06:36,390 - BeaconNode           - WARNING: Failed to produce attestation data while waiting for checkpoints: BeaconNodeReturnedBadRequest(...)
2025-12-14 21:06:36,441 - BeaconNode           - WARNING: Failed to produce attestation data while waiting for checkpoints: BeaconNodeReturnedBadRequest(...)
... [continues indefinitely every ~50ms]

2025-12-14 21:06:37,830 - AttestationService   - INFO : Published attestations for slot 13243531, count: 1, head root: 0x7f69b6e3...
```

After restart, the issue is resolved:

```
2025-12-14 21:07:01,355 - vero-init            - INFO : Starting vero fix-beacon-node-init (commit 38deed372214d352500bc045e8fdda388c78e01d)
2025-12-14 21:07:01,975 - MultiBeaconNode      - INFO : Successfully initialized 6/6 beacon nodes
2025-12-14 21:07:02,029 - vero-init            - INFO : Current epoch: 413860
2025-12-14 21:07:02,029 - vero-init            - INFO : Current slot: 13243533
```

### Expected Behavior

1. Vero should not request attestation data for slots that are significantly in the past
2. If a stale slot request fails, Vero should recognize the slot is outdated and stop retrying
3. Any pending/stuck tasks for old slots should be cleaned up

### Actual Behavior

1. Vero gets stuck in a loop requesting data for a slot that is ~5,500+ slots behind
2. The requests continue indefinitely at ~20 requests/second
3. Only a container restart resolves the issue

### Root Cause Hypothesis

This appears to be related to the attestation duty tracking or checkpoint waiting logic. Possible causes:

1. An attestation duty task gets "stuck" and never completes or times out
2. The slot number in some internal state is not updated when new slots arrive
3. A race condition where an old duty remains active while new duties are processed
4. The "waiting for checkpoints" logic may have an infinite retry without slot validation

### Suggested Investigation

1. Check where `produce_attestation_data` is called with a slot parameter
2. Look for any slot validation before making the beacon node request
3. Investigate the checkpoint waiting logic that logs "waiting for checkpoints"
4. Check if there's a timeout or slot-staleness check for pending attestation duties

### Workaround

Auto-restart script that detects high frequency of "is not the current slot" errors:

```bash
# Count stale slot errors in last 120 seconds
stale_count=$(docker logs eth-lido-validator-1 --since "120s" 2>&1 | grep -c "is not the current slot" || true)
if [ "$stale_count" -ge 50 ]; then
    docker restart eth-lido-validator-1
fi
```

### Impact

- **Severity:** Low-Medium
- **Validator impact:** Attestations still succeed (surprisingly)
- **Resource impact:** High - unnecessary beacon node requests (~20/sec)
- **Log impact:** Fills logs with warnings
- **Workaround available:** Yes (auto-restart script)

### Relationship to Other Issues

This may be related to the ConflictingIdError issue previously reported, as both involve stale internal state that persists after some event. The fix-beacon-node-init branch addresses ConflictingIdError but this stale slot issue still occurs.

### Additional Context

- The slot was exactly 5,547 slots behind, suggesting this may have started at a specific point and never recovered
- The validator continued to successfully publish attestations for current slots during this time
- The issue occurred after ~5 days of uptime

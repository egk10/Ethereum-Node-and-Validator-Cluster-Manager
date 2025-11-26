# ethd Update Integration

## Overview

eth-manager now uses `./ethd update --non-interactive` to upgrade Ethereum clients instead of running raw git and Docker commands. This change fixes recurring file ownership issues that occurred during upgrades.

## Why This Matters

### The Problem

When eth-manager upgraded nodes, it would:
1. SSH as root user
2. Run `git pull` directly as root
3. Create new files with root:root ownership

This conflicted with ethd's expectation that files are owned by the directory owner (egk).

### The Solution

eth-docker's `ethd update` command has built-in owner detection:
1. Detects the directory owner
2. If run as root, uses `sudo -u egk` for git operations
3. Ensures all new files are owned by egk:egk
4. Automatically fixes permissions after operations

## Implementation Details

### Code Changes

**File:** `eth_validators/node_manager.py`

1. **Added validation function:**
   - `_validate_ethd_exists()` - Checks if ethd script exists before upgrade

2. **Modified upgrade functions:**
   - `_upgrade_single_network_node()` - Uses `./ethd update --non-interactive`
   - `_upgrade_multi_network_node()` - Uses `./ethd update --non-interactive`

3. **Updated timeouts:**
   - Increased from 300s (5 min) to 600s (10 min) to account for ethd's additional checks

### Command

```bash
./ethd update --non-interactive
```

**Flags:**
- `--non-interactive`: Skips prompts and auto-accepts migrations/resyncs (required for automation)

## File Ownership

### Before (Raw Commands)

```
ssh root@node "cd /home/egk/eth-docker && git pull"
# Files created as root:root ❌
```

### After (ethd Update)

```
ssh root@node "cd /home/egk/eth-docker && ./ethd update --non-interactive"
# ethd detects owner = egk
# Runs git as: sudo -u egk
# Files created as egk:egk ✅
```

## Testing

### Verify File Ownership

After upgrade, check that files are owned by egk:

```bash
# On the node
ls -la /home/egk/eth-docker/prometheus/ | head -5
# Expected: All files owned by egk:egk
```

### Verify No Root-Owned Files

```bash
# From management node
for node in minipcamd minipcamd2 minipcamd3 minitx orangepi5-plus; do
  echo "=== $node ==="
  ssh root@$node.velociraptor-scylla.ts.net "find /home/egk/eth-docker -user root | wc -l"
done
# Expected: All output = 0
```

### Test Upgrade

```bash
python3 upgrade_clients.py
```

## Error Handling

If ethd is not found:

```
ethd not found or not executable at /home/egk/eth-docker/ethd

This indicates eth-docker is not properly installed or configured.
```

**Solution:** Verify eth-docker installation:
```bash
ssh root@node "ls -la /home/egk/eth-docker/ethd"
```

## Timeout

If upgrade takes longer than expected:

```
Upgrade timeout after 10 minutes
```

**Reasons:**
- Large container image rebuilds
- Database migrations
- Disk cache pruning
- Network constraints

**Solution:** Check node status and manually run:
```bash
ssh root@node "cd /home/egk/eth-docker && ./ethd logs -f --tail 20"
```

## Migration from Old Behavior

### No Action Needed

If you've previously deployed eth-manager upgrades:
- Old root-owned files will persist
- New files created by `ethd update` will be egk-owned
- eth-manager will continue to work correctly

### Optional: Clean Up Existing Root-Owned Files

```bash
# SSH to node as root
ssh root@node

# Fix ownership on existing files
sudo chown -R egk:egk /home/egk/eth-docker/prometheus/
sudo chown -R egk:egk /home/egk/eth-docker/.eth/
```

## Troubleshooting

### Docker Permissions

If you see docker permission errors after upgrade:

```bash
ssh root@node "cd /home/egk/eth-docker && docker compose logs prometheus | tail -20"
```

### Git Conflicts

If git pull fails:

```bash
ssh root@node "cd /home/egk/eth-docker && git status"
```

### Slow Upgrades

ethd update includes additional checks not in raw commands:
- Disk space validation
- Configuration migration detection
- Permission verification

This is normal and ensures consistency.

## See Also

- `docs/PERMISSION_ISSUE_ROOT_CAUSE.md` - Detailed explanation of the problem
- `eth_validators/node_manager.py` - Implementation
- `upgrade_clients.py` - Integration entry point

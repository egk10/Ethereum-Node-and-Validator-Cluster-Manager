# Automatic Permission Fixing on Client Upgrades

⚠️ **DEPRECATED:** This document describes an implementation approach that has been superseded. The current solution integrates ethd update directly, which **prevents permission issues entirely** rather than fixing them afterwards. See [`ETHD_UPDATE_INTEGRATION.md`](ETHD_UPDATE_INTEGRATION.md) for current implementation.

## Overview (Legacy)

Starting with this version, the Ethereum client upgrade process **automatically fixes file permissions** after each upgrade. This prevents the permission issues that were previously requiring manual fixes after upgrades.

## The Problem We're Solving

When `docker compose up -d` restarts containers during an upgrade:

1. **New files get created** by container processes
2. **Wrong ownership is assigned** - either root or the container's UID
3. **ethd commands fail** when run by the ssh_user (e.g., egk)
4. **chmod warnings appear** when ethd tries to modify files it doesn't own

This was causing the minipcamd permission issues we fixed earlier.

## How It Works Now

### Before: Manual Fix Required
```bash
# Old workflow:
1. python3 upgrade_clients.py
2. ❌ Upgrade succeeds but permissions are wrong
3. Manual: sudo chown -R egk:egk prometheus/ .eth/
4. Manual: Find and set proper permissions
5. Manual: Restart containers again
```

### After: Automatic & Seamless
```bash
# New workflow:
1. python3 upgrade_clients.py
2. ✅ Upgrade succeeds
3. ✅ Permissions automatically fixed
4. ✅ Containers verified with correct ownership
5. ✅ No manual intervention needed
```

## What Gets Fixed

After each successful upgrade, the system:

### 1. **Determines Target User**
   - For nodes with `/home/egk` in eth_docker_path and ssh_user=root → uses egk user
   - For other configurations → uses the ssh_user
   - This ensures files can be modified by the user running ethd commands

### 2. **Fixes Ownership**
   ```bash
   sudo chown -R {target_user}:{target_user} prometheus/ .eth/
   ```
   - Recursively changes all file ownership
   - Handles both prometheus configs and .eth validator keys

### 3. **Sets Proper Permissions**
   ```bash
   # Directories: rwxr-xr-x (755)
   sudo find prometheus/ .eth/ -type d -exec chmod 755 {} \;
   
   # Files: rw-r--r-- (644)
   sudo find prometheus/ .eth/ -type f -exec chmod 644 {} \;
   ```

### 4. **Error Handling**
   - Uses `|| true` to ignore errors (some files may be inaccessible)
   - Permission fixes are best-effort, don't block upgrade success
   - Errors are logged but don't cascade failures

## Key Features

✅ **Automatic**: Runs after every successful upgrade
✅ **Safe**: Uses best-effort approach, ignores permission errors
✅ **Idempotent**: Safe to run multiple times
✅ **Logged**: Reports success/failure of permission fixes
✅ **User-Aware**: Detects correct target user from config

## Configuration Detection

The system automatically detects the correct user:

```python
# For minipcamd nodes (common configuration):
ssh_user = 'root'
eth_docker_path = '/home/egk/eth-docker'
# → Detects: Use 'egk' as target user (because path contains /home/egk)

# For other nodes:
ssh_user = 'ubuntu'
eth_docker_path = '/home/ubuntu/eth-docker'
# → Detects: Use 'ubuntu' as target user
```

## Upgrade Output Example

```
[1/6] ⏳ Upgrading lido102...
    Domain: minipcamd.velociraptor-scylla.ts.net
    🌐 Internet access detected
    ✅ Upgrade successful!
    🔧 Fixing permissions post-upgrade for lido102...
    ✅ Permissions fixed successfully
```

## Manual Permission Fixing (If Needed)

If you ever need to manually fix permissions on a node:

```bash
# SSH into the node
ssh root@minipcamd.velociraptor-scylla.ts.net

# Navigate to eth-docker
cd /home/egk/eth-docker

# Run the fix (same as automatic process)
sudo chown -R egk:egk prometheus/ .eth/
sudo find prometheus/ .eth/ -type d -exec chmod 755 {} \;
sudo find prometheus/ .eth/ -type f -exec chmod 644 {} \;

# Restart containers
docker compose down && docker compose up -d
```

Or use the provided script:
```bash
scripts/fix-minipcamd-prometheus-ownership.sh
```

## Verification

After upgrade, verify permissions are correct:

```bash
ssh root@minipcamd.velociraptor-scylla.ts.net "cd /home/egk/eth-docker && ls -la prometheus/ .eth/ | head -10"

# Should show:
# -rw-r--r--  1 egk egk  ... (files owned by egk)
# drwxr-xr-x  5 egk egk  ... (directories owned by egk)
```

Test that ethd commands work without chmod warnings:

```bash
ssh root@minipcamd.velociraptor-scylla.ts.net "cd /home/egk/eth-docker && ./ethd keys sign-exit 0xb3d0e69d..."

# Should show clean output with NO chmod warnings
# ✓ Signed voluntary exit for validator...
# ✓ Writing the exit message into file succeeded
```

## Troubleshooting

### Still Seeing chmod Warnings?

1. **Manually run the fix**:
   ```bash
   ssh root@{node} "cd /home/egk/eth-docker && sudo chown -R egk:egk prometheus/ .eth/"
   ```

2. **Verify it worked**:
   ```bash
   ssh root@{node} "ls -la /home/egk/eth-docker/prometheus/ | head -5"
   ```

3. **Restart containers**:
   ```bash
   ssh root@{node} "cd /home/egk/eth-docker && docker compose down && docker compose up -d"
   ```

### Permission Fix Fails During Upgrade?

The upgrade continues even if permission fixing fails (non-blocking).

To fix after the fact:
```bash
ssh root@{node} "cd /home/egk/eth-docker && sudo chown -R egk:egk prometheus/ .eth/ && sudo find prometheus/ .eth/ -type f -exec chmod 644 {} \;"
```

## Technical Details

### Why This Matters

The previous issue on minipcamd:
- Container created files as root during `docker compose up`
- ethd runs as egk user (from egk's ssh session)
- egk can't chmod files owned by root → "Operation not permitted"
- Exit message signing failed with chmod errors

### The Solution

- After upgrade, auto-fix ownership to egk:egk
- Now ethd (running as egk) can modify its own files
- chmod warnings disappear
- All operations work cleanly

### Why After Upgrade?

- Upgrade restarts containers
- Containers may create new files/volumes
- New files may have wrong ownership
- Fixing after upgrade ensures clean state

## Related Files

- **Code**: `eth_validators/node_manager.py` → `_fix_docker_permissions_post_upgrade()`
- **Upgrade Script**: `upgrade_clients.py`
- **Manual Fix Scripts**:
  - `scripts/fix-minipcamd-permissions.sh`
  - `scripts/fix-minipcamd-prometheus-ownership.sh`

## Future Improvements

Possible enhancements:
- [ ] Add logging to track what files were fixed
- [ ] Create a separate permission audit command
- [ ] Add dry-run mode to see what would be fixed
- [ ] Create node-specific permission profiles
- [ ] Monitor for permission issues in production

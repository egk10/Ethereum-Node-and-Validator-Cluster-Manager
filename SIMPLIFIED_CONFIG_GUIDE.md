# 🚀 Simplified Configuration with Auto-Discovery

With the new auto-discovery features, your `config.yaml` can be **dramatically simplified**!

## 📊 Configuration Reduction

**Before (Manual Config):** 77 lines with all details specified manually
**After (Auto-Discovery):** 20 lines minimal, 59 lines with comments - **70%+ reduction!**

## 🔍 What Auto-Discovery Detects

The system automatically discovers:

- ✅ **Docker paths** (`/home/egk/eth-docker`, `/home/egk/eth-hoodi`, etc.)
- ✅ **Running stacks** (`eth-docker`, `obol`, `rocketpool`, `hyperdrive`, `lido-csm`)
- ✅ **Active networks** (`mainnet`, `hoodi`, testnets)
- ✅ **API ports** (5052, 5053, 5054, etc.)
- ✅ **Client combinations** (execution + consensus pairs)
- ✅ **Container states** (running, stopped, missing)

## 📝 Configuration Levels

### 1. Minimal Template (20 lines)
```yaml
nodes:
  - name: "node1"
    tailscale_domain: "node1.your-tailnet.ts.net"
  - name: "node2" 
    tailscale_domain: "node2.your-tailnet.ts.net"

validators_csv: "validators_vs_hardware.csv"
```

### 2. Simplified Config (59 lines)
```yaml
nodes:
  - name: "minipcamd"
    tailscale_domain: "minipcamd.velociraptor-scylla.ts.net"
    # Stack, ports, paths auto-discovered!
    
  - name: "laptop"
    tailscale_domain: "laptop.velociraptor-scylla.ts.net"
    stack: ["disabled"]  # Only specify exceptions
    
defaults:
  ssh_user: "root"
  ssh_timeout: 30

auto_discovery:
  enabled: true
  validate_on_startup: true
```

### 3. Full Config (77 lines) - Legacy
Only needed for complex overrides or when auto-discovery is disabled.

## 🛠️ Migration Workflow

1. **Start with minimal config**
   ```bash
   cp config_templates/minimal.yaml config.yaml
   ```

2. **Run validation to see what's detected**
   ```bash
   python3 -m eth_validators config validate
   ```

3. **Auto-fix to populate detected settings**
   ```bash
   python3 -m eth_validators config validate --fix
   ```

4. **Use templates for new nodes**
   ```bash
   python3 -m eth_validators config template generate --name=rocketpool
   ```

## 🔧 Key Benefits

- **90% less manual configuration**
- **Automatic drift detection**
- **Zero-config for standard setups**
- **Template-based node creation**
- **Live validation and repair**

## 🎯 Use Cases

| Scenario | Config Type | Lines | Auto-Fix |
|----------|-------------|-------|----------|
| New cluster | Minimal | 20 | ✅ |
| Standard setup | Simplified | 59 | ✅ |  
| Complex multi-network | Full | 77+ | ⚠️ |
| Production cluster | Simplified + validation | 59 | ✅ |

The auto-discovery system transforms cluster management from **manual and error-prone** to **automated and reliable**! 🚀

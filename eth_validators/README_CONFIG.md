# 📝 Configuration Files Guide

This directory contains all the configuration files needed to run the Ethereum Node and Validator Cluster Manager.

## 📁 Files Overview

### 🔧 Configuration Files
| File | Purpose | Usage |
|------|---------|-------|
| `config.sample.yaml` | **🎯 Public sample configuration** | Copy to `config.yaml` and customize |
| `config.simple.yaml` | **⚡ Simplified config example** | Shows minimal configuration with auto-discovery |
| `config.yaml` | **🔒 Your actual configuration** | *Keep private - contains your real domains* |
| `validators_vs_hardware.sample.csv` | **📊 Validator mapping example** | Copy to `validators_vs_hardware.csv` |
| `validators_vs_hardware.csv` | **🔒 Your validator mappings** | *Keep private - contains real validator data* |

### 📋 Template Files
| File | Description |
|------|-------------|
| `../config_templates/minimal.yaml` | Ultra-minimal config template (20 lines) |

## 🚀 Quick Start

### 1. **First-time Setup**
```bash
# Copy sample configuration
cp config.sample.yaml config.yaml
cp validators_vs_hardware.sample.csv validators_vs_hardware.csv

# Edit with your actual details
nano config.yaml
```

### 2. **Validate Configuration**
```bash
# Check configuration
python3 -m eth_validators config validate

# Auto-fix detected issues
python3 -m eth_validators config validate --fix
```

### 3. **Use Templates for New Nodes**
```bash
# See available templates
python3 -m eth_validators config template list

# Generate RocketPool node config
python3 -m eth_validators config template generate --name=rocketpool
```

## 🔍 Auto-Discovery Features

The system can automatically detect:
- ✅ **Docker paths** (`/home/user/eth-docker`)
- ✅ **Running stacks** (`eth-docker`, `obol`, `rocketpool`)
- ✅ **API ports** (5052, 5053, etc.)
- ✅ **Active networks** (`mainnet`, testnets)
- ✅ **Client versions** (execution + consensus pairs)

This means you can start with a minimal config and let auto-discovery fill in the details!

## 📊 Configuration Complexity Levels

### Level 1: **Minimal** (20 lines)
```yaml
nodes:
  - name: "node1"
    tailscale_domain: "node1.your-tailnet.ts.net"
validators_csv: "validators_vs_hardware.csv"
```

### Level 2: **Simplified** (60 lines)
- Basic node definitions
- Auto-discovery enabled
- Comments and guidance

### Level 3: **Complete** (80+ lines)
- Full manual configuration
- All options specified
- Complex multi-network setups

## 🛡️ Security Notes

### ⚠️ **Never commit to public repos:**
- `config.yaml` - Contains your actual Tailscale domains
- `validators_vs_hardware.csv` - Contains real validator indices and keys

### ✅ **Safe for public repos:**
- `config.sample.yaml` - Sanitized example
- `validators_vs_hardware.sample.csv` - Fake validator data
- All template files

## 🔧 Supported Stacks

| Stack | Description | Auto-Detected |
|-------|-------------|---------------|
| `eth-docker` | Standard ETH-Docker setup | ✅ |
| `obol` | Obol Distributed Validators | ✅ |
| `rocketpool` | RocketPool liquid staking | ✅ |
| `hyperdrive` | NodeSet Hyperdrive | ✅ |
| `lido-csm` | Lido Community Staking | ✅ |
| `ssv` | SSV Network | 🚧 |
| `stakewise` | StakeWise V3 | 🚧 |

## 🎯 Best Practices

1. **Start minimal** - Use auto-discovery to fill gaps
2. **Validate frequently** - Run `config validate` after changes  
3. **Use templates** - Generate consistent configurations
4. **Keep backups** - Auto-discovery creates config backups
5. **Monitor drift** - System alerts when config diverges from reality

## 🆘 Troubleshooting

### Config validation fails?
```bash
python3 -m eth_validators config validate --fix
```

### Need a fresh start?
```bash
cp config.sample.yaml config.yaml
python3 -m eth_validators config validate --fix
```

### Want to see what's detected?
```bash
python3 -m eth_validators config discover
```

## 🔗 Related Commands

- `python3 -m eth_validators node list` - Show cluster overview
- `python3 -m eth_validators config summary` - Configuration statistics  
- `python3 -m eth_validators config template list` - Available templates

---

💡 **Pro Tip**: Start with `config_templates/minimal.yaml`, run `config validate --fix`, and let auto-discovery do the heavy lifting!

# 🚀 Ethereum Node and Validator Cluster Manager v1.0.6

## Installation Guide & Quick Start Examples

**Latest Release**: v1.0.6 - Consolidated CLI with Enhanced Charon Automation

---

## 📦 Quick Installation Options

### Option 1: Easy Install (Recommended)
```bash
# Download and auto-install
curl -fsSL https://github.com/egk10/Ethereum-Node-and-Validator-Cluster-Manager/releases/download/v1.0.6/install.sh | bash

# Or manual download
wget https://github.com/egk10/Ethereum-Node-and-Validator-Cluster-Manager/releases/download/v1.0.6/ethereum-validator-manager-standard-v1.0.6.zip
unzip ethereum-validator-manager-standard-v1.0.6.zip
cd ethereum-validator-manager-standard-v1.0.6
./install.sh
```

### Option 2: Docker (Multi-Architecture)
```bash
# Pull latest image
docker pull egk10/ethereum-node-and-validator-cluster-manager:1.0.6

# Or specific variant
docker pull egk10/ethereum-node-and-validator-cluster-manager:1.0.6-full
```

---

## 🎯 Release Variants

| Variant | Size | Features | Best For |
|---------|------|----------|----------|
| **Core** | ~15MB | Essential validator management | Basic setups |
| **Standard** | ~25MB | Core + backup + performance | Most users |
| **Monitoring** | ~35MB | Standard + Grafana/Prometheus | Production |
| **Full** | ~45MB | All features + AI analysis | Advanced users |

---

## ⚡ Quick Start Examples

### 1. Initial Setup
```bash
# Install dependencies
python3 -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows
pip install -r requirements.txt

# Configure your nodes
cp eth_validators/config.yaml.example eth_validators/config.yaml
# Edit config.yaml with your node details
```

### 2. Essential Commands (New Consolidated CLI)

```bash
# List all nodes with client diversity analysis
python3 -m eth_validators node list

# Check live client versions across all nodes
python3 -m eth_validators node versions --all

# Upgrade Docker containers on all nodes
python3 -m eth_validators node upgrade --all

# Inspect validator duties for specific node
python3 -m eth_validators node inspect minipcamd.velociraptor-scylla.ts.net

# Update Charon on Obol distributed validator nodes
python3 -m eth_validators node update-charon --dry-run
python3 -m eth_validators node update-charon
```

### 3. Performance Monitoring
```bash
# Get performance summary for all validators
python3 -m eth_validators performance summary

# AI-powered log analysis (Full variant only)
python3 -m eth_validators ai analyze minipcamd --hours 24

# Get AI health scores
python3 -m eth_validators ai health
```

### 4. Validator Management
```bash
# Sync validator CSV with beacon node status
python3 -m eth_validators validator sync

# List active validators only
python3 -m eth_validators validator list-active

# Search validators by protocol or node
python3 -m eth_validators validator search "CSM LIDO"

# Get detailed validator statistics
python3 -m eth_validators validator stats
```

---

## 🐳 Docker Usage Examples

### Basic Docker Setup
```bash
# Create workspace directory
mkdir -p ~/ethereum-validator-manager
cd ~/ethereum-validator-manager

# Run with volume mounting
docker run -it --rm \
  -v $(pwd):/workspace \
  -w /workspace \
  egk10/ethereum-node-and-validator-cluster-manager:1.0.6 \
  python3 -m eth_validators node list
```

### Production Docker Setup
```bash
# Create persistent container
docker run -d --name validator-manager \
  --restart unless-stopped \
  -v ~/validator-config:/app/eth_validators \
  -p 8080:8080 \
  egk10/ethereum-node-and-validator-cluster-manager:1.0.6-monitoring

# Execute commands in running container
docker exec validator-manager python3 -m eth_validators node versions --all
docker exec validator-manager python3 -m eth_validators performance summary
```

### Docker Compose Setup
```yaml
# docker-compose.yml
version: '3.8'
services:
  validator-manager:
    image: egk10/ethereum-node-and-validator-cluster-manager:1.0.6-standard
    container_name: validator-manager
    restart: unless-stopped
    volumes:
      - ./config:/app/eth_validators
      - ./data:/app/data
    environment:
      - PYTHONUNBUFFERED=1
    command: ["tail", "-f", "/dev/null"]  # Keep container running

# Usage
docker-compose up -d
docker-compose exec validator-manager python3 -m eth_validators node list
```

---

## 🎯 Command Reference (v1.0.6 Consolidated CLI)

### Node Management Commands
```bash
# Static cluster overview
python3 -m eth_validators node list

# Live client versions and sync status
python3 -m eth_validators node versions <node_name>
python3 -m eth_validators node versions --all

# Docker container upgrades
python3 -m eth_validators node upgrade <node_name>
python3 -m eth_validators node upgrade --all

# Live validator duties inspection
python3 -m eth_validators node inspect <node_name>

# Charon updates for Obol nodes
python3 -m eth_validators node update-charon [--dry-run] [--node <name>]
```

### Performance & AI Commands
```bash
# Performance monitoring
python3 -m eth_validators performance summary

# AI analysis (Full variant)
python3 -m eth_validators ai analyze <node_name> [--hours 24]
python3 -m eth_validators ai health [--threshold 70]
python3 -m eth_validators ai patterns <node_name> [--days 7]
python3 -m eth_validators ai recommend <node_name> [--focus performance]
```

### Validator Management
```bash
# Validator synchronization and management
python3 -m eth_validators validator sync [--dry-run]
python3 -m eth_validators validator status [--show-exited]
python3 -m eth_validators validator list-active [--format table]
python3 -m eth_validators validator search <term>
python3 -m eth_validators validator stats
```

### System Commands
```bash
# System updates and maintenance
python3 -m eth_validators system updates [node_name]
python3 -m eth_validators system upgrade [node_name] [--all]
python3 -m eth_validators system reboot <node_name>
```

---

## 🔧 Configuration

### Basic config.yaml Setup
```yaml
nodes:
  - name: "mainnode"
    tailscale_domain: "mainnode.velociraptor-scylla.ts.net"
    ssh_user: "root"
    exec_client: "geth"
    consensus_client: "lighthouse"
    beacon_api_port: 5052
    stack: ["eth-docker"]
    
  - name: "obolnode"
    tailscale_domain: "obolnode.velociraptor-scylla.ts.net"
    ssh_user: "egk"
    exec_client: "nethermind"
    consensus_client: "teku"
    beacon_api_port: 5052
    stack: ["obol", "charon"]
```

### Multi-Network Configuration
```yaml
nodes:
  - name: "multinode"
    tailscale_domain: "multinode.example.ts.net"
    ssh_user: "root"
    networks:
      mainnet:
        network: "mainnet"
        exec_client: "geth"
        consensus_client: "lighthouse"
        beacon_api_port: 5052
      testnet:
        network: "holesky" 
        exec_client: "nethermind"
        consensus_client: "teku"
        beacon_api_port: 5053
    stack: ["eth-docker"]
```

---

## 🚀 What's New in v1.0.6

### ✨ Major CLI Improvements
- **Consolidated Commands**: Reduced from 10+ commands to 5 streamlined commands
- **Enhanced Charon Detection**: Now executes actual `charon version` inside containers
- **Professional Interface**: Emoji indicators and consistent command structure
- **GitHub API Integration**: Real-time latest version checking

### 🎯 New Features
- `node inspect`: Renamed from `analyze` with enhanced validator duty inspection
- `node update-charon`: Automated Charon updates for Obol distributed validators
- `node versions --all`: Consolidated client version checking with update indicators
- Enhanced table formats with `🔄` (update needed) and `✅` (current) indicators

### 🔧 Infrastructure Improvements
- Comprehensive Charon update script with auto-discovery
- Enhanced multi-network support for complex configurations
- Improved error handling and status reporting
- Professional CLI descriptions and help text

---

## 📊 Usage Examples by Scenario

### Daily Operations
```bash
# Morning health check
python3 -m eth_validators node list
python3 -m eth_validators performance summary

# Check for updates
python3 -m eth_validators node versions --all

# Update if needed
python3 -m eth_validators node upgrade --all
```

### Obol Distributed Validator Management
```bash
# Check Charon versions
python3 -m eth_validators node versions --all | grep -i charon

# Update Charon (dry run first)
python3 -m eth_validators node update-charon --dry-run
python3 -m eth_validators node update-charon

# Inspect validator duties
python3 -m eth_validators node inspect obol-node-1
```

### Troubleshooting
```bash
# Deep validator inspection
python3 -m eth_validators node inspect problematic-node

# AI-powered analysis (Full variant)
python3 -m eth_validators ai analyze problematic-node --hours 6
python3 -m eth_validators ai recommend problematic-node --focus reliability

# Check validator status
python3 -m eth_validators validator sync
python3 -m eth_validators validator search "problematic-node"
```

---

## 🆘 Support & Documentation

- **GitHub Issues**: [Report bugs or request features](https://github.com/egk10/Ethereum-Node-and-Validator-Cluster-Manager/issues)
- **Documentation**: [Full documentation in repository](https://github.com/egk10/Ethereum-Node-and-Validator-Cluster-Manager)
- **Discord**: [Community support](https://discord.gg/ethereum-staking)

---

## 🎉 Ready to Start!

Choose your installation method above and start managing your Ethereum validator cluster with professional-grade tools and AI-powered insights!

```bash
# Quick test after installation
python3 -m eth_validators --help
python3 -m eth_validators node --help
```

**Happy Staking!** 🚀⚡🔥

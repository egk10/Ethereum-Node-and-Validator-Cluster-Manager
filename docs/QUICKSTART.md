# 🚀 Ethereum Validator Cluster Manager - Quick Start

**Get started in under 5 minutes!** This tool automatically manages your Ethereum validators with zero manual CSV files.

## ⚡ One-Command Setup

```bash
# Download and install
git clone https://github.com/egk10/Ethereum-Node-and-Validator-Cluster-Manager.git
cd Ethereum-Node-and-Validator-Cluster-Manager

# Install dependencies
pip3 install -r requirements.txt

# Interactive setup - answers just a few questions!
python3 -m eth_validators quickstart
```

That's it! The tool will:
- ✅ Ask you simple questions about your setup
- ✅ Generate all configuration files automatically  
- ✅ Discover your validators automatically
- ✅ Set up monitoring and automation

## 🎯 What You'll Be Asked

The interactive setup only asks for essentials:

1. **Cluster name** (e.g., "my-validators")
2. **Network** (mainnet/holesky/sepolia) 
3. **Your nodes** (name and hostname/IP)
4. **Monitoring preferences** (auto-discovery frequency)

No complex configuration files, no manual CSV creation!

## 📊 Daily Usage

Once set up, everything is automated:

```bash
# Check validator status
python3 -m eth_validators validator list

# View performance
python3 -m eth_validators performance summary  

# AI health analysis
python3 -m eth_validators ai health

# Check node status
python3 -m eth_validators node list
```

## 🔄 Automated Features

After quickstart, the tool automatically:
- 🔍 **Discovers validators** from your running nodes
- 📊 **Updates CSV files** with live beacon chain data  
- 🧠 **Monitors performance** and detects issues
- ⚡ **Runs daily/weekly** via cron (optional)

## 🎁 Key Benefits

- **Zero manual setup** - no config files to edit
- **No CSV maintenance** - everything auto-discovered
- **Live data** - always current validator status
- **90% less work** - automated monitoring
- **Production ready** - handles multi-node clusters

## 🆘 Need Help?

```bash
# Any command has help
python3 -m eth_validators <command> --help

# Check your setup status
python3 -m eth_validators validator status

# Re-run setup if needed
python3 -m eth_validators quickstart
```

## 🎯 Perfect For

- **New users** starting from scratch
- **Solo stakers** with 1-5 nodes  
- **Small operators** with multiple protocols
- **Anyone** tired of manual CSV management

**Ready to eliminate validator management complexity?** Run `quickstart` now! 🚀

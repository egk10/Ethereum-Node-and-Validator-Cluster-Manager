#!/usr/bin/env python3
"""
Ethereum Node and Validator Cluster Manager - Release Builder
Generates modular releases for different use cases
"""

import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from release_config import CORE_MODULES, CORE_CONFIG, OPTIONAL_MODULES, RELEASE_TYPES

class ReleaseBuilder:
    def __init__(self, version="1.0.0"):
        self.version = version
        self.project_root = Path(__file__).parent
        self.build_dir = self.project_root / "dist"
        
    def clean_build_dir(self):
        """Clean the build directory"""
        if self.build_dir.exists():
            shutil.rmtree(self.build_dir)
        self.build_dir.mkdir(parents=True, exist_ok=True)
        
    def copy_core_files(self, target_dir):
        """Copy core files to target directory"""
        # Copy core modules
        for module_path in CORE_MODULES:
            src = self.project_root / module_path
            dst = target_dir / module_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.exists():
                shutil.copy2(src, dst)
                
        # Copy core config files
        for config_path in CORE_CONFIG:
            src = self.project_root / config_path
            dst = target_dir / config_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.exists():
                shutil.copy2(src, dst)
                
    def copy_optional_files(self, target_dir, modules):
        """Copy optional module files"""
        for module_name in modules:
            if module_name in OPTIONAL_MODULES:
                for file_path in OPTIONAL_MODULES[module_name]:
                    if file_path.endswith("/"):
                        # Directory
                        src_dir = self.project_root / file_path.rstrip("/")
                        dst_dir = target_dir / file_path.rstrip("/")
                        if src_dir.exists():
                            shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)
                    elif "*" in file_path:
                        # Glob pattern
                        import glob
                        for src in glob.glob(str(self.project_root / file_path)):
                            src_path = Path(src)
                            dst = target_dir / src_path.name
                            shutil.copy2(src_path, dst)
                    else:
                        # Regular file
                        src = self.project_root / file_path
                        dst = target_dir / file_path
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        if src.exists():
                            shutil.copy2(src, dst)
                            
    def create_requirements_file(self, target_dir, dependencies):
        """Create requirements.txt with specified dependencies"""
        req_file = target_dir / "requirements.txt"
        with open(req_file, "w") as f:
            for dep in dependencies:
                f.write(f"{dep}\n")
                
    def create_setup_script(self, target_dir, release_type):
        """Create installation script"""
        setup_content = f"""#!/bin/bash
# Ethereum Node and Validator Cluster Manager - {release_type.title()} Release v{self.version}
# Installation Script

set -e

echo "🚀 Installing Ethereum Node and Validator Cluster Manager ({release_type.title()} Release)"

# Check Python version
if ! python3 --version | grep -q "Python 3\\."; then
    echo "❌ Python 3 is required but not found"
    exit 1
fi

# Create virtual environment
echo "📦 Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Install dependencies
echo "📦 Installing dependencies..."
pip install -r requirements.txt

# Make CLI executable
chmod +x eth_validators/*.py

echo "✅ Installation complete!"
echo ""
echo "🎯 Usage:"
echo "   source venv/bin/activate"
echo "   python3 -m eth_validators --help"
echo ""
echo "📋 Configure your nodes in eth_validators/config.yaml"
echo "💡 See README.md for detailed setup instructions"
"""
        
        setup_file = target_dir / "install.sh"
        with open(setup_file, "w") as f:
            f.write(setup_content)
        os.chmod(setup_file, 0o755)
        
        # Copy easy install scripts if they exist
        for script in ['install.sh', 'install.bat']:
            script_path = self.project_root / script
            if script_path.exists():
                dst_path = target_dir / f"easy-{script}"
                shutil.copy2(script_path, dst_path)
                if script.endswith('.sh'):
                    os.chmod(dst_path, 0o755)
        
    def create_readme(self, target_dir, release_type, description):
        """Create release-specific README"""
        release_info = RELEASE_TYPES[release_type]
        
        readme_content = f"""# Ethereum Node and Validator Cluster Manager
## {release_type.title()} Release v{self.version}

{description}

### 🎯 This Release Includes:
- ✅ Core validator cluster management
- ✅ Multi-network support (mainnet + testnets)
- ✅ Client version monitoring and upgrades
- ✅ Node synchronization status tracking
"""

        if "backup" in release_info["modules"]:
            readme_content += "- ✅ Validator backup management\n"
        if "enhanced_performance" in release_info["modules"]:
            readme_content += "- ✅ Enhanced performance metrics\n"
        if "grafana" in release_info["modules"]:
            readme_content += "- ✅ Grafana/Prometheus monitoring integration\n"
        if "ai" in release_info["modules"]:
            readme_content += "- ✅ AI-powered log analysis (Experimental)\n"
            
        readme_content += f"""

### 🚀 Quick Start:

#### Option 1: Easy Install (Recommended)
```bash
# Extract the release
unzip ethereum-validator-manager-{release_type}-v{self.version}.zip
cd ethereum-validator-manager-{release_type}-v{self.version}

# Easy install (creates simple 'eth-validators' command)
./easy-install.sh

# Use simple commands
eth-validators --help
eth-validators node list
eth-validators performance summary
```

#### Option 2: Manual Install
```bash
# Extract and install
./install.sh
source venv/bin/activate

# Use with python module
python3 -m eth_validators --help
```

### 📋 Requirements:
- Python 3.8+
- SSH access to validator nodes
- Docker-based Ethereum clients (eth-docker recommended)

### 🔧 Configuration:
1. Copy `eth_validators/config.example.yaml` to `eth_validators/config.yaml`
2. Update with your node configurations
3. Configure Tailscale domains or IP addresses
4. Set up SSH keys for remote access

### 📖 Documentation:
- Full documentation: https://github.com/egk10/Ethereum-Node-and-Validator-Cluster-Manager
- Release notes: See CHANGELOG.md

### 🆘 Support:
- Issues: https://github.com/egk10/Ethereum-Node-and-Validator-Cluster-Manager/issues
- Discussions: https://github.com/egk10/Ethereum-Node-and-Validator-Cluster-Manager/discussions

---
Built with ❤️ for the Ethereum validator community
"""
        
        readme_file = target_dir / "README.md"
        with open(readme_file, "w") as f:
            f.write(readme_content)
            
    def build_release(self, release_type):
        """Build a specific release type"""
        if release_type not in RELEASE_TYPES:
            raise ValueError(f"Unknown release type: {release_type}")
            
        release_info = RELEASE_TYPES[release_type]
        release_name = f"ethereum-validator-manager-{release_type}-v{self.version}"
        release_dir = self.build_dir / release_name
        
        print(f"🔨 Building {release_type} release...")
        
        # Create release directory
        release_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy core files
        self.copy_core_files(release_dir)
        
        # Copy optional modules (skip 'core' since it's already copied)
        modules = [m for m in release_info["modules"] if m != "core"]
        self.copy_optional_files(release_dir, modules)
        
        # Create requirements file
        self.create_requirements_file(release_dir, release_info["dependencies"])
        
        # Create setup script
        self.create_setup_script(release_dir, release_type)
        
        # Create release README
        self.create_readme(release_dir, release_type, release_info["description"])
        
        # Create ZIP archive
        zip_path = self.build_dir / f"{release_name}.zip"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(release_dir):
                for file in files:
                    file_path = Path(root) / file
                    arcname = file_path.relative_to(release_dir)
                    zipf.write(file_path, arcname)
                    
        print(f"✅ Created {zip_path}")
        return zip_path
        
    def build_all_releases(self):
        """Build all release types"""
        self.clean_build_dir()
        
        release_files = []
        for release_type in RELEASE_TYPES:
            zip_path = self.build_release(release_type)
            release_files.append(zip_path)
            
        return release_files

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Build Ethereum Validator Manager releases")
    parser.add_argument("--version", default="1.0.0", help="Release version")
    parser.add_argument("--type", choices=list(RELEASE_TYPES.keys()) + ["all"], 
                       default="all", help="Release type to build")
    
    args = parser.parse_args()
    
    builder = ReleaseBuilder(args.version)
    
    if args.type == "all":
        release_files = builder.build_all_releases()
        print(f"\\n🎉 Built {len(release_files)} releases:")
        for file in release_files:
            print(f"   📦 {file}")
    else:
        zip_path = builder.build_release(args.type)
        print(f"\\n🎉 Built release: {zip_path}")

if __name__ == "__main__":
    main()

#!/bin/bash

# 🚀 Ethereum Validator Manager - Easy Install Script
# This script installs the tool and creates a simple 'eth-validators' command

set -e

echo "🚀 Installing Ethereum Validator Cluster Manager..."

# Check if running as root
if [[ $EUID -eq 0 ]]; then
    INSTALL_DIR="/usr/local/bin"
    CONFIG_DIR="/etc/eth-validators"
    DATA_DIR="/var/lib/eth-validators"
    echo "📁 Installing system-wide (requires root)"
else
    INSTALL_DIR="$HOME/.local/bin"
    CONFIG_DIR="$HOME/.config/eth-validators"
    DATA_DIR="$HOME/.local/share/eth-validators"
    echo "📁 Installing for current user"
    
    # Create ~/.local/bin if it doesn't exist and add to PATH
    mkdir -p "$HOME/.local/bin"
    if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
        echo "🔧 Adding ~/.local/bin to PATH..."
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
        export PATH="$HOME/.local/bin:$PATH"
    fi
fi

# Create directories
echo "📂 Creating directories..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$CONFIG_DIR"
mkdir -p "$DATA_DIR"

# Install Python dependencies with a safe fallback
echo "🐍 Installing Python dependencies..."
PKGS=(click pyyaml requests tabulate colorama pandas numpy)
if ! command -v pip3 &> /dev/null; then
    echo "❌ Error: pip3 not found. Please install Python 3 and pip3 (e.g. apt install python3-pip python3-venv)"
    exit 1
fi

# If running inside an existing virtualenv, install there
if [[ -n "$VIRTUAL_ENV" ]]; then
    echo "🔁 Detected active virtualenv; installing into it..."
    pip3 install "${PKGS[@]}"
else
    # Try a per-user install first
    echo "🔁 Trying pip --user install..."
    if pip3 install --user "${PKGS[@]}"; then
        echo "✅ Python packages installed with --user"
    else
        # Fallback: create a dedicated venv in the data directory and install there
        echo "⚠️  --user install failed (common on PEP 668 systems). Creating virtualenv at $DATA_DIR/venv and installing packages there..."
        if python3 -m venv "$DATA_DIR/venv"; then
            # Activate venv for this script session
            # shellcheck disable=SC1091
            source "$DATA_DIR/venv/bin/activate"
            pip install --upgrade pip
            pip install "${PKGS[@]}"
            deactivate || true
            echo "✅ Python packages installed into virtualenv: $DATA_DIR/venv"
        else
            echo "❌ Failed to create virtualenv. On Debian/Ubuntu ensure package 'python3-venv' is installed."
            exit 1
        fi
    fi
fi

# Copy application files
echo "📦 Installing application files..."
cp -r eth_validators "$DATA_DIR/"

# Create the wrapper script
echo "🔧 Creating eth-validators command..."
cat > "$INSTALL_DIR/eth-validators" << 'EOF'
#!/bin/bash

# Ethereum Validator Cluster Manager Wrapper Script
# This script uses a bundled virtualenv when present, otherwise falls back to system python3

# Find the installation directory
if [[ -f "/var/lib/eth-validators/eth_validators/__main__.py" ]]; then
    APP_DIR="/var/lib/eth-validators"
elif [[ -f "$HOME/.local/share/eth-validators/eth_validators/__main__.py" ]]; then
    APP_DIR="$HOME/.local/share/eth-validators"
else
    echo "❌ Error: eth-validators not found. Please run install.sh first."
    exit 1
fi

# Prefer venv inside the app data dir if present
if [[ -x "$APP_DIR/venv/bin/python" ]]; then
    PY="$APP_DIR/venv/bin/python"
else
    PY="python3"
fi

export PYTHONPATH="$APP_DIR:$PYTHONPATH"
cd "$APP_DIR"
"$PY" -m eth_validators "$@"
EOF

# Make the script executable
chmod +x "$INSTALL_DIR/eth-validators"

# Copy configuration files
if [[ -f "eth_validators/config.yaml" ]]; then
    echo "⚙️ Installing configuration..."
    cp eth_validators/config.yaml "$CONFIG_DIR/"
    cp eth_validators/validators_vs_hardware.csv "$CONFIG_DIR/"
fi

# Create config symlink in app directory
ln -sf "$CONFIG_DIR/config.yaml" "$DATA_DIR/eth_validators/config.yaml" 2>/dev/null || true
ln -sf "$CONFIG_DIR/validators_vs_hardware.csv" "$DATA_DIR/eth_validators/validators_vs_hardware.csv" 2>/dev/null || true

echo ""
echo "✅ Installation completed successfully!"
echo ""
echo "🎯 Quick Start:"
echo "   eth-validators --help"
echo "   eth-validators node list"
echo "   eth-validators performance summary"
echo ""
echo "📁 Configuration files:"
echo "   Config: $CONFIG_DIR/config.yaml"
echo "   Nodes:  $CONFIG_DIR/validators_vs_hardware.csv"
echo ""
echo "🔧 To configure your nodes, edit:"
echo "   nano $CONFIG_DIR/validators_vs_hardware.csv"
echo ""

# Test the installation
if command -v eth-validators &> /dev/null; then
    echo "🧪 Testing installation..."
    if eth-validators --help > /dev/null 2>&1; then
        echo "✅ Installation test passed!"
    else
        echo "⚠️  Installation test failed, but files are installed."
    fi
else
    echo "⚠️  Command 'eth-validators' not found in PATH."
    echo "💡 You may need to restart your terminal or run:"
    echo "   source ~/.bashrc"
fi

echo ""
echo "🚀 Ready to manage your Ethereum validators!"

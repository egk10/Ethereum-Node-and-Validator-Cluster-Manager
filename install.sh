#!/bin/bash
# Ethereum Node and Validator Cluster Manager - Unified Release v1.1.3
# Installation Script
set -e

echo "🚀 Installing Ethereum Node and Validator Cluster Manager (Unified Release)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ Python 3 is required but not found"; exit 1
fi

echo "📦 Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

echo "📦 Installing dependencies..."
pip install -r requirements.txt

chmod +x eth_validators/*.py || true

echo "✅ Installation complete!"
echo ""
echo "🎯 Usage:"
echo "   source venv/bin/activate"
echo "   python3 -m eth_validators --help"
echo ""
echo "📋 Generate your config via: python3 -m eth_validators quickstart"
echo "💡 See README.md for detailed setup instructions"

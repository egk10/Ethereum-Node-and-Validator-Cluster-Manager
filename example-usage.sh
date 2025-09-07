#!/bin/bash
# Example usage script demonstrating the abstracted interface
# This shows how users can now use simple commands without Python knowledge

echo "🚀 Ethereum Node and Validator Cluster Manager - Usage Examples"
echo ""

# Check if we're in the project directory
if [[ ! -f "eth-manager" ]]; then
    echo "❌ Please run this script from the project root directory"
    exit 1
fi

echo "1️⃣  Basic help:"
./eth-manager --help
echo ""

echo "2️⃣  Quick start wizard:"
echo "   ./eth-manager quickstart"
echo ""

echo "3️⃣  Node status check:"
echo "   ./eth-manager node status"
echo ""

echo "4️⃣  Validator discovery:"
echo "   ./eth-manager validator discover"
echo ""

echo "5️⃣  Performance monitoring:"
echo "   ./eth-manager performance summary"
echo ""

echo "6️⃣  System updates:"
echo "   ./eth-manager system update"
echo ""

echo "✅ No more Python commands needed!"
echo "✅ No more virtual environment activation!"
echo "✅ Just simple, clean commands!"

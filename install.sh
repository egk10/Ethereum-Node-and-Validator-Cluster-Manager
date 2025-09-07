#!/bin/bash
# Ethereum Node and Validator Cluster Manager - Installation Script
# This script sets up the project for local use

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR" && pwd)"

# Function to check system requirements
check_requirements() {
    print_info "Checking system requirements..."

    # Check Python
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 is required but not found. Please install Python 3.8 or higher."
        exit 1
    fi

    # Check Python version
    PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    if [[ $(echo "$PYTHON_VERSION < 3.8" | bc -l) -eq 1 ]]; then
        print_error "Python 3.8 or higher is required. Found: $PYTHON_VERSION"
        exit 1
    fi

    print_success "Python $PYTHON_VERSION found"
}

# Function to setup virtual environment
setup_venv() {
    print_info "Setting up virtual environment..."

    if [[ ! -d "$PROJECT_ROOT/venv" ]]; then
        python3 -m venv "$PROJECT_ROOT/venv"
        print_success "Virtual environment created"
    else
        print_info "Virtual environment already exists"
    fi

    # Activate and setup
    source "$PROJECT_ROOT/venv/bin/activate"
    pip install --upgrade pip

    # Install requirements
    if [[ -f "$PROJECT_ROOT/requirements.txt" ]]; then
        print_info "Installing core requirements..."
        pip install -r "$PROJECT_ROOT/requirements.txt"
        print_success "Core requirements installed"
    fi

    if [[ -f "$PROJECT_ROOT/requirements-ml.txt" ]]; then
        print_info "Installing ML requirements (optional)..."
        pip install -r "$PROJECT_ROOT/requirements-ml.txt" || print_warning "Some ML requirements failed to install (optional)"
    fi

    touch "$PROJECT_ROOT/.venv_setup_complete"
}

# Function to create convenience scripts
create_scripts() {
    print_info "Creating convenience scripts..."

    # Create a local run script
    cat > "$PROJECT_ROOT/run.sh" << 'EOF'
#!/bin/bash
# Local run script for Ethereum Node and Validator Cluster Manager

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/venv/bin/activate"
python3 -m eth_validators "$@"
EOF

    chmod +x "$PROJECT_ROOT/run.sh"
    print_success "Local run script created: ./run.sh"
}

# Function to show usage instructions
show_usage() {
    echo ""
    print_success "Installation complete!"
    echo ""
    print_info "Usage options:"
    echo ""
    echo "1️⃣  Local usage (from project directory):"
    echo "   ./run.sh --help"
    echo "   ./run.sh quickstart"
    echo "   ./run.sh node status"
    echo ""
    echo "2️⃣  Use wrapper script (recommended):"
    echo "   ./eth-manager --help"
    echo "   ./eth-manager quickstart"
    echo "   ./eth-manager node status"
    echo ""
    echo "3️⃣  Global installation (optional - run anywhere):"
    echo "   ./install-global.sh"
    echo "   Then use: eth-manager --help"
    echo ""
    echo "4️⃣  Manual Python execution:"
    echo "   source venv/bin/activate"
    echo "   python3 -m eth_validators --help"
    echo ""
    print_info "Recommended: Start with ./eth-manager quickstart"
}

# Main installation function
main() {
    echo "🚀 Ethereum Node and Validator Cluster Manager - Installation"
    echo ""

    # Check requirements
    check_requirements

    # Setup virtual environment
    setup_venv

    # Create convenience scripts
    create_scripts

    # Show usage
    show_usage
}

# Run main function
main "$@"

#!/bin/bash
# System-wide installation script for Ethereum Node and Validator Cluster Manager
# This script installs the eth-manager wrapper globally for easy access

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

# Function to check if we're in the right directory
check_setup() {
    if [[ ! -f "$PROJECT_ROOT/eth_validators/__main__.py" ]]; then
        print_error "Error: eth_validators module not found in $PROJECT_ROOT"
        print_error "Please run this script from the project root directory."
        exit 1
    fi

    if [[ ! -f "$PROJECT_ROOT/eth-manager" ]]; then
        print_error "Error: eth-manager wrapper script not found"
        print_error "Please ensure the wrapper script exists in the project root."
        exit 1
    fi
}

# Function to find the best location for global installation
find_install_location() {
    # Check for common bin directories in order of preference
    local install_paths=("$HOME/.local/bin" "$HOME/bin" "/usr/local/bin")

    for path in "${install_paths[@]}"; do
        if [[ -d "$path" ]] && [[ -w "$path" ]]; then
            echo "$path"
            return 0
        fi
    done

    # If no writable directory found, create ~/.local/bin
    local local_bin="$HOME/.local/bin"
    mkdir -p "$local_bin"
    echo "$local_bin"
}

# Function to install the wrapper globally
install_global() {
    local install_path="$1"
    local wrapper_path="$install_path/eth-manager"

    print_info "Installing eth-manager to $install_path..."

    # Copy the wrapper script
    cp "$PROJECT_ROOT/eth-manager" "$wrapper_path"
    chmod +x "$wrapper_path"

    print_success "Wrapper installed to $wrapper_path"
}

# Function to update PATH if needed
update_path() {
    local install_path="$1"
    local shell_rc=""

    # Detect shell and corresponding rc file
    case "$SHELL" in
        */bash)
            shell_rc="$HOME/.bashrc"
            ;;
        */zsh)
            shell_rc="$HOME/.zshrc"
            ;;
        */fish)
            shell_rc="$HOME/.config/fish/config.fish"
            ;;
        *)
            print_warning "Unsupported shell: $SHELL"
            print_warning "Please manually add $install_path to your PATH"
            return
            ;;
    esac

    # Check if path is already in PATH
    if [[ ":$PATH:" != *":$install_path:"* ]]; then
        print_info "Adding $install_path to PATH in $shell_rc"

        if [[ "$shell_rc" == *".fish" ]]; then
            echo "set -gx PATH $install_path \$PATH" >> "$shell_rc"
        else
            echo "export PATH=\"$install_path:\$PATH\"" >> "$shell_rc"
        fi

        print_success "PATH updated. Please restart your shell or run: source $shell_rc"
    else
        print_info "PATH already contains $install_path"
    fi
}

# Function to create a simple alias as fallback
create_alias() {
    local shell_rc=""

    case "$SHELL" in
        */bash)
            shell_rc="$HOME/.bashrc"
            ;;
        */zsh)
            shell_rc="$HOME/.zshrc"
            ;;
        */fish)
            shell_rc="$HOME/.config/fish/config.fish"
            ;;
        *)
            print_warning "Unsupported shell: $SHELL"
            return
            ;;
    esac

    print_info "Creating alias in $shell_rc as fallback..."

    if [[ "$shell_rc" == *".fish" ]]; then
        echo "alias eth-manager='$PROJECT_ROOT/eth-manager'" >> "$shell_rc"
    else
        echo "alias eth-manager='$PROJECT_ROOT/eth-manager'" >> "$shell_rc"
    fi

    print_success "Alias created. Please restart your shell or run: source $shell_rc"
}

# Main installation function
main() {
    print_info "🚀 Installing Ethereum Node and Validator Cluster Manager globally"

    # Check setup
    check_setup

    # Find installation location
    local install_path
    install_path=$(find_install_location)

    # Install globally
    install_global "$install_path"

    # Update PATH
    update_path "$install_path"

    # Test installation
    print_info "Testing installation..."
    if command -v eth-manager &> /dev/null; then
        print_success "Installation successful! You can now use 'eth-manager' from anywhere"
        print_info "Try: eth-manager --help"
    else
        print_warning "Installation completed, but eth-manager not found in PATH"
        print_warning "You can still use it directly: $install_path/eth-manager"
        print_warning "Or create an alias by running: create_alias"
    fi

    print_success "Installation complete!"
    echo ""
    print_info "Usage examples:"
    echo "  eth-manager --help                    # Show help"
    echo "  eth-manager quickstart               # Setup wizard"
    echo "  eth-manager node status              # Check node status"
    echo "  eth-manager validator discover       # Discover validators"
}

# Run main function
main "$@"

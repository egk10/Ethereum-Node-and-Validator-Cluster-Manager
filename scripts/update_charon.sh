#!/bin/bash

# Charon Update Script for Obol Distributed Validator Nodes
# This script updates Charon containers across all nodes running Obol stack

set -e  # Exit on any error

# ANSI color codes for output formatting
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Array of nodes running Obol/Charon (from CSV analysis)
OBOL_NODES=(
    "orangepi5-plus.velociraptor-scylla.ts.net"
    "minipcamd.velociraptor-scylla.ts.net"
    "minipcamd2.velociraptor-scylla.ts.net"
    "minipcamd3.velociraptor-scylla.ts.net"
    "opi5.velociraptor-scylla.ts.net"
)

# SSH users to try (in order of preference)
SSH_USERS=("root" "egk" "ubuntu" "user")

# Default Charon directory paths to check (in order of preference)
CHARON_PATHS=(
    "/home/egk/charon-distributed-validator-node"
    "~/charon-distributed-validator-node"
    "~/obol-dvt" 
    "~/obol"
    "~/charon"
    "~/dvt"
    "/opt/charon"
    "/opt/obol"
    "/home/user/charon-distributed-validator-node"
    "/home/user/obol"
    "/home/ubuntu/charon-distributed-validator-node"
    "/home/ubuntu/obol"
    "/root/charon-distributed-validator-node"
    "/root/obol"
)

# Function to find working SSH user and Charon directory on a node
find_charon_setup() {
    local node=$1
    local working_user=""
    local found_path=""
    
    # Try different SSH users
    for user in "${SSH_USERS[@]}"; do
        # Check if we can connect with this user
        if ssh -o ConnectTimeout=5 -o BatchMode=yes "$user@$node" "echo 'connected'" >/dev/null 2>&1; then
            working_user=$user
            
            # Try the predefined paths
            for path in "${CHARON_PATHS[@]}"; do
                if ssh -o ConnectTimeout=10 -o BatchMode=yes "$user@$node" "test -d $path && test -f $path/docker-compose.yml" 2>/dev/null; then
                    # Verify it actually contains Charon
                    if ssh -o ConnectTimeout=10 -o BatchMode=yes "$user@$node" "grep -qi 'charon' $path/docker-compose.yml" 2>/dev/null; then
                        found_path=$path
                        break 2  # Break out of both loops
                    fi
                fi
            done
            
            # If not found with predefined paths, try searching
            if [[ -z "$found_path" ]]; then
                # Search in common locations for docker-compose files containing charon
                local search_dirs=("~" "/opt" "/home/$user" "/home/user" "/home/ubuntu" "/root")
                for search_dir in "${search_dirs[@]}"; do
                    local found_dirs=$(ssh -o ConnectTimeout=15 -o BatchMode=yes "$user@$node" \
                        "find $search_dir -maxdepth 3 -name 'docker-compose.yml' -exec grep -l 'charon' {} \\; 2>/dev/null | head -5" 2>/dev/null || true)
                        
                    if [[ -n "$found_dirs" ]]; then
                        # Take the first match and get its directory
                        local compose_file=$(echo "$found_dirs" | head -1)
                        found_path=$(ssh -o ConnectTimeout=10 -o BatchMode=yes "$user@$node" "dirname '$compose_file'" 2>/dev/null || true)
                        if [[ -n "$found_path" ]]; then
                            break 2  # Break out of both loops
                        fi
                    fi
                done
            fi
            
            # If found with this user, break
            if [[ -n "$found_path" ]]; then
                break
            fi
        fi
    done
    
    if [[ -z "$working_user" ]] || [[ -z "$found_path" ]]; then
        return 1
    fi
    
    echo "$working_user:$found_path"
    return 0
}

# Function to check if Charon container is running
check_charon_status() {
    local ssh_user=$1
    local node=$2
    local charon_dir=$3
    
    print_status "Checking Charon status on $node..."
    
    if ssh -o ConnectTimeout=10 -o BatchMode=yes "$ssh_user@$node" "cd $charon_dir && docker compose ps charon | grep -q 'Up'" 2>/dev/null; then
        print_success "Charon is running on $node"
        return 0
    else
        print_warning "Charon is not running on $node"
        return 1
    fi
}

# Function to get current Charon version
get_charon_version() {
    local ssh_user=$1
    local node=$2
    local charon_dir=$3
    
    local version=$(ssh -o ConnectTimeout=10 -o BatchMode=yes "$ssh_user@$node" \
        "cd $charon_dir && docker compose ps charon --format 'table {{.Image}}' | tail -n 1 | cut -d':' -f2" 2>/dev/null || echo "unknown")
    
    echo "$version"
}

# Function to update Charon on a single node
update_charon_node() {
    local node=$1
    local dry_run=$2
    
    print_status "Processing node: $node"
    
    # Find Charon setup (user and directory)  
    print_status "Looking for Charon setup on $node..."
    local setup_info
    if ! setup_info=$(find_charon_setup "$node" 2>/dev/null); then
        print_error "Skipping $node - Charon setup not found"
        return 1
    fi
    
    # Parse the setup info
    local ssh_user=$(echo "$setup_info" | cut -d':' -f1)
    local charon_dir=$(echo "$setup_info" | cut -d':' -f2-)
    
    print_success "Found Charon setup - User: $ssh_user, Directory: $charon_dir"
    
    # Get current version
    local current_version=$(get_charon_version "$ssh_user" "$node" "$charon_dir")
    print_status "Current Charon version on $node: $current_version"
    
    if [[ "$dry_run" == "true" ]]; then
        print_status "[DRY RUN] Would update Charon on $node at $charon_dir (user: $ssh_user)"
        return 0
    fi
    
    # Check if Charon is currently running
    local was_running=false
    if check_charon_status "$ssh_user" "$node" "$charon_dir"; then
        was_running=true
    fi
    
    print_status "Updating Charon on $node..."
    
    # Pull latest Charon image
    print_status "Pulling latest Charon image..."
    if ssh -o ConnectTimeout=30 "$ssh_user@$node" "cd $charon_dir && docker compose pull charon" 2>/dev/null; then
        print_success "Successfully pulled latest Charon image"
    else
        print_error "Failed to pull Charon image on $node"
        return 1
    fi
    
    # Restart Charon container
    print_status "Restarting Charon container..."
    if ssh -o ConnectTimeout=30 "$ssh_user@$node" "cd $charon_dir && docker compose up -d charon" 2>/dev/null; then
        print_success "Successfully restarted Charon container"
    else
        print_error "Failed to restart Charon container on $node"
        return 1
    fi
    
    # Wait a moment and check if it's running
    sleep 5
    if check_charon_status "$ssh_user" "$node" "$charon_dir"; then
        local new_version=$(get_charon_version "$ssh_user" "$node" "$charon_dir")
        print_success "Charon update completed on $node"
        print_status "New version: $new_version"
        
        if [[ "$current_version" != "$new_version" ]]; then
            print_success "Version updated: $current_version → $new_version"
        else
            print_status "Version unchanged (already up to date)"
        fi
        return 0
    else
        print_error "Charon failed to start after update on $node"
        return 1
    fi
}

# Function to show summary
show_summary() {
    local successful_nodes=("$@")
    
    echo
    print_status "=== UPDATE SUMMARY ==="
    
    if [[ ${#successful_nodes[@]} -eq 0 ]]; then
        print_error "No nodes were successfully updated"
        return 1
    fi
    
    print_success "Successfully updated ${#successful_nodes[@]} nodes:"
    for node in "${successful_nodes[@]}"; do
        echo "  ✓ $node"
    done
    
    local failed_count=$((${#OBOL_NODES[@]} - ${#successful_nodes[@]}))
    if [[ $failed_count -gt 0 ]]; then
        print_warning "$failed_count nodes failed to update"
    fi
    
    print_status "Charon update process completed!"
}

# Main execution function
main() {
    local dry_run=false
    local selected_nodes=()
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --dry-run)
                dry_run=true
                shift
                ;;
            --node)
                selected_nodes+=("$2")
                shift 2
                ;;
            --help)
                echo "Usage: $0 [OPTIONS]"
                echo "Options:"
                echo "  --dry-run          Show what would be done without making changes"
                echo "  --node NODE        Update only specified node (can be used multiple times)"
                echo "  --help             Show this help message"
                echo
                echo "Available nodes:"
                for node in "${OBOL_NODES[@]}"; do
                    echo "  $node"
                done
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                echo "Use --help for usage information"
                exit 1
                ;;
        esac
    done
    
    # Use selected nodes or all nodes
    local nodes_to_process=("${OBOL_NODES[@]}")
    if [[ ${#selected_nodes[@]} -gt 0 ]]; then
        nodes_to_process=("${selected_nodes[@]}")
    fi
    
    print_status "=== CHARON UPDATE SCRIPT ==="
    print_status "Nodes to process: ${#nodes_to_process[@]}"
    
    if [[ "$dry_run" == "true" ]]; then
        print_warning "DRY RUN MODE - No changes will be made"
    fi
    
    echo
    
    local successful_updates=()
    
    # Process each node
    for node in "${nodes_to_process[@]}"; do
        echo "----------------------------------------"
        if update_charon_node "$node" "$dry_run"; then
            successful_updates+=("$node")
        fi
        echo
    done
    
    echo "========================================"
    show_summary "${successful_updates[@]}"
}

# Run main function with all arguments
main "$@"

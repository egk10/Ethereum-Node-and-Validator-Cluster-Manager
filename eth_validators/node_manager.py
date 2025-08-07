"""
Handles direct interaction with a node, including SSH commands and API calls
for status, versioning, and synchronization checks.
"""
import subprocess
import requests
import json
import socket
import time
import re

def _is_stack_disabled(stack):
    """Check if stack is disabled - supports both string and list format"""
    if isinstance(stack, list):
        return 'disabled' in stack
    else:
        return stack == 'disabled'

def _get_free_port():
    """Finds and returns a free local port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]


def _get_execution_sync_status(api_url):
    """
    Checks the execution client sync status via JSON-RPC.
    Returns 'Synced', 'Syncing', or 'Error'.
    """
    headers = {'Content-Type': 'application/json'}
    payload = json.dumps({"jsonrpc":"2.0", "method":"eth_syncing", "params":[], "id":1})
    try:
        response = requests.post(api_url, headers=headers, data=payload, timeout=5)
        if response.status_code == 200:
            result = response.json().get('result')
            if result is False:
                return "Synced"
            elif isinstance(result, dict):
                return "Syncing"
        return "Error"
    except requests.RequestException:
        return "API Error"

def _get_consensus_sync_status(api_url):
    """
    Checks the consensus client sync status via Beacon API.
    Returns 'Synced', 'Syncing', or 'Error'.
    """
    try:
        response = requests.get(f"{api_url}/eth/v1/node/syncing", timeout=5)
        if response.status_code == 200:
            is_syncing = response.json().get('data', {}).get('is_syncing', True)
            return "Syncing" if is_syncing else "Synced"
        return "Error"
    except requests.RequestException:
        return "API Error"

def get_node_status(node_config):
    """
    Gathers comprehensive status for a node, including docker ps and sync status.
    """
    results = {}
    ssh_user = node_config.get('ssh_user', 'root')
    ssh_target = f"{ssh_user}@{node_config['tailscale_domain']}"

    # 1. Get docker ps output
    try:
        docker_ps_cmd = ['ssh', ssh_target, 'docker', 'ps', '--format', 'table {{.Names}}\\t{{.Image}}\\t{{.Status}}']
        process = subprocess.run(docker_ps_cmd, capture_output=True, text=True, check=True, timeout=15)
        results['docker_ps'] = process.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        results['docker_ps'] = f"Error fetching docker status: {e}"
        return results # Stop if we can't even run docker ps

    # 2. Setup SSH tunnels for API calls
    el_port = _get_free_port()
    cl_port = _get_free_port()
    el_tunnel_cmd = ['ssh', '-o', 'ConnectTimeout=10', '-N', '-L', f'{el_port}:localhost:{node_config["execution_api_port"]}', ssh_target]
    cl_tunnel_cmd = ['ssh', '-o', 'ConnectTimeout=10', '-N', '-L', f'{cl_port}:localhost:{node_config["beacon_api_port"]}', ssh_target]

    el_proc = subprocess.Popen(el_tunnel_cmd)
    cl_proc = subprocess.Popen(cl_tunnel_cmd)
    time.sleep(3) # Give tunnels time to establish

    try:
        # 3. Get sync status
        el_api_url = f"http://localhost:{el_port}"
        cl_api_url = f"http://localhost:{cl_port}"
        results['execution_sync'] = _get_execution_sync_status(el_api_url)
        results['consensus_sync'] = _get_consensus_sync_status(cl_api_url)
    finally:
        # 4. Close tunnels
        el_proc.terminate()
        cl_proc.terminate()

    return results

def upgrade_node_docker_clients(node_config):
    """Upgrade docker clients for a node - supports single and multi-network nodes"""
    
    # Check if this is a multi-network node
    networks = node_config.get('networks')
    if networks:
        return _upgrade_multi_network_node(node_config)
    else:
        return _upgrade_single_network_node(node_config)

def _upgrade_single_network_node(node_config):
    """
    Upgrades Docker-based Ethereum clients (execution, consensus, mev-boost) 
    on a single network node using eth-docker. This does NOT upgrade the Ubuntu system.
    
    For Ubuntu system updates, use: sudo apt update && sudo apt upgrade -y
    """
    results = {}
    ssh_user = node_config.get('ssh_user', 'root')
    ssh_target = f"{ssh_user}@{node_config['tailscale_domain']}"
    eth_docker_path = node_config.get('eth_docker_path', '/opt/eth-docker')
    is_local = node_config.get('is_local', False)
    
    if is_local:
        # Execute locally without SSH
        upgrade_cmd = f'cd {eth_docker_path} && git config --global --add safe.directory {eth_docker_path} && git checkout main && git pull && docker compose pull && docker compose build --pull && docker compose up -d'
    else:
        # Execute via SSH  
        upgrade_cmd = f'ssh {ssh_target} "git config --global --add safe.directory {eth_docker_path} && cd {eth_docker_path} && git checkout main && git pull && docker compose pull && docker compose build --pull && docker compose up -d"'
    
    try:
        process = subprocess.run(upgrade_cmd, shell=True, capture_output=True, text=True, timeout=300)
        results['upgrade_output'] = process.stdout
        results['upgrade_error'] = process.stderr
        results['upgrade_success'] = process.returncode == 0
    except subprocess.TimeoutExpired:
        results['upgrade_error'] = "Upgrade timeout after 5 minutes"
        results['upgrade_success'] = False
    
    return results

def _upgrade_multi_network_node(node_config):
    """
    Upgrades Docker-based Ethereum clients on a multi-network node.
    Each network (mainnet, testnet) has its own eth-docker directory.
    """
    networks = node_config['networks']
    results = {}
    overall_success = True
    is_local = node_config.get('is_local', False)
    ssh_user = node_config.get('ssh_user', 'root')
    ssh_target = f"{ssh_user}@{node_config['tailscale_domain']}"
    
    for network_key, network_config in networks.items():
        eth_docker_path = network_config['eth_docker_path']
        network_name = network_config.get('network_name', network_key)
        
        network_result = {
            'upgrade_output': '',
            'upgrade_error': '',
            'upgrade_success': True
        }
        
        # Execute commands step by step for better error handling
        commands = [
            f"git config --global --add safe.directory {eth_docker_path}",
            f"cd {eth_docker_path}",
            "git checkout main",
            "git pull",
            "docker compose pull",
            "docker compose build --pull",
            "docker compose up -d"
        ]
        
        for i, cmd in enumerate(commands, 1):
            if is_local:
                if cmd.startswith('cd '):
                    # Skip cd command for local execution, we'll use cwd parameter
                    continue
                    
                # Execute locally without SSH
                try:
                    process = subprocess.run(cmd, shell=True, capture_output=True, text=True, 
                                           timeout=120, cwd=eth_docker_path)
                    
                    if process.returncode != 0:
                        network_result['upgrade_error'] += f"Command '{cmd}' failed: {process.stderr}\n"
                        network_result['upgrade_success'] = False
                        break
                    else:
                        network_result['upgrade_output'] += f"✓ {cmd}: {process.stdout}\n"
                        
                except subprocess.TimeoutExpired:
                    network_result['upgrade_error'] += f"Command '{cmd}' timeout after 2 minutes\n"
                    network_result['upgrade_success'] = False
                    break
                except Exception as e:
                    network_result['upgrade_error'] += f"Command '{cmd}' exception: {str(e)}\n"
                    network_result['upgrade_success'] = False
                    break
            else:
                # Execute via SSH - combine all commands
                full_cmd = f'ssh {ssh_target} "cd {eth_docker_path} && {" && ".join(commands[2:])}"'
                try:
                    process = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=300)
                    network_result['upgrade_output'] = process.stdout
                    network_result['upgrade_error'] = process.stderr
                    network_result['upgrade_success'] = process.returncode == 0
                except subprocess.TimeoutExpired:
                    network_result['upgrade_error'] = "Upgrade timeout after 5 minutes"
                    network_result['upgrade_success'] = False
                break  # Exit the command loop for SSH mode
        
        results[network_name] = network_result
        if not network_result['upgrade_success']:
            overall_success = False
    
    results['overall_success'] = overall_success
    return results

def get_system_update_status(node_config):
    """
    Checks if Ubuntu system updates are available (does not install them).
    Uses 'apt upgrade -s' to simulate and count what would actually be upgraded,
    excluding phased updates that Ubuntu intentionally holds back.
    
    Fallback strategy: If APT is locked/busy, uses apt-check as alternative.
    Supports both local and remote nodes.
    """
    results = {}
    ssh_user = node_config.get('ssh_user', 'root')
    is_local = node_config.get('is_local', False)
    
    # Primary method: Wait for APT locks to be released, then check updates
    if ssh_user == 'root':
        # Wait for locks (max 30 seconds), then check updates
        apt_wait_cmd = 'timeout=30; while [ $timeout -gt 0 ] && (fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || fuser /var/lib/apt/lists/lock >/dev/null 2>&1); do sleep 2; timeout=$((timeout-2)); done'
        apt_check_cmd = 'if [ $timeout -gt 0 ]; then apt update >/dev/null 2>&1 && apt upgrade -s 2>/dev/null | grep "^Inst " | wc -l; else echo "FALLBACK"; fi'
        full_cmd = f'{apt_wait_cmd}; {apt_check_cmd}'
    else:
        # Wait for locks (max 30 seconds), then check updates  
        apt_wait_cmd = 'timeout=30; while [ $timeout -gt 0 ] && (sudo fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || sudo fuser /var/lib/apt/lists/lock >/dev/null 2>&1); do sleep 2; timeout=$((timeout-2)); done'
        apt_check_cmd = 'if [ $timeout -gt 0 ]; then sudo apt update >/dev/null 2>&1 && sudo apt upgrade -s 2>/dev/null | grep "^Inst " | wc -l; else echo "FALLBACK"; fi'
        full_cmd = f'{apt_wait_cmd}; {apt_check_cmd}'
    
    # Execute command locally or via SSH
    if is_local:
        check_cmd = full_cmd
    else:
        ssh_target = f"{ssh_user}@{node_config['tailscale_domain']}"
        check_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} '{full_cmd}'"
    
    try:
        process = subprocess.run(check_cmd, shell=True, capture_output=True, text=True, timeout=60)
        if process.returncode == 0:
            output = process.stdout.strip()
            
            # Check if we need to use fallback method
            if output == "FALLBACK":
                # Use apt-check as fallback when APT is locked/busy
                if is_local:
                    if ssh_user == 'root':
                        fallback_cmd = '/usr/lib/update-notifier/apt-check 2>&1'
                    else:
                        fallback_cmd = 'sudo /usr/lib/update-notifier/apt-check 2>&1'
                else:
                    ssh_target = f"{ssh_user}@{node_config['tailscale_domain']}"
                    fallback_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} '/usr/lib/update-notifier/apt-check 2>&1'"
                    if ssh_user != 'root':
                        fallback_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} 'sudo /usr/lib/update-notifier/apt-check 2>&1'"
                
                fallback_process = subprocess.run(fallback_cmd, shell=True, capture_output=True, text=True, timeout=15)
                if fallback_process.returncode == 0:
                    # apt-check returns "packages;security" format (e.g., "3;2")
                    apt_check_output = fallback_process.stdout.strip()
                    if ';' in apt_check_output:
                        update_count = int(apt_check_output.split(';')[0])
                        results['updates_available'] = f"{update_count} (apt-check)"
                        results['needs_system_update'] = update_count > 0
                    else:
                        results['updates_available'] = f"Fallback Error"
                        results['needs_system_update'] = False
                else:
                    results['updates_available'] = f"Fallback Failed"
                    results['needs_system_update'] = False
            else:
                # Normal apt upgrade simulation worked
                update_count = int(output)
                results['updates_available'] = update_count
                results['needs_system_update'] = update_count > 0
        else:
            # Better error reporting
            error_msg = process.stderr.strip() if process.stderr.strip() else f"Command failed (return code: {process.returncode})"
            results['updates_available'] = f"Connection Error" if not is_local else f"Command Error"
            results['needs_system_update'] = False
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as e:
        if isinstance(e, subprocess.TimeoutExpired):
            results['updates_available'] = "Timeout"
        else:
            results['updates_available'] = "SSH Error" if not is_local else "Local Error"
        results['needs_system_update'] = False
    
    return results

def perform_system_upgrade(node_config):
    """
    Performs Ubuntu system upgrade via SSH: sudo apt update && sudo apt upgrade -y
    This will actually install system updates on the remote node.
    Supports both local and remote nodes.
    
    Note: Requires either:
    - SSH user is 'root', OR
    - SSH user has passwordless sudo access configured
    """
    results = {}
    ssh_user = node_config.get('ssh_user', 'root')
    is_local = node_config.get('is_local', False)
    
    # Determine if we need sudo or not
    if ssh_user == 'root':
        apt_cmd = 'apt update && apt upgrade -y'
    else:
        apt_cmd = 'sudo apt update && sudo apt upgrade -y'
    
    # Add APT lock handling - wait for other apt processes to finish
    if ssh_user == 'root':
        full_cmd = f'while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || fuser /var/lib/apt/lists/lock >/dev/null 2>&1; do echo "Waiting for other apt process to finish..."; sleep 5; done; {apt_cmd}'
    else:
        full_cmd = f'while sudo fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || sudo fuser /var/lib/apt/lists/lock >/dev/null 2>&1; do echo "Waiting for other apt process to finish..."; sleep 5; done; {apt_cmd}'
    
    # Execute locally or via SSH
    if is_local:
        upgrade_cmd = full_cmd
    else:
        ssh_target = f"{ssh_user}@{node_config['tailscale_domain']}"
        upgrade_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} '{full_cmd}'"
    
    try:
        process = subprocess.run(upgrade_cmd, shell=True, capture_output=True, text=True, timeout=900)  # 15 minute timeout
        results['upgrade_output'] = process.stdout
        results['upgrade_error'] = process.stderr
        results['upgrade_success'] = process.returncode == 0
        results['return_code'] = process.returncode
        
        # Add helpful error messages
        if not results['upgrade_success']:
            if 'sudo: a password is required' in results['upgrade_error']:
                results['upgrade_error'] += f"\n\nTip: User '{ssh_user}' needs passwordless sudo access. Either:\n" \
                                          f"1. Use 'root' as ssh_user in config.yaml, OR\n" \
                                          f"2. Configure passwordless sudo for '{ssh_user}' {'locally' if is_local else 'on the remote node'}"
            elif 'Permission denied' in results['upgrade_error']:
                results['upgrade_error'] += f"\n\nTip: Check {'local user permissions' if is_local else 'SSH key authentication or user permissions'}"
            elif 'Could not get lock' in results['upgrade_error']:
                results['upgrade_error'] += f"\n\nTip: Another apt process was running. The command includes automatic waiting, but it may have timed out."
                
    except subprocess.TimeoutExpired:
        results['upgrade_error'] = "System upgrade timeout after 15 minutes (includes waiting for apt locks)"
        results['upgrade_success'] = False
        results['return_code'] = -1
    
    return results

def get_docker_client_versions(node_config):
    """
    Checks current and latest versions of Ethereum clients running in Docker containers.
    Gets actual running container versions from Docker logs and compares with latest GitHub releases.
    Returns information about execution client, consensus client, validator client, and whether updates are needed.
    Supports multi-network nodes (mainnet + testnet).
    """
    results = {}
    
    # Check if this node has multiple networks configured
    networks = node_config.get('networks', {})
    if networks:
        # Multi-network node (like eliedesk with mainnet + testnet)
        return _get_multi_network_client_versions(node_config)
    
    # Standard single-network node processing
    return _get_single_network_client_versions(node_config)

def _get_multi_network_client_versions(node_config):
    """Handle nodes with multiple networks (mainnet + testnet)"""
    networks = node_config.get('networks', {})
    is_local = node_config.get('is_local', False)
    
    if is_local:
        ssh_target = None
    else:
        ssh_user = node_config.get('ssh_user', 'root')
        ssh_target = f"{ssh_user}@{node_config['tailscale_domain']}"
    
    all_results = {}
    
    for network_name, network_config in networks.items():
        try:
            # Get containers for this network
            container_prefix = network_config.get('container_prefix', 'eth-docker')
            
            if ssh_target is None:
                containers_cmd = f"docker ps --format '{{{{.Names}}}}:{{{{.Image}}}}' | grep '{container_prefix}' 2>/dev/null || echo 'No containers'"
            else:
                containers_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} 'docker ps --format \"{{{{.Names}}}}:{{{{.Image}}}}\" | grep \"{container_prefix}\" 2>/dev/null || echo \"No containers\"'"
            
            containers_process = subprocess.run(containers_cmd, shell=True, capture_output=True, text=True, timeout=10)
            
            network_results = {
                'network': network_config.get('network_name', network_name),
                'execution_current': 'Unknown',
                'execution_latest': 'Unknown',
                'execution_client': 'Unknown',
                'consensus_current': 'Unknown', 
                'consensus_latest': 'Unknown',
                'consensus_client': 'Unknown',
                'validator_current': 'N/A',
                'validator_latest': 'N/A',
                'validator_client': 'N/A',
                'execution_needs_update': False,
                'consensus_needs_update': False,
                'validator_needs_update': False,
                'needs_client_update': False
            }
            
            if containers_process.returncode == 0 and "No containers" not in containers_process.stdout:
                container_lines = containers_process.stdout.strip().split('\n')
                
                for line in container_lines:
                    if ':' in line:
                        container_name, image = line.split(':', 1)
                        
                        # Identify execution client
                        if 'execution' in container_name.lower():
                            client_name = _identify_client_from_image(image, 'execution')
                            if client_name != "Unknown":
                                exec_version = _get_version_via_docker_exec(ssh_target, container_name, client_name)
                                if exec_version and exec_version not in ["Error", "Unknown", "Exec Error"]:
                                    network_results['execution_current'] = exec_version
                                else:
                                    network_results['execution_current'] = _get_client_version_from_logs(ssh_target, container_name, client_name)
                                network_results['execution_client'] = client_name
                        
                        # Identify consensus client
                        elif 'consensus' in container_name.lower():
                            client_name = _identify_client_from_image(image, 'consensus')
                            if client_name != "Unknown":
                                exec_version = _get_version_via_docker_exec(ssh_target, container_name, client_name)
                                if exec_version and exec_version not in ["Error", "Unknown", "Exec Error"]:
                                    network_results['consensus_current'] = exec_version
                                else:
                                    network_results['consensus_current'] = _get_client_version_from_logs(ssh_target, container_name, client_name)
                                network_results['consensus_client'] = client_name
            
            # Get latest versions from GitHub releases for this network
            exec_client_name = network_results['execution_client']
            cons_client_name = network_results['consensus_client']
            
            if exec_client_name != "Unknown":
                network_results['execution_latest'] = _get_latest_github_release(exec_client_name)
                network_results['execution_needs_update'] = _version_needs_update(
                    network_results['execution_current'], 
                    network_results['execution_latest']
                )
            
            if cons_client_name != "Unknown":
                network_results['consensus_latest'] = _get_latest_github_release(cons_client_name)
                network_results['consensus_needs_update'] = _version_needs_update(
                    network_results['consensus_current'], 
                    network_results['consensus_latest']
                )
                
                # Set validator client info to match consensus client
                network_results['validator_client'] = cons_client_name
                network_results['validator_current'] = network_results['consensus_current']
                network_results['validator_latest'] = network_results['consensus_latest']
                network_results['validator_needs_update'] = network_results['consensus_needs_update']
            
            # Set overall needs_client_update flag
            network_results['needs_client_update'] = (
                network_results['execution_needs_update'] or 
                network_results['consensus_needs_update'] or 
                network_results['validator_needs_update']
            )
            
            all_results[network_name] = network_results
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            all_results[network_name] = {'error': f"Failed to get versions for {network_name}: {e}"}
    
    return all_results

def _get_single_network_client_versions(node_config):
    """Handle standard single-network nodes"""
    results = {}
    
    # Skip nodes with disabled eth-docker or explicitly disabled Ethereum clients
    stack = node_config.get('stack', ['eth-docker'])
    ethereum_clients_enabled = node_config.get('ethereum_clients_enabled', True)

    if (_is_stack_disabled(stack) or 
        ethereum_clients_enabled is False):
        results = {
            'execution_current': 'Disabled',
            'execution_latest': 'N/A',
            'execution_client': 'Disabled',
            'consensus_current': 'Disabled',
            'consensus_latest': 'N/A',
            'consensus_client': 'Disabled',
            'validator_current': 'Disabled',
            'validator_latest': 'N/A', 
            'validator_client': 'Disabled',
            'execution_needs_update': False,
            'consensus_needs_update': False,
            'validator_needs_update': False,
            'needs_client_update': False
        }
        return results
    
    # Check if this is a local node (no SSH required)
    is_local = node_config.get('is_local', False)
    ssh_user = node_config.get('ssh_user', 'root')
    
    if is_local:
        # For local execution, use direct commands
        ssh_target = None
    else:
        ssh_target = f"{ssh_user}@{node_config['tailscale_domain']}"
    
    try:
        # Get running containers with their images
        if ssh_target is None:
            # Local execution
            containers_cmd = "docker ps --format '{{.Names}}:{{.Image}}' 2>/dev/null || echo 'Error'"
        else:
            # Remote execution via SSH
            containers_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} 'docker ps --format \"{{{{.Names}}}}:{{{{.Image}}}}\" 2>/dev/null || echo \"Error\"'"
            
        containers_process = subprocess.run(containers_cmd, shell=True, capture_output=True, text=True, timeout=10)
        
        # Initialize results
        execution_current = "Unknown"
        consensus_current = "Unknown"
        validator_current = "Unknown"
        execution_client_name = "Unknown"
        consensus_client_name = "Unknown"
        validator_client_name = "Unknown"
        execution_container = None
        consensus_container = None
        validator_container = None
        execution_image = None
        consensus_image = None
        validator_image = None
        
        # For nodes with multiple validator clients, collect all of them
        validator_clients = []  # List of (client_name, container, image)
        
        # Parse running containers to identify clients and versions
        if containers_process.returncode == 0 and "Error" not in containers_process.stdout:
            container_lines = containers_process.stdout.strip().split('\n')
            
            for line in container_lines:
                if ':' in line:
                    container_name, image = line.split(':', 1)
                    
                    # Special handling for Erigon with integrated Caplin consensus
                    if 'erigon' in container_name.lower() or 'erigon' in image.lower():
                        # Erigon can run with integrated Caplin consensus client
                        execution_client_name = _identify_client_from_image(image, 'execution')
                        execution_container = container_name
                        execution_image = image
                        
                        # If no separate consensus client found yet, assume Caplin is integrated
                        if consensus_client_name == "Unknown":
                            consensus_client_name = 'erigon-caplin' 
                            consensus_container = container_name  # Same container as execution
                            consensus_image = image
                    
                    # Identify other execution clients
                    elif any(exec_client in container_name.lower() for exec_client in 
                           ['execution', 'geth', 'nethermind', 'reth', 'besu']):
                        execution_client_name = _identify_client_from_image(image, 'execution')
                        execution_container = container_name
                        execution_image = image
                    
                    # Identify consensus clients (beacon nodes) - these override erigon-caplin
                    elif any(cons_client in container_name.lower() for cons_client in 
                             ['consensus', 'lighthouse', 'prysm', 'teku', 'nimbus', 'lodestar', 'grandine']) and 'validator' not in container_name.lower():
                        consensus_client_name = _identify_client_from_image(image, 'consensus')
                        consensus_container = container_name
                        consensus_image = image
                    
                    # Identify validator clients (separate from consensus) - collect multiple
                    # Detect Vero validator containers (Lido CSM)
                    elif 'vero' in image.lower() or ('eth-docker-validator' in container_name.lower() and 'vero' in image.lower()):
                        validator_clients.append(("vero", container_name, image))
                    # Detect Lodestar validator containers in DVT setups
                    elif ('lodestar' in image.lower() and 'lodestar' in container_name.lower() and 
                          consensus_container != container_name):
                        # Specific detection for Lodestar validator containers in DVT setups
                        validator_clients.append(("lodestar", container_name, image))
                    elif (any(val_client in container_name.lower() for val_client in 
                             ['validator', 'vc']) and 'grafana' not in container_name.lower() and 'prometheus' not in container_name.lower()):
                        # Standard validator containers
                        detected_client = _identify_client_from_image(image, 'validator')
                        validator_clients.append((detected_client, container_name, image))
        
        # Choose primary validator client for version display
        # Priority: Vero > Lodestar > Others (for multi-validator setups)
        if validator_clients:
            # Sort by priority: Vero first, then Lodestar, then others
            def validator_priority(client_info):
                client_name = client_info[0].lower()
                if 'vero' in client_name:
                    return 0  # Highest priority
                elif 'lodestar' in client_name:
                    return 1
                else:
                    return 2
            
            validator_clients.sort(key=validator_priority)
            
            # Use the highest priority validator as primary
            validator_client_name, validator_container, validator_image = validator_clients[0]
            
            # For display purposes, show multiple validators if present
            if len(validator_clients) > 1:
                additional_validators = [client[0] for client in validator_clients[1:]]
                # We'll use this information later in the display logic
        
        # Get actual versions from Docker logs, with fallback to image version and exec command
        if execution_container and execution_client_name != "Unknown":
            # Special handling for erigon when integrated with caplin
            if execution_client_name == 'erigon' and consensus_client_name == 'erigon-caplin':
                # Use same API version for both execution and consensus since they're integrated
                api_version = _get_caplin_version_from_api(ssh_target, node_config)
                if api_version and api_version not in ["Unknown", "Error", "API Error"]:
                    execution_current = api_version
                else:
                    # Fallback to traditional methods
                    execution_current = _get_client_version_from_logs(ssh_target, execution_container, execution_client_name)
            # For certain other clients, try docker exec first as it's more reliable than old logs
            elif execution_client_name.lower() in ['nethermind', 'reth', 'besu', 'geth']:
                exec_version = _get_version_via_docker_exec(ssh_target, execution_container, execution_client_name)
                if exec_version and exec_version not in ["Error", "Unknown", "Exec Error"]:
                    execution_current = exec_version
                else:
                    execution_current = _get_client_version_from_logs(ssh_target, execution_container, execution_client_name)
            else:
                execution_current = _get_client_version_from_logs(ssh_target, execution_container, execution_client_name)
            
            # Fallback to image version if both methods fail
            if execution_current in ["No Version Found", "Empty Logs", "Log Error", "Error", "Unknown", "Exec Error"] or execution_current.startswith("Error:") or execution_current.startswith("Debug:"):
                execution_current = _extract_image_version(f"image: {execution_image}")
        
        if consensus_container and consensus_client_name != "Unknown":
            # Special handling for erigon-caplin: get version from Beacon API
            if consensus_client_name == 'erigon-caplin':
                api_version = _get_caplin_version_from_api(ssh_target, node_config)
                if api_version and api_version not in ["Unknown", "Error", "API Error"]:
                    consensus_current = api_version
                else:
                    consensus_current = _get_client_version_from_logs(ssh_target, consensus_container, consensus_client_name)
            else:
                consensus_current = _get_client_version_from_logs(ssh_target, consensus_container, consensus_client_name)
            
            # Fallback to image version if logs don't provide version  
            if consensus_current in ["No Version Found", "Empty Logs", "Log Error"] or consensus_current.startswith("Error:") or consensus_current.startswith("Debug:"):
                # Try to get version via docker exec command
                exec_version = _get_version_via_docker_exec(ssh_target, consensus_container, consensus_client_name)
                if exec_version and exec_version not in ["Error", "Unknown", "Exec Error"]:
                    consensus_current = exec_version
                else:
                    consensus_current = _extract_image_version(f"image: {consensus_image}")
        
        if validator_container and validator_client_name != "Unknown":
            # For Vero (Lido CSM), get version from container environment
            if 'vero' in validator_client_name.lower():
                validator_current = _get_vero_version_from_container(ssh_target, validator_container)
            # For Lodestar in DVT setup, use special version detection first
            elif 'lodestar' in validator_client_name.lower():
                validator_current = _get_lodestar_version_from_container(ssh_target, validator_container)
            else:
                validator_current = _get_client_version_from_logs(ssh_target, validator_container, validator_client_name)
            
            # Fallback to other methods if needed  
            if validator_current in ["No Version Found", "Empty Logs", "Log Error", "Unknown"] or validator_current.startswith("Error:") or validator_current.startswith("Debug:"):
                # Skip fallback methods for Vero (local builds don't respond to exec commands)
                if 'vero' in validator_client_name.lower():
                    validator_current = "local"
                # Try to get version via docker exec command (for non-Lodestar, non-Vero clients)
                elif 'lodestar' not in validator_client_name.lower():
                    exec_version = _get_version_via_docker_exec(ssh_target, validator_container, validator_client_name)
                    if exec_version and exec_version not in ["Error", "Unknown", "Exec Error"]:
                        validator_current = exec_version
                
                # Final fallback to image version
                if validator_current in ["No Version Found", "Empty Logs", "Log Error", "Unknown", "Exec Error"]:
                    validator_current = _extract_image_version(f"image: {validator_image}")
        
        # Handle case where validator might be integrated with consensus client
        # This can happen in all-in-one setups where validator runs with consensus
        if validator_current == "Unknown" and consensus_client_name != "Unknown":
            # Check if consensus client also runs validator (common in some setups)
            # For now, assume separate validator detection is working correctly
            pass
        
        # Get latest versions from GitHub releases
        execution_latest = "Unknown"
        consensus_latest = "Unknown"
        validator_latest = "Unknown"
        
        if execution_client_name != "Unknown":
            execution_latest = _get_latest_github_release(execution_client_name)
        
        if consensus_client_name != "Unknown":
            consensus_latest = _get_latest_github_release(consensus_client_name)
        
        # Handle validator client separately - don't assume it's the same as consensus client
        if validator_client_name != "Unknown" and validator_client_name != consensus_client_name:
            # Separate validator client detected (e.g., Vero, Charon, etc.)
            validator_latest = _get_latest_github_release(validator_client_name)
        elif validator_client_name == "Unknown" and consensus_client_name != "Unknown":
            # No separate validator detected, fallback to consensus client for validator duties
            validator_client_name = consensus_client_name
            validator_current = consensus_current
            validator_latest = consensus_latest
        else:
            validator_latest = "Unknown"
        
        # Store results
        results['execution_current'] = execution_current
        results['execution_latest'] = execution_latest
        results['execution_client'] = execution_client_name
        results['consensus_current'] = consensus_current
        results['consensus_latest'] = consensus_latest
        results['consensus_client'] = consensus_client_name
        results['validator_current'] = validator_current
        results['validator_latest'] = validator_latest
        results['validator_client'] = validator_client_name
        
        # Determine if updates are needed
        exec_needs_update = _version_needs_update(execution_current, execution_latest)
        consensus_needs_update = _version_needs_update(consensus_current, consensus_latest)
        # Validator update status should be based on validator client, not consensus client
        if validator_client_name != "Unknown" and validator_client_name != consensus_client_name:
            # Separate validator client - check its versions
            validator_needs_update = _version_needs_update(validator_current, validator_latest)
        else:
            # Validator is integrated with consensus client
            validator_needs_update = consensus_needs_update
        
        results['execution_needs_update'] = exec_needs_update
        results['consensus_needs_update'] = consensus_needs_update
        results['validator_needs_update'] = validator_needs_update
        results['needs_client_update'] = exec_needs_update or consensus_needs_update or validator_needs_update
        
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        results['execution_current'] = "SSH Error"
        results['execution_latest'] = "SSH Error"
        results['execution_client'] = "Unknown"
        results['consensus_current'] = "SSH Error"  
        results['consensus_latest'] = "SSH Error"
        results['consensus_client'] = "Unknown"
        results['validator_current'] = "SSH Error"
        results['validator_latest'] = "SSH Error"
        results['validator_client'] = "Unknown"
        results['execution_needs_update'] = False
        results['consensus_needs_update'] = False
        results['validator_needs_update'] = False
        results['needs_client_update'] = False
    
    return results

def _get_version_via_docker_exec(ssh_target, container_name, client_name):
    """
    Tries to get version by executing version commands directly in the container.
    Some clients respond to --version flags.
    ssh_target can be None for local execution.
    """
    import re
    
    # Client-specific version commands
    version_commands = {
        'geth': ['geth', 'version'],
        'nethermind': ['/nethermind/nethermind', '--version'],
        'reth': ['reth', '--version'], 
        'besu': ['besu', '--version'],
        'erigon': ['erigon', '--version'],
        'erigon-caplin': ['erigon', '--version'],  # Same as erigon since Caplin is integrated
        'lighthouse': ['lighthouse', '--version'],
        'prysm': ['prysm', '--version'],
        'teku': ['teku', '--version'],
        'nimbus': ['nimbus_beacon_node', '--version'],
        'lodestar': ['lodestar', '--version'],
        'grandine': ['grandine', '--version']
    }
    
    if client_name not in version_commands:
        return "Unknown"
    
    try:
        # Prepare the docker exec command
        cmd_parts = version_commands[client_name]
        docker_exec_cmd = f"docker exec {container_name} {' '.join(cmd_parts)} 2>&1"
        
        # Execute locally or via SSH
        if ssh_target is None:
            # Local execution
            exec_process = subprocess.run(docker_exec_cmd, shell=True, capture_output=True, text=True, timeout=10)
        else:
            # Remote execution via SSH
            exec_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} '{docker_exec_cmd}'"
            exec_process = subprocess.run(exec_cmd, shell=True, capture_output=True, text=True, timeout=10)
        
        if exec_process.returncode == 0:
            output = exec_process.stdout.strip()
            
            # Try to extract version from output
            version_patterns = [
                r'erigon version (\d+\.\d+\.\d+)',  # Erigon: "erigon version 3.0.13-hash"
                r'Grandine (\d+\.\d+\.\d+)',        # Grandine: "Grandine 1.1.2"  
                r'Version:\s*(\d+\.\d+\.\d+)\+',    # Nethermind: "Version: 1.32.3+hash"
                r'Version:\s*v?(\d+\.\d+\.\d+)',    # General: "Version: v1.32.3" or "Version: 1.32.3"
                r'v?(\d+\.\d+\.\d+)',               # Simple: "v1.32.3" or "1.32.3"
                r'version\s*v?(\d+\.\d+\.\d+)'      # General: "version v1.32.3"
            ]
            
            for pattern in version_patterns:
                match = re.search(pattern, output, re.IGNORECASE)
                if match:
                    return match.group(1)
        
        return "Exec Error"
        
    except Exception as e:
        return "Error"

def _get_lodestar_version_from_container(ssh_target, container_name):
    """
    Special version detection for Lodestar in DVT/Charon setups.
    Tries multiple methods to extract version information.
    """
    try:
        # Try the Lodestar-specific version command first
        lodestar_cmd = f"docker exec {container_name} /usr/app/node_modules/.bin/lodestar --version 2>/dev/null"
        full_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} '{lodestar_cmd}'"
        result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0 and result.stdout.strip():
            output = result.stdout.strip()
            # Parse version from Lodestar output like "Version: v1.32.0/8f56b55"
            import re
            version_match = re.search(r'Version:\s*v?(\d+\.\d+\.\d+)', output)
            if version_match:
                return version_match.group(1)
        
        # Fallback methods
        fallback_commands = [
            f"docker exec {container_name} cat package.json 2>/dev/null | grep '\"version\"' | head -1",
            f"docker inspect {container_name} --format '{{{{.Config.Image}}}}' 2>/dev/null"
        ]
        
        for cmd in fallback_commands:
            full_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} '{cmd}'"
            result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0 and result.stdout.strip():
                output = result.stdout.strip()
                
                # Parse from package.json
                if '"version"' in output:
                    import re
                    version_match = re.search(r'"version":\s*"([^"]+)"', output)
                    if version_match:
                        return version_match.group(1)
                
                # Parse from image tag
                if ':' in output and 'lodestar' in output.lower():
                    return _extract_image_version(f"image: {output}")
        
        return "Unknown"
        
    except Exception:
        return "Unknown"

def _get_caplin_version_from_api(ssh_target, node_config):
    """
    Get Erigon+Caplin version directly from the Beacon API.
    Example API response: {"data":{"version":"Caplin/v3.0.15 linux/amd64"}}
    """
    try:
        import json
        beacon_api_port = node_config.get('beacon_api_port', 5052)
        
        if ssh_target is None:
            # Local execution
            api_cmd = f"curl -s --connect-timeout 5 --max-time 10 http://localhost:{beacon_api_port}/eth/v1/node/version"
        else:
            # Remote execution via SSH
            api_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} \"curl -s --connect-timeout 5 --max-time 10 http://localhost:{beacon_api_port}/eth/v1/node/version\""
        
        result = subprocess.run(api_cmd, shell=True, capture_output=True, text=True, timeout=15)
        
        if result.returncode == 0 and result.stdout.strip():
            try:
                # Parse JSON response
                api_data = json.loads(result.stdout.strip())
                version_string = api_data.get('data', {}).get('version', '')
                
                # Parse version from "Caplin/v3.0.15 linux/amd64"
                if 'Caplin/' in version_string:
                    import re
                    version_match = re.search(r'Caplin/v?(\d+\.\d+\.\d+)', version_string)
                    if version_match:
                        return version_match.group(1)
                
                # Fallback: try to extract any version pattern
                version_match = re.search(r'v?(\d+\.\d+\.\d+)', version_string)
                if version_match:
                    return version_match.group(1)
                    
            except (json.JSONDecodeError, KeyError) as e:
                # If JSON parsing fails, try to extract version directly from string
                import re
                version_match = re.search(r'v?(\d+\.\d+\.\d+)', result.stdout)
                if version_match:
                    return version_match.group(1)
        
        return "API Error"
        
    except Exception as e:
        return "API Error"

def _get_vero_version_from_container(ssh_target, container_name):
    """
    Special version detection for Vero containers.
    Gets version from container environment variables.
    """
    try:
        # Try to get version from container environment (GIT_TAG) - using simpler approach
        env_cmd = f"docker inspect {container_name} -f '{{{{range .Config.Env}}}}{{{{println .}}}}{{{{end}}}}' | grep GIT_TAG"
        full_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} \"{env_cmd}\""
        result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0 and result.stdout.strip():
            # Parse GIT_TAG=v1.1.3 format
            output = result.stdout.strip()
            if 'GIT_TAG=' in output:
                version = output.split('GIT_TAG=')[1].strip()
                # Remove 'v' prefix if present
                if version.startswith('v'):
                    version = version[1:]
                return version
        
        # Fallback to "local" if we can't determine version
        return "local"
        
    except Exception:
        return "local"

def _get_client_version_from_logs(ssh_target, container_name, client_name):
    """
    Extracts the actual client version from Docker container logs.
    Each Ethereum client prints its version during startup.
    ssh_target can be None for local execution.
    """
    import re
    
    try:
        # Determine if we're running locally or via SSH
        if ssh_target is None:
            # Local execution
            logs_cmd = f"docker logs --tail 100 {container_name} 2>&1"
        else:
            # Remote execution via SSH
            logs_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} 'docker logs --tail 100 {container_name} 2>&1'"
            
        logs_process = subprocess.run(logs_cmd, shell=True, capture_output=True, text=True, timeout=15)
        
        logs = ""
        if logs_process.returncode == 0:
            logs = logs_process.stdout.strip()
        
        # If no version found in recent logs, try the beginning of logs (for busy clients like Lodestar)
        if not logs or not re.search(r'version|Version|v\d+\.\d+\.\d+', logs, re.IGNORECASE):
            if ssh_target is None:
                # Local execution
                head_cmd = f"docker logs {container_name} 2>&1 | head -50"
            else:
                # Remote execution via SSH
                head_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} 'docker logs {container_name} 2>&1 | head -50'"
                
            head_process = subprocess.run(head_cmd, shell=True, capture_output=True, text=True, timeout=15)
            if head_process.returncode == 0:
                head_logs = head_process.stdout.strip()
                if head_logs and re.search(r'version|Version|v\d+\.\d+\.\d+', head_logs, re.IGNORECASE):
                    logs = head_logs
        
        if not logs:
            return "Empty Logs"
        
        # Client-specific version patterns (more comprehensive)
        version_patterns = {
            'geth': [
                r'Geth/v(\d+\.\d+\.\d+)',
                r'Version: (\d+\.\d+\.\d+)',
                r'geth version (\d+\.\d+\.\d+)',
                r'go-ethereum v(\d+\.\d+\.\d+)',
                r'ethereum/client-go:v(\d+\.\d+\.\d+)',
                r'Starting Geth.*?(\d+\.\d+\.\d+)',
                r'Welcome to Geth.*?v(\d+\.\d+\.\d+)'
            ],
            'nethermind': [
                r'Version: (\d+\.\d+\.\d+)\+',  # Match version with commit hash
                r'Version: (\d+\.\d+\.\d+)',    # Match version without commit hash
                r'Nethermind \((\d+\.\d+\.\d+)\)',
                r'Nethermind v(\d+\.\d+\.\d+)',
                r'Starting Nethermind (\d+\.\d+\.\d+)',
                r'Nethermind Ethereum Client (\d+\.\d+\.\d+)'
            ],
            'reth': [
                r'reth Version: (\d+\.\d+\.\d+)',
                r'reth v(\d+\.\d+\.\d+)',
                r'Version (\d+\.\d+\.\d+)',
                r'Starting reth v(\d+\.\d+\.\d+)',
                r'reth (\d+\.\d+\.\d+)',
                r'paradigmxyz/reth:v(\d+\.\d+\.\d+)',
                r'Reth version v(\d+\.\d+\.\d+)',
                r'Starting up reth v(\d+\.\d+\.\d+)'
            ],
            'besu': [
                r'besu/v(\d+\.\d+\.\d+)',
                r'Besu version: v(\d+\.\d+\.\d+)',
                r'Version: (\d+\.\d+\.\d+)',
                r'Starting Besu version v(\d+\.\d+\.\d+)',
                r'hyperledger/besu:(\d+\.\d+\.\d+)',
                r'Hyperledger Besu v(\d+\.\d+\.\d+)',
                r'Starting Hyperledger Besu.*?(\d+\.\d+\.\d+)'
            ],
            'erigon': [
                r'Erigon version: v(\d+\.\d+\.\d+)',
                r'erigon/(\d+\.\d+\.\d+)',
                r'Version: (\d+\.\d+\.\d+)',
                r'Starting Erigon (\d+\.\d+\.\d+)',
                r'ledgerwatch/erigon:v(\d+\.\d+\.\d+)',
                r'Erigon/v(\d+\.\d+\.\d+)',
                r'erigon.*?(\d+\.\d+\.\d+)',
                r'Building Erigon.*?(\d+\.\d+\.\d+)'
            ],
            'erigon-caplin': [
                # Same patterns as erigon since Caplin is integrated
                r'Erigon version: v(\d+\.\d+\.\d+)',
                r'erigon/(\d+\.\d+\.\d+)', 
                r'Version: (\d+\.\d+\.\d+)',
                r'Starting Erigon (\d+\.\d+\.\d+)',
                r'ledgerwatch/erigon:v(\d+\.\d+\.\d+)',
                r'Erigon/v(\d+\.\d+\.\d+)',
                r'erigon.*?(\d+\.\d+\.\d+)',
                r'Building Erigon.*?(\d+\.\d+\.\d+)',
                # Caplin-specific log patterns
                r'Caplin.*?(\d+\.\d+\.\d+)',
                r'Starting Caplin.*?(\d+\.\d+\.\d+)',
                r'Beacon API.*?v(\d+\.\d+\.\d+)'
            ],
            'lighthouse': [
                r'Lighthouse v(\d+\.\d+\.\d+)',
                r'Version: v(\d+\.\d+\.\d+)',
                r'lighthouse (\d+\.\d+\.\d+)',
                r'Starting beacon node.*?v(\d+\.\d+\.\d+)',
                r'sigp/lighthouse:v(\d+\.\d+\.\d+)'
            ],
            'prysm': [
                r'Prysm/v(\d+\.\d+\.\d+)',
                r'Version: v(\d+\.\d+\.\d+)',
                r'prysm version (\d+\.\d+\.\d+)',
                r'Starting Prysm v(\d+\.\d+\.\d+)',
                r'prysmaticlabs/prysm.*?:v(\d+\.\d+\.\d+)'
            ],
            'teku': [
                r'teku/v(\d+\.\d+\.\d+)',
                r'Version: (\d+\.\d+\.\d+)',
                r'Teku version: v(\d+\.\d+\.\d+)',
                r'Starting Teku.*?(\d+\.\d+\.\d+)',
                r'consensys/teku:(\d+\.\d+\.\d+)'
            ],
            'nimbus': [
                r'Nimbus beacon node v(\d+\.\d+\.\d+)',
                r'nimbus_beacon_node v(\d+\.\d+\.\d+)',
                r'Version: (\d+\.\d+\.\d+)',
                r'Starting Nimbus.*?v(\d+\.\d+\.\d+)',
                r'statusim/nimbus-eth2:.*?(\d+\.\d+\.\d+)'
            ],
            'lodestar': [
                r'version=v(\d+\.\d+\.\d+)',       # New pattern for "version=v1.32.0/8f56b55"
                r'Lodestar/(\d+\.\d+\.\d+)',
                r'lodestar v(\d+\.\d+\.\d+)',
                r'Version: (\d+\.\d+\.\d+)',
                r'Starting Lodestar.*?v(\d+\.\d+\.\d+)',
                r'chainsafe/lodestar:v(\d+\.\d+\.\d+)'
            ],
            'grandine': [
                r'client version: Grandine/(\d+\.\d+\.\d+)',  # Specific for Grandine log format
                r'Grandine/(\d+\.\d+\.\d+)',
                r'grandine v(\d+\.\d+\.\d+)',
                r'Version: (\d+\.\d+\.\d+)',
                r'Starting Grandine.*?v(\d+\.\d+\.\d+)',
                r'grandinetech/grandine:v(\d+\.\d+\.\d+)',
                r'Grandine (\d+\.\d+\.\d+)'
            ]
        }
        
        # Try client-specific patterns first
        if client_name in version_patterns:
            for pattern in version_patterns[client_name]:
                match = re.search(pattern, logs, re.IGNORECASE | re.MULTILINE | re.DOTALL)
                if match:
                    return match.group(1)
        
        # Fallback: broader version patterns
        fallback_patterns = [
            r'[vV]ersion:?\s*v?(\d+\.\d+\.\d+)',
            r'v(\d+\.\d+\.\d+)',
            r'(\d+\.\d+\.\d+[-\w]*)',  # Include pre-release versions
            r'Starting.*?(\d+\.\d+\.\d+)',
            r'Welcome.*?(\d+\.\d+\.\d+)',
            r'Client.*?(\d+\.\d+\.\d+)'
        ]
        
        for pattern in fallback_patterns:
            match = re.search(pattern, logs, re.IGNORECASE | re.MULTILINE)
            if match:
                version = match.group(1)
                # Clean up the version (remove non-standard suffixes)
                clean_version = re.match(r'(\d+\.\d+\.\d+)', version)
                if clean_version:
                    return clean_version.group(1)
                return version
        
        # Debug: If no version found, check if logs contain any numbers
        # This helps us understand what's in the logs
        if re.search(r'\d+\.\d+', logs):
            # There are version-like numbers, but our patterns didn't catch them
            # Let's try a very broad search for the first occurrence
            broad_match = re.search(r'(\d+\.\d+\.\d+)', logs)
            if broad_match:
                return broad_match.group(1)
        
        return "No Version Found"
        
    except Exception as e:
        return f"Error: {str(e)[:20]}"

def _identify_client_from_image(image, client_type):
    """
    Identifies the Ethereum client from the Docker image name.
    Returns the client name for GitHub API lookup and display.
    Extracts clean client name from complex image strings.
    """
    image_lower = image.lower()
    
    if client_type == 'execution':
        if 'geth' in image_lower:
            return 'geth'
        elif 'nethermind' in image_lower:
            return 'nethermind'
        elif 'reth' in image_lower:
            return 'reth'
        elif 'besu' in image_lower:
            return 'besu'
        elif 'erigon' in image_lower:
            return 'erigon'
    
    elif client_type in ['consensus', 'validator']:
        if 'lighthouse' in image_lower:
            return 'lighthouse'
        elif 'prysm' in image_lower:
            return 'prysm'
        elif 'teku' in image_lower:
            return 'teku'
        elif 'nimbus' in image_lower:
            return 'nimbus'
        elif 'lodestar' in image_lower:
            return 'lodestar'
        elif 'grandine' in image_lower:
            return 'grandine'
    
    return "Unknown"

def _get_latest_github_release(client_name):
    """
    Gets the latest release version from GitHub for a specific Ethereum client.
    Implements caching and rate limiting awareness.
    """
    # Cache to avoid repeated API calls within the same session
    if not hasattr(_get_latest_github_release, 'cache'):
        _get_latest_github_release.cache = {}
        _get_latest_github_release.last_reset_check = 0
    
    # Check cache first
    if client_name in _get_latest_github_release.cache:
        cached_data = _get_latest_github_release.cache[client_name]
        # Cache is valid for 10 minutes
        if time.time() - cached_data['timestamp'] < 600:
            return cached_data['version']
    
    # GitHub repositories mapping
    github_repos = {
        'geth': 'ethereum/go-ethereum',
        'nethermind': 'NethermindEth/nethermind',
        'reth': 'paradigmxyz/reth',
        'besu': 'hyperledger/besu',
        'erigon': 'ledgerwatch/erigon',
        'erigon-caplin': 'ledgerwatch/erigon',  # Caplin is integrated into Erigon
        'lighthouse': 'sigp/lighthouse',
        'prysm': 'prysmaticlabs/prysm',
        'teku': 'Consensys/teku',
        'nimbus': 'status-im/nimbus-eth2',
        'lodestar': 'ChainSafe/lodestar',
        'grandine': 'grandinetech/grandine',
        'vero': 'serenita-org/vero'  # Vero validator client from Serenita
    }
    
    if client_name not in github_repos:
        return "Unknown"
    
    repo = github_repos[client_name]
    api_url = f"https://api.github.com/repos/{repo}/releases/latest"
    
    try:
        response = requests.get(api_url, timeout=10)
        
        if response.status_code == 200:
            release_data = response.json()
            tag_name = release_data.get('tag_name', '')
            # Clean version tag (remove 'v' prefix if present)
            version = tag_name.lstrip('v')
            
            # Cache the result
            _get_latest_github_release.cache[client_name] = {
                'version': version,
                'timestamp': time.time()
            }
            
            return version
        elif response.status_code == 403:
            # Rate limited - return cached version if available, otherwise indicate rate limiting
            if client_name in _get_latest_github_release.cache:
                return _get_latest_github_release.cache[client_name]['version']
            else:
                return "Rate Limited"
        else:
            return "API Error"
    except Exception as e:
        # If we have a cached version, return it during network errors
        if client_name in _get_latest_github_release.cache:
            return _get_latest_github_release.cache[client_name]['version']
        return "Network Error"

def _version_needs_update(current_version, latest_version):
    """
    Compares current and latest versions to determine if an update is needed.
    Handles semantic versioning comparison.
    """
    error_states = ["Unknown", "Error", "SSH Error", "Log Error", "Log Parse Error", 
                   "Empty Logs", "No Version Found"]
    
    if current_version in error_states or current_version.startswith("Error:") or \
       latest_version in ["Unknown", "Error", "API Error", "Network Error"]:
        return False
    
    # If current version is "local", "latest", or "main", try to be more conservative
    if current_version in ["local", "latest", "main", "master"]:
        return False
    
    # Simple string comparison for now - could be enhanced with proper semver
    if current_version != latest_version:
        return True
    
    return False

def _extract_version_number(version_string):
    """
    Extracts version number from client version output.
    Handles different client output formats.
    """
    import re
    
    if not version_string or version_string in ["Unknown", "Error"]:
        return version_string
        
    # Common patterns for version extraction
    patterns = [
        r'v?(\d+\.\d+\.\d+)',  # Standard semver
        r'Version:\s*(\d+\.\d+\.\d+)',  # Some clients use "Version: x.y.z"
        r'version\s*(\d+\.\d+\.\d+)',  # Case insensitive version
        r'(\d+\.\d+\.\d+)'  # Just numbers
    ]
    
    for pattern in patterns:
        match = re.search(pattern, version_string, re.IGNORECASE)
        if match:
            return match.group(1)
    
    # If no version pattern found, return first word that might be version-like
    words = version_string.strip().split()
    for word in words:
        if re.match(r'v?\d+\.\d+', word):
            return word.lstrip('v')
    
    return "Unknown"

def _extract_image_version(image_string):
    """
    Extracts version from Docker image name and formats it compactly.
    Example: "nethermind/nethermind:1.25.4" -> "1.25.4"
    Example: "besu/v25.7.0/linux-x86_64/openjdk-java-21" -> "25.7.0"
    """
    import re
    
    if not image_string or "image:" not in image_string:
        return "Unknown"
        
    # Extract everything after "image:" and clean it
    image_part = image_string.split("image:")[-1].strip()
    
    # Extract version after the last ":"
    if ":" in image_part:
        version = image_part.split(":")[-1].strip()
        # Remove quotes and extra characters
        version = re.sub(r'["\']', '', version)
        
        # Clean up complex version strings to show only version number
        # Handle formats like: v25.7.0/linux-x86_64/openjdk-java-21 -> 25.7.0
        if "/" in version:
            version = version.split("/")[0]  # Take only first part before slash
        
        # Remove 'v' prefix if present
        if version.startswith('v'):
            version = version[1:]
            
        return version
    
    return "latest"

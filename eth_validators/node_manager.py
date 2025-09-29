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
    eth_docker_path = node_config.get('eth_docker_path', '/home/egk/eth-docker')
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
    results = {'fallback_used': False}
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
                results['fallback_used'] = True
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
                        results['updates_available'] = update_count
                        results['needs_system_update'] = update_count > 0
                    else:
                        results['updates_available'] = "Fallback Error"
                        results['needs_system_update'] = False
                else:
                    results['updates_available'] = "Fallback Failed"
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
    noninteractive_opts = ('-yq '
                           '-o Dpkg::Options::="--force-confdef" '
                           '-o Dpkg::Options::="--force-confold"')

    if ssh_user == 'root':
        apt_cmd = (
            'DEBIAN_FRONTEND=noninteractive apt-get update -y && '
            f'DEBIAN_FRONTEND=noninteractive apt-get upgrade {noninteractive_opts}'
        )
    else:
        apt_cmd = (
            'sudo env DEBIAN_FRONTEND=noninteractive apt-get update -y && '
            f'sudo env DEBIAN_FRONTEND=noninteractive apt-get upgrade {noninteractive_opts}'
        )
    
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
                    
                    # Identify execution clients - check both container name and image
                    elif ('execution' in container_name.lower() or 
                          any(exec_client in container_name.lower() or exec_client in image.lower() 
                              for exec_client in ['geth', 'nethermind', 'reth', 'besu', 'erigon'])):
                        execution_client_name = _identify_client_from_image(image, 'execution')
                        execution_container = container_name
                        execution_image = image
                    
                    # Identify consensus clients (beacon nodes) - these override erigon-caplin
                    elif (('consensus' in container_name.lower() or 
                          any(cons_client in container_name.lower() or cons_client in image.lower()
                              for cons_client in ['lighthouse', 'prysm', 'teku', 'nimbus', 'lodestar', 'grandine'])) 
                          and 'validator' not in container_name.lower()):
                        consensus_client_name = _identify_client_from_image(image, 'consensus')
                        consensus_container = container_name
                        consensus_image = image                    # Identify validator clients (separate from consensus) - collect multiple
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
            elif execution_client_name.lower() in ['nethermind', 'reth', 'besu', 'geth', 'erigon']:
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
        elif validator_client_name == consensus_client_name and consensus_client_name != "Unknown":
            # Same client for both consensus and validator (e.g., lodestar, teku, prysm)
            # Use the consensus client's latest version for validator too since they're always the same
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
    Enhanced to handle local builds and various image formats.
    """
    image_lower = image.lower()
    
    if client_type == 'execution':
        # Check for execution clients (order matters for specificity)
        if 'reth' in image_lower:
            return 'reth'
        elif 'nethermind' in image_lower:
            return 'nethermind'
        elif 'geth' in image_lower or 'go-ethereum' in image_lower:
            return 'geth'
        elif 'besu' in image_lower:
            return 'besu'
        elif 'erigon' in image_lower:
            return 'erigon'
    
    elif client_type in ['consensus', 'validator']:
        # Check for consensus/validator clients (order matters for specificity)
        if 'lighthouse' in image_lower:
            return 'lighthouse'
        elif 'grandine' in image_lower:
            return 'grandine'
        elif 'lodestar' in image_lower:
            return 'lodestar'
        elif 'prysm' in image_lower:
            return 'prysm'
        elif 'teku' in image_lower:
            return 'teku'
        elif 'nimbus' in image_lower:
            return 'nimbus'
    
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
    Handles semantic versioning comparison with pre-release handling.
    """
    error_states = ["Unknown", "Error", "SSH Error", "Log Error", "Log Parse Error", 
                   "Empty Logs", "No Version Found"]
    
    if current_version in error_states or current_version.startswith("Error:") or \
       latest_version in ["Unknown", "Error", "API Error", "Network Error"]:
        return False
    
    # If current version is "local", "latest", or "main", try to be more conservative
    if current_version in ["local", "latest", "main", "master"]:
        return False
    
    # Use semantic version comparison
    return _compare_versions(current_version, latest_version) < 0

def _compare_versions(version1, version2):
    """
    Compare two version strings using semantic versioning rules.
    Returns:
        -1 if version1 < version2 (version1 needs update)
         0 if version1 == version2 (versions are equal)
         1 if version1 > version2 (version1 is newer)
    
    Handles pre-release versions like 8.0.0-rc.0, 8.0.0-alpha.1, etc.
    """
    import re
    
    def parse_version(version_str):
        """Parse version string into components for comparison"""
        # Clean version string
        version_str = version_str.strip().lstrip('v')
        
        # Split version and pre-release parts
        if '-' in version_str:
            base_version, pre_release = version_str.split('-', 1)
        else:
            base_version, pre_release = version_str, None
        
        # Parse base version (major.minor.patch)
        version_parts = base_version.split('.')
        try:
            major = int(version_parts[0]) if len(version_parts) > 0 else 0
            minor = int(version_parts[1]) if len(version_parts) > 1 else 0
            patch = int(version_parts[2]) if len(version_parts) > 2 else 0
        except (ValueError, IndexError):
            # Fallback for malformed versions
            major = minor = patch = 0
        
        return (major, minor, patch, pre_release)
    
    v1_parts = parse_version(version1)
    v2_parts = parse_version(version2)
    
    # Compare base version (major.minor.patch)
    v1_base = v1_parts[:3]
    v2_base = v2_parts[:3]
    
    if v1_base < v2_base:
        return -1
    elif v1_base > v2_base:
        return 1
    
    # Base versions are equal, check pre-release
    v1_pre = v1_parts[3]
    v2_pre = v2_parts[3]
    
    # If one has pre-release and other doesn't
    if v1_pre is None and v2_pre is not None:
        # 8.0.0 > 8.0.0-rc.0 (stable is newer than pre-release)
        return 1
    elif v1_pre is not None and v2_pre is None:
        # 8.0.0-rc.0 < 8.0.0 (pre-release is older than stable)
        return -1
    elif v1_pre is None and v2_pre is None:
        # Both are stable versions and base versions are equal
        return 0
    
    # Both have pre-release identifiers - compare them
    # This is a simple comparison - could be enhanced for better pre-release ordering
    if v1_pre == v2_pre:
        return 0
    elif v1_pre < v2_pre:
        return -1
    else:
        return 1

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

def get_node_port_mappings(node_config, source: str = "both"):
    """Collect port mappings for a node from docker and/or eth-docker .env files.

    Returns a dict with entries and optional errors:
      {
        'node': name,
        'entries': [ { 'service','container','host_port','container_port','proto','source','network' }... ],
        'errors': [str,...]
      }

    source: 'docker' | 'env' | 'both'
    """
    name = node_config.get('name')
    is_local = node_config.get('is_local', False)
    ssh_user = node_config.get('ssh_user', 'root')
    ssh_target = None if is_local else f"{ssh_user}@{node_config['tailscale_domain']}"
    results = {'node': name, 'entries': [], 'errors': []}

    def _run(cmd, timeout=15, cwd=None):
        try:
            if ssh_target is None:
                return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=cwd)
            else:
                # Wrap remote command
                return subprocess.run(f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} '{cmd}'", shell=True, capture_output=True, text=True, timeout=timeout)
        except Exception as e:
            class R:
                pass
            r = R()
            r.returncode = 1
            r.stdout = ''
            r.stderr = str(e)
            return r

    def _guess_service(container_name: str, image: str = ""):
        c = container_name.lower()
        i = (image or "").lower()
        if any(k in c or k in i for k in ['execution', 'geth', 'nethermind', 'reth', 'besu', 'erigon']):
            return 'execution'
        if any(k in c or k in i for k in ['consensus', 'beacon', 'lighthouse', 'teku', 'nimbus', 'lodestar', 'prysm', 'grandine', 'caplin']):
            return 'consensus'
        if any(k in c or k in i for k in ['validator', 'vc', 'vero', 'charon']):
            return 'validator'
        if 'mev' in c or 'boost' in c:
            return 'mev-boost'
        if 'grafana' in c:
            return 'grafana'
        if 'prometheus' in c:
            return 'prometheus'
        return 'other'

    def _add_entry(service, container, host_port, container_port, proto, src, network=None, published=None):
        try:
            hp = int(str(host_port).split('-')[0]) if host_port else None
        except Exception:
            hp = None
        try:
            cp = int(str(container_port).split('-')[0]) if container_port else None
        except Exception:
            cp = None
        results['entries'].append({
            'service': service,
            'container': container,
            'host_port': hp,
            'container_port': cp,
            'proto': proto or 'tcp',
            'source': src,
            'network': network or '-',
            'published': bool(published) if published is not None else (hp is not None)
        })

    # Indexes to relate env ports to live docker ports
    docker_index = {}  # (host_port, proto) -> {'container': str, 'container_port': int}
    docker_keys = set()

    # 1) From docker ps
    if source in ('both', 'docker'):
        # Use pipe-separated format to avoid tab issues with long port mappings
        ps_cmd = 'docker ps --format "{{.ID}}|{{.Names}}|{{.Image}}|{{.Ports}}"'
        r = _run(ps_cmd, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            # Handle line continuations in docker ps output - port mappings can wrap
            raw_lines = r.stdout.strip().split('\n')
            processed_lines = []
            current_line = ""
            
            for line in raw_lines:
                line = line.strip()
                # Check if this line has the expected pipe-separated format (4 fields)
                if line.count('|') >= 3:
                    # This is a new container entry, save previous if exists
                    if current_line:
                        processed_lines.append(current_line)
                    current_line = line
                elif current_line and line:
                    # This is likely a continuation of port mappings from previous line
                    current_line = current_line.rstrip() + " " + line
                    
            # Don't forget the last line
            if current_line:
                processed_lines.append(current_line)
            
            for line in processed_lines:
                try:
                    parts = line.split('|')
                    if len(parts) < 4:
                        continue
                    cid, cname, image, ports = parts[0], parts[1], parts[2], '|'.join(parts[3:])  # Handle multiple pipes in ports
                    service = _guess_service(cname, image)
                    # Parse ports: handle complex formats like "0.0.0.0:30315->30315/tcp, [::]:30315->30315/tcp, 30303/tcp"
                    import re as _re
                    
                    # Track unique port mappings to avoid duplicates from IPv4/IPv6
                    seen_mappings = set()
                    
                    # Split on commas but handle complex IPv6 addresses carefully
                    port_items = []
                    current = ""
                    bracket_depth = 0
                    
                    for char in ports:
                        if char == '[':
                            bracket_depth += 1
                        elif char == ']':
                            bracket_depth -= 1
                        elif char == ',' and bracket_depth == 0:
                            if current.strip():
                                port_items.append(current.strip())
                            current = ""
                            continue
                        current += char
                    
                    if current.strip():
                        port_items.append(current.strip())
                    
                    for item in port_items:
                        item = item.strip()
                        if not item:
                            continue
                            
                        if '->' in item:
                            # Published port mapping like "0.0.0.0:30315->30315/tcp" or "[::]:9002->9002/udp"
                            left, right = item.split('->', 1)
                            
                            # Parse protocol from right side (e.g., "30315/tcp" or "8545-8546/tcp")
                            proto = 'tcp'
                            cont_part = right
                            if '/' in right:
                                cont_part, proto = right.rsplit('/', 1)
                            
                            # Extract host port from left side - handle IPv4 and IPv6 formats
                            host_part = None
                            if left.startswith('[') and ']:' in left:
                                # IPv6 format like "[::]:9002"
                                host_part = left.split(']:')[-1]
                            elif ':' in left and not left.startswith('['):
                                # IPv4 format like "0.0.0.0:30315"  
                                host_part = left.split(':')[-1]
                            else:
                                # Direct port
                                host_part = left
                            
                            if host_part and cont_part:
                                # Create unique key to avoid IPv4/IPv6 duplicates
                                mapping_key = (host_part, cont_part, proto)
                                if mapping_key not in seen_mappings:
                                    seen_mappings.add(mapping_key)
                                    
                                    # Handle port ranges (e.g., "8545-8546")
                                    if '-' in host_part and _re.match(r'^\d+-\d+$', host_part):
                                        try:
                                            start_port, end_port = host_part.split('-', 1)
                                            for port_num in range(int(start_port), int(end_port) + 1):
                                                _add_entry(service, cname, port_num, port_num, proto, 'docker', published=True)
                                                docker_index[(port_num, proto)] = {'container': cname, 'container_port': port_num}
                                                docker_keys.add((port_num, proto))
                                        except (ValueError, TypeError):
                                            # Fallback to treating as single port
                                            try:
                                                hp = int(host_part)
                                                cp = int(cont_part) if cont_part.isdigit() else hp
                                                _add_entry(service, cname, hp, cp, proto, 'docker', published=True)
                                                docker_index[(hp, proto)] = {'container': cname, 'container_port': cp}
                                                docker_keys.add((hp, proto))
                                            except ValueError:
                                                pass
                                    else:
                                        # Single port
                                        try:
                                            hp = int(host_part)
                                            cp = int(cont_part) if cont_part.isdigit() else hp
                                            _add_entry(service, cname, hp, cp, proto, 'docker', published=True)
                                            docker_index[(hp, proto)] = {'container': cname, 'container_port': cp}
                                            docker_keys.add((hp, proto))
                                        except ValueError:
                                            pass
                                            
                        else:
                            # Bare exposure like "30303/tcp" or "9000-9001/tcp"
                            proto = 'tcp'
                            port_part = item
                            if '/' in item:
                                port_part, proto = item.rsplit('/', 1)
                            
                            # Inspect network mode for the container to determine if published
                            net_mode = None
                            insp = _run(f"docker inspect -f '{{{{.HostConfig.NetworkMode}}}}' {cid}", timeout=10)
                            if insp.returncode == 0:
                                net_mode = (insp.stdout or '').strip()
                            
                            # If host network, host port equals container port (published)
                            if net_mode == 'host':
                                # Handle port ranges in host network mode
                                if '-' in port_part and _re.match(r'^\d+-\d+$', port_part):
                                    try:
                                        start_port, end_port = port_part.split('-', 1)
                                        for port_num in range(int(start_port), int(end_port) + 1):
                                            _add_entry(service, cname, port_num, port_num, proto, 'docker', published=True)
                                            docker_index[(port_num, proto)] = {'container': cname, 'container_port': port_num}
                                            docker_keys.add((port_num, proto))
                                    except (ValueError, TypeError):
                                        try:
                                            hp = int(port_part)
                                            _add_entry(service, cname, hp, hp, proto, 'docker', published=True)
                                            docker_index[(hp, proto)] = {'container': cname, 'container_port': hp}
                                            docker_keys.add((hp, proto))
                                        except ValueError:
                                            pass
                                else:
                                    try:
                                        hp = int(port_part)
                                        _add_entry(service, cname, hp, hp, proto, 'docker', published=True)
                                        docker_index[(hp, proto)] = {'container': cname, 'container_port': hp}
                                        docker_keys.add((hp, proto))
                                    except ValueError:
                                        pass
                            else:
                                # Not host network; keep as container-only exposure (not published)
                                try:
                                    cp = int(port_part) if port_part.isdigit() else None
                                    _add_entry(service, cname, None, cp, proto, 'docker', published=False)
                                except ValueError:
                                    pass
                except Exception as e:
                    results['errors'].append(f"docker-parse:{str(e)[:40]}")
        else:
            if r.stderr:
                results['errors'].append(f"docker:{r.stderr.strip()[:80]}")

    # 2) From .env files in eth-docker directories
    if source in ('both', 'env'):
        env_files = []
        networks = node_config.get('networks') or {}
        if networks:
            for net_key, net_cfg in networks.items():
                path = net_cfg.get('eth_docker_path') or net_cfg.get('path') or ''
                if path:
                    env_files.append((net_key, f"{path}/.env"))
        else:
            base_path = node_config.get('eth_docker_path', '/home/egk/eth-docker')
            env_files.append(('-', f"{base_path}/.env"))

        for net_name, env_path in env_files:
            # Read .env content
            cat_cmd = f"test -f {env_path} && cat {env_path} || echo __MISSING__"
            r = _run(cat_cmd, timeout=10)
            if r.returncode != 0 or not r.stdout:
                continue
            content = r.stdout
            if '__MISSING__' in content:
                continue
            try:
                for line in content.splitlines():
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' not in line:
                        continue
                    key, val = line.split('=', 1)
                    key = key.strip().upper()
                    val = val.strip()
                    # Accept any *_PORT or *PORTS variables
                    if key.endswith('PORT') or key.endswith('PORTS') or key.endswith('_PORT_TCP') or key.endswith('_PORT_UDP'):
                        # Extract numbers/ranges from val e.g., "8545", "30303-30304"
                        import re as _re
                        m = _re.findall(r"\b\d{2,5}(?:-\d{2,5})?\b", val)
                        if not m:
                            continue
                        # Guess protocol by name
                        proto = 'tcp'
                        if 'UDP' in key:
                            proto = 'udp'
                        # Guess service from key
                        service = 'other'
                        lk = key.lower()
                        if any(k in lk for k in ['el_', 'execution', 'geth', 'nethermind', 'reth', 'besu', 'erigon']):
                            service = 'execution'
                        elif any(k in lk for k in ['cl_', 'consensus', 'beacon', 'lighthouse', 'teku', 'nimbus', 'lodestar', 'prysm', 'grandine', 'caplin']):
                            service = 'consensus'
                        elif any(k in lk for k in ['validator', 'vc', 'vero', 'charon']):
                            service = 'validator'
                        elif 'mev' in lk or 'boost' in lk:
                            service = 'mev-boost'
                        for tok in m:
                            # Prefer live docker mapping when available; skip duplicate env entries
                            try:
                                hp = int(str(tok).split('-')[0]) if tok else None
                            except Exception:
                                hp = None
                            if hp is not None and (hp, proto) in docker_keys:
                                # Already represented by docker; skip to avoid duplicates
                                continue
                            # Enrich container info from docker when possible
                            cont_name = service
                            cont_port = None
                            if hp is not None and (hp, proto) in docker_index:
                                cont_name = docker_index[(hp, proto)]['container'] or '-'
                                cont_port = docker_index[(hp, proto)]['container_port']
                            # Default container_port to host_port if unknown to keep table filled
                            if cont_port is None:
                                cont_port = hp
                            _add_entry(service, cont_name, hp, cont_port, proto, 'env', net_name)
            except Exception as e:
                results['errors'].append(f"env-parse:{str(e)[:40]}")

    return results


def run_command_on_node(node_name, command, timeout=10):
    """Run a command on a node via SSH and return the output.
    
    Args:
        node_name: The name of the node from config
        command: The command to run
        timeout: Timeout in seconds
        
    Returns:
        Command output as string, or None if failed
    """
    import subprocess
    import yaml
    try:
        from eth_validators.config import get_config_path
        config = yaml.safe_load(get_config_path().read_text())
        
        # Find the node config
        node_config = None
        for node in config.get('nodes', []):
            if node.get('name') == node_name:
                node_config = node
                break
        
        if not node_config:
            return None
            
        is_local = node_config.get('is_local', False)
        ssh_user = node_config.get('ssh_user', 'root')
        
        if is_local:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
        else:
            ssh_target = f"{ssh_user}@{node_config['tailscale_domain']}"
            ssh_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} '{command}'"
            result = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            return None
            
    except Exception:
        return None


def get_env_p2p_ports(node_config):
    """Extract P2P ports from .env file configuration"""
    import re
    
    name = node_config.get('name')
    is_local = node_config.get('is_local', False)
    eth_docker_path = node_config.get('eth_docker_path', '/home/egk/eth-docker')
    p2p_ports = {}
    
    try:
        if is_local:
            env_file = f"{eth_docker_path}/.env"
            with open(env_file, 'r') as f:
                env_content = f.read()
        else:
            ssh_user = node_config.get('ssh_user', 'root')
            tailscale_domain = node_config.get('tailscale_domain')
            result = subprocess.run(f"ssh {ssh_user}@{tailscale_domain} 'cat {eth_docker_path}/.env'", 
                                  shell=True, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                return p2p_ports
            env_content = result.stdout
        
        # Extract P2P related port variables
        p2p_patterns = {
            'EL_P2P_PORT': 'execution',
            'EL_P2P_PORT_2': 'execution', 
            'EL_DISCOVERY_PORT': 'execution',
            'ERIGON_P2P_PORT_3': 'execution',
            'ERIGON_TORRENT_PORT': 'execution',
            'CL_P2P_PORT': 'consensus',
            'PRYSM_PORT': 'consensus',
            'CL_QUIC_PORT': 'consensus',
            'CHARON_P2P_EXTERNAL_HOSTNAME_PORT': 'validator'
        }
        
        for var_name, service_type in p2p_patterns.items():
            pattern = rf'^{var_name}=(\d+)'
            match = re.search(pattern, env_content, re.MULTILINE)
            if match:
                port = int(match.group(1))
                p2p_ports[port] = {
                    'service': service_type,
                    'env_var': var_name,
                    'source': 'env'
                }
                
    except Exception as e:
        pass  # Return empty dict on error
        
    return p2p_ports


def get_compose_p2p_ports(node_config):
    """Extract P2P ports from docker-compose.yml port mappings"""
    import re
    import yaml
    
    name = node_config.get('name')
    is_local = node_config.get('is_local', False)
    eth_docker_path = node_config.get('eth_docker_path', '/home/egk/eth-docker')
    p2p_ports = {}
    
    try:
        # Get COMPOSE_FILE or default files
        compose_files = ['docker-compose.yml']
        
        if is_local:
            env_file = f"{eth_docker_path}/.env"
            try:
                with open(env_file, 'r') as f:
                    for line in f:
                        if line.strip().startswith('COMPOSE_FILE='):
                            compose_file_value = line.strip().split('=', 1)[1]
                            compose_files = [f.strip() for f in compose_file_value.split(':')]
                            break
            except:
                pass
        else:
            ssh_user = node_config.get('ssh_user', 'root')
            tailscale_domain = node_config.get('tailscale_domain')
            result = subprocess.run(f"ssh {ssh_user}@{tailscale_domain} 'cd {eth_docker_path} && grep COMPOSE_FILE .env'", 
                                  shell=True, capture_output=True, text=True, timeout=10)
            if result.returncode == 0 and result.stdout.strip():
                compose_file_value = result.stdout.strip().split('=', 1)[1]
                compose_files = [f.strip() for f in compose_file_value.split(':')]
        
        # Parse each compose file for P2P services
        p2p_services = ['execution', 'consensus', 'validator']
        
        for compose_file in compose_files:
            try:
                if is_local:
                    with open(f"{eth_docker_path}/{compose_file}", 'r') as f:
                        compose_data = yaml.safe_load(f)
                else:
                    result = subprocess.run(f"ssh {ssh_user}@{tailscale_domain} 'cat {eth_docker_path}/{compose_file}'", 
                                          shell=True, capture_output=True, text=True, timeout=10)
                    if result.returncode != 0:
                        continue
                    compose_data = yaml.safe_load(result.stdout)
                
                if not compose_data or 'services' not in compose_data:
                    continue
                
                # Look for P2P services and their ports
                for service_name, service_config in compose_data['services'].items():
                    # Check if this is a P2P service
                    service_type = None
                    for p2p_service in p2p_services:
                        if p2p_service in service_name.lower():
                            service_type = p2p_service
                            break
                    
                    # Special case: Erigon execution service may also run Caplin consensus
                    if service_name.lower() == 'execution' and not service_type:
                        service_type = 'execution'
                        
                        # Check if this is Erigon with Caplin by looking at the image or env
                        image = service_config.get('image', '')
                        if 'erigon' in image.lower():
                            # For Erigon, also check for consensus ports from environment
                            # Add virtual consensus ports that should be exposed
                            env_vars = service_config.get('environment', [])
                            if isinstance(env_vars, list):
                                env_dict = {}
                                for env_var in env_vars:
                                    if '=' in env_var:
                                        key, value = env_var.split('=', 1)
                                        env_dict[key] = value
                            elif isinstance(env_vars, dict):
                                env_dict = env_vars
                            else:
                                env_dict = {}
                            
                            # Add Erigon Caplin consensus ports if they exist in env
                            caplin_ports = {
                                'CL_P2P_PORT': 'consensus',
                                'PRYSM_PORT': 'consensus', 
                                'CL_QUIC_PORT': 'consensus'
                            }
                            
                            for env_var, cons_service in caplin_ports.items():
                                port_value = env_dict.get(env_var)
                                if port_value and port_value.isdigit():
                                    port_num = int(port_value)
                                    if _is_likely_p2p_port(port_num, 'tcp', cons_service):
                                        p2p_ports[port_num] = {
                                            'service': cons_service,
                                            'container_port': port_num,
                                            'protocol': 'tcp',
                                            'source': 'compose_erigon_caplin',
                                            'compose_file': compose_file,
                                            'env_var': env_var
                                        }
                                    if env_var in ['PRYSM_PORT', 'CL_P2P_PORT'] and _is_likely_p2p_port(port_num, 'udp', cons_service):
                                        p2p_ports[port_num] = {
                                            'service': cons_service,
                                            'container_port': port_num,
                                            'protocol': 'udp',
                                            'source': 'compose_erigon_caplin',
                                            'compose_file': compose_file,
                                            'env_var': env_var
                                        }
                    
                    if not service_type:
                        continue
                    
                    # Extract port mappings
                    ports = service_config.get('ports', [])
                    for port_mapping in ports:
                        if isinstance(port_mapping, str):
                            # Parse port mapping like "30307:30307" or "30307:30307/tcp"
                            match = re.match(r'(\d+):(\d+)(?:/(tcp|udp))?', port_mapping)
                            if match:
                                host_port = int(match.group(1))
                                container_port = int(match.group(2))
                                protocol = match.group(3) or 'tcp'
                                
                                # Consider it P2P if it's in common P2P ranges or explicitly configured
                                if (_is_likely_p2p_port(host_port, protocol, service_type)):
                                    p2p_ports[host_port] = {
                                        'service': service_type,
                                        'container_port': container_port,
                                        'protocol': protocol,
                                        'source': 'compose',
                                        'compose_file': compose_file
                                    }
                                    
            except Exception:
                continue
                
    except Exception:
        pass
        
    return p2p_ports


def _is_likely_p2p_port(port, protocol, service_type):
    """Check if a port is likely a P2P port based on common ranges and service type"""
    # Standard P2P ranges
    if 30300 <= port <= 30400:  # Execution P2P
        return service_type == 'execution'
    if 32300 <= port <= 32400:  # Erigon extended P2P
        return service_type == 'execution'  
    if 42000 <= port <= 42100:  # Erigon discovery
        return service_type == 'execution'
    if 9000 <= port <= 9100:   # Consensus P2P
        return service_type == 'consensus'
    if 3600 <= port <= 3700:   # Charon DV
        return service_type == 'validator'
    
    return False

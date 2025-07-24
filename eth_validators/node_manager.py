"""
Handles direct interaction with a node, including SSH commands and API calls
for status, versioning, and synchronization checks.
"""
import subprocess
import requests
import json
import socket
import time

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
    """
    Upgrades Docker-based Ethereum clients (execution, consensus, mev-boost) 
    on a node using eth-docker. This does NOT upgrade the Ubuntu system.
    
    For Ubuntu system updates, use: sudo apt update && sudo apt upgrade -y
    """
    results = {}
    ssh_user = node_config.get('ssh_user', 'root')
    ssh_target = f"{ssh_user}@{node_config['tailscale_domain']}"
    eth_docker_path = node_config.get('eth_docker_path', '/opt/eth-docker')
    
    upgrade_cmd = [
        'ssh', ssh_target,
        f'cd {eth_docker_path} && git checkout main && git pull && '
        'docker compose pull && docker compose build --pull && docker compose up -d'
    ]
    
    try:
        process = subprocess.run(upgrade_cmd, shell=True, capture_output=True, text=True, timeout=300)
        results['upgrade_output'] = process.stdout
        results['upgrade_error'] = process.stderr
        results['upgrade_success'] = process.returncode == 0
    except subprocess.TimeoutExpired:
        results['upgrade_error'] = "Upgrade timeout after 5 minutes"
        results['upgrade_success'] = False
    
    return results

def get_system_update_status(node_config):
    """
    Checks if Ubuntu system updates are available (does not install them).
    Uses 'apt upgrade -s' to simulate and count what would actually be upgraded,
    excluding phased updates that Ubuntu intentionally holds back.
    """
    results = {}
    ssh_user = node_config.get('ssh_user', 'root')
    ssh_target = f"{ssh_user}@{node_config['tailscale_domain']}"
    
    # Use apt upgrade simulation to see what would actually be upgraded
    # Add basic APT lock check - if locked, assume no updates needed for now
    if ssh_user == 'root':
        check_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} 'if fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || fuser /var/lib/apt/lists/lock >/dev/null 2>&1; then echo \"0\"; else apt update >/dev/null 2>&1 && apt upgrade -s 2>/dev/null | grep \"^Inst \" | wc -l; fi'"
    else:
        check_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} 'if sudo fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || sudo fuser /var/lib/apt/lists/lock >/dev/null 2>&1; then echo \"0\"; else sudo apt update >/dev/null 2>&1 && sudo apt upgrade -s 2>/dev/null | grep \"^Inst \" | wc -l; fi'"
    
    try:
        process = subprocess.run(check_cmd, shell=True, capture_output=True, text=True, timeout=25)
        if process.returncode == 0:
            update_count = int(process.stdout.strip())
            results['updates_available'] = update_count
            results['needs_system_update'] = update_count > 0
        else:
            # Better error reporting
            error_msg = process.stderr.strip() if process.stderr.strip() else f"SSH connection failed (return code: {process.returncode})"
            results['updates_available'] = f"Connection Error"
            results['needs_system_update'] = False
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as e:
        if isinstance(e, subprocess.TimeoutExpired):
            results['updates_available'] = "Timeout"
        else:
            results['updates_available'] = "SSH Error"
        results['needs_system_update'] = False
    
    return results

def perform_system_upgrade(node_config):
    """
    Performs Ubuntu system upgrade via SSH: sudo apt update && sudo apt upgrade -y
    This will actually install system updates on the remote node.
    
    Note: Requires either:
    - SSH user is 'root', OR
    - SSH user has passwordless sudo access configured
    """
    results = {}
    ssh_user = node_config.get('ssh_user', 'root')
    ssh_target = f"{ssh_user}@{node_config['tailscale_domain']}"
    
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
    
    # Run the system upgrade command with proper SSH options
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
                                          f"2. Configure passwordless sudo for '{ssh_user}' on the remote node"
            elif 'Permission denied' in results['upgrade_error']:
                results['upgrade_error'] += f"\n\nTip: Check SSH key authentication or user permissions"
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
    Gets actual running container versions and compares with latest GitHub releases.
    Returns information about execution client, consensus client, and whether updates are needed.
    """
    results = {}
    ssh_user = node_config.get('ssh_user', 'root')
    ssh_target = f"{ssh_user}@{node_config['tailscale_domain']}"
    
    try:
        # Get running containers with their images
        containers_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} 'docker ps --format \"{{{{.Names}}}}:{{{{.Image}}}}\" 2>/dev/null || echo \"Error\"'"
        containers_process = subprocess.run(containers_cmd, shell=True, capture_output=True, text=True, timeout=20)
        
        # Initialize results
        execution_current = "Unknown"
        consensus_current = "Unknown"
        execution_client_name = "Unknown"
        consensus_client_name = "Unknown"
        
        # Parse running containers to identify clients and versions
        if containers_process.returncode == 0 and "Error" not in containers_process.stdout:
            container_lines = containers_process.stdout.strip().split('\n')
            
            for line in container_lines:
                if ':' in line:
                    container_name, image = line.split(':', 1)
                    
                    # Identify execution clients
                    if any(exec_client in container_name.lower() for exec_client in 
                           ['execution', 'geth', 'nethermind', 'reth', 'besu', 'erigon']):
                        execution_current = _extract_image_version(f"image: {image}")
                        execution_client_name = _identify_client_from_image(image, 'execution')
                    
                    # Identify consensus clients
                    elif any(cons_client in container_name.lower() for cons_client in 
                             ['consensus', 'lighthouse', 'prysm', 'teku', 'nimbus', 'lodestar', 'grandine']):
                        consensus_current = _extract_image_version(f"image: {image}")
                        consensus_client_name = _identify_client_from_image(image, 'consensus')
        
        # Get latest versions from GitHub releases
        execution_latest = "Unknown"
        consensus_latest = "Unknown"
        
        if execution_client_name != "Unknown":
            execution_latest = _get_latest_github_release(execution_client_name)
        
        if consensus_client_name != "Unknown":
            consensus_latest = _get_latest_github_release(consensus_client_name)
        
        # Store results
        results['execution_current'] = execution_current
        results['execution_latest'] = execution_latest
        results['execution_client'] = execution_client_name
        results['consensus_current'] = consensus_current
        results['consensus_latest'] = consensus_latest
        results['consensus_client'] = consensus_client_name
        
        # Determine if updates are needed
        exec_needs_update = _version_needs_update(execution_current, execution_latest)
        consensus_needs_update = _version_needs_update(consensus_current, consensus_latest)
        
        results['execution_needs_update'] = exec_needs_update
        results['consensus_needs_update'] = consensus_needs_update
        results['needs_client_update'] = exec_needs_update or consensus_needs_update
        
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        results['execution_current'] = "SSH Error"
        results['execution_latest'] = "SSH Error"
        results['execution_client'] = "Unknown"
        results['consensus_current'] = "SSH Error"  
        results['consensus_latest'] = "SSH Error"
        results['consensus_client'] = "Unknown"
        results['execution_needs_update'] = False
        results['consensus_needs_update'] = False
        results['needs_client_update'] = False
    
    return results

def _identify_client_from_image(image, client_type):
    """
    Identifies the Ethereum client from the Docker image name.
    Returns the client name for GitHub API lookup.
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
    
    elif client_type == 'consensus':
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
    """
    # GitHub repositories mapping
    github_repos = {
        'geth': 'ethereum/go-ethereum',
        'nethermind': 'NethermindEth/nethermind',
        'reth': 'paradigmxyz/reth',
        'besu': 'hyperledger/besu',
        'erigon': 'ledgerwatch/erigon',
        'lighthouse': 'sigp/lighthouse',
        'prysm': 'prysmaticlabs/prysm',
        'teku': 'Consensys/teku',
        'nimbus': 'status-im/nimbus-eth2',
        'lodestar': 'ChainSafe/lodestar',
        'grandine': 'grandinetech/grandine'
    }
    
    if client_name not in github_repos:
        return "Unknown"
    
    repo = github_repos[client_name]
    api_url = f"https://api.github.com/repos/{repo}/releases/latest"
    
    try:
        import requests
        response = requests.get(api_url, timeout=10)
        if response.status_code == 200:
            release_data = response.json()
            tag_name = release_data.get('tag_name', '')
            # Clean version tag (remove 'v' prefix if present)
            version = tag_name.lstrip('v')
            return version
        else:
            return "API Error"
    except Exception as e:
        return "Network Error"

def _version_needs_update(current_version, latest_version):
    """
    Compares current and latest versions to determine if an update is needed.
    Handles semantic versioning comparison.
    """
    if current_version in ["Unknown", "Error", "SSH Error", "local", "latest"] or \
       latest_version in ["Unknown", "Error", "API Error", "Network Error"]:
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
    Extracts version from Docker image name.
    Example: "nethermind/nethermind:1.25.4" -> "1.25.4"
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
        return version
    
    return "latest"

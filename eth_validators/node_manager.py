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
    Gets actual running container versions from Docker logs and compares with latest GitHub releases.
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
        execution_container = None
        consensus_container = None
        execution_image = None
        consensus_image = None
        
        # Parse running containers to identify clients and versions
        if containers_process.returncode == 0 and "Error" not in containers_process.stdout:
            container_lines = containers_process.stdout.strip().split('\n')
            
            for line in container_lines:
                if ':' in line:
                    container_name, image = line.split(':', 1)
                    
                    # Identify execution clients
                    if any(exec_client in container_name.lower() for exec_client in 
                           ['execution', 'geth', 'nethermind', 'reth', 'besu', 'erigon']):
                        execution_client_name = _identify_client_from_image(image, 'execution')
                        execution_container = container_name
                        execution_image = image
                    
                    # Identify consensus clients
                    elif any(cons_client in container_name.lower() for cons_client in 
                             ['consensus', 'lighthouse', 'prysm', 'teku', 'nimbus', 'lodestar', 'grandine']):
                        consensus_client_name = _identify_client_from_image(image, 'consensus')
                        consensus_container = container_name
                        consensus_image = image
        
        # Get actual versions from Docker logs, with fallback to image version and exec command
        if execution_container and execution_client_name != "Unknown":
            execution_current = _get_client_version_from_logs(ssh_target, execution_container, execution_client_name)
            # Fallback to image version if logs don't provide version
            if execution_current in ["No Version Found", "Empty Logs", "Log Error"] or execution_current.startswith("Error:") or execution_current.startswith("Debug:"):
                # Try to get version via docker exec command
                exec_version = _get_version_via_docker_exec(ssh_target, execution_container, execution_client_name)
                if exec_version and exec_version not in ["Error", "Unknown"]:
                    execution_current = exec_version
                else:
                    execution_current = _extract_image_version(f"image: {execution_image}")
        
        if consensus_container and consensus_client_name != "Unknown":
            consensus_current = _get_client_version_from_logs(ssh_target, consensus_container, consensus_client_name)
            # Fallback to image version if logs don't provide version  
            if consensus_current in ["No Version Found", "Empty Logs", "Log Error"] or consensus_current.startswith("Error:") or consensus_current.startswith("Debug:"):
                # Try to get version via docker exec command
                exec_version = _get_version_via_docker_exec(ssh_target, consensus_container, consensus_client_name)
                if exec_version and exec_version not in ["Error", "Unknown"]:
                    consensus_current = exec_version
                else:
                    consensus_current = _extract_image_version(f"image: {consensus_image}")
        
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

def _get_version_via_docker_exec(ssh_target, container_name, client_name):
    """
    Tries to get version by executing version commands directly in the container.
    Some clients respond to --version flags.
    """
    import re
    
    # Client-specific version commands
    version_commands = {
        'geth': ['geth', 'version'],
        'nethermind': ['nethermind', '--version'],
        'reth': ['reth', '--version'], 
        'besu': ['besu', '--version'],
        'erigon': ['erigon', '--version'],
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
        # Try to execute version command in container
        cmd_parts = version_commands[client_name]
        exec_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} 'docker exec {container_name} {' '.join(cmd_parts)} 2>&1'"
        
        exec_process = subprocess.run(exec_cmd, shell=True, capture_output=True, text=True, timeout=10)
        
        if exec_process.returncode == 0:
            output = exec_process.stdout.strip()
            
            # Try to extract version from output
            version_patterns = [
                r'v?(\d+\.\d+\.\d+)',
                r'Version:?\s*v?(\d+\.\d+\.\d+)',
                r'version\s*v?(\d+\.\d+\.\d+)'
            ]
            
            for pattern in version_patterns:
                match = re.search(pattern, output, re.IGNORECASE)
                if match:
                    return match.group(1)
        
        return "Exec Error"
        
    except Exception as e:
        return "Error"

def _get_client_version_from_logs(ssh_target, container_name, client_name):
    """
    Extracts the actual client version from Docker container logs.
    Each Ethereum client prints its version during startup.
    """
    import re
    
    try:
        # Get recent logs from container (last 100 lines to catch version info)
        logs_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} 'docker logs --tail 100 {container_name} 2>&1'"
        logs_process = subprocess.run(logs_cmd, shell=True, capture_output=True, text=True, timeout=15)
        
        if logs_process.returncode != 0:
            return "Log Error"
        
        logs = logs_process.stdout.strip()
        if not logs:
            return "Empty Logs"
        
        # Debug mode: save first 500 chars of logs to understand content
        debug_snippet = logs[:500].replace('\n', '\\n')
        
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
                r'Nethermind \((\d+\.\d+\.\d+)\)',
                r'Version: (\d+\.\d+\.\d+)',
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
                r'ledgerwatch/erigon:v(\d+\.\d+\.\d+)'
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
                r'Lodestar/(\d+\.\d+\.\d+)',
                r'lodestar v(\d+\.\d+\.\d+)',
                r'Version: (\d+\.\d+\.\d+)',
                r'Starting Lodestar.*?v(\d+\.\d+\.\d+)',
                r'chainsafe/lodestar:v(\d+\.\d+\.\d+)'
            ],
            'grandine': [
                r'Grandine (\d+\.\d+\.\d+)',
                r'grandine v(\d+\.\d+\.\d+)',
                r'Version: (\d+\.\d+\.\d+)',
                r'Starting Grandine.*?v(\d+\.\d+\.\d+)',
                r'grandinetech/grandine:v(\d+\.\d+\.\d+)'
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

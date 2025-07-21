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

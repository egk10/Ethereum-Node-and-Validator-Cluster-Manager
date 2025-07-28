"""
Handles fetching and calculating validator performance metrics by first checking
the official validator status and then querying performance from multiple client types
(Lighthouse, Teku) with a failover strategy.
"""
import csv
import requests
import yaml
from pathlib import Path
import subprocess
import socket
import time
import json
import random

CONFIG_PATH = Path(__file__).parent / 'config.yaml'
VALIDATORS_PATH = Path(__file__).parent / 'validators_vs_hardware.csv'

# Definir os nós de consulta por tipo de cliente
LIGHTHOUSE_QUERY_NODES = ['minitx', 'minipcamd2']
TEKU_QUERY_NODES = ['minipcamd3']

def _get_free_port():
    """Finds and returns a free local port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

def _get_validator_status(api_url, index):
    """Fetches the official status of a validator from the beacon chain."""
    try:
        status_url = f"{api_url}/eth/v1/beacon/states/head/validators/{index}"
        response = requests.get(status_url, timeout=7)
        if response.status_code == 200:
            return response.json().get('data', {}).get('status', 'Unknown')
        return 'Unknown'
    except requests.RequestException:
        return 'API Error'

def _get_metrics_period_info(api_url, index, total_attestations):
    """Calculates the period covered by the metrics based on validator activation and current epoch."""
    try:
        # Get validator activation info
        validator_url = f"{api_url}/eth/v1/beacon/states/head/validators/{index}"
        response = requests.get(validator_url, timeout=7)
        if response.status_code != 200:
            return "Period Unknown"
        
        validator_data = response.json().get('data', {}).get('validator', {})
        activation_epoch = validator_data.get('activation_epoch')
        
        # Get current epoch
        finality_url = f"{api_url}/eth/v1/beacon/states/head/finality_checkpoints"
        response = requests.get(finality_url, timeout=7)
        if response.status_code != 200:
            return "Period Unknown"
        
        current_epoch = response.json().get('data', {}).get('current_justified', {}).get('epoch')
        
        if activation_epoch and current_epoch:
            epochs_active = int(current_epoch) - int(activation_epoch)
            days_active = (epochs_active * 32 * 12) / (60 * 60 * 24)  # 32 slots per epoch, 12 seconds per slot
            
            # Estimate when metrics collection started
            if total_attestations > 0:
                # If we have fewer attestations than expected, metrics collection might have started later
                if total_attestations < epochs_active * 0.5:  # Less than 50% of expected
                    estimated_days = (total_attestations * 32 * 12) / (60 * 60 * 24)
                    return f"~{estimated_days:.0f} days (node restart/re-sync)"
                else:
                    return f"~{days_active:.0f} days (since activation)"
            else:
                return f"~{days_active:.0f} days (since activation)"
        
        return "Period Unknown"
    except Exception:
        return "Period Unknown"

def _get_lighthouse_performance(api_url, index):
    """Fetches performance data from a Lighthouse node with period information."""
    try:
        perf_url = f"{api_url}/lighthouse/ui/validator_metrics"
        headers = {'Content-Type': 'application/json'}
        payload = {"indices": [int(index)]}
        response = requests.post(perf_url, headers=headers, data=json.dumps(payload), timeout=7)
        if response.status_code == 200:
            data = response.json().get('data', {}).get('validators', {})
            if data and str(index) in data:
                perf = data[str(index)]
                
                # Calculate period information from attestation counts
                hits = perf.get('attestation_hits', 0)
                misses = perf.get('attestation_misses', 0)
                total_attestations = hits + misses
                
                return {
                    'attestation_hit_percentage': perf.get('attestation_hit_percentage'),
                    'attestation_misses': perf.get('attestation_misses'),
                    'inclusion_distance': perf.get('latest_attestation_inclusion_distance'),
                    'total_attestations': total_attestations,
                    'source': 'lighthouse'
                }
        return None
    except requests.RequestException:
        return None

def _get_teku_performance(api_url, index):
    """Fetches and normalizes performance data from a Teku node."""
    try:
        perf_url = f"{api_url}/teku/v1/validators/{index}/performance"
        response = requests.get(perf_url, timeout=7)
        if response.status_code == 200:
            perf = response.json().get('data', {})
            total_attestations = perf.get('attestation_count', 0)
            correct_target = perf.get('correctly_voted_target_count', 0)
            
            hit_percentage = (correct_target / total_attestations) * 100 if total_attestations > 0 else 0
            misses = total_attestations - correct_target
            
            return {
                'attestation_hit_percentage': hit_percentage,
                'attestation_misses': misses,
                'inclusion_distance': perf.get('inclusion_distance_average'),
                'total_attestations': total_attestations,
                'source': 'teku'
            }
        return None
    except requests.RequestException:
        return None

def get_performance_summary():
    """
    Selects one validator per node and queries its status and performance
    across a multi-client failover chain.
    """
    # --- Step 1: Ler configs e selecionar validadores ---
    try:
        with open(CONFIG_PATH, 'r') as f:
            config = yaml.safe_load(f)
        nodes_from_config = config.get('nodes', [])
    except (FileNotFoundError, Exception) as e:
        return [["Error", f"Failed to process config.yaml: {e}", "", "", "", ""]]

    all_query_nodes = LIGHTHOUSE_QUERY_NODES + TEKU_QUERY_NODES
    query_node_configs = {n['name']: n for n in nodes_from_config if n['name'] in all_query_nodes}
    
    try:
        # Use only active validators instead of all validators
        from .validator_sync import get_active_validators_only
        
        all_validators = get_active_validators_only()
        if not all_validators:
            # Fallback to loading all validators if active filter fails
            with open(VALIDATORS_PATH, mode='r', encoding='utf-8') as infile:
                reader = csv.DictReader(infile)
                reader.fieldnames = [name.strip() for name in reader.fieldnames]
                all_validators = list(reader)
        
    except (FileNotFoundError, ImportError, Exception) as e:
        # Fallback to original CSV loading
        try:
            with open(VALIDATORS_PATH, mode='r', encoding='utf-8') as infile:
                reader = csv.DictReader(infile)
                reader.fieldnames = [name.strip() for name in reader.fieldnames]
                all_validators = list(reader)
        except Exception as fallback_e:
            return [["Error", f"Failed to process validators vs hardware.csv: {fallback_e}", "", "", "", ""]]

    validators_by_node = {v.get('tailscale dns', '').strip(): [] for v in all_validators if v.get('tailscale dns')}
    for v in all_validators:
        domain = v.get('tailscale dns', '').strip()
        if domain and v.get('validator index'):
            validators_by_node[domain].append(v)

    selected_validators = {}
    for node_config in nodes_from_config:
        node_name = node_config['name']
        node_domain = node_config.get('tailscale_domain', '').strip()
        if node_domain in validators_by_node and validators_by_node[node_domain]:
            selected = random.choice(validators_by_node[node_domain])
            selected_validators[node_name] = selected.get('validator index')

    # --- Step 2: Buscar dados com failover multi-client ---
    final_results = {}
    ssh_processes = {}
    
    try:
        for node_name, index in selected_validators.items():
            if not index: continue
            
            status = 'Unknown'
            performance = None

            for query_node_name in all_query_nodes:
                if query_node_name not in query_node_configs: continue
                
                if query_node_name not in ssh_processes or ssh_processes[query_node_name]['process'].poll() is not None:
                    cfg = query_node_configs[query_node_name]
                    local_port = _get_free_port()
                    ssh_target = f"{cfg.get('ssh_user', 'root')}@{cfg['tailscale_domain']}"
                    tunnel_cmd = ['ssh', '-o', 'ConnectTimeout=10', '-N', '-L', f'{local_port}:localhost:{cfg["beacon_api_port"]}', ssh_target]
                    
                    print(f"Opening SSH tunnel to {query_node_name}...")
                    proc = subprocess.Popen(tunnel_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    ssh_processes[query_node_name] = {'process': proc, 'port': local_port}
                    time.sleep(3)

                port = ssh_processes[query_node_name]['port']
                api_url = f"http://localhost:{port}"
                
                print(f"Querying validator {index} for node {node_name} via {query_node_name}...")
                
                if status == 'Unknown' or status == 'API Error':
                    current_status = _get_validator_status(api_url, index)
                    if current_status not in ['Unknown', 'API Error']:
                        status = current_status

                if "active" not in status:
                    break

                if query_node_name in LIGHTHOUSE_QUERY_NODES:
                    performance = _get_lighthouse_performance(api_url, index)
                elif query_node_name in TEKU_QUERY_NODES:
                    performance = _get_teku_performance(api_url, index)
                
                if performance is not None:
                    # Add period information to performance data
                    total_attestations = performance.get('total_attestations', 0)
                    period_info = _get_metrics_period_info(api_url, index, total_attestations)
                    performance['period_info'] = period_info
                    break

            final_results[node_name] = {'status': status, 'performance': performance, 'index': index}

    finally:
        for name, ssh_info in ssh_processes.items():
            print(f"Closing SSH tunnel to {name}.")
            ssh_info['process'].terminate()

    # --- Step 3: Construir a tabela final ---
    table_data = []
    all_node_names = {n['name'] for n in nodes_from_config}
    
    for node_name in sorted(list(all_node_names)):
        result = final_results.get(node_name)
        
        if not result:
            table_data.append([node_name, "No validator in CSV", "N/A", "N/A", "N/A", "Check CSV mapping"])
            continue

        index = result['index']
        status = result['status']
        perf = result['performance']
        
        if perf:
            eff = perf.get('attestation_hit_percentage')
            misses = perf.get('attestation_misses')
            dist = perf.get('inclusion_distance')
            total_attestations = perf.get('total_attestations', 0)
            period_info = perf.get('period_info', 'Unknown period')
            source = perf.get('source', 'unknown')
            
            # Format misses with period context
            misses_display = f"{misses}"
            if total_attestations > 0:
                misses_display = f"{misses}/{total_attestations}"
            
            # Create detailed status with period info
            status_with_period = f"{status} | {period_info} ({source})"
            
            table_data.append([node_name, index, f"{eff:.2f}%" if eff is not None else "N/A", 
                             misses_display, dist, status_with_period])
        else:
            # Lógica de status aprimorada
            final_status = status
            if 'active' in status:
                final_status = f"{status} (No Perf Data)"
            table_data.append([node_name, index, "N/A", "N/A", "N/A", final_status])

    def sort_key(row):
        is_numeric = isinstance(row[1], int) or (isinstance(row[1], str) and row[1].isdigit())
        return (0 if is_numeric else 1, row[0])

    table_data.sort(key=sort_key)
    return table_data
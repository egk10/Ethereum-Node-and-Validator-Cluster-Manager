"""
Enhanced Validator Performance Data Extractor
Integrates with beacon nodes, validator APIs, and logs to extract comprehensive performance metrics
"""
import json
import re
import requests
import subprocess
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from pathlib import Path
import yaml
import logging

logger = logging.getLogger(__name__)

def get_config_path():
    """Find config.yaml in current directory first, then in eth_validators directory"""
    # First check current working directory (where user runs the command)
    current_dir_config = Path.cwd() / 'config.yaml'
    if current_dir_config.exists():
        return current_dir_config
    
    # Fallback to the default location (for backward compatibility)
    default_config = Path(__file__).parent / 'config.yaml'
    return default_config

class ValidatorPerformanceExtractor:
    """Enhanced extractor for comprehensive validator performance data"""
    
    def __init__(self):
        self.config_path = get_config_path()
        self.load_config()
        
    def load_config(self):
        """Load node configuration"""
        try:
            with open(self.config_path, 'r') as f:
                self.config = yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            self.config = {'nodes': []}
    
    def extract_beacon_node_performance(self, node_config: Dict[str, Any], validator_indices: List[int]) -> Dict[str, Any]:
        """Extract performance data from beacon node APIs"""
        try:
            ssh_target = f"{node_config.get('ssh_user', 'root')}@{node_config['tailscale_domain']}"
            beacon_port = node_config.get('beacon_api_port', 5052)
            
            # Set up SSH tunnel
            local_port = self._get_free_port()
            tunnel_cmd = ['ssh', '-o', 'ConnectTimeout=10', '-N', '-L', 
                         f'{local_port}:localhost:{beacon_port}', ssh_target]
            
            tunnel_process = subprocess.Popen(tunnel_cmd, stdout=subprocess.PIPE, 
                                            stderr=subprocess.PIPE)
            time.sleep(3)  # Wait for tunnel
            
            try:
                api_url = f"http://localhost:{local_port}"
                performance_data = {}
                
                # Extract comprehensive performance metrics
                performance_data['beacon_node_info'] = self._get_beacon_node_info(api_url)
                performance_data['sync_status'] = self._get_sync_status(api_url)
                performance_data['peer_info'] = self._get_peer_info(api_url)
                performance_data['validator_performance'] = self._get_validator_performance_metrics(
                    api_url, validator_indices)
                performance_data['chain_info'] = self._get_chain_info(api_url)
                
                return performance_data
                
            finally:
                tunnel_process.terminate()
                
        except Exception as e:
            logger.error(f"Failed to extract beacon performance: {e}")
            return {'error': str(e)}
    
    def _get_beacon_node_info(self, api_url: str) -> Dict[str, Any]:
        """Get beacon node information and health"""
        try:
            # Node version and identity
            version_resp = requests.get(f"{api_url}/eth/v1/node/version", timeout=10)
            identity_resp = requests.get(f"{api_url}/eth/v1/node/identity", timeout=10)
            health_resp = requests.get(f"{api_url}/eth/v1/node/health", timeout=10)
            
            return {
                'version': version_resp.json().get('data', {}) if version_resp.status_code == 200 else None,
                'identity': identity_resp.json().get('data', {}) if identity_resp.status_code == 200 else None,
                'health_status_code': health_resp.status_code,
                'is_healthy': health_resp.status_code == 200
            }
        except Exception as e:
            return {'error': str(e)}
    
    def _get_sync_status(self, api_url: str) -> Dict[str, Any]:
        """Get detailed sync status information"""
        try:
            sync_resp = requests.get(f"{api_url}/eth/v1/node/syncing", timeout=10)
            
            if sync_resp.status_code == 200:
                sync_data = sync_resp.json().get('data', {})
                
                # Calculate sync percentage if syncing
                if sync_data.get('is_syncing'):
                    head_slot = int(sync_data.get('head_slot', 0))
                    sync_distance = int(sync_data.get('sync_distance', 0))
                    if sync_distance > 0:
                        sync_percentage = (head_slot / (head_slot + sync_distance)) * 100
                        sync_data['sync_percentage'] = sync_percentage
                
                return sync_data
            
            return {'error': f'Sync status request failed: {sync_resp.status_code}'}
            
        except Exception as e:
            return {'error': str(e)}
    
    def _get_peer_info(self, api_url: str) -> Dict[str, Any]:
        """Get peer connectivity information"""
        try:
            peers_resp = requests.get(f"{api_url}/eth/v1/node/peers", timeout=10)
            
            if peers_resp.status_code == 200:
                peers_data = peers_resp.json().get('data', [])
                
                # Analyze peer distribution
                peer_states = {}
                peer_directions = {}
                
                for peer in peers_data:
                    state = peer.get('state', 'unknown')
                    direction = peer.get('direction', 'unknown')
                    
                    peer_states[state] = peer_states.get(state, 0) + 1
                    peer_directions[direction] = peer_directions.get(direction, 0) + 1
                
                return {
                    'total_peers': len(peers_data),
                    'peer_states': peer_states,
                    'peer_directions': peer_directions,
                    'connected_peers': peer_states.get('connected', 0),
                    'disconnected_peers': peer_states.get('disconnected', 0)
                }
            
            return {'error': f'Peers request failed: {peers_resp.status_code}'}
            
        except Exception as e:
            return {'error': str(e)}
    
    def _get_validator_performance_metrics(self, api_url: str, validator_indices: List[int]) -> Dict[str, Any]:
        """Get comprehensive validator performance metrics"""
        try:
            validator_metrics = {}
            
            for index in validator_indices:
                try:
                    # Get validator status and details
                    validator_resp = requests.get(
                        f"{api_url}/eth/v1/beacon/states/head/validators/{index}", 
                        timeout=10
                    )
                    
                    if validator_resp.status_code == 200:
                        validator_data = validator_resp.json().get('data', {})
                        
                        # Extract validator information
                        validator_info = {
                            'index': index,
                            'status': validator_data.get('status'),
                            'balance': validator_data.get('balance'),
                            'validator': validator_data.get('validator', {}),
                            'performance_metrics': {}
                        }
                        
                        # Try to get client-specific performance metrics
                        performance = self._get_client_specific_performance(api_url, index)
                        if performance:
                            validator_info['performance_metrics'] = performance
                        
                        # Get recent attestations
                        attestations = self._get_recent_attestations(api_url, index)
                        if attestations:
                            validator_info['recent_attestations'] = attestations
                        
                        validator_metrics[str(index)] = validator_info
                        
                except Exception as e:
                    logger.warning(f"Failed to get metrics for validator {index}: {e}")
                    validator_metrics[str(index)] = {'error': str(e)}
            
            return validator_metrics
            
        except Exception as e:
            return {'error': str(e)}
    
    def _get_client_specific_performance(self, api_url: str, index: int) -> Optional[Dict[str, Any]]:
        """Get client-specific performance metrics (Lighthouse, Teku, etc.)"""
        # Try Lighthouse API
        try:
            lighthouse_resp = requests.post(
                f"{api_url}/lighthouse/ui/validator_metrics",
                headers={'Content-Type': 'application/json'},
                json={"indices": [index]},
                timeout=10
            )
            
            if lighthouse_resp.status_code == 200:
                lighthouse_data = lighthouse_resp.json().get('data', {}).get('validators', {})
                if str(index) in lighthouse_data:
                    metrics = lighthouse_data[str(index)]
                    return {
                        'client': 'lighthouse',
                        'attestation_hit_percentage': metrics.get('attestation_hit_percentage'),
                        'attestation_hits': metrics.get('attestation_hits'),
                        'attestation_misses': metrics.get('attestation_misses'),
                        'latest_attestation_inclusion_distance': metrics.get('latest_attestation_inclusion_distance'),
                        'average_attestation_inclusion_distance': metrics.get('average_attestation_inclusion_distance')
                    }
        except:
            pass
        
        # Try Teku API
        try:
            teku_resp = requests.get(f"{api_url}/teku/v1/validators/{index}/performance", timeout=10)
            if teku_resp.status_code == 200:
                teku_data = teku_resp.json().get('data', {})
                return {
                    'client': 'teku',
                    'attestation_count': teku_data.get('attestation_count'),
                    'correctly_voted_target_count': teku_data.get('correctly_voted_target_count'),
                    'correctly_voted_source_count': teku_data.get('correctly_voted_source_count'),
                    'correctly_voted_head_count': teku_data.get('correctly_voted_head_count'),
                    'inclusion_distance_average': teku_data.get('inclusion_distance_average'),
                    'block_proposal_count': teku_data.get('block_proposal_count')
                }
        except:
            pass
        
        return None
    
    def _get_recent_attestations(self, api_url: str, index: int, epochs: int = 5) -> Optional[List[Dict[str, Any]]]:
        """Get recent attestation history for validator"""
        try:
            # Get current epoch
            finality_resp = requests.get(f"{api_url}/eth/v1/beacon/states/head/finality_checkpoints", timeout=10)
            if finality_resp.status_code != 200:
                return None
            
            current_epoch = int(finality_resp.json().get('data', {}).get('current_justified', {}).get('epoch', 0))
            
            attestations = []
            for epoch in range(max(0, current_epoch - epochs), current_epoch + 1):
                try:
                    # Get attestations for this epoch
                    attestation_resp = requests.get(
                        f"{api_url}/eth/v1/beacon/states/{epoch}/validator_balances?id={index}",
                        timeout=10
                    )
                    
                    if attestation_resp.status_code == 200:
                        balance_data = attestation_resp.json().get('data', [])
                        if balance_data:
                            attestations.append({
                                'epoch': epoch,
                                'balance': balance_data[0].get('balance'),
                                'effective_balance': balance_data[0].get('effective_balance', 0)
                            })
                            
                except Exception:
                    continue
            
            return attestations if attestations else None
            
        except Exception:
            return None
    
    def _get_chain_info(self, api_url: str) -> Dict[str, Any]:
        """Get blockchain state information"""
        try:
            # Get genesis info
            genesis_resp = requests.get(f"{api_url}/eth/v1/beacon/genesis", timeout=10)
            
            # Get current finality checkpoints
            finality_resp = requests.get(f"{api_url}/eth/v1/beacon/states/head/finality_checkpoints", timeout=10)
            
            # Get current head
            head_resp = requests.get(f"{api_url}/eth/v1/beacon/headers/head", timeout=10)
            
            chain_info = {}
            
            if genesis_resp.status_code == 200:
                genesis_data = genesis_resp.json().get('data', {})
                chain_info['genesis_time'] = genesis_data.get('genesis_time')
                chain_info['genesis_validators_root'] = genesis_data.get('genesis_validators_root')
            
            if finality_resp.status_code == 200:
                finality_data = finality_resp.json().get('data', {})
                chain_info['finality'] = finality_data
            
            if head_resp.status_code == 200:
                head_data = head_resp.json().get('data', {})
                chain_info['head'] = head_data
            
            return chain_info
            
        except Exception as e:
            return {'error': str(e)}
    
    def extract_log_performance_metrics(self, node_config: Dict[str, Any], hours: int = 24) -> Dict[str, Any]:
        """Extract performance metrics from container logs"""
        try:
            ssh_target = f"{node_config.get('ssh_user', 'root')}@{node_config['tailscale_domain']}"
            
            # Get Ethereum containers
            containers = self._get_ethereum_containers(ssh_target)
            
            log_metrics = {}
            
            for container in containers:
                container_metrics = self._extract_container_performance_logs(
                    ssh_target, container, hours
                )
                log_metrics[container] = container_metrics
            
            return log_metrics
            
        except Exception as e:
            return {'error': str(e)}
    
    def _extract_container_performance_logs(self, ssh_target: str, container: str, hours: int) -> Dict[str, Any]:
        """Extract performance metrics from specific container logs"""
        try:
            since_time = datetime.now() - timedelta(hours=hours)
            since_str = since_time.strftime('%Y-%m-%dT%H:%M:%S')
            
            cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} 'docker logs {container} --since {since_str} 2>&1'"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                return {'error': f'Failed to get logs for {container}'}
            
            log_lines = result.stdout.split('\n')
            
            # Extract performance indicators
            performance_metrics = {
                'total_log_lines': len(log_lines),
                'attestation_performance': self._extract_attestation_metrics(log_lines),
                'block_performance': self._extract_block_metrics(log_lines),
                'sync_performance': self._extract_sync_metrics(log_lines),
                'network_performance': self._extract_network_metrics(log_lines),
                'resource_performance': self._extract_resource_metrics(log_lines),
                'error_analysis': self._extract_error_metrics(log_lines),
                'timestamp_range': self._extract_time_range(log_lines)
            }
            
            return performance_metrics
            
        except Exception as e:
            return {'error': str(e)}
    
    def _extract_attestation_metrics(self, log_lines: List[str]) -> Dict[str, Any]:
        """Extract attestation-related performance metrics from logs"""
        attestation_metrics = {
            'successful_attestations': 0,
            'failed_attestations': 0,
            'late_attestations': 0,
            'inclusion_distances': [],
            'attestation_timing': []
        }
        
        for line in log_lines:
            lower_line = line.lower()
            
            # Count successful attestations
            if any(phrase in lower_line for phrase in ['successfully published attestation', 'attestation sent', 'published attestation']):
                attestation_metrics['successful_attestations'] += 1
                
                # Extract inclusion distance if present
                distance_match = re.search(r'inclusion.*distance.*?(\d+)', line, re.IGNORECASE)
                if distance_match:
                    attestation_metrics['inclusion_distances'].append(int(distance_match.group(1)))
            
            # Count failed attestations
            elif any(phrase in lower_line for phrase in ['failed to publish attestation', 'attestation.*failed', 'could not submit attestation']):
                attestation_metrics['failed_attestations'] += 1
            
            # Detect late attestations
            elif any(phrase in lower_line for phrase in ['late attestation', 'attestation.*late', 'missed.*attestation']):
                attestation_metrics['late_attestations'] += 1
        
        # Calculate averages
        if attestation_metrics['inclusion_distances']:
            attestation_metrics['average_inclusion_distance'] = sum(attestation_metrics['inclusion_distances']) / len(attestation_metrics['inclusion_distances'])
        
        # Calculate success rate
        total_attestations = attestation_metrics['successful_attestations'] + attestation_metrics['failed_attestations']
        if total_attestations > 0:
            attestation_metrics['success_rate'] = (attestation_metrics['successful_attestations'] / total_attestations) * 100
        
        return attestation_metrics
    
    def _extract_block_metrics(self, log_lines: List[str]) -> Dict[str, Any]:
        """Extract block proposal performance metrics"""
        block_metrics = {
            'successful_blocks': 0,
            'failed_blocks': 0,
            'block_timing': [],
            'block_rewards': []
        }
        
        for line in log_lines:
            lower_line = line.lower()
            
            if any(phrase in lower_line for phrase in ['successfully published block', 'block.*published', 'produced block']):
                block_metrics['successful_blocks'] += 1
                
                # Extract block reward if present
                reward_match = re.search(r'reward.*?(\d+\.?\d*)', line, re.IGNORECASE)
                if reward_match:
                    block_metrics['block_rewards'].append(float(reward_match.group(1)))
            
            elif any(phrase in lower_line for phrase in ['failed to publish block', 'block.*failed', 'could not produce block']):
                block_metrics['failed_blocks'] += 1
        
        # Calculate averages
        if block_metrics['block_rewards']:
            block_metrics['average_block_reward'] = sum(block_metrics['block_rewards']) / len(block_metrics['block_rewards'])
        
        return block_metrics
    
    def _extract_sync_metrics(self, log_lines: List[str]) -> Dict[str, Any]:
        """Extract sync performance metrics"""
        sync_metrics = {
            'sync_events': 0,
            'sync_behind_count': 0,
            'sync_progress_indicators': [],
            'peer_count_changes': []
        }
        
        for line in log_lines:
            lower_line = line.lower()
            
            if any(phrase in lower_line for phrase in ['syncing', 'sync.*progress', 'catching up']):
                sync_metrics['sync_events'] += 1
                
                # Extract sync progress percentage
                progress_match = re.search(r'(\d+\.?\d*)%', line)
                if progress_match:
                    sync_metrics['sync_progress_indicators'].append(float(progress_match.group(1)))
            
            elif any(phrase in lower_line for phrase in ['behind.*head', 'sync.*lag', 'not synced']):
                sync_metrics['sync_behind_count'] += 1
            
            # Extract peer count information
            peer_match = re.search(r'peers?.*?(\d+)', line, re.IGNORECASE)
            if peer_match:
                sync_metrics['peer_count_changes'].append(int(peer_match.group(1)))
        
        return sync_metrics
    
    def _extract_network_metrics(self, log_lines: List[str]) -> Dict[str, Any]:
        """Extract network performance metrics"""
        network_metrics = {
            'connection_errors': 0,
            'timeout_errors': 0,
            'dns_errors': 0,
            'peer_connection_events': 0,
            'bandwidth_indicators': []
        }
        
        for line in log_lines:
            lower_line = line.lower()
            
            if any(phrase in lower_line for phrase in ['connection.*error', 'connection.*failed', 'unable to connect']):
                network_metrics['connection_errors'] += 1
            
            elif any(phrase in lower_line for phrase in ['timeout', 'request.*timeout', 'connection.*timeout']):
                network_metrics['timeout_errors'] += 1
            
            elif any(phrase in lower_line for phrase in ['dns.*failed', 'dns.*error', 'name resolution']):
                network_metrics['dns_errors'] += 1
            
            elif any(phrase in lower_line for phrase in ['peer.*connected', 'peer.*disconnected', 'new.*peer']):
                network_metrics['peer_connection_events'] += 1
        
        return network_metrics
    
    def _extract_resource_metrics(self, log_lines: List[str]) -> Dict[str, Any]:
        """Extract resource usage metrics"""
        resource_metrics = {
            'memory_warnings': 0,
            'disk_warnings': 0,
            'cpu_warnings': 0,
            'memory_usage_indicators': [],
            'disk_usage_indicators': []
        }
        
        for line in log_lines:
            lower_line = line.lower()
            
            if any(phrase in lower_line for phrase in ['memory.*limit', 'out of memory', 'memory.*error']):
                resource_metrics['memory_warnings'] += 1
            
            elif any(phrase in lower_line for phrase in ['disk.*full', 'no space left', 'disk.*error']):
                resource_metrics['disk_warnings'] += 1
            
            elif any(phrase in lower_line for phrase in ['cpu.*high', 'high.*load', 'cpu.*limit']):
                resource_metrics['cpu_warnings'] += 1
            
            # Extract memory usage percentages
            memory_match = re.search(r'memory.*?(\d+\.?\d*)%', line, re.IGNORECASE)
            if memory_match:
                resource_metrics['memory_usage_indicators'].append(float(memory_match.group(1)))
            
            # Extract disk usage percentages
            disk_match = re.search(r'disk.*?(\d+\.?\d*)%', line, re.IGNORECASE)
            if disk_match:
                resource_metrics['disk_usage_indicators'].append(float(disk_match.group(1)))
        
        return resource_metrics
    
    def _extract_error_metrics(self, log_lines: List[str]) -> Dict[str, Any]:
        """Extract error and warning metrics"""
        error_metrics = {
            'total_errors': 0,
            'total_warnings': 0,
            'critical_errors': 0,
            'error_categories': {},
            'recent_errors': []
        }
        
        for line in log_lines:
            lower_line = line.lower()
            
            if any(phrase in lower_line for phrase in ['error', 'err:', 'exception', 'failed']):
                error_metrics['total_errors'] += 1
                
                # Categorize errors
                if 'attestation' in lower_line:
                    error_metrics['error_categories']['attestation'] = error_metrics['error_categories'].get('attestation', 0) + 1
                elif 'block' in lower_line:
                    error_metrics['error_categories']['block'] = error_metrics['error_categories'].get('block', 0) + 1
                elif 'network' in lower_line:
                    error_metrics['error_categories']['network'] = error_metrics['error_categories'].get('network', 0) + 1
                elif 'sync' in lower_line:
                    error_metrics['error_categories']['sync'] = error_metrics['error_categories'].get('sync', 0) + 1
                else:
                    error_metrics['error_categories']['other'] = error_metrics['error_categories'].get('other', 0) + 1
                
                # Critical errors
                if any(phrase in lower_line for phrase in ['critical', 'fatal', 'panic', 'crashed']):
                    error_metrics['critical_errors'] += 1
                
                # Store recent errors (last 10)
                if len(error_metrics['recent_errors']) < 10:
                    error_metrics['recent_errors'].append(line.strip()[:200])
            
            elif any(phrase in lower_line for phrase in ['warning', 'warn:', 'warn ', 'caution']):
                error_metrics['total_warnings'] += 1
        
        return error_metrics
    
    def _extract_time_range(self, log_lines: List[str]) -> Dict[str, Any]:
        """Extract timestamp range from logs"""
        timestamps = []
        
        for line in log_lines[:50]:  # Check first 50 lines
            timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2}[\s T]\d{2}:\d{2}:\d{2})', line)
            if timestamp_match:
                try:
                    timestamps.append(datetime.fromisoformat(timestamp_match.group(1).replace(' ', 'T')))
                except:
                    pass
        
        for line in log_lines[-50:]:  # Check last 50 lines
            timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2}[\s T]\d{2}:\d{2}:\d{2})', line)
            if timestamp_match:
                try:
                    timestamps.append(datetime.fromisoformat(timestamp_match.group(1).replace(' ', 'T')))
                except:
                    pass
        
        if timestamps:
            return {
                'earliest_log': min(timestamps).isoformat(),
                'latest_log': max(timestamps).isoformat(),
                'log_span_hours': (max(timestamps) - min(timestamps)).total_seconds() / 3600
            }
        
        return {'error': 'No timestamps found in logs'}
    
    def _get_ethereum_containers(self, ssh_target: str) -> List[str]:
        """Get list of Ethereum-related containers"""
        try:
            cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} 'docker ps --format \"{{{{.Names}}}}\" | grep -E \"(consensus|execution|validator|beacon|nimbus|lighthouse|teku|prysm|lodestar|geth|nethermind|besu|reth|erigon|charon|mev)\"'"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
            
            if result.returncode == 0:
                return [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]
            return []
            
        except Exception:
            return []
    
    def _get_free_port(self) -> int:
        """Get a free local port for SSH tunneling"""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            return s.getsockname()[1]
    
    def extract_comprehensive_performance(self, node_name: str, validator_indices: List[int] = None, hours: int = 24) -> Dict[str, Any]:
        """Extract comprehensive performance data from all sources"""
        try:
            # Find node configuration
            node_config = None
            for node in self.config.get('nodes', []):
                if node.get('name') == node_name:
                    node_config = node
                    break
            
            if not node_config:
                return {'error': f'Node {node_name} not found in configuration'}
            
            # If no validator indices provided, try to get them from CSV
            if not validator_indices:
                validator_indices = self._get_validator_indices_for_node(node_name)
            
            performance_data = {
                'node_name': node_name,
                'extraction_timestamp': datetime.now().isoformat(),
                'validator_indices': validator_indices,
                'beacon_node_performance': {},
                'log_performance': {},
                'summary': {}
            }
            
            # Extract beacon node performance
            if validator_indices:
                logger.info(f"Extracting beacon performance for {node_name}...")
                performance_data['beacon_node_performance'] = self.extract_beacon_node_performance(
                    node_config, validator_indices
                )
            
            # Extract log performance
            logger.info(f"Extracting log performance for {node_name}...")
            performance_data['log_performance'] = self.extract_log_performance_metrics(
                node_config, hours
            )
            
            # Generate summary
            performance_data['summary'] = self._generate_performance_summary(performance_data)
            
            return performance_data
            
        except Exception as e:
            return {'error': str(e)}
    
    def _get_validator_indices_for_node(self, node_name: str) -> List[int]:
        """Get validator indices for a node from CSV file"""
        try:
            validators_path = Path(__file__).parent / 'validators_vs_hardware.csv'
            
            if not validators_path.exists():
                return []
            
            import csv
            validator_indices = []
            
            with open(validators_path, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('tailscale dns', '').strip() == self._get_node_domain(node_name):
                        index = row.get('validator index', '').strip()
                        if index and index.isdigit():
                            validator_indices.append(int(index))
            
            return validator_indices
            
        except Exception:
            return []
    
    def _get_node_domain(self, node_name: str) -> str:
        """Get tailscale domain for a node"""
        for node in self.config.get('nodes', []):
            if node.get('name') == node_name:
                return node.get('tailscale_domain', '')
        return ''
    
    def _generate_performance_summary(self, performance_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a comprehensive performance summary"""
        summary = {
            'overall_health_score': 0,
            'key_metrics': {},
            'alerts': [],
            'recommendations': []
        }
        
        # Analyze beacon node performance
        beacon_data = performance_data.get('beacon_node_performance', {})
        if beacon_data and 'error' not in beacon_data:
            beacon_health = self._calculate_beacon_health_score(beacon_data)
            summary['key_metrics']['beacon_health'] = beacon_health
        
        # Analyze log performance
        log_data = performance_data.get('log_performance', {})
        if log_data and 'error' not in log_data:
            log_health = self._calculate_log_health_score(log_data)
            summary['key_metrics']['log_health'] = log_health
        
        # Calculate overall health score
        health_scores = [score for score in summary['key_metrics'].values() if isinstance(score, (int, float))]
        if health_scores:
            summary['overall_health_score'] = sum(health_scores) / len(health_scores)
        
        # Generate alerts and recommendations
        summary['alerts'] = self._generate_performance_alerts(performance_data)
        summary['recommendations'] = self._generate_performance_recommendations(performance_data)
        
        return summary
    
    def _calculate_beacon_health_score(self, beacon_data: Dict[str, Any]) -> float:
        """Calculate health score from beacon node data"""
        score = 100.0
        
        # Check node health
        if not beacon_data.get('beacon_node_info', {}).get('is_healthy', False):
            score -= 30
        
        # Check sync status
        sync_status = beacon_data.get('sync_status', {})
        if sync_status.get('is_syncing', False):
            sync_percentage = sync_status.get('sync_percentage', 0)
            score -= (100 - sync_percentage) * 0.5
        
        # Check peer connectivity
        peer_info = beacon_data.get('peer_info', {})
        connected_peers = peer_info.get('connected_peers', 0)
        if connected_peers < 8:  # Minimum recommended peers
            score -= (8 - connected_peers) * 5
        
        return max(0, score)
    
    def _calculate_log_health_score(self, log_data: Dict[str, Any]) -> float:
        """Calculate health score from log analysis"""
        scores = []
        
        for container, metrics in log_data.items():
            if 'error' in metrics:
                continue
            
            container_score = 100.0
            
            # Attestation performance
            attestation_metrics = metrics.get('attestation_performance', {})
            success_rate = attestation_metrics.get('success_rate', 100)
            container_score = min(container_score, success_rate)
            
            # Error analysis
            error_metrics = metrics.get('error_analysis', {})
            total_errors = error_metrics.get('total_errors', 0)
            if total_errors > 0:
                # Penalize based on error rate
                total_lines = metrics.get('total_log_lines', 1)
                error_rate = (total_errors / total_lines) * 100
                container_score -= error_rate * 10
            
            scores.append(max(0, container_score))
        
        return sum(scores) / len(scores) if scores else 0
    
    def _generate_performance_alerts(self, performance_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate performance alerts based on extracted data"""
        alerts = []
        
        # Check beacon node alerts
        beacon_data = performance_data.get('beacon_node_performance', {})
        if beacon_data.get('sync_status', {}).get('is_syncing', False):
            alerts.append({
                'severity': 'warning',
                'category': 'sync',
                'message': 'Node is currently syncing'
            })
        
        # Check log-based alerts
        log_data = performance_data.get('log_performance', {})
        for container, metrics in log_data.items():
            error_metrics = metrics.get('error_analysis', {})
            
            if error_metrics.get('critical_errors', 0) > 0:
                alerts.append({
                    'severity': 'critical',
                    'category': 'errors',
                    'message': f'{container}: {error_metrics["critical_errors"]} critical errors detected'
                })
            
            attestation_metrics = metrics.get('attestation_performance', {})
            success_rate = attestation_metrics.get('success_rate', 100)
            if success_rate < 95:
                alerts.append({
                    'severity': 'warning',
                    'category': 'performance',
                    'message': f'{container}: Low attestation success rate ({success_rate:.1f}%)'
                })
        
        return alerts
    
    def _generate_performance_recommendations(self, performance_data: Dict[str, Any]) -> List[str]:
        """Generate performance improvement recommendations"""
        recommendations = []
        
        beacon_data = performance_data.get('beacon_node_performance', {})
        peer_info = beacon_data.get('peer_info', {})
        
        # Peer recommendations
        connected_peers = peer_info.get('connected_peers', 0)
        if connected_peers < 8:
            recommendations.append(f"Increase peer connections (currently {connected_peers}, recommended: 8+)")
        
        # Sync recommendations
        if beacon_data.get('sync_status', {}).get('is_syncing', False):
            recommendations.append("Monitor sync progress and ensure adequate resources during sync")
        
        # Log-based recommendations
        log_data = performance_data.get('log_performance', {})
        for container, metrics in log_data.items():
            error_metrics = metrics.get('error_analysis', {})
            
            if error_metrics.get('total_errors', 0) > 10:
                recommendations.append(f"Investigate recurring errors in {container}")
            
            resource_metrics = metrics.get('resource_performance', {})
            if resource_metrics.get('memory_warnings', 0) > 0:
                recommendations.append(f"Consider increasing memory allocation for {container}")
        
        return recommendations

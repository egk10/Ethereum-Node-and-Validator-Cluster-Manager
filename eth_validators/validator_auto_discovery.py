"""
Validator Auto-Discovery Module

This module automatically discovers validators running on nodes by:
1. Querying beacon chain APIs to get validator information
2. Mapping validators to nodes based on running containers
3. Generating a simplified CSV with essential validator data
4. Eliminating the need for manual validator CSV setup
"""

import logging
import csv
import requests
import json
import subprocess
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path

from .config import get_all_node_configs

logger = logging.getLogger(__name__)

def _run_command(node_cfg, command):
    """Run a command on a node, handling both local and remote execution"""
    is_local = node_cfg.get('is_local', False)
    
    if is_local:
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=15)
            return result
        except Exception as e:
            # Return a mock result object for consistency
            class MockResult:
                def __init__(self, returncode=1, stdout="", stderr=str(e)):
                    self.returncode = returncode
                    self.stdout = stdout
                    self.stderr = stderr
            return MockResult()
    else:
        ssh_target = f"{node_cfg.get('ssh_user', 'root')}@{node_cfg['tailscale_domain']}"
        ssh_command = f"ssh -o ConnectTimeout=10 -o BatchMode=yes {ssh_target} \"{command}\""
        try:
            result = subprocess.run(ssh_command, shell=True, capture_output=True, text=True, timeout=15)
            return result
        except Exception as e:
            # Return a mock result object for consistency
            class MockResult:
                def __init__(self, returncode=1, stdout="", stderr=str(e)):
                    self.returncode = returncode
                    self.stdout = stdout
                    self.stderr = stderr
            return MockResult()

class ValidatorAutoDiscovery:
    """Automatically discovers validators and their node assignments"""
    
    def __init__(self, config_file_path: str):
        self.config_file_path = config_file_path
        self.discovered_validators = []
        
    def discover_all_validators(self) -> List[Dict]:
        """
        Discover all validators across all nodes
        
        Returns:
            List of validator dictionaries with essential information
        """
        logger.info("Starting validator auto-discovery across cluster")
        
        all_validators = []
        node_configs = get_all_node_configs()
        
        for node_config in node_configs:
            node_name = node_config.get('name')
            
            # Skip disabled nodes
            if self._is_node_disabled(node_config):
                logger.info(f"Skipping disabled node: {node_name}")
                continue
                
            try:
                # Discover validators on this node
                node_validators = self._discover_node_validators(node_config)
                all_validators.extend(node_validators)
                
                logger.info(f"Found {len(node_validators)} validators on {node_name}")
                
            except Exception as e:
                logger.error(f"Failed to discover validators on {node_name}: {e}")
                continue
        
        logger.info(f"Total validators discovered: {len(all_validators)}")
        return all_validators
    
    def _discover_node_validators(self, node_config: Dict) -> List[Dict]:
        """Discover validators running on a specific node"""
        node_name = node_config.get('name')
        validators = []
        
        # Get beacon API endpoint
        beacon_api_url = self._get_beacon_api_url(node_config)
        if not beacon_api_url:
            logger.warning(f"No beacon API available for {node_name}")
            return []
        
        try:
            # Get validator keys from running containers
            validator_keys = self._extract_validator_keys_from_node(node_config)
            
            if not validator_keys:
                logger.warning(f"No validator keys found on {node_name}")
                return []
            
            # Query beacon chain for validator information
            validator_info = self._query_validators_from_beacon(beacon_api_url, validator_keys)
            
            # Detect protocol/stack
            protocol = self._detect_protocol(node_config)
            
            # Build validator records
            for pubkey, info in validator_info.items():
                validators.append({
                    'validator_index': info.get('index', 'unknown'),
                    'public_key': pubkey,
                    'node_name': node_name,
                    'protocol': protocol,
                    'status': info.get('status', 'unknown'),
                    'balance': info.get('balance', 0),
                    'last_updated': datetime.now().isoformat()
                })
        
        except Exception as e:
            logger.error(f"Error discovering validators on {node_name}: {e}")
        
        return validators
    
    def _get_beacon_api_url(self, node_config: Dict) -> Optional[str]:
        """Get beacon chain API URL for a node"""
        beacon_port = node_config.get('beacon_api_port', 5052)
        
        if not beacon_port:
            return None
            
        if node_config.get('is_local'):
            return f"http://localhost:{beacon_port}"
        else:
            # For remote nodes, we'd need SSH tunneling (implement if needed)
            return f"http://localhost:{beacon_port}"
    
    def _extract_validator_keys_from_node(self, node_config: Dict) -> List[str]:
        """Extract validator public keys from running containers"""
        node_name = node_config.get('name')
        validator_keys = []
        
        try:
            # Method 1: Check validator client containers for keystore files
            keys_from_keystores = self._get_keys_from_keystores(node_config)
            validator_keys.extend(keys_from_keystores)
            
            # Method 2: Query validator client API if available
            keys_from_api = self._get_keys_from_validator_api(node_config)
            validator_keys.extend(keys_from_api)
            
            # Method 3: Parse from validator logs (last resort)
            if not validator_keys:
                keys_from_logs = self._get_keys_from_logs(node_config)
                validator_keys.extend(keys_from_logs)
            
        except Exception as e:
            logger.error(f"Failed to extract validator keys from {node_name}: {e}")
        
        # Remove duplicates and return
        return list(set(validator_keys))
    
    def _get_keys_from_keystores(self, node_config: Dict) -> List[str]:
        """Extract validator keys from keystore directories"""
        keys = []
        
        # Common keystore paths based on stack
        stack = node_config.get('stack', [])
        eth_docker_path = node_config.get('eth_docker_path', '/home/user/eth-docker')
        
        keystore_paths = []
        
        if 'eth-docker' in stack:
            keystore_paths.append(f"{eth_docker_path}/.eth/validator_keys")
            
        if 'obol' in stack:
            keystore_paths.extend([
                f"{eth_docker_path}/charon/validator_keys",
                f"{eth_docker_path}/.charon/validator_keys"
            ])
            
        if 'rocketpool' in stack:
            keystore_paths.append(f"{eth_docker_path}/.rocketpool/data/validators")
        
        # Search for keystore files
        for path in keystore_paths:
            try:
                keys.extend(self._scan_keystore_directory(node_config, path))
            except Exception as e:
                logger.debug(f"Could not scan keystore path {path}: {e}")
                continue
        
        return keys
    
    def _scan_keystore_directory(self, node_config: Dict, keystore_path: str) -> List[str]:
        """Scan a keystore directory for validator public keys"""
        keys = []
        
        # Build command to find keystore files
        if node_config.get('is_local'):
            find_cmd = f"find {keystore_path} -name 'keystore-*.json' 2>/dev/null || true"
        else:
            ssh_user = node_config.get('ssh_user', 'root')
            domain = node_config['tailscale_domain']
            find_cmd = f"ssh -o ConnectTimeout=10 {ssh_user}@{domain} \"find {keystore_path} -name 'keystore-*.json' 2>/dev/null || true\""
        
        result = _run_command(node_config, find_cmd)
        
        if result.returncode == 0 and result.stdout.strip():
            keystore_files = result.stdout.strip().split('\n')
            
            # Extract public keys from keystore filenames or content
            for keystore_file in keystore_files:
                key = self._extract_key_from_keystore_file(node_config, keystore_file)
                if key:
                    keys.append(key)
        
        return keys
    
    def _extract_key_from_keystore_file(self, node_config: Dict, keystore_file: str) -> Optional[str]:
        """Extract public key from keystore file"""
        try:
            # Method 1: Extract from filename (common pattern: keystore-m_12381_3600_0_0_0-1234567890.json)
            if 'keystore-m_' in keystore_file:
                # Try to read the actual keystore file for the public key
                if node_config.get('is_local'):
                    cat_cmd = f"cat {keystore_file} 2>/dev/null || true"
                else:
                    ssh_user = node_config.get('ssh_user', 'root')
                    domain = node_config['tailscale_domain']
                    cat_cmd = f"ssh -o ConnectTimeout=10 {ssh_user}@{domain} \"cat {keystore_file} 2>/dev/null || true\""
                
                result = _run_command(node_config, cat_cmd)
                
                if result.returncode == 0 and result.stdout.strip():
                    try:
                        keystore_data = json.loads(result.stdout)
                        # Look for pubkey in keystore
                        if 'pubkey' in keystore_data:
                            return f"0x{keystore_data['pubkey']}"
                    except json.JSONDecodeError:
                        pass
        
        except Exception as e:
            logger.debug(f"Could not extract key from {keystore_file}: {e}")
        
        return None
    
    def _get_keys_from_validator_api(self, node_config: Dict) -> List[str]:
        """Get validator keys from validator client API"""
        keys = []
        
        # This would require implementing API calls to validator clients
        # For now, return empty list - can be enhanced later
        return keys
    
    def _get_keys_from_logs(self, node_config: Dict) -> List[str]:
        """Extract validator keys from container logs (last resort)"""
        keys = []
        
        try:
            # Get validator container names
            containers = self._get_validator_containers(node_config)
            
            for container in containers:
                # Look for validator key mentions in logs
                log_keys = self._parse_validator_keys_from_logs(node_config, container)
                keys.extend(log_keys)
        
        except Exception as e:
            logger.debug(f"Could not extract keys from logs: {e}")
        
        return keys
    
    def _get_validator_containers(self, node_config: Dict) -> List[str]:
        """Get validator container names for a node"""
        containers = []
        
        # Build docker ps command
        if node_config.get('is_local'):
            docker_cmd = "docker ps --format '{{.Names}}' | grep -E '(validator|charon)' || true"
        else:
            ssh_user = node_config.get('ssh_user', 'root')
            domain = node_config['tailscale_domain']
            docker_cmd = f"ssh -o ConnectTimeout=10 {ssh_user}@{domain} \"docker ps --format '{{{{.Names}}}}' | grep -E '(validator|charon)' || true\""
        
        result = _run_command(node_config, docker_cmd)
        
        if result.returncode == 0 and result.stdout.strip():
            containers = result.stdout.strip().split('\n')
        
        return containers
    
    def _parse_validator_keys_from_logs(self, node_config: Dict, container_name: str) -> List[str]:
        """Parse validator keys from container logs"""
        keys = []
        
        # Get recent logs from container
        if node_config.get('is_local'):
            logs_cmd = f"docker logs --tail=100 {container_name} 2>/dev/null | grep -oE '0x[a-fA-F0-9]{{96}}' | head -20 || true"
        else:
            ssh_user = node_config.get('ssh_user', 'root')
            domain = node_config['tailscale_domain']
            logs_cmd = f"ssh -o ConnectTimeout=10 {ssh_user}@{domain} \"docker logs --tail=100 {container_name} 2>/dev/null | grep -oE '0x[a-fA-F0-9]{{96}}' | head -20 || true\""
        
        result = _run_command(node_config, logs_cmd)
        
        if result.returncode == 0 and result.stdout.strip():
            potential_keys = result.stdout.strip().split('\n')
            # Filter for valid BLS public keys (48 bytes = 96 hex chars + 0x)
            keys = [key.strip() for key in potential_keys if len(key) == 98 and key.startswith('0x')]
        
        return keys
    
    def _query_validators_from_beacon(self, beacon_api_url: str, validator_keys: List[str]) -> Dict[str, Dict]:
        """Query beacon chain API for validator information"""
        validator_info = {}
        
        if not validator_keys:
            return validator_info
        
        try:
            # Query validators endpoint
            # API: /eth/v1/beacon/states/head/validators
            api_url = f"{beacon_api_url}/eth/v1/beacon/states/head/validators"
            
            # For large numbers of validators, we might need to batch the requests
            # For now, query all at once (may need optimization)
            params = {'id': ','.join(validator_keys[:50])}  # Limit to first 50
            
            response = requests.get(api_url, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                
                if 'data' in data:
                    for validator in data['data']:
                        pubkey = validator['validator']['pubkey']
                        validator_info[pubkey] = {
                            'index': validator['index'],
                            'status': validator['status'],
                            'balance': validator['balance']
                        }
            
        except Exception as e:
            logger.error(f"Failed to query beacon API {beacon_api_url}: {e}")
        
        return validator_info
    
    def _detect_protocol(self, node_config: Dict) -> str:
        """Detect the primary staking protocol for a node"""
        stack = node_config.get('stack', [])
        
        # Priority order for protocol detection
        if 'rocketpool' in stack:
            return 'rocketpool'
        elif 'lido-csm' in stack:
            return 'lido-csm'
        elif 'hyperdrive' in stack:
            return 'nodeset-hyperdrive'
        elif 'obol' in stack:
            return 'obol-dvt'
        elif 'ssv' in stack:
            return 'ssv-network'
        elif 'stakewise' in stack:
            return 'stakewise'
        elif 'eth-docker' in stack:
            return 'solo-staking'
        else:
            return 'unknown'
    
    def _is_node_disabled(self, node_config: Dict) -> bool:
        """Check if a node is disabled"""
        stack = node_config.get('stack', [])
        return 'disabled' in stack or node_config.get('ethereum_clients_enabled') is False
    
    def generate_validators_csv(self, output_file: str = "validators_auto_discovered.csv") -> str:
        """
        Generate simplified validators CSV file automatically
        
        Args:
            output_file: Output CSV filename
            
        Returns:
            Path to generated CSV file
        """
        logger.info(f"Generating auto-discovered validators CSV: {output_file}")
        
        # Discover all validators
        validators = self.discover_all_validators()
        
        # Write to CSV even if empty
        csv_path = Path(self.config_file_path).parent / output_file
        
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['validator_index', 'public_key', 'node_name', 'protocol', 'status', 'last_updated']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            # Write header
            writer.writeheader()
            
            # Write validator data
            for validator in validators:
                writer.writerow({
                    'validator_index': validator['validator_index'],
                    'public_key': validator['public_key'],
                    'node_name': validator['node_name'],
                    'protocol': validator['protocol'],
                    'status': validator['status'],
                    'last_updated': validator['last_updated']
                })
        
        if validators:
            logger.info(f"Generated CSV with {len(validators)} validators: {csv_path}")
        else:
            logger.info(f"Generated empty CSV file: {csv_path}")
            
        return str(csv_path)
    
    def update_existing_csv(self, csv_file: str) -> bool:
        """
        Update existing validators CSV with auto-discovered data
        
        Args:
            csv_file: Path to existing CSV file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Discover current validators
            discovered = self.discover_all_validators()
            
            if not discovered:
                logger.warning("No validators discovered for CSV update")
                return False
            
            # Create backup
            backup_file = f"{csv_file}.backup_{int(datetime.now().timestamp())}"
            if Path(csv_file).exists():
                Path(csv_file).rename(backup_file)
                logger.info(f"Created backup: {backup_file}")
            
            # Write updated CSV
            self.generate_validators_csv(Path(csv_file).name)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to update CSV {csv_file}: {e}")
            return False

def auto_generate_validators_csv(config_file_path: str, output_file: str = "validators_auto_discovered.csv") -> str:
    """
    Convenience function to auto-generate validators CSV
    
    Args:
        config_file_path: Path to configuration file
        output_file: Output CSV filename
        
    Returns:
        Path to generated CSV file
    """
    discovery = ValidatorAutoDiscovery(config_file_path)
    return discovery.generate_validators_csv(output_file)

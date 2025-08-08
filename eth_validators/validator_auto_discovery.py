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
        
        try:
            # Get validator keys from running containers (PRIMARY DISCOVERY)
            validator_keys = self._extract_validator_keys_from_node(node_config)
            
            if not validator_keys:
                logger.warning(f"No validator keys found on {node_name}")
                return []
            
            # Detect protocol/stack
            protocol = self._detect_protocol(node_config)
            
            # Build validator records without requiring beacon API
            # This ensures discovery works even when beacon APIs are not accessible
            for pubkey in validator_keys:
                validators.append({
                    'validator_index': 'unknown',  # Will be populated later if beacon API is available
                    'public_key': pubkey,
                    'node_name': node_name,
                    'protocol': protocol,
                    'status': 'discovered',  # Basic status - will be enhanced if beacon API works
                    'balance': 0,  # Will be populated later if beacon API is available
                    'last_updated': datetime.now().isoformat()
                })
            
            logger.info(f"Found {len(validator_keys)} validator keys on {node_name}")
            
            # OPTIONAL: Try to enhance with beacon chain data if available
            # This is a nice-to-have but not required for basic discovery
            try:
                beacon_api_url = self._get_beacon_api_url(node_config)
                if beacon_api_url:
                    logger.debug(f"Attempting to enhance validator data with beacon API for {node_name}")
                    validator_info = self._query_validators_from_beacon(beacon_api_url, validator_keys)
                    
                    # Update validator records with beacon chain data if available
                    for validator in validators:
                        pubkey = validator['public_key']
                        if pubkey in validator_info:
                            beacon_data = validator_info[pubkey]
                            validator['validator_index'] = beacon_data.get('index', 'unknown')
                            validator['status'] = beacon_data.get('status', 'discovered')
                            validator['balance'] = beacon_data.get('balance', 0)
                            
                    logger.info(f"Enhanced {len(validator_info)} validators with beacon chain data")
                else:
                    logger.debug(f"No beacon API configuration for {node_name} - using basic discovery only")
            except Exception as beacon_error:
                logger.debug(f"Beacon API enhancement failed for {node_name}: {beacon_error}")
                logger.debug("Continuing with basic validator discovery (validator keys found successfully)")
        
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
        """Extract validator keys from keystore directories using ethd keys list (BEST METHOD)"""
        keys = []
        
        # Method 1: Use ethd keys list for eth-docker stacks (MOST RELIABLE)
        if 'eth-docker' in node_config.get('stack', []):
            ethd_keys = self._get_keys_via_ethd_command(node_config)
            keys.extend(ethd_keys)
            if ethd_keys:
                logger.info(f"Found {len(ethd_keys)} validators via ethd keys list")
                return keys  # If ethd works, we're done - this is the most reliable method
        
        # Method 2: Use hyperdrive validator status for NodeSet Hyperdrive stacks
        if 'hyperdrive' in node_config.get('stack', []):
            hyperdrive_keys = self._get_keys_via_hyperdrive_command(node_config)
            keys.extend(hyperdrive_keys)
            if hyperdrive_keys:
                logger.info(f"Found {len(hyperdrive_keys)} validators via hyperdrive validator status")
                return keys  # If hyperdrive works, we're done
        
        # Method 3: Traditional keystore file scanning (fallback)
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
        
        # Search for keystore files (fallback method)
        for path in keystore_paths:
            try:
                keys.extend(self._scan_keystore_directory(node_config, path))
            except Exception as e:
                logger.debug(f"Could not scan keystore path {path}: {e}")
                continue
        
        return keys
    
    def _get_keys_via_ethd_command(self, node_config: Dict) -> List[str]:
        """Get validator keys using ethd keys list command - MOST RELIABLE METHOD"""
        keys = []
        
        try:
            # Get the correct eth-docker path for this node
            eth_docker_path = node_config.get('eth_docker_path', '/home/egk/eth-docker')
            
            # Build the command - get ALL output and filter in Python (more reliable than grep)
            if node_config.get('is_local'):
                cmd = f"cd {eth_docker_path} && ./ethd keys list 2>/dev/null"
            else:
                domain = node_config['tailscale_domain']
                ssh_user = node_config.get('ssh_user', 'root')
                # Reduced timeout for better user experience - fail fast if node is unreachable
                cmd = f"ssh -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=2 {ssh_user}@{domain} \"cd {eth_docker_path} && timeout 15 ./ethd keys list 2>/dev/null\""
            
            logger.debug(f"Running ethd command: {cmd}")
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20)  # Reduced from 30s
            
            if result.returncode == 0 and result.stdout.strip():
                # Filter output for validator public keys (0x + 96 hex characters)
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    line = line.strip()
                    if line.startswith('0x') and len(line) == 98:  # 0x + 96 hex chars = 98 total
                        keys.append(line.lower())
                
                if keys:
                    logger.info(f"Successfully found {len(keys)} validators via ethd keys list")
                else:
                    logger.warning(f"ethd keys list ran but found no validator keys")
            else:
                logger.debug(f"ethd command failed: return code {result.returncode}")
                logger.debug(f"STDOUT: {result.stdout[:200]}")
                logger.debug(f"STDERR: {result.stderr[:200]}")
                    
        except subprocess.TimeoutExpired:
            logger.warning(f"ethd keys list command timed out for {node_config.get('name')} - node may be unreachable")
        except Exception as e:
            logger.debug(f"ethd keys list command failed: {e}")
        
        return keys
    
    def _get_keys_via_hyperdrive_command(self, node_config: Dict) -> List[str]:
        """Get validator keys using hyperdrive sw v s command - FOR NODESET HYPERDRIVE"""
        keys = []
        
        try:
            # Build the correct hyperdrive stakewise validator status command
            if node_config.get('is_local'):
                cmd = "hyperdrive --allow-root sw v s 2>/dev/null"
            else:
                domain = node_config['tailscale_domain']
                ssh_user = node_config.get('ssh_user', 'root')
                # Improved SSH with faster timeouts and better error handling
                cmd = f"ssh -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=2 {ssh_user}@{domain} \"timeout 15 hyperdrive --allow-root sw v s 2>/dev/null\""
            
            logger.debug(f"Running hyperdrive command: {cmd}")
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20)  # Reduced timeout
            
            if result.returncode == 0 and result.stdout.strip():
                # Check if StakeWise module is enabled
                output = result.stdout.strip()
                if "StakeWise module is not enabled" in output:
                    logger.debug(f"StakeWise module not enabled on {node_config.get('name')}")
                    return keys  # Return empty list - this is expected, not an error
                
                # Parse hyperdrive output for validator public keys
                lines = output.split('\n')
                import re
                
                for line in lines:
                    line = line.strip()
                    # Look for "Validator" lines followed by public key (from screenshots: "Validator a5d9b0cf9426a714d04167...")
                    if line.startswith('Validator ') and len(line) > 10:
                        # Extract the public key part after "Validator "
                        pubkey_match = re.search(r'Validator\s+([a-f0-9]{96})', line, re.IGNORECASE)
                        if pubkey_match:
                            pubkey = f"0x{pubkey_match.group(1).lower()}"
                            keys.append(pubkey)
                
                if keys:
                    logger.info(f"Successfully found {len(keys)} validators via hyperdrive sw v s")
                else:
                    logger.debug(f"hyperdrive sw v s ran but found no validator keys - may need module configuration")
            else:
                logger.debug(f"hyperdrive command failed: return code {result.returncode}")
                if result.stderr and "command not found" not in result.stderr:
                    logger.debug(f"STDERR: {result.stderr[:200]}")
                    
        except subprocess.TimeoutExpired:
            logger.debug(f"hyperdrive command timed out for {node_config.get('name')} - node may be unreachable")
        except Exception as e:
            logger.debug(f"hyperdrive sw v s command failed: {e}")
        
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
        """Get validator keys from validator client API - FULL AUTOMATED DISCOVERY"""
        keys = []
        node_name = node_config.get('name')
        
        try:
            # Method 1: Query keymanager API (most reliable for automated discovery)
            keymanager_keys = self._query_keymanager_api(node_config)
            keys.extend(keymanager_keys)
            
            # Method 2: Query validator containers directly
            if not keys:
                container_keys = self._query_validator_containers(node_config)
                keys.extend(container_keys)
                
            # Method 3: Parse validator client logs for pubkeys
            if not keys:
                log_keys = self._extract_pubkeys_from_validator_logs(node_config)
                keys.extend(log_keys)
                
        except Exception as e:
            logger.error(f"Failed to get keys from validator API for {node_name}: {e}")
        
        return list(set(keys))  # Remove duplicates
    
    def _query_keymanager_api(self, node_config: Dict) -> List[str]:
        """Query keymanager API for managed validators - PRIMARY METHOD"""
        keys = []
        
        # Common keymanager API ports
        keymanager_ports = [7500, 5062, 8080, 9000]
        
        for port in keymanager_ports:
            try:
                if node_config.get('is_local'):
                    url = f"http://localhost:{port}/eth/v1/keystores"
                    response = requests.get(url, timeout=5)
                else:
                    # Use SSH tunnel for remote access
                    domain = node_config['tailscale_domain']
                    ssh_user = node_config.get('ssh_user', 'root')
                    curl_cmd = f"curl -s --max-time 5 'http://localhost:{port}/eth/v1/keystores'"
                    cmd = f"ssh -o ConnectTimeout=10 {ssh_user}@{domain} \"{curl_cmd}\""
                    
                    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
                    if result.returncode == 0 and result.stdout.strip():
                        response_data = json.loads(result.stdout)
                        if 'data' in response_data:
                            for keystore in response_data['data']:
                                if 'validating_pubkey' in keystore:
                                    pubkey = keystore['validating_pubkey']
                                    if not pubkey.startswith('0x'):
                                        pubkey = f"0x{pubkey}"
                                    keys.append(pubkey)
                            logger.info(f"Found {len(keys)} validators via keymanager API on port {port}")
                            break  # Success, no need to try other ports
                        
            except Exception as e:
                logger.debug(f"Keymanager API port {port} failed: {e}")
                continue
                
        return keys
    
    def _query_validator_containers(self, node_config: Dict) -> List[str]:
        """Query running validator containers for managed keys"""
        keys = []
        
        try:
            # Get list of validator containers
            if node_config.get('is_local'):
                cmd = "docker ps --format '{{.Names}}' | grep -E 'validator|charon'"
            else:
                domain = node_config['tailscale_domain']
                ssh_user = node_config.get('ssh_user', 'root')
                cmd = f"ssh -o ConnectTimeout=10 {ssh_user}@{domain} \"docker ps --format '{{.Names}}' | grep -E 'validator|charon'\""
            
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
            
            if result.returncode == 0 and result.stdout.strip():
                containers = result.stdout.strip().split('\n')
                
                for container in containers:
                    container_keys = self._extract_keys_from_container(node_config, container.strip())
                    keys.extend(container_keys)
                    
        except Exception as e:
            logger.debug(f"Container query failed: {e}")
            
        return keys
    
    def _extract_keys_from_container(self, node_config: Dict, container_name: str) -> List[str]:
        """Extract validator keys from a specific container"""
        keys = []
        
        try:
            # Try to find keystore files inside the container
            keystore_paths = [
                '/keystores',
                '/validator_keys', 
                '/keys',
                '/opt/charon/validator_keys',
                '/root/.eth2validators/keys'
            ]
            
            for path in keystore_paths:
                if node_config.get('is_local'):
                    cmd = f"docker exec {container_name} find {path} -name 'keystore-*.json' 2>/dev/null | head -10"
                else:
                    domain = node_config['tailscale_domain']
                    ssh_user = node_config.get('ssh_user', 'root')
                    cmd = f"ssh -o ConnectTimeout=10 {ssh_user}@{domain} \"docker exec {container_name} find {path} -name 'keystore-*.json' 2>/dev/null | head -10\""
                
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
                
                if result.returncode == 0 and result.stdout.strip():
                    keystore_files = result.stdout.strip().split('\n')
                    
                    for keystore_file in keystore_files:
                        pubkey = self._extract_pubkey_from_container_keystore(node_config, container_name, keystore_file)
                        if pubkey:
                            keys.append(pubkey)
                            
                    if keys:  # Found keys in this path, no need to check others
                        break
                        
        except Exception as e:
            logger.debug(f"Container key extraction failed for {container_name}: {e}")
            
        return keys
    
    def _extract_pubkey_from_container_keystore(self, node_config: Dict, container_name: str, keystore_file: str) -> str:
        """Extract public key from keystore file inside container"""
        try:
            if node_config.get('is_local'):
                cmd = f"docker exec {container_name} cat {keystore_file} 2>/dev/null"
            else:
                domain = node_config['tailscale_domain']
                ssh_user = node_config.get('ssh_user', 'root')
                cmd = f"ssh -o ConnectTimeout=10 {ssh_user}@{domain} \"docker exec {container_name} cat {keystore_file} 2>/dev/null\""
            
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0 and result.stdout.strip():
                keystore_data = json.loads(result.stdout)
                if 'pubkey' in keystore_data:
                    pubkey = keystore_data['pubkey']
                    if not pubkey.startswith('0x'):
                        pubkey = f"0x{pubkey}"
                    return pubkey
                    
        except Exception as e:
            logger.debug(f"Could not extract pubkey from {keystore_file}: {e}")
            
        return None
    
    def _extract_pubkeys_from_validator_logs(self, node_config: Dict) -> List[str]:
        """Extract validator public keys from validator container logs"""
        keys = []
        
        try:
            # Get validator containers
            if node_config.get('is_local'):
                cmd = "docker ps --format '{{.Names}}' | grep -E 'validator|charon'"
            else:
                domain = node_config['tailscale_domain']
                ssh_user = node_config.get('ssh_user', 'root')
                cmd = f"ssh -o ConnectTimeout=10 {ssh_user}@{domain} \"docker ps --format '{{.Names}}' | grep -E 'validator|charon'\""
            
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
            
            if result.returncode == 0 and result.stdout.strip():
                containers = result.stdout.strip().split('\n')
                
                for container in containers:
                    container = container.strip()
                    
                    # Get recent logs and search for pubkeys
                    if node_config.get('is_local'):
                        log_cmd = f"docker logs --tail 1000 {container} 2>&1 | grep -i -E '0x[a-f0-9]{{96}}|pubkey.*0x[a-f0-9]{{96}}' | head -20"
                    else:
                        domain = node_config['tailscale_domain']
                        ssh_user = node_config.get('ssh_user', 'root')
                        log_cmd = f"ssh -o ConnectTimeout=10 {ssh_user}@{domain} \"docker logs --tail 1000 {container} 2>&1 | grep -i -E '0x[a-f0-9]{{96}}|pubkey.*0x[a-f0-9]{{96}}' | head -20\""
                    
                    log_result = subprocess.run(log_cmd, shell=True, capture_output=True, text=True, timeout=15)
                    
                    if log_result.returncode == 0 and log_result.stdout.strip():
                        # Extract 96-character hex strings (validator pubkeys)
                        import re
                        pubkey_pattern = r'0x[a-f0-9]{96}'
                        matches = re.findall(pubkey_pattern, log_result.stdout, re.IGNORECASE)
                        
                        for match in matches:
                            if match not in keys:
                                keys.append(match.lower())
                                
        except Exception as e:
            logger.debug(f"Log extraction failed: {e}")
            
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

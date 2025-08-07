"""
Auto-Discovery Module - Automatically discovers node configurations

This module scans nodes to detect:
- Running Docker containers and their configurations
- Active networks (mainnet, testnets)
- API ports and endpoints
- Client types and versions
- Stack components (eth-docker, obol, lido-csm, etc.)
"""

import subprocess
import json
import re
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

class AutoConfigDiscovery:
    """Discovers node configuration automatically via SSH and API calls"""
    
    def __init__(self):
        self.common_ports = [5052, 5053, 5054, 5155, 5156]  # Common beacon API ports
        self.common_paths = [
            '/home/egk/eth-docker',
            '/home/egk/eth-hoodi', 
            '/home/root/eth-docker',
            '/opt/eth-docker'
        ]
        
    def discover_node_config(self, node_name: str, ssh_user: str, tailscale_domain: str) -> Dict:
        """
        Discover complete configuration for a node
        
        Args:
            node_name: Name of the node
            ssh_user: SSH user to connect with
            tailscale_domain: Tailscale domain for the node
            
        Returns:
            Complete discovered configuration
        """
        logger.info(f"Starting auto-discovery for node: {node_name}")
        
        ssh_target = f"{ssh_user}@{tailscale_domain}" if ssh_user != 'local' else None
        is_local = ssh_target is None
        
        discovery_result = {
            'name': node_name,
            'ssh_user': ssh_user,
            'tailscale_domain': tailscale_domain,
            'is_local': is_local,
            'docker_paths': [],
            'active_networks': {},
            'api_ports': {},
            'detected_stacks': [],
            'containers': [],
            'client_info': {},
            'errors': []
        }
        
        try:
            # 1. Discover Docker paths
            discovery_result['docker_paths'] = self._discover_docker_paths(ssh_target)
            
            # 2. Get running containers
            discovery_result['containers'] = self._get_containers(ssh_target)
            
            # 3. Discover active networks
            discovery_result['active_networks'] = self._discover_active_networks(discovery_result['containers'])
            
            # 4. Discover API ports
            discovery_result['api_ports'] = self._discover_api_ports(ssh_target)
            
            # 5. Detect stacks in use
            discovery_result['detected_stacks'] = self._discover_stacks(discovery_result['containers'])
            
            # 6. Get client information
            discovery_result['client_info'] = self._discover_clients(discovery_result['containers'])
            
            logger.info(f"Discovery completed for {node_name}")
            
        except Exception as e:
            error_msg = f"Discovery failed for {node_name}: {str(e)}"
            logger.error(error_msg)
            discovery_result['errors'].append(error_msg)
            
        return discovery_result
    
    def _discover_docker_paths(self, ssh_target: Optional[str]) -> List[str]:
        """Discover all eth-docker paths on the node"""
        found_paths = []
        
        for path in self.common_paths:
            if self._path_exists(ssh_target, path):
                found_paths.append(path)
                logger.info(f"Found Docker path: {path}")
                
        return found_paths
    
    def _path_exists(self, ssh_target: Optional[str], path: str) -> bool:
        """Check if a path exists on the node"""
        try:
            if ssh_target:
                cmd = f'ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} "test -d {path}"'
            else:
                cmd = f'test -d {path}'
                
            result = subprocess.run(cmd, shell=True, capture_output=True, timeout=15)
            return result.returncode == 0
        except:
            return False
    
    def _get_containers(self, ssh_target: Optional[str]) -> List[Dict]:
        """Get all running Docker containers"""
        try:
            if ssh_target:
                cmd = f'ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} "docker ps --format \'{{{{.Names}}}}\t{{{{.Image}}}}\t{{{{.Status}}}}\t{{{{.Ports}}}}\'"'
            else:
                cmd = 'docker ps --format "{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"'
                
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20)
            
            if result.returncode != 0:
                return []
                
            containers = []
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    parts = line.split('\t')
                    if len(parts) >= 3:
                        containers.append({
                            'name': parts[0],
                            'image': parts[1], 
                            'status': parts[2],
                            'ports': parts[3] if len(parts) > 3 else ''
                        })
            
            logger.info(f"Found {len(containers)} running containers")
            return containers
            
        except Exception as e:
            logger.error(f"Failed to get containers: {e}")
            return []
    
    def _discover_active_networks(self, containers: List[Dict]) -> Dict[str, Dict]:
        """Discover which networks are actively running"""
        networks = {}
        
        for container in containers:
            container_name = container['name'].lower()
            
            # Detect mainnet (eth-docker)
            if 'eth-docker' in container_name and 'eth-hoodi' not in container_name:
                if 'mainnet' not in networks:
                    networks['mainnet'] = {
                        'network_name': 'mainnet',
                        'container_prefix': 'eth-docker',
                        'eth_docker_path': '/home/egk/eth-docker'
                    }
            
            # Detect hoodi testnet
            elif 'eth-hoodi' in container_name:
                if 'testnet' not in networks:
                    networks['testnet'] = {
                        'network_name': 'hoodi',
                        'container_prefix': 'eth-hoodi', 
                        'eth_docker_path': '/home/egk/eth-hoodi'
                    }
        
        logger.info(f"Discovered networks: {list(networks.keys())}")
        return networks
    
    def _discover_api_ports(self, ssh_target: Optional[str]) -> Dict[str, int]:
        """Discover active beacon API ports"""
        api_ports = {}
        
        for port in self.common_ports:
            if self._port_responding(ssh_target, port):
                network = self._identify_network_by_port(ssh_target, port)
                api_ports[network] = port
                logger.info(f"Found API port {port} for network {network}")
        
        return api_ports
    
    def _port_responding(self, ssh_target: Optional[str], port: int) -> bool:
        """Check if a port is responding"""
        try:
            if ssh_target:
                cmd = f'ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} "curl -s --connect-timeout 3 --max-time 5 http://localhost:{port}/eth/v1/node/version"'
            else:
                cmd = f'curl -s --connect-timeout 3 --max-time 5 http://localhost:{port}/eth/v1/node/version'
                
            result = subprocess.run(cmd, shell=True, capture_output=True, timeout=10)
            return result.returncode == 0 and result.stdout.strip()
        except:
            return False
    
    def _identify_network_by_port(self, ssh_target: Optional[str], port: int) -> str:
        """Identify which network a port belongs to"""
        # Common port mappings
        port_network_map = {
            5052: 'mainnet',
            5053: 'testnet', 
            5154: 'holesky',
            5155: 'sepolia'
        }
        
        return port_network_map.get(port, f'unknown_port_{port}')
    
    def _discover_stacks(self, containers: List[Dict]) -> List[str]:
        """Discover which stacks are running on the node"""
        stacks = set()
        
        for container in containers:
            name = container['name'].lower()
            image = container['image'].lower()
            
            # Detect eth-docker
            if 'eth-docker' in name:
                stacks.add('eth-docker')
            elif 'eth-hoodi' in name:
                stacks.add('eth-hoodi')
                
            # Detect Obol (Charon)
            if 'charon' in name or 'charon' in image:
                stacks.add('obol')
                
            # Detect Lido CSM
            if 'csm' in name or 'lido' in name:
                stacks.add('lido-csm')
                
            # Detect Rocket Pool
            if 'rocketpool' in name or 'rocket' in name:
                stacks.add('rocketpool')
                
            # Detect Hyperdrive
            if 'hyperdrive' in name or 'nodeset' in image:
                stacks.add('hyperdrive')
        
        stack_list = list(stacks)
        logger.info(f"Detected stacks: {stack_list}")
        return stack_list
    
    def _discover_clients(self, containers: List[Dict]) -> Dict[str, Dict]:
        """Discover client types and basic info"""
        clients = {
            'execution': {'name': 'Unknown', 'container': None},
            'consensus': {'name': 'Unknown', 'container': None},
            'validator': {'name': 'Unknown', 'container': None}
        }
        
        for container in containers:
            name = container['name'].lower()
            image = container['image'].lower()
            
            # Execution clients
            if any(client in name or client in image for client in ['geth', 'nethermind', 'reth', 'besu', 'erigon']):
                if 'execution' in name or any(exec_client in name for exec_client in ['geth', 'nethermind', 'reth', 'besu', 'erigon']):
                    clients['execution'] = {
                        'name': self._identify_client_from_image(image),
                        'container': container['name'],
                        'image': image
                    }
            
            # Consensus clients  
            elif any(client in name or client in image for client in ['lighthouse', 'prysm', 'teku', 'nimbus', 'lodestar', 'grandine']):
                if 'consensus' in name or 'validator' not in name:
                    clients['consensus'] = {
                        'name': self._identify_client_from_image(image),
                        'container': container['name'],
                        'image': image
                    }
            
            # Validator clients
            elif 'validator' in name:
                clients['validator'] = {
                    'name': self._identify_client_from_image(image),
                    'container': container['name'],
                    'image': image
                }
        
        return clients
    
    def _identify_client_from_image(self, image: str) -> str:
        """Identify client type from Docker image"""
        image_lower = image.lower()
        
        clients = {
            'geth': 'geth',
            'nethermind': 'nethermind', 
            'reth': 'reth',
            'besu': 'besu',
            'erigon': 'erigon',
            'lighthouse': 'lighthouse',
            'prysm': 'prysm',
            'teku': 'teku',
            'nimbus': 'nimbus',
            'lodestar': 'lodestar',
            'grandine': 'grandine'
        }
        
        for client_key, client_name in clients.items():
            if client_key in image_lower:
                return client_name
                
        return 'unknown'

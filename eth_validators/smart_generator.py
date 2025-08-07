"""
Smart Config Generator - Generates optimized configurations based on discovery

This module takes discovery results and generates optimal YAML configurations,
handling complex scenarios like multi-network nodes, integrated clients, etc.
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

class SmartConfigGenerator:
    """Generates smart configuration based on discovery results"""
    
    def __init__(self):
        self.default_timeouts = {
            'ssh_timeout': 30,
            'container_timeout': 300
        }
    
    def generate_node_config(self, discovery_data: Dict) -> Dict:
        """
        Generate optimized node configuration from discovery data
        
        Args:
            discovery_data: Result from AutoConfigDiscovery
            
        Returns:
            Optimized node configuration dictionary
        """
        logger.info(f"Generating config for node: {discovery_data['name']}")
        
        config = {
            'name': discovery_data['name'],
            'ssh_user': discovery_data['ssh_user'], 
            'tailscale_domain': discovery_data['tailscale_domain']
        }
        
        # Add is_local flag if applicable
        if discovery_data.get('is_local'):
            config['is_local'] = True
        
        # Handle different network scenarios
        active_networks = discovery_data.get('active_networks', {})
        
        if len(active_networks) == 0:
            # No active networks - probably disabled node
            config.update(self._generate_disabled_config())
        elif len(active_networks) == 1:
            # Single network - most common case
            config.update(self._generate_single_network_config(discovery_data, active_networks))
        else:
            # Multi-network node
            config.update(self._generate_multi_network_config(discovery_data, active_networks))
        
        # Add detected stacks
        stacks = discovery_data.get('detected_stacks', [])
        if stacks:
            config['stack'] = stacks
        
        logger.info(f"Generated config for {discovery_data['name']}")
        return config
    
    def _generate_disabled_config(self) -> Dict:
        """Generate configuration for disabled nodes"""
        return {
            'beacon_api_port': None,
            'stack': ['disabled'],
            'ethereum_clients_enabled': False
        }
    
    def _generate_single_network_config(self, discovery_data: Dict, networks: Dict) -> Dict:
        """Generate configuration for single-network nodes"""
        config = {}
        
        # Get the single network
        network_key = list(networks.keys())[0]
        network_info = networks[network_key]
        
        # Set primary eth_docker_path
        config['eth_docker_path'] = network_info.get('eth_docker_path', '/home/egk/eth-docker')
        
        # Set beacon API port
        api_ports = discovery_data.get('api_ports', {})
        if network_key in api_ports:
            config['beacon_api_port'] = api_ports[network_key]
        elif api_ports:
            # Use first available port
            config['beacon_api_port'] = list(api_ports.values())[0]
        else:
            # Use default based on network
            config['beacon_api_port'] = self._get_default_port(network_key)
        
        return config
    
    def _generate_multi_network_config(self, discovery_data: Dict, networks: Dict) -> Dict:
        """Generate configuration for multi-network nodes"""
        config = {}
        
        # For multi-network, set primary path to mainnet if available
        if 'mainnet' in networks:
            config['eth_docker_path'] = networks['mainnet'].get('eth_docker_path', '/home/egk/eth-docker')
            primary_network = 'mainnet'
        else:
            # Use first network as primary
            primary_network = list(networks.keys())[0]
            config['eth_docker_path'] = networks[primary_network].get('eth_docker_path', '/home/egk/eth-docker')
        
        # Set primary beacon API port
        api_ports = discovery_data.get('api_ports', {})
        if primary_network in api_ports:
            config['beacon_api_port'] = api_ports[primary_network]
        else:
            config['beacon_api_port'] = self._get_default_port(primary_network)
        
        # Add networks section for multi-network setup
        config['networks'] = {}
        for network_key, network_info in networks.items():
            config['networks'][network_key] = {
                'network_name': network_info['network_name'],
                'container_prefix': network_info['container_prefix'],
                'eth_docker_path': network_info['eth_docker_path']
            }
            
            # Add beacon API port for each network
            if network_key in api_ports:
                config['networks'][network_key]['beacon_api_port'] = api_ports[network_key]
            else:
                config['networks'][network_key]['beacon_api_port'] = self._get_default_port(network_key)
        
        return config
    
    def _get_default_port(self, network: str) -> int:
        """Get default beacon API port for a network"""
        default_ports = {
            'mainnet': 5052,
            'testnet': 5053,
            'hoodi': 5053,
            'holesky': 5154,
            'sepolia': 5155
        }
        return default_ports.get(network, 5052)
    
    def generate_config_from_template(self, template_name: str, node_name: str, **kwargs) -> Dict:
        """Generate configuration from a template"""
        templates = {
            'basic_mainnet': self._basic_mainnet_template,
            'obol_node': self._obol_node_template, 
            'rocketpool_node': self._rocketpool_node_template,
            'lido_csm_node': self._lido_csm_template,
            'hyperdrive_node': self._hyperdrive_template,
            'testnet_only': self._testnet_only_template
        }
        
        if template_name not in templates:
            raise ValueError(f"Unknown template: {template_name}")
            
        return templates[template_name](node_name, **kwargs)
    
    def _basic_mainnet_template(self, node_name: str, **kwargs) -> Dict:
        """Template for basic mainnet node"""
        return {
            'name': node_name,
            'ssh_user': kwargs.get('ssh_user', 'root'),
            'eth_docker_path': '/home/egk/eth-docker',
            'beacon_api_port': 5052,
            'stack': ['eth-docker'],
            'tailscale_domain': kwargs.get('tailscale_domain', f'{node_name}.velociraptor-scylla.ts.net')
        }
    
    def _obol_node_template(self, node_name: str, **kwargs) -> Dict:
        """Template for Obol distributed validator node"""
        config = self._basic_mainnet_template(node_name, **kwargs)
        config['stack'] = ['eth-docker', 'obol']
        return config
    
    def _rocketpool_node_template(self, node_name: str, **kwargs) -> Dict:
        """Template for Rocket Pool node"""
        config = self._basic_mainnet_template(node_name, **kwargs)
        config['stack'] = ['eth-docker', 'rocketpool']
        return config
    
    def _lido_csm_template(self, node_name: str, **kwargs) -> Dict:
        """Template for Lido CSM node"""
        config = self._basic_mainnet_template(node_name, **kwargs)
        config['stack'] = ['eth-docker', 'lido-csm']
        return config
    
    def _hyperdrive_template(self, node_name: str, **kwargs) -> Dict:
        """Template for Hyperdrive node"""
        config = self._basic_mainnet_template(node_name, **kwargs)
        config['stack'] = ['eth-docker', 'hyperdrive']
        return config
    
    def _testnet_only_template(self, node_name: str, **kwargs) -> Dict:
        """Template for testnet-only node"""
        return {
            'name': node_name,
            'ssh_user': kwargs.get('ssh_user', 'egk'),
            'eth_docker_path': '/home/egk/eth-hoodi',
            'beacon_api_port': 5053,
            'networks': {
                'testnet': {
                    'network_name': 'hoodi',
                    'container_prefix': 'eth-hoodi',
                    'beacon_api_port': 5053,
                    'eth_docker_path': '/home/egk/eth-hoodi'
                }
            },
            'stack': ['eth-hoodi'],
            'tailscale_domain': kwargs.get('tailscale_domain', f'{node_name}.velociraptor-scylla.ts.net')
        }
    
    def optimize_existing_config(self, current_config: Dict, discovery_data: Dict) -> Dict:
        """Optimize an existing configuration based on current reality"""
        logger.info(f"Optimizing config for {current_config.get('name', 'unknown')}")
        
        optimized = current_config.copy()
        
        # Update API ports if they're wrong
        api_ports = discovery_data.get('api_ports', {})
        if api_ports:
            if 'networks' in optimized:
                # Multi-network node
                for network_key, network_config in optimized['networks'].items():
                    if network_key in api_ports:
                        network_config['beacon_api_port'] = api_ports[network_key]
            else:
                # Single network node
                if api_ports:
                    optimized['beacon_api_port'] = list(api_ports.values())[0]
        
        # Update stack based on detected stacks
        detected_stacks = discovery_data.get('detected_stacks', [])
        if detected_stacks:
            optimized['stack'] = detected_stacks
        
        # Remove inactive networks
        active_networks = discovery_data.get('active_networks', {})
        if 'networks' in optimized:
            active_network_keys = set(active_networks.keys())
            current_network_keys = set(optimized['networks'].keys())
            
            # Remove networks that are no longer active
            for network_key in current_network_keys - active_network_keys:
                logger.info(f"Removing inactive network: {network_key}")
                del optimized['networks'][network_key]
        
        return optimized
    
    def suggest_improvements(self, current_config: Dict, discovery_data: Dict) -> List[Dict]:
        """Suggest configuration improvements"""
        suggestions = []
        
        node_name = current_config.get('name', 'unknown')
        
        # Check for wrong API ports
        api_ports = discovery_data.get('api_ports', {})
        current_port = current_config.get('beacon_api_port')
        
        if api_ports and current_port:
            actual_ports = list(api_ports.values())
            if current_port not in actual_ports and actual_ports:
                suggestions.append({
                    'type': 'port_mismatch',
                    'description': f'Beacon API port mismatch: config has {current_port}, but {actual_ports[0]} is responding',
                    'current': current_port,
                    'suggested': actual_ports[0]
                })
        
        # Check for stack mismatches
        current_stack = set(current_config.get('stack', []))
        detected_stack = set(discovery_data.get('detected_stacks', []))
        
        if current_stack != detected_stack:
            suggestions.append({
                'type': 'stack_mismatch',
                'description': f'Stack configuration mismatch',
                'current': list(current_stack),
                'suggested': list(detected_stack)
            })
        
        # Check for inactive networks
        if 'networks' in current_config:
            active_networks = set(discovery_data.get('active_networks', {}).keys())
            configured_networks = set(current_config['networks'].keys())
            
            inactive_networks = configured_networks - active_networks
            if inactive_networks:
                suggestions.append({
                    'type': 'inactive_networks',
                    'description': f'Networks configured but not running: {list(inactive_networks)}',
                    'current': list(configured_networks),
                    'suggested': list(active_networks)
                })
        
        return suggestions

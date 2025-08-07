"""
Config Monitor - Monitors configuration drift and provides sync capabilities

This module monitors for changes in the infrastructure vs configuration,
provides drift detection, and enables cluster-wide synchronization.
"""

import logging
import yaml
import time
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass

from .auto_discovery import AutoConfigDiscovery
from .config_validator import ConfigValidator, ValidationIssue

logger = logging.getLogger(__name__)

@dataclass
class DriftDetection:
    """Represents configuration drift detected on a node"""
    node: str
    drift_type: str
    timestamp: datetime
    config_state: Dict
    live_state: Dict
    severity: str
    auto_correctable: bool

class ConfigMonitor:
    """Monitors configuration drift and provides sync capabilities"""
    
    def __init__(self):
        self.discovery = AutoConfigDiscovery()
        self.validator = ConfigValidator()
        self.drift_history = []
        
    def sync_all_nodes(self, config_file_path: str) -> Dict[str, Any]:
        """
        Synchronize configuration for all nodes with live state
        
        Args:
            config_file_path: Path to configuration file
            
        Returns:
            Dictionary containing sync results for each node
        """
        logger.info("Starting cluster-wide configuration sync")
        
        with open(config_file_path, 'r') as f:
            config = yaml.safe_load(f)
        
        sync_results = {}
        updated_nodes = []
        
        for node_config in config.get('nodes', []):
            node_name = node_config.get('name')
            
            # Skip disabled nodes
            if self._is_node_disabled(node_config):
                sync_results[node_name] = {
                    'status': 'skipped',
                    'reason': 'Node is disabled'
                }
                continue
            
            try:
                # Discover current state
                discovery_data = self.discovery.discover_node_config(
                    node_name,
                    node_config.get('ssh_user', 'root'),
                    node_config.get('tailscale_domain', f'{node_name}.ts.net')
                )
                
                # Check for changes needed
                changes_needed = self._analyze_changes_needed(node_config, discovery_data)
                
                if changes_needed:
                    logger.info(f"Updating configuration for {node_name}")
                    
                    # Apply updates
                    self._apply_sync_updates(node_config, discovery_data)
                    updated_nodes.append(node_name)
                    
                    sync_results[node_name] = {
                        'status': 'updated',
                        'changes': changes_needed,
                        'discovery_data': discovery_data
                    }
                else:
                    sync_results[node_name] = {
                        'status': 'no_changes',
                        'message': 'Configuration is up to date'
                    }
                    
            except Exception as e:
                logger.error(f"Sync failed for {node_name}: {e}")
                sync_results[node_name] = {
                    'status': 'error',
                    'error': str(e)
                }
        
        # Save updated configuration if any changes were made
        if updated_nodes:
            self._save_config(config_file_path, config)
            logger.info(f"Configuration updated for {len(updated_nodes)} nodes: {updated_nodes}")
        
        return {
            'total_nodes': len(config.get('nodes', [])),
            'updated_nodes': len(updated_nodes),
            'updated_node_names': updated_nodes,
            'results': sync_results
        }
    
    def detect_drift(self, config_file_path: str) -> List[DriftDetection]:
        """Detect configuration drift across all nodes"""
        logger.info("Detecting configuration drift")
        
        with open(config_file_path, 'r') as f:
            config = yaml.safe_load(f)
        
        drift_detections = []
        
        for node_config in config.get('nodes', []):
            node_name = node_config.get('name')
            
            if self._is_node_disabled(node_config):
                continue
            
            try:
                # Get current live state
                live_state = self.discovery.discover_node_config(
                    node_name,
                    node_config.get('ssh_user', 'root'),
                    node_config.get('tailscale_domain', f'{node_name}.ts.net')
                )
                
                # Compare with config state
                drift = self._compare_states(node_config, live_state)
                if drift:
                    drift_detections.extend(drift)
                    
            except Exception as e:
                logger.error(f"Drift detection failed for {node_name}: {e}")
                drift_detections.append(DriftDetection(
                    node=node_name,
                    drift_type='detection_error',
                    timestamp=datetime.now(),
                    config_state={},
                    live_state={},
                    severity='error',
                    auto_correctable=False
                ))
        
        # Store in history
        self.drift_history.extend(drift_detections)
        
        return drift_detections
    
    def refresh_single_node(self, node_name: str, config_file_path: str) -> Dict[str, Any]:
        """Refresh configuration for a single node"""
        logger.info(f"Refreshing configuration for node: {node_name}")
        
        with open(config_file_path, 'r') as f:
            config = yaml.safe_load(f)
        
        # Find the node
        node_config = None
        for node in config.get('nodes', []):
            if node.get('name') == node_name:
                node_config = node
                break
        
        if not node_config:
            return {
                'status': 'error',
                'error': f'Node {node_name} not found in configuration'
            }
        
        try:
            # Discover current state
            discovery_data = self.discovery.discover_node_config(
                node_name,
                node_config.get('ssh_user', 'root'),
                node_config.get('tailscale_domain', f'{node_name}.ts.net')
            )
            
            # Check for changes
            changes_needed = self._analyze_changes_needed(node_config, discovery_data)
            
            if changes_needed:
                # Apply updates
                old_config = node_config.copy()
                self._apply_sync_updates(node_config, discovery_data)
                
                # Save configuration
                self._save_config(config_file_path, config)
                
                return {
                    'status': 'updated',
                    'changes': changes_needed,
                    'old_config': old_config,
                    'new_config': node_config
                }
            else:
                return {
                    'status': 'no_changes',
                    'message': 'Configuration is already up to date'
                }
                
        except Exception as e:
            logger.error(f"Refresh failed for {node_name}: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }
    
    def monitor_continuous(self, config_file_path: str, check_interval: int = 300, auto_fix: bool = False):
        """Run continuous monitoring (for daemon/service use)"""
        logger.info(f"Starting continuous monitoring (interval: {check_interval}s, auto_fix: {auto_fix})")
        
        while True:
            try:
                # Detect drift
                drift = self.detect_drift(config_file_path)
                
                if drift:
                    logger.warning(f"Configuration drift detected: {len(drift)} issues")
                    
                    for drift_item in drift:
                        logger.warning(f"Drift on {drift_item.node}: {drift_item.drift_type}")
                    
                    # Auto-fix if enabled
                    if auto_fix:
                        self._auto_fix_drift(config_file_path, drift)
                else:
                    logger.info("No configuration drift detected")
                
                # Wait for next check
                time.sleep(check_interval)
                
            except KeyboardInterrupt:
                logger.info("Monitoring stopped by user")
                break
            except Exception as e:
                logger.error(f"Monitoring error: {e}")
                time.sleep(60)  # Wait a bit before retrying
    
    def _is_node_disabled(self, node_config: Dict) -> bool:
        """Check if a node is disabled"""
        return ('disabled' in node_config.get('stack', []) or 
                node_config.get('ethereum_clients_enabled') == False)
    
    def _analyze_changes_needed(self, node_config: Dict, discovery_data: Dict) -> List[Dict]:
        """Analyze what changes are needed for a node"""
        changes = []
        
        # Check beacon API port
        current_port = node_config.get('beacon_api_port')
        discovered_ports = discovery_data.get('api_ports', {})
        
        if discovered_ports and current_port:
            actual_port = list(discovered_ports.values())[0]
            if current_port != actual_port:
                changes.append({
                    'type': 'beacon_api_port',
                    'old_value': current_port,
                    'new_value': actual_port
                })
        
        # Check stack configuration
        current_stack = set(node_config.get('stack', []))
        detected_stack = set(discovery_data.get('detected_stacks', []))
        
        if current_stack != detected_stack and detected_stack:
            changes.append({
                'type': 'stack',
                'old_value': list(current_stack),
                'new_value': list(detected_stack)
            })
        
        # Check network configurations
        active_networks = discovery_data.get('active_networks', {})
        configured_networks = node_config.get('networks', {})
        
        if configured_networks:
            # Remove inactive networks
            for network_key in list(configured_networks.keys()):
                if network_key not in active_networks:
                    changes.append({
                        'type': 'remove_inactive_network',
                        'old_value': network_key,
                        'new_value': None
                    })
            
            # Update network ports
            for network_key, network_config in configured_networks.items():
                if network_key in discovered_ports:
                    configured_port = network_config.get('beacon_api_port')
                    actual_port = discovered_ports[network_key]
                    
                    if configured_port != actual_port:
                        changes.append({
                            'type': 'network_port',
                            'network': network_key,
                            'old_value': configured_port,
                            'new_value': actual_port
                        })
        
        return changes
    
    def _apply_sync_updates(self, node_config: Dict, discovery_data: Dict):
        """Apply sync updates to node configuration"""
        # Update beacon API port
        discovered_ports = discovery_data.get('api_ports', {})
        if discovered_ports:
            if 'networks' not in node_config:
                # Single network node
                node_config['beacon_api_port'] = list(discovered_ports.values())[0]
            else:
                # Multi-network node - update primary port
                primary_port = list(discovered_ports.values())[0]
                node_config['beacon_api_port'] = primary_port
        
        # Update stack
        detected_stacks = discovery_data.get('detected_stacks', [])
        if detected_stacks:
            node_config['stack'] = detected_stacks
        
        # Update networks
        if 'networks' in node_config:
            active_networks = discovery_data.get('active_networks', {})
            
            # Remove inactive networks
            for network_key in list(node_config['networks'].keys()):
                if network_key not in active_networks:
                    del node_config['networks'][network_key]
            
            # Update network ports
            for network_key in node_config['networks']:
                if network_key in discovered_ports:
                    node_config['networks'][network_key]['beacon_api_port'] = discovered_ports[network_key]
    
    def _compare_states(self, node_config: Dict, live_state: Dict) -> List[DriftDetection]:
        """Compare configuration state with live state"""
        drift = []
        node_name = node_config.get('name')
        timestamp = datetime.now()
        
        # Compare beacon API ports
        config_port = node_config.get('beacon_api_port')
        live_ports = live_state.get('api_ports', {})
        
        if live_ports and config_port:
            live_port = list(live_ports.values())[0]
            if config_port != live_port:
                drift.append(DriftDetection(
                    node=node_name,
                    drift_type='beacon_api_port_mismatch',
                    timestamp=timestamp,
                    config_state={'beacon_api_port': config_port},
                    live_state={'beacon_api_port': live_port},
                    severity='critical',
                    auto_correctable=True
                ))
        
        # Compare stacks
        config_stack = set(node_config.get('stack', []))
        live_stack = set(live_state.get('detected_stacks', []))
        
        if config_stack != live_stack and live_stack:
            drift.append(DriftDetection(
                node=node_name,
                drift_type='stack_mismatch',
                timestamp=timestamp,
                config_state={'stack': list(config_stack)},
                live_state={'stack': list(live_stack)},
                severity='warning',
                auto_correctable=True
            ))
        
        return drift
    
    def _auto_fix_drift(self, config_file_path: str, drift: List[DriftDetection]):
        """Automatically fix detected drift"""
        logger.info(f"Auto-fixing {len(drift)} drift issues")
        
        # Use validator to perform repairs
        _, repairs = self.validator.validate_and_repair(config_file_path, auto_repair=True)
        
        if repairs:
            logger.info(f"Applied {len(repairs)} automatic fixes")
        
    def _save_config(self, config_file_path: str, config: Dict):
        """Save updated configuration"""
        with open(config_file_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, indent=2, sort_keys=False)
    
    def get_drift_history(self, hours: int = 24) -> List[DriftDetection]:
        """Get drift detection history for the last N hours"""
        cutoff = datetime.now() - timedelta(hours=hours)
        return [d for d in self.drift_history if d.timestamp > cutoff]
    
    def get_monitoring_summary(self) -> Dict[str, Any]:
        """Get monitoring summary statistics"""
        recent_drift = self.get_drift_history(24)
        
        return {
            'total_drift_events_24h': len(recent_drift),
            'critical_drift_24h': len([d for d in recent_drift if d.severity == 'critical']),
            'warning_drift_24h': len([d for d in recent_drift if d.severity == 'warning']),
            'auto_correctable_24h': len([d for d in recent_drift if d.auto_correctable]),
            'nodes_with_drift_24h': len(set(d.node for d in recent_drift)),
            'common_drift_types': self._get_common_drift_types(recent_drift)
        }
    
    def _get_common_drift_types(self, drift_list: List[DriftDetection]) -> Dict[str, int]:
        """Get common drift types and their counts"""
        drift_counts = {}
        for drift in drift_list:
            drift_counts[drift.drift_type] = drift_counts.get(drift.drift_type, 0) + 1
        return drift_counts

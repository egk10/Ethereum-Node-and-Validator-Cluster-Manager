"""
Config Validator - Validates and repairs existing configurations

This module checks existing configurations against live node states,
identifies issues, and provides auto-repair capabilities.
"""

import logging
import yaml
from typing import Dict, List, Tuple, Any, Optional
from dataclasses import dataclass
import subprocess

from .auto_discovery import AutoConfigDiscovery
from .smart_generator import SmartConfigGenerator

logger = logging.getLogger(__name__)

@dataclass
class ValidationIssue:
    """Represents a configuration validation issue"""
    node: str
    issue_type: str
    severity: str  # 'critical', 'warning', 'info'
    description: str
    current_value: Any
    suggested_value: Any
    auto_fixable: bool
    fix_command: Optional[str] = None

@dataclass  
class RepairAction:
    """Represents a configuration repair action that was performed"""
    node: str
    action_type: str
    description: str
    old_config: Dict
    new_config: Dict
    success: bool
    error_message: Optional[str] = None

class ConfigValidator:
    """Validates configuration files against live node states"""
    
    def __init__(self):
        self.discovery = AutoConfigDiscovery()
        self.generator = SmartConfigGenerator()
        
    def validate_and_repair(self, config_file_path: str, auto_repair: bool = False) -> Tuple[List[ValidationIssue], List[RepairAction]]:
        """
        Validate configuration file and optionally perform auto-repairs
        
        Args:
            config_file_path: Path to configuration YAML file
            auto_repair: Whether to automatically fix issues
            
        Returns:
            Tuple of (issues_found, repairs_performed)
        """
        logger.info(f"Validating configuration: {config_file_path}")
        
        # Load current configuration
        with open(config_file_path, 'r') as f:
            config = yaml.safe_load(f)
            
        issues = []
        repairs = []
        
        # Validate each node
        for node_config in config.get('nodes', []):
            node_issues, node_repairs = self._validate_node(node_config, auto_repair)
            issues.extend(node_issues)
            repairs.extend(node_repairs)
        
        # Save updated configuration if repairs were made
        if repairs and auto_repair:
            self._save_config(config_file_path, config)
            logger.info(f"Configuration updated with {len(repairs)} repairs")
        
        return issues, repairs
    
    def _validate_node(self, node_config: Dict, auto_repair: bool = False) -> Tuple[List[ValidationIssue], List[RepairAction]]:
        """Validate a single node configuration"""
        node_name = node_config.get('name', 'unknown')
        logger.info(f"Validating node: {node_name}")
        
        issues = []
        repairs = []
        
        # Skip disabled nodes
        if 'disabled' in node_config.get('stack', []) or node_config.get('ethereum_clients_enabled') == False:
            logger.info(f"Skipping disabled node: {node_name}")
            return issues, repairs
            
        try:
            # Discover current state
            discovery_data = self.discovery.discover_node_config(
                node_name,
                node_config.get('ssh_user', 'root'),
                node_config.get('tailscale_domain', f'{node_name}.ts.net')
            )
            
            # Check for discovery errors
            if discovery_data.get('errors'):
                for error in discovery_data['errors']:
                    issues.append(ValidationIssue(
                        node=node_name,
                        issue_type='discovery_error',
                        severity='warning',
                        description=f'Discovery error: {error}',
                        current_value=None,
                        suggested_value=None,
                        auto_fixable=False
                    ))
            
            # Validate beacon API port
            port_issue, port_repair = self._validate_beacon_api_port(node_config, discovery_data, auto_repair)
            if port_issue:
                issues.append(port_issue)
            if port_repair:
                repairs.append(port_repair)
            
            # Validate network configurations
            network_issues, network_repairs = self._validate_networks(node_config, discovery_data, auto_repair)
            issues.extend(network_issues)
            repairs.extend(network_repairs)
            
            # Validate stack configuration
            stack_issue, stack_repair = self._validate_stack(node_config, discovery_data, auto_repair)
            if stack_issue:
                issues.append(stack_issue)
            if stack_repair:
                repairs.append(stack_repair)
                
            # Validate docker paths
            path_issue, path_repair = self._validate_docker_paths(node_config, discovery_data, auto_repair)
            if path_issue:
                issues.append(path_issue)
            if path_repair:
                repairs.append(path_repair)
                
        except Exception as e:
            logger.error(f"Validation failed for {node_name}: {e}")
            issues.append(ValidationIssue(
                node=node_name,
                issue_type='validation_error',
                severity='critical',
                description=f'Validation failed: {str(e)}',
                current_value=None,
                suggested_value=None,
                auto_fixable=False
            ))
        
        return issues, repairs
    
    def _validate_beacon_api_port(self, node_config: Dict, discovery_data: Dict, auto_repair: bool) -> Tuple[Optional[ValidationIssue], Optional[RepairAction]]:
        """Validate beacon API port configuration"""
        node_name = node_config.get('name')
        current_port = node_config.get('beacon_api_port')
        discovered_ports = discovery_data.get('api_ports', {})
        
        if not discovered_ports or not current_port:
            return None, None
            
        # For single-network nodes
        if 'networks' not in node_config:
            actual_port = list(discovered_ports.values())[0]
            if current_port != actual_port:
                issue = ValidationIssue(
                    node=node_name,
                    issue_type='wrong_beacon_port',
                    severity='critical',
                    description=f'Beacon API port mismatch: configured {current_port}, but {actual_port} is responding',
                    current_value=current_port,
                    suggested_value=actual_port,
                    auto_fixable=True
                )
                
                repair = None
                if auto_repair:
                    old_config = node_config.copy()
                    node_config['beacon_api_port'] = actual_port
                    repair = RepairAction(
                        node=node_name,
                        action_type='update_beacon_port',
                        description=f'Updated beacon API port from {current_port} to {actual_port}',
                        old_config={'beacon_api_port': current_port},
                        new_config={'beacon_api_port': actual_port},
                        success=True
                    )
                    
                return issue, repair
        
        return None, None
    
    def _validate_networks(self, node_config: Dict, discovery_data: Dict, auto_repair: bool) -> Tuple[List[ValidationIssue], List[RepairAction]]:
        """Validate network configurations"""
        issues = []
        repairs = []
        node_name = node_config.get('name')
        
        configured_networks = node_config.get('networks', {})
        active_networks = discovery_data.get('active_networks', {})
        
        if not configured_networks:
            return issues, repairs
            
        # Check for inactive networks
        for network_key, network_config in configured_networks.items():
            if network_key not in active_networks:
                issues.append(ValidationIssue(
                    node=node_name,
                    issue_type='inactive_network',
                    severity='warning',
                    description=f'Network "{network_key}" is configured but not running',
                    current_value=network_key,
                    suggested_value='remove',
                    auto_fixable=True
                ))
                
                if auto_repair:
                    old_config = configured_networks.copy()
                    del node_config['networks'][network_key]
                    repairs.append(RepairAction(
                        node=node_name,
                        action_type='remove_inactive_network',
                        description=f'Removed inactive network: {network_key}',
                        old_config={'networks': old_config},
                        new_config={'networks': node_config.get('networks', {})},
                        success=True
                    ))
        
        # Check for wrong ports in networks
        discovered_ports = discovery_data.get('api_ports', {})
        for network_key, network_config in configured_networks.items():
            if network_key in discovered_ports:
                configured_port = network_config.get('beacon_api_port')
                actual_port = discovered_ports[network_key]
                
                if configured_port and configured_port != actual_port:
                    issues.append(ValidationIssue(
                        node=node_name,
                        issue_type='wrong_network_port',
                        severity='critical',
                        description=f'Network "{network_key}" port mismatch: configured {configured_port}, actual {actual_port}',
                        current_value=configured_port,
                        suggested_value=actual_port,
                        auto_fixable=True
                    ))
                    
                    if auto_repair:
                        old_port = configured_port
                        node_config['networks'][network_key]['beacon_api_port'] = actual_port
                        repairs.append(RepairAction(
                            node=node_name,
                            action_type='update_network_port',
                            description=f'Updated {network_key} port from {old_port} to {actual_port}',
                            old_config={'port': old_port},
                            new_config={'port': actual_port},
                            success=True
                        ))
        
        return issues, repairs
    
    def _validate_stack(self, node_config: Dict, discovery_data: Dict, auto_repair: bool) -> Tuple[Optional[ValidationIssue], Optional[RepairAction]]:
        """Validate stack configuration"""
        node_name = node_config.get('name')
        configured_stacks = set(node_config.get('stack', []))
        detected_stacks = set(discovery_data.get('detected_stacks', []))
        
        if configured_stacks != detected_stacks:
            issue = ValidationIssue(
                node=node_name,
                issue_type='stack_mismatch',
                severity='warning',
                description=f'Stack mismatch: configured {list(configured_stacks)}, detected {list(detected_stacks)}',
                current_value=list(configured_stacks),
                suggested_value=list(detected_stacks),
                auto_fixable=True
            )
            
            repair = None
            if auto_repair and detected_stacks:
                old_stacks = list(configured_stacks)
                node_config['stack'] = list(detected_stacks)
                repair = RepairAction(
                    node=node_name,
                    action_type='update_stack',
                    description=f'Updated stack from {old_stacks} to {list(detected_stacks)}',
                    old_config={'stack': old_stacks},
                    new_config={'stack': list(detected_stacks)},
                    success=True
                )
            
            return issue, repair
            
        return None, None
    
    def _validate_docker_paths(self, node_config: Dict, discovery_data: Dict, auto_repair: bool) -> Tuple[Optional[ValidationIssue], Optional[RepairAction]]:
        """Validate docker path configuration"""
        node_name = node_config.get('name')
        configured_path = node_config.get('eth_docker_path')
        discovered_paths = discovery_data.get('docker_paths', [])
        
        if configured_path and discovered_paths:
            if configured_path not in discovered_paths:
                # Suggest the first discovered path
                suggested_path = discovered_paths[0]
                
                issue = ValidationIssue(
                    node=node_name,
                    issue_type='wrong_docker_path',
                    severity='warning',
                    description=f'Docker path not found: {configured_path}, found: {discovered_paths}',
                    current_value=configured_path,
                    suggested_value=suggested_path,
                    auto_fixable=True
                )
                
                repair = None
                if auto_repair:
                    old_path = configured_path
                    node_config['eth_docker_path'] = suggested_path
                    repair = RepairAction(
                        node=node_name,
                        action_type='update_docker_path',
                        description=f'Updated docker path from {old_path} to {suggested_path}',
                        old_config={'eth_docker_path': old_path},
                        new_config={'eth_docker_path': suggested_path},
                        success=True
                    )
                
                return issue, repair
        
        return None, None
    
    def _save_config(self, config_file_path: str, config: Dict):
        """Save updated configuration to file"""
        try:
            with open(config_file_path, 'w') as f:
                yaml.dump(config, f, default_flow_style=False, indent=2, sort_keys=False)
            logger.info(f"Configuration saved: {config_file_path}")
        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")
            raise
    
    def validate_single_node(self, node_name: str, config_file_path: str) -> List[ValidationIssue]:
        """Validate a single node without making repairs"""
        with open(config_file_path, 'r') as f:
            config = yaml.safe_load(f)
            
        for node_config in config.get('nodes', []):
            if node_config.get('name') == node_name:
                issues, _ = self._validate_node(node_config, auto_repair=False)
                return issues
        
        return [ValidationIssue(
            node=node_name,
            issue_type='node_not_found',
            severity='critical',
            description=f'Node "{node_name}" not found in configuration',
            current_value=None,
            suggested_value=None,
            auto_fixable=False
        )]
    
    def get_validation_summary(self, issues: List[ValidationIssue]) -> Dict[str, Any]:
        """Generate a summary of validation results"""
        summary = {
            'total_issues': len(issues),
            'critical': len([i for i in issues if i.severity == 'critical']),
            'warnings': len([i for i in issues if i.severity == 'warning']),
            'info': len([i for i in issues if i.severity == 'info']),
            'auto_fixable': len([i for i in issues if i.auto_fixable]),
            'by_node': {},
            'by_type': {}
        }
        
        # Group by node
        for issue in issues:
            if issue.node not in summary['by_node']:
                summary['by_node'][issue.node] = []
            summary['by_node'][issue.node].append(issue)
        
        # Group by issue type
        for issue in issues:
            if issue.issue_type not in summary['by_type']:
                summary['by_type'][issue.issue_type] = []
            summary['by_type'][issue.issue_type].append(issue)
        
        return summary

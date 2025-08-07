"""
Configuration Automation System for Ethereum Validator Cluster Manager

This module provides intelligent configuration discovery, validation, and auto-repair
capabilities to minimize manual configuration errors and maintenance overhead.

Architecture:
- AutoConfigDiscovery: Discovers node configuration automatically
- SmartConfigGenerator: Generates optimized configurations
- ConfigValidator: Validates and repairs existing configurations
- ConfigMonitor: Monitors for configuration drift
- ConfigTemplates: Manages configuration templates
"""

import logging
import subprocess
import json
import re
import yaml
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class DiscoveryResult:
    """Result of node configuration discovery"""
    node_name: str
    ssh_info: Dict[str, str]
    docker_paths: List[str]
    active_networks: Dict[str, Dict]
    api_ports: Dict[str, int]
    detected_stacks: List[str]
    containers: List[Dict]
    client_info: Dict[str, Dict]
    errors: List[str]

@dataclass 
class ValidationIssue:
    """Configuration validation issue"""
    node: str
    issue_type: str
    severity: str  # critical, warning, info
    description: str
    current_value: Any
    suggested_value: Any
    auto_fixable: bool

@dataclass
class RepairAction:
    """Configuration repair action"""
    node: str
    action_type: str
    description: str
    old_config: Dict
    new_config: Dict
    success: bool
    error_message: Optional[str] = None

class ConfigAutomationSystem:
    """Main orchestrator for configuration automation"""
    
    def __init__(self, config_file_path: str):
        self.config_file_path = config_file_path
        self.discovery = AutoConfigDiscovery()
        self.generator = SmartConfigGenerator()
        self.validator = ConfigValidator()
        self.monitor = ConfigMonitor()
        self.templates = ConfigTemplates()
        
    def auto_discover_node(self, node_name: str, ssh_user: str, tailscale_domain: str) -> DiscoveryResult:
        """Discover complete configuration for a node"""
        return self.discovery.discover_node_config(node_name, ssh_user, tailscale_domain)
        
    def validate_current_config(self, auto_repair: bool = False) -> Tuple[List[ValidationIssue], List[RepairAction]]:
        """Validate current configuration and optionally auto-repair"""
        return self.validator.validate_and_repair(self.config_file_path, auto_repair)
        
    def sync_all_nodes(self) -> Dict[str, DiscoveryResult]:
        """Sync configuration for all nodes"""
        return self.monitor.sync_all_nodes(self.config_file_path)
        
    def create_node_from_template(self, template_name: str, node_name: str, **kwargs) -> Dict:
        """Create new node configuration from template"""
        return self.templates.create_from_template(template_name, node_name, **kwargs)

# Import all submodules
from .auto_discovery import AutoConfigDiscovery
from .smart_generator import SmartConfigGenerator  
from .config_validator import ConfigValidator
from .config_monitor import ConfigMonitor
from .config_templates import ConfigTemplates

"""
Handles loading configuration from config.yaml and providing
helper functions to access node configurations.
"""
import yaml
import os
from pathlib import Path

def get_config_path():
    """
    Find config.yaml in multiple locations with priority:
    1. Current working directory (where user runs the command)
    2. PROJECT_ROOT environment variable (set by eth-manager wrapper)
    3. Parent directory of eth_validators module (project root)
    4. eth_validators directory itself (for backward compatibility)
    """
    # First check current working directory (where user runs the command)
    current_dir_config = Path.cwd() / 'config.yaml'
    if current_dir_config.exists():
        return current_dir_config
    
    # Check if PROJECT_ROOT environment variable is set (from eth-manager wrapper)
    project_root = os.environ.get('PROJECT_ROOT')
    if project_root:
        project_root_config = Path(project_root) / 'config.yaml'
        if project_root_config.exists():
            return project_root_config
    
    # Check parent directory of eth_validators (typical project structure)
    parent_config = Path(__file__).parent.parent / 'config.yaml'
    if parent_config.exists():
        return parent_config
    
    # Fallback to eth_validators directory itself (for backward compatibility)
    default_config = Path(__file__).parent / 'config.yaml'
    return default_config

def get_all_node_configs():
    """Loads and returns all node configurations from config.yaml."""
    try:
        with open(get_config_path(), 'r') as f:
            config = yaml.safe_load(f)
        return config.get('nodes', [])
    except (FileNotFoundError, yaml.YAMLError):
        return []

def get_node_config(name_or_domain):
    """
    Finds and returns the configuration for a single node by its name
    or tailscale_domain.
    """
    all_nodes = get_all_node_configs()
    for node_cfg in all_nodes:
        if node_cfg.get('name') == name_or_domain or node_cfg.get('tailscale_domain') == name_or_domain:
            return node_cfg
    return None

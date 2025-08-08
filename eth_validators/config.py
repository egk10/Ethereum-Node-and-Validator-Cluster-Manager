"""
Handles loading configuration from config.yaml and providing
helper functions to access node configurations.
"""
import yaml
from pathlib import Path

def get_config_path():
    """Find config.yaml in current directory first, then in eth_validators directory"""
    # First check current working directory (where user runs the command)
    current_dir_config = Path.cwd() / 'config.yaml'
    if current_dir_config.exists():
        return current_dir_config
    
    # Fallback to the default location (for backward compatibility)
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

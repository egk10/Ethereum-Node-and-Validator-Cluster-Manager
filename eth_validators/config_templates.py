"""
Config Templates - Template management for configuration generation

This module provides template management capabilities for generating
consistent node configurations across different setups and environments.
"""

import logging
import yaml
import os
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class ConfigTemplate:
    """Represents a configuration template"""
    name: str
    description: str
    template_data: Dict[str, Any]
    supported_stacks: List[str]
    supported_networks: List[str]
    version: str
    created: datetime
    updated: datetime

class ConfigTemplateManager:
    """Manages configuration templates"""
    
    def __init__(self, templates_dir: str = "config_templates"):
        self.templates_dir = templates_dir
        self.templates = {}
        self._ensure_templates_dir()
        self._load_builtin_templates()
    
    def create_template(self, name: str, description: str, base_config: Dict[str, Any], 
                       supported_stacks: List[str], supported_networks: List[str]) -> ConfigTemplate:
        """Create a new template from configuration data"""
        logger.info(f"Creating new template: {name}")
        
        template = ConfigTemplate(
            name=name,
            description=description,
            template_data=base_config,
            supported_stacks=supported_stacks,
            supported_networks=supported_networks,
            version="1.0",
            created=datetime.now(),
            updated=datetime.now()
        )
        
        self.templates[name] = template
        self._save_template(template)
        
        return template
    
    def generate_config_from_template(self, template_name: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        """Generate configuration from template with variables"""
        logger.info(f"Generating configuration from template: {template_name}")
        
        if template_name not in self.templates:
            raise ValueError(f"Template {template_name} not found")
        
        template = self.templates[template_name]
        config = self._deep_copy_dict(template.template_data)
        
        # Replace variables in configuration
        config = self._replace_template_variables(config, variables)
        
        return config
    
    def get_default_template_for_stack(self, stack: str) -> Optional[str]:
        """Get the default template for a given stack"""
        for template_name, template in self.templates.items():
            if stack in template.supported_stacks:
                return template_name
        return None
    
    def generate_node_config(self, node_name: str, template_name: str, 
                           stack: List[str], networks: Dict[str, Any] = None) -> Dict[str, Any]:
        """Generate complete node configuration"""
        logger.info(f"Generating node config for {node_name} using template {template_name}")
        
        variables = {
            'node_name': node_name,
            'stack': stack,
            'networks': networks or {},
            'timestamp': datetime.now().isoformat(),
        }
        
        # Generate base config from template
        config = self.generate_config_from_template(template_name, variables)
        
        # Add node-specific customizations
        if networks:
            config = self._add_network_configurations(config, networks)
        
        return config
    
    def list_templates(self) -> Dict[str, ConfigTemplate]:
        """List all available templates"""
        return self.templates
    
    def get_template_by_stack(self, stack: str) -> List[ConfigTemplate]:
        """Get all templates that support a specific stack"""
        return [template for template in self.templates.values() 
                if stack in template.supported_stacks]
    
    def _ensure_templates_dir(self):
        """Ensure templates directory exists"""
        if not os.path.exists(self.templates_dir):
            os.makedirs(self.templates_dir)
    
    def _load_builtin_templates(self):
        """Load built-in configuration templates"""
        
        # ETH-Docker basic template
        eth_docker_template = ConfigTemplate(
            name="eth_docker_basic",
            description="Basic ETH-Docker setup for mainnet validation",
            template_data={
                "name": "{{node_name}}",
                "tailscale_domain": "{{node_name}}.ts.net",
                "ssh_user": "root",
                "ethereum_clients_enabled": True,
                "execution_client": "erigon",
                "consensus_client": "caplin",
                "stack": ["eth-docker"],
                "beacon_api_port": 5052,
                "metrics": {
                    "prometheus_enabled": True,
                    "prometheus_port": 9090,
                    "grafana_enabled": True,
                    "grafana_port": 3000
                }
            },
            supported_stacks=["eth-docker"],
            supported_networks=["mainnet"],
            version="1.0",
            created=datetime.now(),
            updated=datetime.now()
        )
        
        # RocketPool template
        rocketpool_template = ConfigTemplate(
            name="rocketpool",
            description="RocketPool node configuration",
            template_data={
                "name": "{{node_name}}",
                "tailscale_domain": "{{node_name}}.ts.net",
                "ssh_user": "root",
                "ethereum_clients_enabled": True,
                "execution_client": "geth",
                "consensus_client": "lighthouse",
                "stack": ["rocketpool"],
                "beacon_api_port": 5052,
                "metrics": {
                    "prometheus_enabled": True,
                    "prometheus_port": 9090,
                    "grafana_enabled": True,
                    "grafana_port": 3000
                },
                "rocketpool": {
                    "node_fee": "{{rocketpool_fee|default:15}}",
                    "node_timezone": "UTC"
                }
            },
            supported_stacks=["rocketpool"],
            supported_networks=["mainnet"],
            version="1.0",
            created=datetime.now(),
            updated=datetime.now()
        )
        
        # NodeSet Hyperdrive template
        nodeset_template = ConfigTemplate(
            name="nodeset_hyperdrive",
            description="NodeSet Hyperdrive configuration",
            template_data={
                "name": "{{node_name}}",
                "tailscale_domain": "{{node_name}}.ts.net",
                "ssh_user": "root",
                "ethereum_clients_enabled": True,
                "execution_client": "geth",
                "consensus_client": "lighthouse",
                "stack": ["nodeset", "hyperdrive"],
                "beacon_api_port": 5052,
                "metrics": {
                    "prometheus_enabled": True,
                    "prometheus_port": 9090,
                    "grafana_enabled": True,
                    "grafana_port": 3000
                }
            },
            supported_stacks=["nodeset", "hyperdrive"],
            supported_networks=["mainnet"],
            version="1.0",
            created=datetime.now(),
            updated=datetime.now()
        )
        
        # Lido CSM template
        lido_template = ConfigTemplate(
            name="lido_csm",
            description="Lido Community Staking Module configuration",
            template_data={
                "name": "{{node_name}}",
                "tailscale_domain": "{{node_name}}.ts.net",
                "ssh_user": "root",
                "ethereum_clients_enabled": True,
                "execution_client": "geth",
                "consensus_client": "lighthouse",
                "stack": ["lido-csm"],
                "beacon_api_port": 5052,
                "metrics": {
                    "prometheus_enabled": True,
                    "prometheus_port": 9090,
                    "grafana_enabled": True,
                    "grafana_port": 3000
                }
            },
            supported_stacks=["lido-csm"],
            supported_networks=["mainnet"],
            version="1.0",
            created=datetime.now(),
            updated=datetime.now()
        )
        
        # Multi-network template
        multi_network_template = ConfigTemplate(
            name="multi_network",
            description="Multi-network node supporting mainnet and testnet",
            template_data={
                "name": "{{node_name}}",
                "tailscale_domain": "{{node_name}}.ts.net",
                "ssh_user": "root",
                "ethereum_clients_enabled": True,
                "execution_client": "erigon",
                "consensus_client": "caplin",
                "stack": ["eth-docker"],
                "beacon_api_port": 5052,
                "networks": {
                    "mainnet": {
                        "enabled": True,
                        "beacon_api_port": 5052
                    },
                    "hoodi": {
                        "enabled": True,
                        "beacon_api_port": 5053
                    }
                },
                "metrics": {
                    "prometheus_enabled": True,
                    "prometheus_port": 9090,
                    "grafana_enabled": True,
                    "grafana_port": 3000
                }
            },
            supported_stacks=["eth-docker"],
            supported_networks=["mainnet", "hoodi"],
            version="1.0",
            created=datetime.now(),
            updated=datetime.now()
        )
        
        # Store templates
        self.templates = {
            "eth_docker_basic": eth_docker_template,
            "rocketpool": rocketpool_template,
            "nodeset_hyperdrive": nodeset_template,
            "lido_csm": lido_template,
            "multi_network": multi_network_template
        }
        
        logger.info(f"Loaded {len(self.templates)} built-in templates")
    
    def _replace_template_variables(self, obj: Any, variables: Dict[str, Any]) -> Any:
        """Recursively replace template variables in configuration"""
        if isinstance(obj, dict):
            result = {}
            for key, value in obj.items():
                new_key = self._replace_string_variables(key, variables)
                new_value = self._replace_template_variables(value, variables)
                result[new_key] = new_value
            return result
        elif isinstance(obj, list):
            return [self._replace_template_variables(item, variables) for item in obj]
        elif isinstance(obj, str):
            return self._replace_string_variables(obj, variables)
        else:
            return obj
    
    def _replace_string_variables(self, text: str, variables: Dict[str, Any]) -> str:
        """Replace template variables in a string"""
        if not isinstance(text, str):
            return text
        
        result = text
        
        # Replace {{variable}} patterns
        for var_name, var_value in variables.items():
            pattern = f"{{{{{var_name}}}}}"
            if pattern in result:
                result = result.replace(pattern, str(var_value))
        
        # Handle default values {{variable|default:value}}
        import re
        default_pattern = r'\{\{(\w+)\|default:(.*?)\}\}'
        matches = re.findall(default_pattern, result)
        
        for var_name, default_value in matches:
            pattern = f"{{{{{var_name}|default:{default_value}}}}}"
            if var_name in variables:
                result = result.replace(pattern, str(variables[var_name]))
            else:
                result = result.replace(pattern, default_value)
        
        return result
    
    def _add_network_configurations(self, config: Dict[str, Any], networks: Dict[str, Any]) -> Dict[str, Any]:
        """Add network-specific configurations"""
        if networks and len(networks) > 1:
            config["networks"] = {}
            
            for network_name, network_config in networks.items():
                config["networks"][network_name] = {
                    "enabled": network_config.get("enabled", True),
                    "beacon_api_port": network_config.get("beacon_api_port", 5052)
                }
        
        return config
    
    def _deep_copy_dict(self, obj: Any) -> Any:
        """Deep copy a dictionary or other object"""
        if isinstance(obj, dict):
            return {key: self._deep_copy_dict(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [self._deep_copy_dict(item) for item in obj]
        else:
            return obj
    
    def _save_template(self, template: ConfigTemplate):
        """Save template to disk"""
        template_file = os.path.join(self.templates_dir, f"{template.name}.yaml")
        
        template_data = {
            "name": template.name,
            "description": template.description,
            "supported_stacks": template.supported_stacks,
            "supported_networks": template.supported_networks,
            "version": template.version,
            "created": template.created.isoformat(),
            "updated": template.updated.isoformat(),
            "template": template.template_data
        }
        
        with open(template_file, 'w') as f:
            yaml.dump(template_data, f, default_flow_style=False, indent=2)
    
    def export_template(self, template_name: str, output_file: str):
        """Export template to file"""
        if template_name not in self.templates:
            raise ValueError(f"Template {template_name} not found")
        
        template = self.templates[template_name]
        self._save_template_to_file(template, output_file)
        
        logger.info(f"Template {template_name} exported to {output_file}")
    
    def import_template(self, template_file: str) -> ConfigTemplate:
        """Import template from file"""
        logger.info(f"Importing template from {template_file}")
        
        with open(template_file, 'r') as f:
            template_data = yaml.safe_load(f)
        
        template = ConfigTemplate(
            name=template_data["name"],
            description=template_data["description"],
            template_data=template_data["template"],
            supported_stacks=template_data["supported_stacks"],
            supported_networks=template_data["supported_networks"],
            version=template_data.get("version", "1.0"),
            created=datetime.fromisoformat(template_data["created"]),
            updated=datetime.fromisoformat(template_data["updated"])
        )
        
        self.templates[template.name] = template
        
        return template
    
    def _save_template_to_file(self, template: ConfigTemplate, output_file: str):
        """Save template to specific file"""
        template_data = {
            "name": template.name,
            "description": template.description,
            "supported_stacks": template.supported_stacks,
            "supported_networks": template.supported_networks,
            "version": template.version,
            "created": template.created.isoformat(),
            "updated": template.updated.isoformat(),
            "template": template.template_data
        }
        
        with open(output_file, 'w') as f:
            yaml.dump(template_data, f, default_flow_style=False, indent=2)
    
    def get_template_summary(self) -> Dict[str, Any]:
        """Get summary of all templates"""
        return {
            "total_templates": len(self.templates),
            "templates_by_stack": self._group_templates_by_stack(),
            "templates_by_network": self._group_templates_by_network(),
            "template_names": list(self.templates.keys())
        }
    
    def _group_templates_by_stack(self) -> Dict[str, List[str]]:
        """Group templates by supported stacks"""
        stack_groups = {}
        
        for template_name, template in self.templates.items():
            for stack in template.supported_stacks:
                if stack not in stack_groups:
                    stack_groups[stack] = []
                stack_groups[stack].append(template_name)
        
        return stack_groups
    
    def _group_templates_by_network(self) -> Dict[str, List[str]]:
        """Group templates by supported networks"""
        network_groups = {}
        
        for template_name, template in self.templates.items():
            for network in template.supported_networks:
                if network not in network_groups:
                    network_groups[network] = []
                network_groups[network].append(template_name)
        
        return network_groups
    
    def validate_template_variables(self, template_name: str, variables: Dict[str, Any]) -> List[str]:
        """Validate that all required template variables are provided"""
        if template_name not in self.templates:
            return [f"Template {template_name} not found"]
        
        template = self.templates[template_name]
        template_str = yaml.dump(template.template_data)
        
        # Find all template variables
        import re
        variable_pattern = r'\{\{(\w+)(?:\|default:.*?)?\}\}'
        required_vars = set(re.findall(variable_pattern, template_str))
        
        # Check for missing variables
        missing_vars = []
        for var in required_vars:
            if var not in variables:
                # Check if it has a default value
                default_pattern = f"{{{{{var}|default:"
                if default_pattern not in template_str:
                    missing_vars.append(var)
        
        return [f"Missing required variable: {var}" for var in missing_vars]

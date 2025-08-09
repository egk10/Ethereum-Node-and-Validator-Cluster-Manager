"""
Simple Interactive Setup for New Users

This module provides a streamlined onboarding experience where new users
can get started with just a few questions in an interactive prompt.
No complex config files, no manual CSV creation - everything automated.
"""

import logging
import yaml
import click
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

def _run_command(node_cfg, command):
    """Run a command on a node, handling both local and remote execution"""
    import subprocess
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

def _detect_running_stacks(node_cfg):
    """Detect all running stacks/services on a node by checking docker containers"""
    detected_stacks = []
    
    try:
        # Get all running containers
        command = "docker ps --format 'table {{.Names}}\\t{{.Image}}' | tail -n +2"
        result = _run_command(node_cfg, command)
        
        if result.returncode != 0 or not result.stdout.strip():
            return ["unknown"]
        
        containers = result.stdout.strip().split('\n')
        container_info = []
        
        for container_line in containers:
            # Handle both tab and multiple space separations
            if '\t' in container_line:
                parts = container_line.split('\t', 1)
            else:
                # Split on multiple spaces (common with docker ps output)
                parts = [x for x in container_line.split() if x]
                if len(parts) >= 2:
                    # Take first part as name, join rest as image
                    parts = [parts[0], ' '.join(parts[1:])]
                else:
                    continue
            
            if len(parts) >= 2:
                name, image = parts[0].strip(), parts[1].strip()
                container_info.append({'name': name, 'image': image})
        
        # Detect different stacks based on container patterns
        stack_indicators = {
            'charon': ['charon', 'obolnetwork/charon'],
            'rocketpool': ['rocketpool', 'rocket-pool', 'rp_', 'rp-'],
            'hyperdrive': ['hyperdrive', 'nodeset'],
            'ssv': ['ssv', 'bloxstaking'],
            'lido-csm': ['lido', 'csm'],
            'stakewise': ['stakewise'],
            'obol': ['charon', 'obolnetwork'],
            'eth-docker': ['eth-docker', 'ethereum/client-go', 'sigp/lighthouse', 'consensys/teku', 'status-im/nimbus-eth2', 'chainsafe/lodestar', 'prysmaticlabs/prysm-beacon-chain']
        }
        
        # Check for each stack
        for stack, indicators in stack_indicators.items():
            for container in container_info:
                name_lower = container['name'].lower()
                image_lower = container['image'].lower()
                
                for indicator in indicators:
                    if indicator.lower() in name_lower or indicator.lower() in image_lower:
                        if stack not in detected_stacks:
                            detected_stacks.append(stack)
                        break
        
        # Clean up duplicates: charon detection means obol
        if 'charon' in detected_stacks and 'obol' not in detected_stacks:
            detected_stacks.append('obol')
        if 'obol' in detected_stacks and 'charon' in detected_stacks:
            detected_stacks.remove('charon')  # Keep obol, remove charon duplicate
        
        # Final stack list
        if not detected_stacks:
            detected_stacks = ["unknown"]
        
        return detected_stacks
        
    except Exception as e:
        return ["error"]

class SimpleSetupWizard:
    """Interactive setup wizard for new users"""
    
    def __init__(self):
        self.config = {
            'nodes': [],
            'networks': ['mainnet'],
            'monitoring': {
                'enabled': True,
                'auto_discovery': True
            }
        }
        self.base_path = Path.cwd()
    
    def run_interactive_setup(self) -> Dict:
        """
        Run interactive setup wizard
        
        Returns:
            Complete configuration dictionary
        """
        click.echo("🚀 Welcome to Ethereum Validator Cluster Manager!")
        click.echo("=" * 50)
        click.echo("This wizard will set up everything you need in just a few minutes.\n")
        
        # Step 1: Basic cluster info
        self._setup_basic_info()
        
        # Step 2: Add nodes
        self._setup_nodes()
        
        # Step 3: Configure monitoring
        self._setup_monitoring()
        
        # Step 4: Generate files
        self._generate_configuration_files()
        
        return self.config
    
    def _setup_basic_info(self):
        """Setup basic cluster information"""
        click.echo("📋 Step 1: Basic Information")
        click.echo("-" * 30)
        
        # Cluster name
        cluster_name = click.prompt(
            "What's your cluster name? (e.g., 'my-validators')",
            default="ethereum-validators"
        )
        self.config['cluster_name'] = cluster_name
        
        # Network
        network = click.prompt(
            "Which network? (mainnet/holesky/sepolia)",
            default="mainnet",
            type=click.Choice(['mainnet', 'holesky', 'sepolia'])
        )
        self.config['networks'] = [network]
        
        click.echo(f"✅ Cluster: {cluster_name} on {network}\n")
    
    def _setup_nodes(self):
        """Setup node information"""
        click.echo("🖥️  Step 2: Node Setup")
        click.echo("-" * 25)
        
        click.echo("Let's add your validator nodes. You can add more later.")
        
        while True:
            node_config = self._add_single_node()
            if node_config:
                self.config['nodes'].append(node_config)
                
                if not click.confirm("Add another node?", default=False):
                    break
            else:
                break
        
        if not self.config['nodes']:
            click.echo("⚠️ No nodes added. You can add them later with 'config discover'")
        else:
            click.echo(f"✅ Added {len(self.config['nodes'])} nodes\n")
    
    def _add_single_node(self) -> Optional[Dict]:
        """Add a single node interactively"""
        click.echo("\n➕ Adding new node:")
        
        # Node name/hostname
        node_name = click.prompt("Node name or hostname (e.g., 'validator1' or 'node.example.com')")
        
        if not node_name.strip():
            return None
        
        node_config = {
            'name': node_name,
            'stack': [],
            'ethereum_clients_enabled': True
        }
        
        # Check if it's local or remote
        is_local = click.confirm(f"Is '{node_name}' running locally on this machine?", default=False)
        
        if is_local:
            node_config['is_local'] = True
            node_config['tailscale_domain'] = 'localhost'
        else:
            # Remote node setup
            domain = click.prompt(
                f"Full domain/IP for '{node_name}' (e.g., 'node1.tailnet.ts.net' or '192.168.1.100')"
            )
            node_config['tailscale_domain'] = domain
            
            ssh_user = click.prompt("SSH username", default="root")
            node_config['ssh_user'] = ssh_user
        
        # Auto-detect stack or ask
        if click.confirm("Auto-detect what's running on this node?", default=True):
            click.echo("🔍 Detecting running services...")
            
            # Try to detect what's actually running
            detected_stacks = _detect_running_stacks(node_config)
            
            if detected_stacks and detected_stacks != ["unknown"] and detected_stacks != ["error"]:
                # Filter to main stacks only (not individual clients)
                main_stacks = []
                for stack in detected_stacks:
                    if stack in ['eth-docker', 'rocketpool', 'obol', 'hyperdrive', 'ssv', 'lido-csm', 'stakewise']:
                        main_stacks.append(stack)
                
                if main_stacks:
                    node_config['stack'] = main_stacks
                    stack_display = ', '.join(main_stacks)
                    click.echo(f"✅ Detected stacks: {stack_display}")
                else:
                    # Default fallback
                    node_config['stack'] = ['eth-docker']
                    click.echo("⚠️  No specific stacks detected, using default: eth-docker")
            else:
                # Detection failed, use default
                node_config['stack'] = ['eth-docker']
                click.echo("⚠️  Auto-detection failed, using default: eth-docker")
                if detected_stacks == ["error"]:
                    click.echo("💡 Note: Ensure SSH access is working for better detection")
        else:
            # Manual stack selection
            available_stacks = [
                'eth-docker', 'rocketpool', 'lido-csm', 
                'obol', 'hyperdrive', 'stakewise'
            ]
            
            click.echo("Available stacks:")
            for i, stack in enumerate(available_stacks, 1):
                click.echo(f"  {i}. {stack}")
            
            stack_choice = click.prompt(
                "Select stack number (or type name)",
                default="1"
            )
            
            try:
                stack_idx = int(stack_choice) - 1
                if 0 <= stack_idx < len(available_stacks):
                    stack_name = available_stacks[stack_idx]
                else:
                    stack_name = stack_choice
            except ValueError:
                stack_name = stack_choice
            
            node_config['stack'] = [stack_name]
        
        click.echo(f"✅ Node '{node_name}' configured")
        return node_config
    
    def _setup_monitoring(self):
        """Setup monitoring configuration"""
        click.echo("📊 Step 3: Monitoring & Discovery")
        click.echo("-" * 35)
        
        # Auto-discovery
        auto_discovery = click.confirm(
            "Enable automatic validator discovery? (finds validators automatically)",
            default=True
        )
        self.config['monitoring']['auto_discovery'] = auto_discovery
        
        if auto_discovery:
            # Discovery frequency
            frequency = click.prompt(
                "How often should validators be discovered? (daily/weekly/hourly)",
                default="daily",
                type=click.Choice(['daily', 'weekly', 'hourly'])
            )
            self.config['monitoring']['discovery_frequency'] = frequency
        
        # Performance monitoring
        performance_monitoring = click.confirm(
            "Enable performance monitoring?",
            default=True
        )
        self.config['monitoring']['performance_enabled'] = performance_monitoring
        
        click.echo("✅ Monitoring configured\n")
    
    def _generate_configuration_files(self):
        """Generate all necessary configuration files"""
        click.echo("📁 Step 4: Generating Configuration")
        click.echo("-" * 40)
        
        # Create config.yaml
        config_path = self.base_path / 'config.yaml'
        with open(config_path, 'w') as f:
            yaml.dump(self.config, f, default_flow_style=False, indent=2)
        click.echo(f"✅ Created: {config_path}")
        
        # Auto-discover validators if enabled
        if self.config['monitoring'].get('auto_discovery', False):
            click.echo("🔍 Running initial validator discovery...")
            self._run_initial_discovery()
        
        click.echo("✅ Setup complete!")
    
    def _run_initial_discovery(self):
        """Run initial validator discovery"""
        try:
            from .validator_auto_discovery import ValidatorAutoDiscovery
            
            discovery = ValidatorAutoDiscovery(str(self.base_path / 'config.yaml'))
            csv_path = discovery.generate_validators_csv('validators.csv')
            
            # Count discovered validators
            import csv
            with open(csv_path, 'r') as f:
                reader = csv.DictReader(f)
                validator_count = sum(1 for row in reader)
            
            if validator_count > 0:
                click.echo(f"🎉 Found {validator_count} validators!")
                click.echo(f"📄 Saved to: {csv_path}")
            else:
                click.echo("⚠️ No validators found yet - they'll be discovered as nodes come online")
                
        except Exception as e:
            click.echo(f"⚠️ Initial discovery failed: {e}")
            click.echo("Don't worry - you can run 'validator discover' later")

def quick_start_new_user() -> str:
    """
    Complete new user onboarding in one command
    
    Returns:
        Path to generated config file
    """
    wizard = SimpleSetupWizard()
    config = wizard.run_interactive_setup()
    
    return str(wizard.base_path / 'config.yaml')

def show_next_steps():
    """Show user what to do after setup"""
    click.echo("\n🎯 You're all set! Here's what you can do next:")
    click.echo("-" * 50)
    
    click.echo("📊 Check your setup:")
    click.echo("   python3 -m eth_validators node list")
    click.echo("   python3 -m eth_validators validator list")
    
    click.echo("\n🔍 Discover validators:")
    click.echo("   python3 -m eth_validators validator discover")
    
    click.echo("\n📈 Monitor performance:")
    click.echo("   python3 -m eth_validators performance summary")
    
    click.echo("\n🧠 AI analysis:")
    click.echo("   python3 -m eth_validators ai health")
    
    click.echo("\n⚡ Automate updates:")
    click.echo("   python3 -m eth_validators validator automate --setup")
    
    click.echo("\n💡 Need help? Run any command with --help")
    click.echo("🚀 Happy validating!")

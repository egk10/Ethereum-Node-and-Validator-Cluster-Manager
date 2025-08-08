import click
import yaml
import subprocess
import time
import csv
import json
from pathlib import Path
from tabulate import tabulate
import re
from datetime import datetime
from . import performance
from .config import get_node_config, get_all_node_configs
from .performance import get_performance_summary
from .node_manager import get_node_status, upgrade_node_docker_clients, get_system_update_status, perform_system_upgrade, get_docker_client_versions
from .ai_analyzer import ValidatorLogAnalyzer
from .validator_sync import ValidatorSyncManager, get_active_validators_only
from .validator_editor import InteractiveValidatorEditor
from .validator_auto_discovery import ValidatorAutoDiscovery, auto_generate_validators_csv
from .simple_setup import SimpleSetupWizard, quick_start_new_user, show_next_steps

CONFIG_PATH = Path(__file__).parent / 'config.yaml'

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

def _get_charon_version(ssh_target, tailscale_domain, node_cfg=None):
    """Get Charon version if it's running on the node"""
    try:
        # First try to get the actual running version by executing charon version
        command = "docker ps --format 'table {{.Names}}' | grep charon | head -1"
        result = _run_command(node_cfg, command) if node_cfg else subprocess.run(f"ssh -o ConnectTimeout=10 -o BatchMode=yes {ssh_target} \"{command}\"", shell=True, capture_output=True, text=True, timeout=15)
        
        if result.returncode == 0 and result.stdout.strip():
            container_name = result.stdout.strip()
            
            # Try to get actual version from the running container
            version_command = f"docker exec {container_name} charon version 2>/dev/null | head -1 | awk '{{print $NF}}' || echo 'exec_failed'"
            version_result = _run_command(node_cfg, version_command) if node_cfg else subprocess.run(f"ssh -o ConnectTimeout=10 -o BatchMode=yes {ssh_target} \"{version_command}\"", shell=True, capture_output=True, text=True, timeout=10)
            
            if version_result.returncode == 0 and version_result.stdout.strip() and version_result.stdout.strip() != "exec_failed":
                version = version_result.stdout.strip()
                # Clean up version string (remove 'v' prefix if present and extract just the version number)
                if version.startswith('v'):
                    version = version[1:]
                
                # Extract just the version number (before any git commit info)
                if '[' in version:
                    version = version.split('[')[0].strip()
                
                return version
            
            # Fallback: get version from image tag
            image_command = "docker ps --format 'table {{.Names}}\\t{{.Image}}' | grep charon | head -1 | awk '{print $2}'"
            image_result = _run_command(node_cfg, image_command) if node_cfg else subprocess.run(f"ssh -o ConnectTimeout=10 -o BatchMode=yes {ssh_target} \"{image_command}\"", shell=True, capture_output=True, text=True, timeout=10)
            
            if image_result.returncode == 0 and image_result.stdout.strip():
                image = image_result.stdout.strip()
                if ':' in image:
                    version = image.split(':')[-1]
                    return version
                else:
                    return "latest"
        
        return "N/A"
    except (subprocess.TimeoutExpired, Exception):
        return "N/A"

def _get_latest_charon_version():
    """Get the latest Charon version from GitHub releases"""
    try:
        import requests
        url = "https://api.github.com/repos/ObolNetwork/charon/releases/latest"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return data.get('tag_name', 'Unknown').lstrip('v')
        return "Unknown"
    except Exception:
        return "Unknown"

def _is_stack_disabled(stack):
    """Check if stack is disabled - supports both string and list format"""
    if isinstance(stack, list):
        return 'disabled' in stack
    else:
        return stack == 'disabled'

def _has_ethereum_clients(node_cfg):
    """
    Check if a node is configured to run Ethereum clients.
    A node is considered to have clients if its stack is not 'disabled'
    and the 'ethereum_clients_enabled' flag is not explicitly set to false.
    """
    if _is_stack_disabled(node_cfg.get('stack', [])):
        return False
    if node_cfg.get('ethereum_clients_enabled') is False:
        return False
    return True

def _is_charon_only_node(node_cfg):
    """
    Check if a node is running only Charon (Obol distributed validator) 
    without traditional execution/consensus clients.
    """
    if not _has_ethereum_clients(node_cfg):
        # Check if Charon is actually running
        ssh_target = f"{node_cfg.get('ssh_user', 'root')}@{node_cfg['tailscale_domain']}"
        charon_version = _get_charon_version(ssh_target, node_cfg['tailscale_domain'], node_cfg)
        return charon_version != "N/A"
    return False

def _get_validator_only_clients(node_cfg):
    """
    For nodes without execution/consensus clients, detect what validator clients are running.
    Returns a dict with validator client info.
    """
    if _has_ethereum_clients(node_cfg):
        return None
    
    ssh_target = f"{node_cfg.get('ssh_user', 'root')}@{node_cfg['tailscale_domain']}"
    validator_clients = []
    
    try:
        # Check for Charon
        charon_version = _get_charon_version(ssh_target, node_cfg['tailscale_domain'], node_cfg)
        if charon_version != "N/A":
            validator_clients.append(f"charon/{charon_version}")
        
        # Check for Lodestar validator
        command = "docker ps --format 'table {{.Names}}\\t{{.Image}}' | grep -E 'lodestar.*validator|lodestar.*latest' | head -1"
        result = _run_command(node_cfg, command)
        
        if result.returncode == 0 and result.stdout.strip():
            # Get Lodestar version
            container_line = result.stdout.strip()
            if 'lodestar' in container_line.lower():
                image_part = container_line.split('\t')[-1] if '\t' in container_line else container_line.split()[-1]
                if ':' in image_part:
                    version = image_part.split(':')[-1]
                    validator_clients.append(f"lodestar/{version}")
                else:
                    validator_clients.append("lodestar/latest")
        
        # Check for Vero validator
        command = "docker ps --format 'table {{.Names}}\\t{{.Image}}' | grep -E 'vero|validator.*vero' | head -1"
        result = _run_command(node_cfg, command)
        
        if result.returncode == 0 and result.stdout.strip():
            container_line = result.stdout.strip()
            if 'vero' in container_line.lower():
                validator_clients.append("vero/local")
        
        return {
            'validator_clients': validator_clients,
            'display_name': ' + '.join(validator_clients) if validator_clients else 'Unknown',
            'has_clients': len(validator_clients) > 0
        }
        
    except Exception:
        return {
            'validator_clients': [],
            'display_name': 'Error',
            'has_clients': False
        }

def _detect_additional_validators(node_cfg):
    """
    For nodes that DO have execution/consensus clients, detect additional validator clients
    like Vero that might not be detected by the main version detection.
    """
    additional_validators = []
    
    try:
        # First check: if the node has "lido-csm" in stack, it likely has Vero validators
        stack = node_cfg.get('stack', [])
        if 'lido-csm' in stack:
            # Verify by checking for actual Vero containers
            command = "docker ps --format 'table {{.Names}}\\t{{.Image}}' | grep -E 'validator.*vero|vero.*validator|eth-docker-validator'"
            result = _run_command(node_cfg, command)
            
            if result.returncode == 0 and result.stdout.strip():
                container_line = result.stdout.strip()
                if 'vero' in container_line.lower():
                    additional_validators.append("vero")
        
        # Additional checks for other validator clients can be added here
        # For example, checking for Stakewise validators, etc.
        
        return additional_validators
        
    except Exception as e:
        # For debugging, let's see what exceptions are happening
        # print(f"DEBUG: Exception in _detect_additional_validators: {e}")
        return []

@click.group()
def cli():
    """🚀 Ethereum Node and Validator Cluster Manager"""
    pass

# AI Smart Performance Group
@cli.group(name='ai')
def ai_group():
    """🧠 AI-powered log analysis and intelligent monitoring tools"""
    pass

# Performance Monitoring Group  
@cli.group(name='performance')
def performance_group():
    """📊 Validator performance metrics and attestation efficiency analysis"""
    pass

# Node Management Group
@cli.group(name='node')
def node_group():
    """🖥️ Live node operations: monitoring, upgrades, and configuration management"""
    pass

# System Administration Group
@cli.group(name='system')
def system_group():
    """⚙️ System updates, maintenance, and infrastructure management"""
    pass

# Configuration Automation Group
@cli.group(name='config')
def config_group():
    """🔧 Automated configuration management, discovery, and synchronization"""
    pass

@system_group.command(name='update')
@click.argument('node', required=False)
@click.option('--all', is_flag=True, help='Check system updates for all configured nodes')
def system_update(node, all):
    """Check for available Ubuntu system updates (apt update && apt list --upgradable)"""
    config = yaml.safe_load(CONFIG_PATH.read_text())
    
    if all and node:
        click.echo("❌ Cannot specify both --all and a node name")
        return
    elif not all and not node:
        click.echo("❌ Must specify either --all or a node name")
        return
    
    if all:
        # Check system updates for all nodes
        click.echo("🔄 Checking system update status for all configured nodes...")
        
        nodes = config.get('nodes', [])
        if not nodes:
            click.echo("❌ No nodes configured")
            return
        
        table_data = []
        nodes_needing_update = []
        
        for i, node_cfg in enumerate(nodes):
            name = node_cfg['name']
            stack = node_cfg.get('stack', ['eth-docker'])
            
            click.echo(f"📡 Checking {name}... ({i+1}/{len(nodes)})", nl=False, err=True)
            
            # Skip disabled nodes but still show them, UNLESS they have validator-only clients
            if _is_stack_disabled(stack):
                # Check if this disabled node still has validator clients (like Charon)
                validator_info = _get_validator_only_clients(node_cfg)
                if not (validator_info and validator_info['has_clients']):
                    # Truly disabled node with no validator clients
                    table_data.append([f"🔴 {name}", "Disabled", "-", "-"])
                    click.echo(" ✓", err=True)
                    continue
                # If we reach here, it's a "disabled" node but has validator clients, so continue processing
            
            try:
                status = get_system_update_status(node_cfg)
                
                # Check if we got valid results
                updates_available = status.get('updates_available', 'Error')
                needs_update = status.get('needs_system_update', False)
                is_local = node_cfg.get('is_local', False)
                reboot_needed = _check_reboot_needed(node_cfg.get('ssh_user', 'root'), node_cfg['tailscale_domain'], is_local)
                
                # Handle different types of updates_available responses
                if isinstance(updates_available, int):
                    update_count = updates_available
                    if needs_update:
                        status_emoji = "🟡"
                        status_text = f"Updates available ({update_count})"
                        nodes_needing_update.append(name)
                    else:
                        status_emoji = "🟢"
                        status_text = "Up to date"
                    
                    table_data.append([
                        f"{status_emoji} {name}",
                        status_text,
                        f"{update_count} packages" if update_count > 0 else "None",
                        reboot_needed
                    ])
                elif isinstance(updates_available, str) and 'apt-check' in updates_available:
                    # Handle apt-check fallback format like "3 (apt-check)"
                    try:
                        update_count = int(updates_available.split()[0])
                        if needs_update:
                            status_emoji = "🟡"
                            status_text = f"Updates available ({update_count})"
                            nodes_needing_update.append(name)
                        else:
                            status_emoji = "🟢"
                            status_text = "Up to date"
                        
                        table_data.append([
                            f"{status_emoji} {name}",
                            status_text,
                            f"{update_count} packages (fallback)" if update_count > 0 else "None",
                            reboot_needed
                        ])
                    except ValueError:
                        table_data.append([f"❌ {name}", "Parse error", updates_available, "❓ Unknown"])
                else:
                    # Handle error cases like "Connection Error", "Timeout", etc.
                    table_data.append([f"❌ {name}", f"Check failed: {updates_available}", "-", "❓ Unknown"])
                
                click.echo(" ✓", err=True)
                
            except Exception as e:
                table_data.append([f"❌ {name}", f"Error: {str(e)[:30]}...", "-", "❓ Unknown"])
                click.echo(f" ❌ Error", err=True)
        
        click.echo("\nRendering system update status table...")
        headers = ['Node', 'Update Status', 'Available Updates', 'Reboot Needed']
        click.echo(tabulate(table_data, headers=headers, tablefmt='fancy_grid'))
        
        if nodes_needing_update:
            click.echo(f"\n⚠️  Nodes needing system updates: {', '.join(nodes_needing_update)}")
            click.echo(f"💡 Use 'system upgrade --all' to upgrade all nodes")
        else:
            click.echo(f"\n✅ All active nodes are up to date!")
        
    else:
        # Check single node
        node_cfg = next(
            (n for n in config['nodes'] if n.get('tailscale_domain') == node or n.get('name') == node),
            None
        )
        if not node_cfg:
            click.echo(f"❌ Node {node} not found")
            return
        
        stack = node_cfg.get('stack', ['eth-docker'])
        if _is_stack_disabled(stack):
            # Check if this disabled node still has validator clients (like Charon)
            validator_info = _get_validator_only_clients(node_cfg)
            if not (validator_info and validator_info['has_clients']):
                click.echo(f"⚪ Node {node} is disabled")
                return
            # If we reach here, it's a "disabled" node but has validator clients, so continue processing
        
        click.echo(f"🔄 Checking system update status for {node_cfg['name']}...")
        
        try:
            status = get_system_update_status(node_cfg)
            
            # Check if we got valid results  
            updates_available = status.get('updates_available', 'Error')
            needs_update = status.get('needs_system_update', False)
            is_local = node_cfg.get('is_local', False)
            reboot_needed = _check_reboot_needed(node_cfg.get('ssh_user', 'root'), node_cfg['tailscale_domain'], is_local)
            
            click.echo(f"\n📊 SYSTEM UPDATE STATUS: {node_cfg['name'].upper()}")
            click.echo("=" * 50)
            
            # Handle different types of updates_available responses
            if isinstance(updates_available, int):
                update_count = updates_available
                if needs_update:
                    click.echo(f"🟡 Status: Updates available ({update_count} packages)")
                    click.echo(f"📦 Available updates: {update_count}")
                    click.echo(f"🔄 Reboot needed: {reboot_needed}")
                    click.echo(f"\n💡 Use 'system upgrade {node}' to install updates")
                else:
                    click.echo(f"🟢 Status: Up to date")
                    click.echo(f"📦 Available updates: None")
                    click.echo(f"🔄 Reboot needed: {reboot_needed}")
                    
            elif isinstance(updates_available, str) and 'apt-check' in updates_available:
                # Handle apt-check fallback format like "3 (apt-check)"
                try:
                    update_count = int(updates_available.split()[0])
                    if needs_update:
                        click.echo(f"� Status: Updates available ({update_count} packages, via fallback)")
                        click.echo(f"📦 Available updates: {update_count}")
                        click.echo(f"🔄 Reboot needed: {reboot_needed}")
                        click.echo(f"\n💡 Use 'system upgrade {node}' to install updates")
                    else:
                        click.echo(f"🟢 Status: Up to date")
                        click.echo(f"📦 Available updates: None")
                        click.echo(f"🔄 Reboot needed: {reboot_needed}")
                except ValueError:
                    click.echo(f"❌ Status: Parse error")
                    click.echo(f"📦 Raw response: {updates_available}")
            else:
                # Handle error cases
                click.echo(f"❌ Status: Check failed")
                click.echo(f"📦 Error: {updates_available}")
                click.echo(f"🔄 Reboot needed: {reboot_needed}")
        
        except Exception as e:
            click.echo(f"❌ Error checking system updates: {e}")

@system_group.command(name='upgrade')
@click.argument('node', required=False)
@click.option('--all', is_flag=True, help='Upgrade system packages for all configured nodes')
@click.option('--reboot', is_flag=True, help='Automatically reboot nodes if required after upgrade')
def system_upgrade(node, all, reboot):
    """Install Ubuntu system updates (apt update && apt upgrade -y)"""
    config = yaml.safe_load(CONFIG_PATH.read_text())
    
    if all and node:
        click.echo("❌ Cannot specify both --all and a node name")
        return
    elif not all and not node:
        click.echo("❌ Must specify either --all or a node name")
        return
    
    if all:
        # Upgrade all nodes
        click.echo("🔄 Upgrading system packages for all configured nodes...")
        
        nodes = config.get('nodes', [])
        if not nodes:
            click.echo("❌ No nodes configured")
            return
        
        upgrade_results = []
        
        for i, node_cfg in enumerate(nodes):
            name = node_cfg['name']
            stack = node_cfg.get('stack', ['eth-docker'])
            
            # Skip disabled nodes UNLESS they have validator clients
            if _is_stack_disabled(stack):
                # Check if this disabled node still has validator clients (like Charon)
                validator_info = _get_validator_only_clients(node_cfg)
                if not (validator_info and validator_info['has_clients']):
                    click.echo(f"⚪ Skipping {name} (disabled)")
                    continue
                # If we reach here, it's a "disabled" node but has validator clients, so continue processing
            
            click.echo(f"\n🔄 Upgrading {name}... ({i+1}/{len([n for n in nodes if not _is_stack_disabled(n.get('stack', []))])})")
            
            try:
                result = perform_system_upgrade(node_cfg)
                
                if result.get('upgrade_success', False):
                    click.echo(f"✅ {name} system upgrade completed successfully")
                    upgrade_results.append((name, True, None))
                    
                    # Check if reboot is needed and handle it
                    is_local = node_cfg.get('is_local', False)
                    reboot_status = _check_reboot_needed(node_cfg.get('ssh_user', 'root'), node_cfg['tailscale_domain'], is_local)
                    if "Yes" in reboot_status:
                        if reboot:
                            click.echo(f"🔄 Rebooting {name}...")
                            is_local = node_cfg.get('is_local', False)
                            if is_local:
                                reboot_cmd = 'sudo reboot'
                            else:
                                ssh_target = f"{node_cfg.get('ssh_user', 'root')}@{node_cfg['tailscale_domain']}"
                                reboot_cmd = f"ssh -o ConnectTimeout=10 -o BatchMode=yes {ssh_target} 'sudo reboot'"
                            subprocess.run(reboot_cmd, shell=True, timeout=15)
                            click.echo(f"🔄 {name} reboot initiated")
                        else:
                            click.echo(f"⚠️  {name} needs a reboot (use --reboot flag to auto-reboot)")
                else:
                    click.echo(f"❌ {name} system upgrade failed")
                    if result.get('upgrade_error'):
                        click.echo(f"   Error: {result['upgrade_error']}")
                    upgrade_results.append((name, False, result.get('upgrade_error')))
                
            except Exception as e:
                click.echo(f"❌ {name} system upgrade failed with exception: {e}")
                upgrade_results.append((name, False, str(e)))
        
        # Summary
        click.echo(f"\n📊 UPGRADE SUMMARY:")
        successful = [r for r in upgrade_results if r[1]]
        failed = [r for r in upgrade_results if not r[1]]
        
        if successful:
            click.echo(f"✅ Successful upgrades: {', '.join([r[0] for r in successful])}")
        if failed:
            click.echo(f"❌ Failed upgrades: {', '.join([r[0] for r in failed])}")
        
        click.echo(f"🎉 System upgrade process completed!")
        
    else:
        # Upgrade single node
        node_cfg = next(
            (n for n in config['nodes'] if n.get('tailscale_domain') == node or n.get('name') == node),
            None
        )
        if not node_cfg:
            click.echo(f"❌ Node {node} not found")
            return
        
        stack = node_cfg.get('stack', ['eth-docker'])
        if _is_stack_disabled(stack):
            # Check if this disabled node still has validator clients (like Charon)
            validator_info = _get_validator_only_clients(node_cfg)
            if not (validator_info and validator_info['has_clients']):
                click.echo(f"⚪ Node {node} is disabled")
                return
            # If we reach here, it's a "disabled" node but has validator clients, so continue processing
        
        click.echo(f"🔄 Upgrading system packages for {node_cfg['name']}...")
        
        try:
            result = perform_system_upgrade(node_cfg)
            
            if result.get('upgrade_success', False):
                click.echo(f"✅ {node_cfg['name']} system upgrade completed successfully")
                
                # Check if reboot is needed
                is_local = node_cfg.get('is_local', False)
                reboot_status = _check_reboot_needed(node_cfg.get('ssh_user', 'root'), node_cfg['tailscale_domain'], is_local)
                if "Yes" in reboot_status:
                    if reboot:
                        click.echo(f"🔄 Rebooting {node_cfg['name']}...")
                        if is_local:
                            reboot_cmd = 'sudo reboot'
                        else:
                            ssh_target = f"{node_cfg.get('ssh_user', 'root')}@{node_cfg['tailscale_domain']}"
                            reboot_cmd = f"ssh -o ConnectTimeout=10 -o BatchMode=yes {ssh_target} 'sudo reboot'"
                        subprocess.run(reboot_cmd, shell=True, timeout=15)
                        click.echo(f"🔄 {node_cfg['name']} reboot initiated")
                    else:
                        click.echo(f"⚠️  {node_cfg['name']} needs a reboot (use --reboot flag to auto-reboot)")
                
                if result.get('upgrade_output'):
                    click.echo(f"\n📋 Upgrade output:")
                    click.echo(result['upgrade_output'])
            else:
                click.echo(f"❌ {node_cfg['name']} system upgrade failed")
                if result.get('upgrade_error'):
                    click.echo(f"   Error: {result['upgrade_error']}")
        
        except Exception as e:
            click.echo(f"❌ System upgrade failed: {e}")

# Validator Management Group
@cli.group(name='validator')
def validator_group():
    """👥 Validator lifecycle management and duty coordination"""
    pass

@validator_group.command(name='discover')
@click.option('--output', '-o', default='validators_auto_discovered.csv', help='Output CSV filename')
@click.option('--config', '-c', default=str(CONFIG_PATH), help='Configuration file path')
def validator_discover(output, config):
    """🔍 Auto-discover validators across all nodes and generate simplified CSV"""
    click.echo("🔍 Starting validator auto-discovery across cluster...")
    
    try:
        discovery = ValidatorAutoDiscovery(config)
        csv_path = discovery.generate_validators_csv(output)
        
        # Read and display summary
        with open(csv_path, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            validators = list(reader)
        
        if validators:
            click.echo(f"✅ Successfully discovered {len(validators)} validators!")
            click.echo(f"📄 CSV saved to: {csv_path}")
            
            # Show summary by node
            node_counts = {}
            protocol_counts = {}
            
            for validator in validators:
                node = validator['node_name']
                protocol = validator['protocol']
                
                node_counts[node] = node_counts.get(node, 0) + 1
                protocol_counts[protocol] = protocol_counts.get(protocol, 0) + 1
            
            click.echo("\n📊 Discovery Summary:")
            click.echo("By Node:")
            for node, count in node_counts.items():
                click.echo(f"   {node}: {count} validators")
            
            click.echo("\nBy Protocol:")
            for protocol, count in protocol_counts.items():
                click.echo(f"   {protocol}: {count} validators")
        else:
            click.echo("⚠️ No validators discovered")
            
    except Exception as e:
        click.echo(f"❌ Validator discovery failed: {e}")
        raise click.Abort()

@validator_group.command(name='list')
@click.option('--csv-file', default='validators_auto_discovered.csv', help='CSV file to read from')
@click.option('--node', help='Filter by specific node name')
@click.option('--protocol', help='Filter by protocol (e.g., lido-csm, obol-dvt)')
@click.option('--status', help='Filter by validator status (e.g., active, exited)')
def validator_list(csv_file, node, protocol, status):
    """📋 List discovered validators with optional filtering"""
    try:
        csv_path = Path(csv_file)
        
        if not csv_path.exists():
            click.echo(f"❌ CSV file not found: {csv_file}")
            click.echo("💡 Run 'validator discover' first to generate the CSV file")
            return
        
        # Read validators from CSV
        with open(csv_path, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            validators = list(reader)
        
        if not validators:
            click.echo("📭 No validators found in CSV file")
            return
        
        # Apply filters
        filtered = validators
        if node:
            filtered = [v for v in filtered if v['node_name'].lower() == node.lower()]
        if protocol:
            filtered = [v for v in filtered if protocol.lower() in v['protocol'].lower()]
        if status:
            filtered = [v for v in filtered if v['status'].lower() == status.lower()]
        
        if not filtered:
            click.echo("📭 No validators match the specified filters")
            return
        
        # Display results
        click.echo(f"📋 Validators ({len(filtered)} found)")
        click.echo("=" * 100)
        
        table_data = []
        for validator in filtered:
            table_data.append([
                validator['validator_index'],
                validator['public_key'][:12] + '...' + validator['public_key'][-6:],  # Shortened pubkey
                validator['node_name'],
                validator['protocol'],
                validator['status'],
                validator.get('last_updated', 'N/A')[:10]  # Date only
            ])
        
        headers = ['Index', 'Public Key', 'Node', 'Protocol', 'Status', 'Updated']
        click.echo(tabulate(table_data, headers=headers, tablefmt='grid'))
        
    except Exception as e:
        click.echo(f"❌ Failed to list validators: {e}")
        raise click.Abort()

@validator_group.command(name='update-csv')
@click.option('--csv-file', default='validators_vs_hardware.csv', help='Existing CSV file to update')
@click.option('--backup/--no-backup', default=True, help='Create backup of existing CSV')
@click.option('--config', '-c', default=str(CONFIG_PATH), help='Configuration file path')
def validator_update_csv(csv_file, backup, config):
    """🔄 Update existing validators CSV with auto-discovered data"""
    click.echo("🔄 Updating validators CSV with auto-discovered data...")
    
    try:
        discovery = ValidatorAutoDiscovery(config)
        
        if backup and Path(csv_file).exists():
            from datetime import datetime
            backup_name = f"{csv_file}.backup_{int(datetime.now().timestamp())}"
            Path(csv_file).rename(backup_name)
            click.echo(f"💾 Backup created: {backup_name}")
        
        success = discovery.update_existing_csv(csv_file)
        
        if success:
            click.echo(f"✅ Successfully updated {csv_file}")
        else:
            click.echo("⚠️ Update completed with warnings")
            
    except Exception as e:
        click.echo(f"❌ CSV update failed: {e}")
        raise click.Abort()

@validator_group.command(name='compare')
@click.option('--old-csv', default='validators_vs_hardware.csv', help='Original CSV file')
@click.option('--new-csv', default='validators_auto_discovered.csv', help='Auto-discovered CSV file')
def validator_compare(old_csv, new_csv):
    """⚖️ Compare original CSV with auto-discovered validators"""
    click.echo("⚖️ Comparing validator CSV files...")
    
    try:
        old_path = Path(old_csv)
        new_path = Path(new_csv)
        
        if not old_path.exists():
            click.echo(f"❌ Original CSV not found: {old_csv}")
            return
            
        if not new_path.exists():
            click.echo(f"❌ Auto-discovered CSV not found: {new_csv}")
            click.echo("💡 Run 'validator discover' first")
            return
        
        # Read both files
        with open(old_path, 'r', encoding='utf-8') as f:
            old_reader = csv.DictReader(f)
            old_validators = {row.get('validator index', row.get('validator_index', '')): row for row in old_reader}
        
        with open(new_path, 'r', encoding='utf-8') as f:
            new_reader = csv.DictReader(f)
            new_validators = {row['validator_index']: row for row in new_reader}
        
        # Compare
        old_indices = set(old_validators.keys())
        new_indices = set(new_validators.keys())
        
        common = old_indices & new_indices
        only_old = old_indices - new_indices
        only_new = new_indices - old_indices
        
        click.echo(f"\n📊 Comparison Results:")
        click.echo(f"   Common validators: {len(common)}")
        click.echo(f"   Only in original: {len(only_old)}")
        click.echo(f"   Only in discovered: {len(only_new)}")
        
        if only_old:
            click.echo(f"\n🔍 Validators only in original CSV:")
            for idx in list(only_old)[:10]:  # Show first 10
                if idx:  # Skip empty indices
                    click.echo(f"   {idx}")
            if len(only_old) > 10:
                click.echo(f"   ... and {len(only_old) - 10} more")
        
        if only_new:
            click.echo(f"\n🆕 Validators only in discovered CSV:")
            for idx in list(only_new)[:10]:  # Show first 10
                click.echo(f"   {idx}")
            if len(only_new) > 10:
                click.echo(f"   ... and {len(only_new) - 10} more")
                
        # Recommendation
        if len(only_new) > len(only_old):
            click.echo(f"\n💡 Recommendation: Consider using the auto-discovered CSV as it found {len(only_new) - len(only_old)} more validators")
        elif len(only_old) > 0:
            click.echo(f"\n💡 Recommendation: Review validators that appear only in the original CSV")
        else:
            click.echo(f"\n✅ Both files are consistent!")
            
    except Exception as e:
        click.echo(f"❌ Comparison failed: {e}")
        raise click.Abort()

@cli.command(name='quickstart')
def quickstart():
    """🚀 Interactive setup for new users - get started in minutes!"""
    try:
        click.echo("🚀 Ethereum Validator Cluster Manager - Quick Start")
        click.echo("=" * 55)
        
        # Check if already configured
        config_path = Path('config.yaml')
        if config_path.exists():
            if click.confirm("config.yaml already exists. Overwrite with new setup?"):
                config_path.rename(f"config.yaml.backup_{int(time.time())}")
            else:
                click.echo("Setup cancelled. Your existing configuration is preserved.")
                return
        
        # Run interactive setup
        config_file = quick_start_new_user()
        
        # Show next steps
        show_next_steps()
        
    except Exception as e:
        click.echo(f"❌ Quick start failed: {e}")
        raise click.Abort()

@validator_group.command(name='automate')
@click.option('--frequency', type=click.Choice(['daily', 'weekly', 'hourly']), default='daily', help='Update frequency')
@click.option('--setup', is_flag=True, help='Setup automated discovery')
def validator_automate(frequency, setup):
    """⚡ Setup automated validator discovery"""
    click.echo("⚡ Validator Auto-Discovery Automation")
    click.echo("=" * 40)
    
    if not setup:
        click.echo("🔄 Configuration preview:")
        click.echo(f"   Frequency: {frequency}")
        click.echo(f"   Command: validator discover")
        click.echo("\n💡 Use --setup to enable automation")
        return
    
    try:
        # Simple cron setup
        cron_schedule = {
            'daily': '0 6 * * *',
            'weekly': '0 6 * * 1', 
            'hourly': '0 * * * *'
        }[frequency]
        
        base_dir = Path(__file__).parent.parent
        command = f"cd {base_dir} && python3 -m eth_validators validator discover"
        cron_entry = f"{cron_schedule} {command} >> /var/log/validator-discovery.log 2>&1"
        
        click.echo(f"� Automation setup:")
        click.echo(f"   Schedule: {frequency} at 6 AM")
        click.echo(f"   Cron entry: {cron_entry}")
        
        if click.confirm("Add to crontab?"):
            import subprocess
            # Add to crontab
            result = subprocess.run(f'(crontab -l 2>/dev/null; echo "{cron_entry}") | crontab -', 
                                  shell=True, capture_output=True, text=True)
            
            if result.returncode == 0:
                click.echo("✅ Automation enabled!")
                click.echo(f"🔄 Validators will be discovered {frequency}")
            else:
                click.echo(f"❌ Failed to setup automation: {result.stderr}")
        
    except Exception as e:
        click.echo(f"❌ Automation setup failed: {e}")
        raise click.Abort()

def _check_reboot_needed(ssh_user, tailscale_domain, is_local=False):
    """Check if a node needs a reboot by checking for reboot-required file"""
    try:
        if is_local:
            # For local nodes, run the command directly
            cmd = 'test -f /var/run/reboot-required && echo REBOOT_NEEDED || echo NO_REBOOT'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        else:
            # For remote nodes, use SSH
            ssh_target = f"{ssh_user}@{tailscale_domain}"
            cmd = f"ssh -o ConnectTimeout=5 -o BatchMode=yes {ssh_target} 'test -f /var/run/reboot-required && echo REBOOT_NEEDED || echo NO_REBOOT'"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            if "REBOOT_NEEDED" in result.stdout:
                return "🔄 Yes"
            else:
                return "✅ No"
        else:
            return "❓ Unknown"
    except (subprocess.TimeoutExpired, Exception):
        return "❓ Unknown"

@node_group.command(name='list')
def list_cmd():
    """Display a live cluster overview with real-time client diversity analysis."""
    config = yaml.safe_load(CONFIG_PATH.read_text())
    nodes = config.get('nodes', [])
    
    if not nodes:
        click.echo("❌ No nodes found in configuration")
        return
    
    click.echo("🖥️  ETHEREUM NODE CLUSTER OVERVIEW (LIVE DATA)")
    click.echo("=" * 100)
    click.echo("🔄 Fetching live data from all active nodes... (this may take a moment)")
    
    table_data = []
    active_nodes = 0
    disabled_nodes = 0
    
    exec_clients = {}
    consensus_clients = {}
    
    for i, node in enumerate(nodes):
        name = node['name']
        stack = node.get('stack', ['eth-docker'])
        
        click.echo(f"📡 Processing {name}... ({i+1}/{len(nodes)})", nl=False, err=True)
        
        # Stack info with emojis - handle multiple stacks
        stack_emojis = {
            'eth-docker': '🐳', 'disabled': '🚫', 'rocketpool': '🚀', 'obol': '🔗',
            'hyperdrive': '⚡', 'charon': '🌐', 'ssv': '📡', 'stakewise': '🏦',
            'lido-csm': '🏦', 'eth-hoodi': '🧪'
        }
        
        if 'disabled' in stack:
            stack_display = "🚫 disabled"
        else:
            stack_parts = [f"{stack_emojis.get(s.lower(), '⚙️')} {s}" for s in stack]
            stack_display = " + ".join(stack_parts)

        if _is_stack_disabled(stack) or not _has_ethereum_clients(node):
            # Check if this is a validator-only node (like Charon + validator clients)
            validator_info = _get_validator_only_clients(node)
            if validator_info and validator_info['has_clients']:
                status_emoji = "🟢"
                status_text = "Active"
                active_nodes += 1
                clients = f"🔗 {validator_info['display_name']}"
                
                # Override stack display if Charon is detected
                if 'charon' in validator_info.get('display_name', '').lower():
                    stack_display = "🔗 obol"
                    
                click.echo(" ✓", err=True)
            else:
                status_emoji = "🔴"
                status_text = "Disabled"
                clients = "❌ No clients"
                disabled_nodes += 1
                click.echo(" ✓", err=True)
        else:
            status_emoji = "🟢"
            status_text = "Active"
            active_nodes += 1
            
            # Use live client detection instead of static config
            try:
                version_info = get_docker_client_versions(node)
                
                # Handle multi-network nodes (like eliedesk)
                if 'mainnet' in version_info or 'testnet' in version_info:
                    # Multi-network node: aggregate unique clients from active networks only
                    exec_names = set()
                    cons_names = set()
                    for net_info in version_info.values():
                        if isinstance(net_info, dict) and 'error' not in net_info:
                            exec_client = net_info.get('execution_client', 'Unknown')
                            cons_client = net_info.get('consensus_client', 'Unknown')
                            if exec_client not in ['Unknown', 'Error']:
                                exec_names.add(exec_client)
                            if cons_client not in ['Unknown', 'Error']:
                                cons_names.add(cons_client)
                    
                    exec_client = ', '.join(sorted(exec_names)) if exec_names else "N/A"
                    consensus_client = ', '.join(sorted(cons_names)) if cons_names else "N/A"
                else:
                    # Single network node
                    exec_client = version_info.get('execution_client', 'N/A')
                    consensus_client = version_info.get('consensus_client', 'N/A')

                click.echo(" ✓", err=True)
            except Exception as e:
                # If live detection fails, show error status
                exec_client = 'Error'
                consensus_client = 'Error'
                click.echo(f" ❌ Error: {str(e)[:30]}...", err=True)

            # Track diversity
            if exec_client and exec_client not in ['Unknown', 'Error', 'N/A']:
                exec_clients[exec_client] = exec_clients.get(exec_client, 0) + 1
            if consensus_client and consensus_client not in ['Unknown', 'Error', 'N/A']:
                consensus_clients[consensus_client] = consensus_clients.get(consensus_client, 0) + 1
            
            # Check for additional validators like Vero
            additional_validators = _detect_additional_validators(node)
            validator_suffix = ""
            if additional_validators:
                validator_suffix = f" + 🔒 {', '.join(additional_validators)}"
            
            clients = f"⚙️  {exec_client} + 🔗 {consensus_client}{validator_suffix}"

        table_data.append([
            f"{status_emoji} {name}",
            status_text,
            clients,
            stack_display
        ])

    click.echo("\nRendering table...")
    headers = ['Node Name', 'Status', 'Live Ethereum Clients', 'Stack']
    click.echo(tabulate(table_data, headers=headers, tablefmt='fancy_grid'))
    
    click.echo(f"\n📊 CLUSTER SUMMARY:")
    click.echo(f"  🟢 Active nodes: {active_nodes}")
    click.echo(f"  🔴 Disabled nodes: {disabled_nodes}")
    click.echo(f"  📈 Total nodes: {len(nodes)}")
    
    if exec_clients or consensus_clients:
        click.echo(f"\n🌐 LIVE CLIENT DIVERSITY (from {active_nodes} active nodes):")
        if exec_clients:
            exec_total = sum(exec_clients.values())
            click.echo(f"  ⚙️  Execution clients:")
            for client, count in sorted(exec_clients.items()):
                percentage = (count / exec_total) * 100 if exec_total > 0 else 0
                click.echo(f"    • {client}: {count} node(s) ({percentage:.1f}%)")
        
        if consensus_clients:
            consensus_total = sum(consensus_clients.values())
            click.echo(f"  🔗 Consensus clients:")
            for client, count in sorted(consensus_clients.items()):
                percentage = (count / consensus_total) * 100 if consensus_total > 0 else 0
                click.echo(f"    • {client}: {count} node(s) ({percentage:.1f}%)")
        
        if exec_clients and len(exec_clients) < 2:
            click.echo(f"  ⚠️  WARNING: Low execution client diversity!")
        if consensus_clients and len(consensus_clients) < 2:
            click.echo(f"  ⚠️  WARNING: Low consensus client diversity!")
    
    click.echo(f"\n💡 Use 'node versions --all' for detailed version and update status.")
    click.echo("=" * 100)

@node_group.command(name='upgrade')
@click.argument('node', required=False)
@click.option('--all', is_flag=True, help='Upgrade all configured nodes')
def upgrade(node, all):
    """Execute live Docker container upgrades via SSH to remote nodes"""
    if all and node:
        click.echo("❌ Cannot specify both --all and a node name")
        return
    elif not all and not node:
        click.echo("❌ Must specify either --all or a node name")
        return
    
    config = yaml.safe_load(CONFIG_PATH.read_text())
    
    if all:
        # Upgrade all nodes
        click.echo("🔄 Upgrading all configured nodes with active Ethereum clients...")
        
        for node_cfg in config.get('nodes', []):
            name = node_cfg['name']
            
            # Skip nodes with disabled eth-docker
            stack = node_cfg.get('stack', 'eth-docker')
            
            if (_is_stack_disabled(stack) or not _has_ethereum_clients(node_cfg)):
                click.echo(f"⚪ Skipping {name} (Ethereum clients disabled)")
                continue
                
            click.echo(f"🔄 Upgrading {name}...")
            
            # Use the enhanced upgrade function that supports multi-network
            result = upgrade_node_docker_clients(node_cfg)
            
            # Check if this is a multi-network result
            if 'overall_success' in result:
                # Multi-network node
                if result['overall_success']:
                    click.echo(f"✅ {name} upgrade completed successfully for all networks")
                else:
                    click.echo(f"❌ {name} upgrade had some failures")
                
                # Show details for each network
                for network_name, network_result in result.items():
                    if network_name == 'overall_success':
                        continue
                    
                    if network_result['upgrade_success']:
                        click.echo(f"  ✅ {network_name}: Success")
                    else:
                        click.echo(f"  ❌ {network_name}: Failed")
                        if network_result.get('upgrade_error'):
                            click.echo(f"     Error: {network_result['upgrade_error']}")
            else:
                # Single network node
                if result['upgrade_success']:
                    click.echo(f"✅ {name} upgrade completed successfully")
                else:
                    click.echo(f"❌ {name} upgrade failed")
                    if result.get('upgrade_error'):
                        click.echo(f"   Error: {result['upgrade_error']}")
            
            if result.get('upgrade_output'):
                click.echo(f"   Output: {result['upgrade_output']}")
        
        click.echo("🎉 All node upgrades completed!")
    else:
        # Upgrade single node
        node_cfg = next(
            (n for n in config['nodes'] if n.get('tailscale_domain') == node or n.get('name') == node),
            None
        )
        if not node_cfg:
            click.echo(f"Node {node} not found")
            return
        
        # Check if Ethereum clients are disabled
        stack = node_cfg.get('stack', 'eth-docker')
        
        if (_is_stack_disabled(stack) or not _has_ethereum_clients(node_cfg)):
            click.echo(f"⚪ Skipping {node} (Ethereum clients disabled)")
            return
        
        click.echo(f"🔄 Upgrading {node}...")
        
        # Use the enhanced upgrade function that supports multi-network
        result = upgrade_node_docker_clients(node_cfg)
        
        # Check if this is a multi-network result
        if 'overall_success' in result:
            # Multi-network node
            if result['overall_success']:
                click.echo(f"✅ {node} upgrade completed successfully for all networks")
            else:
                click.echo(f"❌ {node} upgrade had some failures")
            
            # Show details for each network
            for network_name, network_result in result.items():
                if network_name == 'overall_success':
                    continue
                
                if network_result['upgrade_success']:
                    click.echo(f"  ✅ {network_name}: Success")
                else:
                    click.echo(f"  ❌ {network_name}: Failed")
                    if network_result.get('upgrade_error'):
                        click.echo(f"     Error: {network_result['upgrade_error']}")
        else:
            # Single network node
            if result['upgrade_success']:
                click.echo(f"✅ {node} upgrade completed successfully")
            else:
                click.echo(f"❌ {node} upgrade failed")
                if result.get('upgrade_error'):
                    click.echo(f"   Error: {result['upgrade_error']}")
        
        if result.get('upgrade_output'):
            click.echo(f"   Output: {result['upgrade_output']}")

@node_group.command(name='inspect')
@click.argument('node_name')
def inspect_node_cmd(node_name):
    """Inspect live validator duties and container status via SSH and beacon API"""
    config = yaml.safe_load(CONFIG_PATH.read_text())
    node_cfg = next(
        (n for n in config['nodes'] if n.get('tailscale_domain') == node_name or n.get('name') == node_name),
        None
    )
    if not node_cfg:
        click.echo(f"Node {node_name} not found")
        return
    
    click.echo(f"🔍 Inspecting validator duties and responsibilities for {node_cfg['name']}...")
    
    # Read validators CSV
    validators_file = Path(__file__).parent / 'validators_vs_hardware.csv'
    if not validators_file.exists():
        click.echo("❌ validators_vs_hardware.csv not found")
        return
    
    import csv
    validators_for_node = []
    
    try:
        with open(validators_file, mode='r', encoding='utf-8') as infile:
            reader = csv.DictReader(infile)
            for row in reader:
                domain = row.get('tailscale dns', '').strip()
                if domain == node_cfg['tailscale_domain']:
                    validators_for_node.append(row)
    except Exception as e:
        click.echo(f"❌ Error reading CSV: {e}")
        return
    
    if not validators_for_node:
        click.echo(f"No validators found for {node_cfg['name']}")
        return
    
    click.echo(f"📊 Found {len(validators_for_node)} validators for {node_cfg['name']}")
    
    # Group by stack/protocol
    stacks = {}
    for validator in validators_for_node:
        stack = validator.get('stack', 'Unknown')
        protocol = validator.get('Protocol', 'Unknown')
        container = validator.get('AI Monitoring containers1', 'Unknown')
        
        key = f"{protocol} ({stack})"
        if key not in stacks:
            stacks[key] = []
        stacks[key].append({
            'index': validator.get('validator index ', 'N/A'),
            'container': container,
            'pubkey_short': validator.get('validator public address', '')[:10] + '...' if validator.get('validator public address') else 'N/A'
        })
    
    # Display detailed analysis
    click.echo("\n" + "="*80)
    click.echo(f"🎯 VALIDATOR ANALYSIS: {node_cfg['name'].upper()}")
    click.echo("="*80)
    
    for stack, validators in stacks.items():
        click.echo(f"\n🔸 {stack}")
        click.echo(f"   Validators: {len(validators)}")
        click.echo(f"   Container: {validators[0]['container']}")
        
        # Check status of a few validators from this stack
        if len(validators) > 0:
            sample_indices = [v['index'] for v in validators[:3] if v['index'] != 'N/A']
            if sample_indices:
                click.echo(f"   Sample status check:")
                ssh_target = f"{node_cfg.get('ssh_user','root')}@{node_cfg['tailscale_domain']}"
                
                for idx in sample_indices:
                    try:
                        status_cmd = f"ssh {ssh_target} \"curl -s http://localhost:{node_cfg['beacon_api_port']}/eth/v1/beacon/states/head/validators/{idx} | jq -r .data.status\""
                        process = subprocess.run(status_cmd, shell=True, capture_output=True, text=True, timeout=10)
                        status = process.stdout.strip().replace('"', '') if process.returncode == 0 else "Error"
                        click.echo(f"     • Validator {idx}: {status}")
                    except:
                        click.echo(f"     • Validator {idx}: Connection Error")
    
    # Show container status
    click.echo(f"\n🐳 Container Status:")
    ssh_target = f"{node_cfg.get('ssh_user','root')}@{node_cfg['tailscale_domain']}"
    
    try:
        command = "docker ps --format 'table {{.Names}}\\t{{.Status}}' | grep -E 'validator|hyperdrive|charon'"
        result = _run_command(node_cfg, command)
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            for line in lines:
                if line and 'NAMES' not in line:
                    click.echo(f"   {line}")
        else:
            click.echo("   Could not fetch container status")
    except:
        click.echo("   Connection error")
    
    click.echo("="*80)

@performance_group.command(name='summary')
def performance_cmd():
    """Query live validator performance metrics via beacon chain APIs and CSV data"""
    click.echo("Fetching performance data for all validators...")
    table_data = performance.get_performance_summary()
    headers = ["Node", "Validator Index", "Attester Eff.", "Misses", "Inclusion Dist.", "Status"]
    
    # ANSI color codes
    RED = '\033[91m'
    YELLOW = '\033[93m'
    RESET = '\033[0m'

    processed_table = []
    for row in table_data:
        # Deconstruct the row: [Node, Index, Eff., Misses, Dist., Status]
        # Indices:                 0,     1,    2,      3,      4,      5
        eff = row[2]
        misses = row[3]
        status = row[5]
        
        color = ""
        
        # Condition for red: status contains "exit" or misses are high
        is_exiting = 'exit' in str(status)
        has_high_misses = False
        try:
            # Check if misses is a number and greater than 3
            if int(misses) > 3:
                has_high_misses = True
        except (ValueError, TypeError):
            pass # Handles cases where misses is 'N/A'

        # Condition for yellow: active but no performance data
        is_active_no_data = 'active' in str(status) and eff == 'N/A'

        if is_exiting or has_high_misses:
            color = RED
        elif is_active_no_data:
            color = YELLOW
        
        if color:
            # Apply color to each cell in the row
            processed_table.append([f"{color}{item}{RESET}" for item in row])
        else:
            processed_table.append(row)

    # Use 'plain' table format as it's safer for rendering ANSI color codes
    click.echo(tabulate(processed_table, headers=headers, tablefmt="plain"))

@node_group.command(name='update-charon')
@click.option('--dry-run', is_flag=True, help='Show what would be done without making changes')
@click.option('--node', 'selected_nodes', multiple=True, help='Update only specified nodes (can be used multiple times)')
def update_charon(dry_run, selected_nodes):
    """Execute live Charon container updates via SSH on Obol distributed validator nodes"""
    import os
    script_path = Path(__file__).parent.parent / 'scripts' / 'update_charon.sh'
    
    if not script_path.exists():
        click.echo("❌ Charon update script not found!")
        return
    
    # Build command arguments  
    cmd_args = [str(script_path)]
    
    if dry_run:
        cmd_args.append('--dry-run')
    
    for node in selected_nodes:
        cmd_args.extend(['--node', node])
    
    # Execute the script
    try:
        subprocess.run(cmd_args, check=True)
    except subprocess.CalledProcessError as e:
        click.echo(f"❌ Charon update failed with exit code {e.returncode}")
    except FileNotFoundError:
        click.echo("❌ Could not execute Charon update script")

@node_group.command(name='versions')
@click.argument('node', required=False)
@click.option('--all', is_flag=True, help='Show client versions for all configured nodes')
def versions(node, all):
    """Query live client versions, sync status, and container health via SSH/API"""
    config = yaml.safe_load(CONFIG_PATH.read_text())
    
    if all:
        nodes = config.get('nodes', [])
        if not nodes:
            click.echo("❌ No nodes configured. Please check your config.yaml file.")
            return
        
        click.echo("🖥️  ETHEREUM NODE VERSION CHECK (LIVE DATA)")
        click.echo("=" * 100)
        click.echo("🔄 Fetching client versions from all configured nodes... (this may take a moment)")
        
        latest_charon = _get_latest_charon_version()
        table_data = []
        active_nodes = 0
        disabled_nodes = 0
        for i, node_cfg in enumerate(nodes):
            name = node_cfg['name']
            stack = node_cfg.get('stack', ['eth-docker'])
            if isinstance(stack, str):
                stack = [stack]
            
            click.echo(f"📡 Processing {name}... ({i+1}/{len(nodes)})", nl=False, err=True)
            
            status_emoji = "🟢"
            status_text = "Active"
            exec_display = cons_display = val_display = charon_display = "-"
            exec_latest_display = cons_latest_display = val_latest_display = charon_latest_display = "-"
            exec_update = cons_update = val_update = charon_update = "-"
            # Disabled node logic
            if _is_stack_disabled(stack) or node_cfg.get('ethereum_clients_enabled') is False:
                # Check if this is a validator-only node (like Charon + validator clients)
                validator_info = _get_validator_only_clients(node_cfg)
                if validator_info and validator_info['has_clients']:
                    status_emoji = "�"
                    status_text = "Active"
                    active_nodes += 1
                    ssh_target = f"{node_cfg.get('ssh_user', 'root')}@{node_cfg['tailscale_domain']}"
                    charon_version = _get_charon_version(ssh_target, node_cfg['tailscale_domain'], node_cfg)
                    charon_needs_update = (charon_version != "N/A" and latest_charon != "Unknown" and charon_version != latest_charon and charon_version != "latest")
                    charon_display = charon_version if charon_version != "N/A" else "-"
                    charon_latest_display = latest_charon if charon_version != "N/A" else "-"
                    charon_update = '🔄' if charon_needs_update else '✅' if charon_version != "N/A" else '-'
                    table_data.append([
                        f"{status_emoji} {name}", status_text, f"🔗 {validator_info['display_name']}", '-', '-', f"🔗 {validator_info['display_name']}", '-', '-', '-', '-', '-', charon_display, charon_latest_display, charon_update
                    ])
                    click.echo(" ✓", err=True)
                else:
                    status_emoji = "�🔴"
                    status_text = "Disabled"
                    disabled_nodes += 1
                    click.echo(" ✓", err=True)
            else:
                active_nodes += 1
                ssh_target = f"{node_cfg.get('ssh_user', 'root')}@{node_cfg['tailscale_domain']}"
                charon_version = _get_charon_version(ssh_target, node_cfg['tailscale_domain'], node_cfg)
                try:
                    version_info = get_docker_client_versions(node_cfg)
                    # Multi-network node
                    if 'mainnet' in version_info or 'testnet' in version_info:
                        for network_key, network_info in version_info.items():
                            network_display_name = network_info.get('network', network_key)
                            exec_client = network_info.get('execution_client', 'Unknown')
                            exec_current = network_info.get('execution_current', 'Unknown')
                            exec_latest = network_info.get('execution_latest', 'Unknown')
                            exec_needs_update = network_info.get('execution_needs_update', False)
                            cons_client = network_info.get('consensus_client', 'Unknown')
                            cons_current = network_info.get('consensus_current', 'Unknown')
                            cons_latest = network_info.get('consensus_latest', 'Unknown')
                            cons_needs_update = network_info.get('consensus_needs_update', False)
                            val_client = network_info.get('validator_client', '-')
                            val_current = network_info.get('validator_current', '-')
                            val_latest = network_info.get('validator_latest', '-')
                            val_needs_update = network_info.get('validator_needs_update', False)
                            charon_needs_update = (charon_version != "N/A" and latest_charon != "Unknown" and charon_version != latest_charon and charon_version != "latest")
                            exec_display = f"{exec_client}/{exec_current}" if exec_client != "Unknown" else "-"
                            exec_latest_display = exec_latest if exec_latest not in ["Unknown", "API Error", "Network Error", "Rate Limited"] else "-"
                            exec_update = '🔄' if exec_needs_update else '✅' if exec_latest_display != "-" else '❓'
                            cons_display = f"{cons_client}/{cons_current}" if cons_client != "Unknown" else "-"
                            cons_latest_display = cons_latest if cons_latest not in ["Unknown", "API Error", "Network Error", "Rate Limited"] else "-"
                            cons_update = '🔄' if cons_needs_update else '✅' if cons_latest_display != "-" else '❓'
                            val_display = f"{val_client}/{val_current}" if val_client not in ["Unknown", "Disabled", "-"] and val_current not in ["Unknown", "Not Running", "-"] else "-"
                            val_latest_display = val_latest if val_latest not in ["Unknown", "Not Running", "Disabled", "-", "API Error", "Network Error", "Rate Limited"] else "-"
                            val_update = '🔄' if val_needs_update else '✅' if val_display != "-" and val_latest_display != "-" else '❓' if val_display != "-" else '-'
                            charon_display = charon_version if charon_version != "N/A" else "-"
                            charon_latest_display = latest_charon if charon_version != "N/A" else "-"
                            charon_update = '🔄' if charon_needs_update else '✅' if charon_version != "N/A" else '-'
                            table_data.append([
                                f"{status_emoji} {name}-{network_display_name}", status_text, exec_display, exec_latest_display, exec_update, cons_display, cons_latest_display, cons_update, val_display, val_latest_display, val_update, charon_display, charon_latest_display, charon_update
                            ])
                        click.echo(" ✓", err=True)
                        continue
                    # Single-network node
                    exec_client = version_info.get('execution_client', 'Unknown')
                    exec_current = version_info.get('execution_current', 'Unknown')
                    exec_latest = version_info.get('execution_latest', 'Unknown')
                    exec_needs_update = version_info.get('execution_needs_update', False)
                    cons_client = version_info.get('consensus_client', 'Unknown')
                    cons_current = version_info.get('consensus_current', 'Unknown')
                    cons_latest = version_info.get('consensus_latest', 'Unknown')
                    cons_needs_update = version_info.get('consensus_needs_update', False)
                    val_client = version_info.get('validator_client', '-')
                    val_current = version_info.get('validator_current', '-')
                    val_latest = version_info.get('validator_latest', '-')
                    val_needs_update = version_info.get('validator_needs_update', False)
                    charon_needs_update = (charon_version != "N/A" and latest_charon != "Unknown" and charon_version != latest_charon and charon_version != "latest")
                    exec_display = f"{exec_client}/{exec_current}" if exec_client != "Unknown" else "-"
                    exec_latest_display = exec_latest if exec_latest not in ["Unknown", "API Error", "Network Error"] else "-"
                    exec_update = '🔄' if exec_needs_update else '✅' if exec_latest_display != "-" else '❓'
                    cons_display = f"{cons_client}/{cons_current}" if cons_client != "Unknown" else "-"
                    cons_latest_display = cons_latest if cons_latest not in ["Unknown", "API Error", "Network Error"] else "-"
                    cons_update = '🔄' if cons_needs_update else '✅' if cons_latest_display != "-" else '❓'
                    val_display = f"{val_client}/{val_current}" if val_client not in ["Unknown", "Disabled", "-"] and val_current not in ["Unknown", "Not Running", "-"] else "-"
                    val_latest_display = val_latest if val_latest not in ["Unknown", "Not Running", "Disabled", "-", "API Error", "Network Error"] else "-"
                    val_update = '🔄' if val_needs_update else '✅' if val_display != "-" and val_latest_display != "-" else '❓' if val_display != "-" else '-'
                    charon_display = charon_version if charon_version != "N/A" else "-"
                    charon_latest_display = latest_charon if charon_version != "N/A" else "-"
                    charon_update = '🔄' if charon_needs_update else '✅' if charon_version != "N/A" else '-'
                    table_data.append([
                        f"{status_emoji} {name}", status_text, exec_display, exec_latest_display, exec_update, cons_display, cons_latest_display, cons_update, val_display, val_latest_display, val_update, charon_display, charon_latest_display, charon_update
                    ])
                    click.echo(" ✓", err=True)
                except Exception as e:
                    table_data.append([
                        f"{status_emoji} {name}", status_text, 'Error', '-', '❌', 'Error', '-', '❌', 'Error', '-', '❌', '-', '-', '-'
                    ])
                    click.echo(f" ❌ Error: {str(e)[:30]}...", err=True)
            # Disabled node row
            if status_text == "Disabled":
                table_data.append([
                    f"{status_emoji} {name}", status_text, '❌ No clients', '-', '-', '❌ No clients', '-', '-', '-', '-', '-', '-', '-', '-'
                ])
        
        click.echo("\nRendering version table...")
        
        # Compact headers for double-line format
        from colorama import Fore, Style
        import re
        headers = ['Node', 'St', 'Execution', '✓', 'Consensus', '✓', 'Validator', '✓', 'DVT', '✓']
        
        # Double-line table processing - each node gets two rows
        compact_table = []
        outdated_nodes = []
        for row in table_data:
            # Smart node name handling - keep essential info but make readable
            node_name = row[0]
            if len(node_name) > 18:
                # For multi-network nodes, show network suffix
                if '-mainnet' in node_name or '-testnet' in node_name or '-hoodi' in node_name:
                    node_parts = node_name.split('-')
                    if len(node_parts) > 1:
                        node_name = f"{node_parts[0][:10]}-{node_parts[-1][:6]}"
                else:
                    node_name = node_name[:16] + '…'
            
            # Color for update status
            def color_status(val):
                if val == '🔄':
                    return Fore.RED + val + Style.RESET_ALL
                elif val == '✅':
                    return Fore.GREEN + val + Style.RESET_ALL
                elif val == '❓':
                    return Fore.YELLOW + val + Style.RESET_ALL
                return val
            
            # Handle disabled nodes with dimmed colors
            if row[1] == 'Disabled':
                compact_table.append([
                    Fore.LIGHTBLACK_EX + node_name + Style.RESET_ALL,
                    Fore.LIGHTBLACK_EX + "Off" + Style.RESET_ALL,
                    Fore.LIGHTBLACK_EX + "No clients" + Style.RESET_ALL,
                    '-',
                    Fore.LIGHTBLACK_EX + "No clients" + Style.RESET_ALL,
                    '-',
                    '-', '-', '-', '-'
                ])
                # Empty second line for disabled nodes
                compact_table.append(['', '', '', '', '', '', '', '', '', ''])
                continue
            
            # Collect outdated nodes for upgrade
            if '🔄' in [row[4], row[7], row[10], row[13]]:
                raw_node_name = row[0]
                clean_name = re.sub(r'[🟢🔴]|\x1b\[[0-9;]*m', '', raw_node_name).strip()
                if '-mainnet' in clean_name or '-testnet' in clean_name or '-hoodi' in clean_name:
                    clean_name = clean_name.split('-')[0]
                outdated_nodes.append(clean_name)
            
            # Parse client info into name and version
            def parse_client_info(client_version):
                if client_version == "-" or not client_version or client_version == "No clients":
                    return "-", ""
                # Handle validator-only display format (e.g., "🔗 charon/1.5.2 + lodestar/latest")
                if client_version.startswith("🔗 "):
                    clean_version = client_version[2:]  # Remove emoji
                    if "/" in clean_version:
                        parts = clean_version.split("/", 1)
                        return parts[0], parts[1] if len(parts) > 1 else ""
                    return clean_version, ""
                # Normal client format (e.g., "nethermind/1.32.4")
                if "/" in client_version:
                    parts = client_version.split("/", 1)  # Split only on first /
                    return parts[0], parts[1] if len(parts) > 1 else ""
                return client_version, ""
            
            # Parse DVT info specially to handle stack name vs version
            def parse_dvt_info(charon_version):
                if charon_version == "-" or not charon_version:
                    return "-", ""
                # If it's just a version number, it's Charon
                if charon_version and not "/" in charon_version and charon_version not in ["-", "N/A"]:
                    return "Charon", charon_version
                # Handle other formats
                if "/" in charon_version:
                    parts = charon_version.split("/", 1)
                    return parts[0].title(), parts[1] if len(parts) > 1 else ""
                return charon_version, ""
            
            # Extract client names and versions
            exec_name, exec_version = parse_client_info(row[2])
            cons_name, cons_version = parse_client_info(row[5])
            val_name, val_version = parse_client_info(row[8])
            dvt_name, dvt_version = parse_dvt_info(row[11])  # Special parsing for DVT
            
            # Extract latest versions from row data (positions 3, 6, 9, 12)
            exec_latest = row[3] if len(row) > 3 else "-"
            cons_latest = row[6] if len(row) > 6 else "-"  
            val_latest = row[9] if len(row) > 9 else "-"
            dvt_latest = row[12] if len(row) > 12 else "-"
            
            # Clean up latest version displays
            if exec_latest in ["Unknown", "API Error", "Network Error", "Rate Limited", "-"]:
                exec_latest = "-"
            if cons_latest in ["Unknown", "API Error", "Network Error", "Rate Limited", "-"]:
                cons_latest = "-"
            if val_latest in ["Unknown", "Not Running", "Disabled", "API Error", "Network Error", "Rate Limited", "-"]:
                val_latest = "-"
            if dvt_latest in ["Unknown", "API Error", "Network Error", "Rate Limited", "-"]:
                dvt_latest = "-"
            
            # Format version display: show "current → latest" if different, otherwise just "current"
            def format_version_display(current, latest):
                if not current or current == "-":
                    return ""
                if not latest or latest == "-" or latest == current:
                    return current[:14]
                # Show update needed: current→latest
                return f"{current[:6]}→{latest[:6]}"
            
            # For validator-only nodes, show validator info in validator column only
            if exec_name.startswith("charon") or cons_name.startswith("charon"):
                # This is a validator-only node, move the info to proper columns
                if dvt_name == "-" and exec_name.startswith("charon"):
                    dvt_name = "Charon"
                    dvt_version = exec_version
                    exec_name, exec_version = "-", ""
                    cons_name, cons_version = "-", ""
                elif dvt_name == "-" and cons_name.startswith("charon"):
                    dvt_name = "Charon"
                    dvt_version = cons_version
                    exec_name, exec_version = "-", ""
                    cons_name, cons_version = "-", ""
            
            # First row: Node name, status, client names, and update status
            compact_table.append([
                node_name,
                "On" if row[1] == "Active" else row[1][:3],
                exec_name[:14] if exec_name != "-" else "-",
                color_status(row[4]),
                cons_name[:14] if cons_name != "-" else "-",
                color_status(row[7]),
                val_name[:14] if val_name != "-" else "-",
                color_status(row[10]),
                dvt_name[:14] if dvt_name != "-" else "-",
                color_status(row[13])
            ])
            
            # Second row: Empty node name/status, client versions with latest info
            version_color = Fore.LIGHTBLACK_EX
            compact_table.append([
                '',  # Empty node name
                '',  # Empty status
                version_color + format_version_display(exec_version, exec_latest) + Style.RESET_ALL if exec_version else '',
                '',  # Empty update status
                version_color + format_version_display(cons_version, cons_latest) + Style.RESET_ALL if cons_version else '',
                '',  # Empty update status
                version_color + format_version_display(val_version, val_latest) + Style.RESET_ALL if val_version else '',
                '',  # Empty update status
                version_color + format_version_display(dvt_version, dvt_latest) + Style.RESET_ALL if dvt_version else '',
                ''   # Empty update status
            ])
        
        # Use grid format with compact double-line layout
        click.echo(tabulate(compact_table, headers=headers, tablefmt='fancy_grid', 
                           stralign='left', numalign='center', maxcolwidths=[16, 3, 14, 3, 14, 3, 14, 3, 14, 3]))
        click.echo(f"\n📊 CLUSTER SUMMARY:")
        click.echo(f"  🟢 Active: {active_nodes}  🔴 Disabled: {disabled_nodes}  Total: {len(nodes)}")
        if outdated_nodes:
            # Remove duplicates while preserving order
            unique_outdated = list(dict.fromkeys(outdated_nodes))
            click.echo(f"\n⚠️  Nodes needing upgrade: {', '.join(unique_outdated)}")
            # Interactive prompt for upgrade
            import sys
            if sys.stdin.isatty():
                click.echo("\n💡 Would you like to start upgrade for outdated nodes now? [y/N]")
                resp = input().strip().lower()
                if resp == 'y':
                    click.echo("\n🚀 Starting upgrade for outdated nodes...")
                    upgrade_results = []
                    for node in unique_outdated:
                        # Remove emoji and network suffix if present
                        node_clean = node.split(' ')[-1].split('-')[0]
                        # Remove color codes
                        node_clean = node_clean.replace('🟢', '').replace('🔴', '').strip()
                        click.echo(f"  📡 Upgrading {node_clean}...")
                        result = subprocess.run([sys.executable, '-m', 'eth_validators', 'node', 'upgrade', node_clean])
                        if result.returncode == 0:
                            click.echo(f"    ✅ {node_clean} upgrade completed")
                            upgrade_results.append((node_clean, True))
                        else:
                            click.echo(f"    ❌ {node_clean} upgrade failed")
                            upgrade_results.append((node_clean, False))
                    click.echo("✅ All upgrade commands completed.")
                    
                    # Show updated table after upgrades
                    click.echo("\n" + "="*70)
                    click.echo("📊 POST-UPGRADE STATUS")
                    click.echo("="*70)
                    click.echo("🔄 Fetching updated version information...")
                    
                    # Re-fetch versions for upgraded nodes
                    updated_table_data = []
                    for node_cfg in nodes:
                        name = node_cfg['name']
                        if name in [r[0] for r in upgrade_results]:
                            # This node was upgraded, re-fetch its versions
                            try:
                                version_info = get_docker_client_versions(node_cfg)
                                ssh_target = f"{node_cfg.get('ssh_user', 'root')}@{node_cfg['tailscale_domain']}"
                                charon_version = _get_charon_version(ssh_target, node_cfg['tailscale_domain'], node_cfg)
                                
                                # Process version info similar to main table
                                if 'mainnet' in version_info or 'testnet' in version_info:
                                    for network_key, network_info in version_info.items():
                                        network_display_name = network_info.get('network', network_key)
                                        exec_client = network_info.get('execution_client', 'Unknown')
                                        exec_current = network_info.get('execution_current', 'Unknown')
                                        cons_client = network_info.get('consensus_client', 'Unknown')
                                        cons_current = network_info.get('consensus_current', 'Unknown')
                                        val_client = network_info.get('validator_client', '-')
                                        val_current = network_info.get('validator_current', '-')
                                        
                                        exec_display = f"{exec_client}/{exec_current}" if exec_client != "Unknown" else "-"
                                        cons_display = f"{cons_client}/{cons_current}" if cons_client != "Unknown" else "-"
                                        val_display = f"{val_client}/{val_current}" if val_client not in ["Unknown", "Disabled", "-"] and val_current not in ["Unknown", "Not Running", "-"] else "-"
                                        charon_display = charon_version if charon_version != "N/A" else "-"
                                        
                                        updated_table_data.append([
                                            f"🟢 {name}-{network_display_name}",
                                            exec_display,
                                            cons_display,
                                            val_display,
                                            charon_display
                                        ])
                                else:
                                    exec_client = version_info.get('execution_client', 'Unknown')
                                    exec_current = version_info.get('execution_current', 'Unknown')
                                    cons_client = version_info.get('consensus_client', 'Unknown')
                                    cons_current = version_info.get('consensus_current', 'Unknown')
                                    val_client = version_info.get('validator_client', '-')
                                    val_current = version_info.get('validator_current', '-')
                                    
                                    exec_display = f"{exec_client}/{exec_current}" if exec_client != "Unknown" else "-"
                                    cons_display = f"{cons_client}/{cons_current}" if cons_client != "Unknown" else "-"
                                    val_display = f"{val_client}/{val_current}" if val_client not in ["Unknown", "Disabled", "-"] and val_current not in ["Unknown", "Not Running", "-"] else "-"
                                    charon_display = charon_version if charon_version != "N/A" else "-"
                                    
                                    updated_table_data.append([
                                        f"🟢 {name}",
                                        exec_display,
                                        cons_display,
                                        val_display,
                                        charon_display
                                    ])
                            except Exception as e:
                                updated_table_data.append([
                                    f"❌ {name}",
                                    "Error",
                                    "Error", 
                                    "Error",
                                    "-"
                                ])
                    
                    if updated_table_data:
                        update_headers = ['Node', 'Execution Client', 'Consensus Client', 'Validator Client', 'Charon']
                        click.echo(tabulate(updated_table_data, headers=update_headers, tablefmt='fancy_grid', stralign='left'))
                        click.echo("\n✅ Upgrade summary:")
                        for node_name, success in upgrade_results:
                            status = "✅ Success" if success else "❌ Failed"
                            click.echo(f"  • {node_name}: {status}")
                    click.echo("="*70)
                else:
                    click.echo("ℹ️  Skipped upgrade.")
        else:
            # Check if we have many unknown statuses (❓)
            unknown_count = 0
            for row in compact_table:
                if len(row) > 4:  # Make sure row has enough columns
                    # Count ❓ symbols in update status columns (indices 4, 7, 10, 13)
                    unknown_count += sum(1 for i in [4, 7, 10, 13] if i < len(row) and '❓' in str(row[i]))
            
            if unknown_count > 0:
                click.echo("❓ Version check status unclear due to GitHub API issues - some versions may need updates")
            else:
                click.echo("✅ All nodes are up to date!")
        click.echo("=" * 70)
        return
    
    if not node:
        click.echo("❌ Please specify a node name or use --all flag")
        click.echo("Usage: python3 -m eth_validators node versions NODE")
        click.echo("   or: python3 -m eth_validators node versions --all")
        return
    
    # Show detailed versions and status for single node
    node_cfg = next(
        (n for n in config['nodes'] if n.get('tailscale_domain') == node or n.get('name') == node),
        None
    )
    if not node_cfg:
        click.echo(f"❌ Node {node} not found")
        return
    
    click.echo(f"🔍 Fetching detailed information for {node_cfg['name']}...")
    ssh_target = f"{node_cfg.get('ssh_user','root')}@{node_cfg['tailscale_domain']}"
    
    # Get status information using the same function as the old status command
    try:
        status_data = get_node_status(node_cfg)
        
        click.echo(f"\n🖥️  NODE: {node_cfg['name'].upper()}")
        click.echo("=" * 60)
        
        # Docker Containers Status
        click.echo(f"\n🐳 DOCKER CONTAINERS:")
        docker_status = status_data.get('docker_ps', 'Could not fetch docker status.')
        if docker_status != 'Could not fetch docker status.':
            click.echo(docker_status)
        else:
            click.echo("❌ Could not fetch container status")
        
        # Sync Status
        click.echo(f"\n🔄 SYNC STATUS:")
        sync_table = [
            ["Execution Client", status_data.get('execution_sync', 'Error')],
            ["Consensus Client", status_data.get('consensus_sync', 'Error')]
        ]
        click.echo(tabulate(sync_table, headers=["Client", "Sync Status"], tablefmt="fancy_grid"))
        
    except Exception as e:
        click.echo(f"⚠️  Could not fetch status information: {e}")
    
    # Check for Charon version (Obol nodes)
    charon_version = _get_charon_version(ssh_target, node_cfg['tailscale_domain'], node_cfg)
    
    # Check if Ethereum clients are disabled
    stack = node_cfg.get('stack', 'eth-docker')
    
    if (_is_stack_disabled(stack) or not _has_ethereum_clients(node_cfg)):
        # Check if this is a validator-only node (like Charon + validator clients)
        validator_info = _get_validator_only_clients(node_cfg)
        if validator_info and validator_info['has_clients']:
            click.echo(f"\n📋 CLIENT VERSIONS:")
            latest_charon = _get_latest_charon_version()
            charon_needs_update = (charon_version != "N/A" and 
                                 latest_charon != "Unknown" and 
                                 charon_version != latest_charon and 
                                 charon_version != "latest")
            charon_status = "🔄" if charon_needs_update else "✅"
            
            # Display all validator clients detected
            click.echo(f"🔗 Validator Infrastructure: {validator_info['display_name']}")
            if charon_version != "N/A":
                click.echo(f"   • Charon (Obol DV): {charon_version} (Latest: {latest_charon}) {charon_status}")
            
            # Show individual validator clients
            for client in validator_info['validator_clients']:
                if 'lodestar' in client.lower():
                    click.echo(f"   • Lodestar Validator: {client.split('/')[-1]}")
                elif 'vero' in client.lower():
                    click.echo(f"   • Vero Validator: {client.split('/')[-1]}")
            
            click.echo(f"ℹ️  This node runs validator infrastructure without execution/consensus clients")
        else:
            click.echo(f"\n📋 CLIENT VERSIONS:")
            if charon_version != "N/A":
                latest_charon = _get_latest_charon_version()
                charon_needs_update = (charon_version != "N/A" and 
                                     latest_charon != "Unknown" and 
                                     charon_version != latest_charon and 
                                     charon_version != "latest")
                charon_status = "🔄" if charon_needs_update else "✅"
                click.echo(f"🔗 Charon: {charon_version} (Latest: {latest_charon}) {charon_status}")
            else:
                click.echo(f"⚪ Node {node} has Ethereum clients disabled")
        return
    
    # Get detailed version information
    click.echo(f"\n📋 CLIENT VERSIONS:")
    
    try:
        version_info = get_docker_client_versions(node_cfg)
        
        # Display Charon version if available
        if charon_version != "N/A":
            latest_charon = _get_latest_charon_version()
            charon_needs_update = (charon_version != "N/A" and 
                                 latest_charon != "Unknown" and 
                                 charon_version != latest_charon and 
                                 charon_version != "latest")
            charon_status = "🔄" if charon_needs_update else "✅"
            click.echo(f"🔗 Charon: {charon_version} (Latest: {latest_charon}) {charon_status}")
        
        # Check if this is a multi-network result
        if 'mainnet' in version_info or 'testnet' in version_info:
            # Multi-network node
            for network_key, network_info in version_info.items():
                network_display_name = network_info.get('network', network_key)
                click.echo(f"\n🌐 Network: {network_display_name.upper()}")
                
                # Execution client
                exec_client = network_info.get('execution_client', 'Unknown')
                exec_current = network_info.get('execution_current', 'Unknown')
                exec_latest = network_info.get('execution_latest', 'Unknown')
                exec_needs_update = network_info.get('execution_needs_update', False)
                exec_status = "🔄" if exec_needs_update else "✅"
                click.echo(f"  ⚙️  Execution: {exec_client}/{exec_current} (Latest: {exec_latest}) {exec_status}")
                
                # Consensus client
                cons_client = network_info.get('consensus_client', 'Unknown')
                cons_current = network_info.get('consensus_current', 'Unknown')
                cons_latest = network_info.get('consensus_latest', 'Unknown')
                cons_needs_update = network_info.get('consensus_needs_update', False)
                cons_status = "🔄" if cons_needs_update else "✅"
                click.echo(f"  🔗 Consensus: {cons_client}/{cons_current} (Latest: {cons_latest}) {cons_status}")
        else:
            # Single network node
            exec_client = version_info.get('execution_client', 'Unknown')
            exec_current = version_info.get('execution_current', 'Unknown')
            exec_latest = version_info.get('execution_latest', 'Unknown')
            exec_needs_update = version_info.get('execution_needs_update', False)
            exec_status = "🔄" if exec_needs_update else "✅"
            
            cons_client = version_info.get('consensus_client', 'Unknown')
            cons_current = version_info.get('consensus_current', 'Unknown')
            cons_latest = version_info.get('consensus_latest', 'Unknown')
            cons_needs_update = version_info.get('consensus_needs_update', False)
            cons_status = "🔄" if cons_needs_update else "✅"
            
            val_client = version_info.get('validator_client', 'Unknown')
            val_current = version_info.get('validator_current', 'Unknown')
            val_latest = version_info.get('validator_latest', 'Unknown')
            val_needs_update = version_info.get('validator_needs_update', False)
            val_status = "🔄" if val_needs_update else "✅" if val_current not in ["Unknown", "Not Running"] else "-"
            
            click.echo(f"⚙️  Execution: {exec_client}/{exec_current} (Latest: {exec_latest}) {exec_status}")
            click.echo(f"🔗 Consensus: {cons_client}/{cons_current} (Latest: {cons_latest}) {cons_status}")
            
            if val_client != "Unknown" and val_current not in ["Unknown", "Not Running"] and val_client != "Disabled":
                click.echo(f"🔒 Validator: {val_client}/{val_current} (Latest: {val_latest}) {val_status}")
    
    except Exception as e:
        click.echo(f"❌ Error checking versions: {e}")
        
        # Fallback to ethd version command
        click.echo(f"\n📋 FALLBACK VERSION CHECK:")
        path = node_cfg.get('eth_docker_path', '~/eth-docker')
        cmd = f"ssh {ssh_target} \"cd {path} && ./ethd version\""
        subprocess.run(cmd, shell=True)

# ====================================
# Configuration Automation Commands  
# ====================================

@config_group.command(name='discover')
@click.option('--node', '-n', help='Discover specific node (default: all)')
@click.option('--save', '-s', is_flag=True, help='Save discovered configuration to config file')
@click.option('--output', '-o', help='Output file for discovered configuration')
def config_discover(node, save, output):
    """🔍 Discover current node configurations automatically"""
    from .config_automation import ConfigAutomationSystem
    
    click.echo("🔍 Starting automated configuration discovery...")
    
    automation = ConfigAutomationSystem(str(CONFIG_PATH))
    
    try:
        if node:
            # Discover single node - need to implement this method
            click.echo(f"❌ Single node discovery not implemented yet. Use --all flag.")
            return
        else:
            # Discover all nodes
            results = automation.sync_all_nodes()
            click.echo(f"\n📋 Discovery results for {results['total_nodes']} nodes:")
        
        # Display results
        if 'results' in results:
            for node_name, result in results['results'].items():
                click.echo(f"\n🖥️  {node_name}:")
                click.echo(f"   Status: {'✅ Success' if result.get('status') == 'success' else '❌ ' + result.get('reason', 'Unknown error')}")
                
                if result.get('discovery_data'):
                    data = result['discovery_data']
                    click.echo(f"   Stack: {', '.join(data.get('detected_stacks', ['Unknown']))}")
                    
                    if 'active_networks' in data:
                        networks = list(data['active_networks'].keys())
                        click.echo(f"   Networks: {', '.join(networks) if networks else 'None detected'}")
                    
                    if 'api_ports' in data:
                        ports = data['api_ports']
                        click.echo(f"   API Ports: {dict(ports)}")
        
        # Summary
        if results.get('updated_nodes', 0) > 0:
            click.echo(f"\n🔄 Updated {results['updated_nodes']} nodes: {', '.join(results.get('updated_node_names', []))}")
        
        # Save if requested
        if save or output:
            output_file = output or str(CONFIG_PATH)
            # Save functionality needs to be implemented
            click.echo(f"\n💾 Save functionality not yet implemented")
    
    except Exception as e:
        click.echo(f"❌ Discovery failed: {e}")
        raise click.Abort()

@config_group.command(name='validate')
@click.option('--config', '-c', default=str(CONFIG_PATH), help='Configuration file path')
@click.option('--fix', '-f', is_flag=True, help='Automatically fix detected issues')
@click.option('--report', '-r', help='Save validation report to file')
def config_validate(config, fix, report):
    """✅ Validate configuration and detect issues"""
    from .config_automation import ConfigAutomationSystem
    
    click.echo("✅ Starting configuration validation...")
    
    automation = ConfigAutomationSystem(config)
    
    try:
        issues, repairs = automation.validate_current_config(auto_repair=fix)
        
        if not issues:
            click.echo("🎉 Configuration is valid - no issues detected!")
            return
        
        click.echo(f"\n⚠️  Found {len(issues)} configuration issues:")
        
        # Group issues by severity
        critical = [i for i in issues if i.severity == 'critical']
        warning = [i for i in issues if i.severity == 'warning']
        info = [i for i in issues if i.severity == 'info']
        
        for severity, issue_list, emoji in [('CRITICAL', critical, '🚨'), ('WARNING', warning, '⚠️'), ('INFO', info, 'ℹ️')]:
            if issue_list:
                click.echo(f"\n{emoji} {severity} ({len(issue_list)} issues):")
                for issue in issue_list:
                    click.echo(f"   • {issue.node}: {issue.description}")
                    if issue.suggested_value:
                        click.echo(f"     💡 Suggested: {issue.suggested_value}")
        
        if repairs and fix:
            click.echo(f"\n🔧 Applied {len(repairs)} automatic repairs:")
            for repair in repairs:
                click.echo(f"   ✅ {repair.node}: {repair.description}")
        elif not fix and any(i.auto_fixable for i in issues):
            auto_fixable = len([i for i in issues if i.auto_fixable])
            click.echo(f"\n💡 {auto_fixable} issues can be automatically fixed with --fix flag")
        
        # Save report if requested
        if report:
            report_data = {
                'timestamp': time.time(),
                'total_issues': len(issues),
                'critical_issues': len(critical),
                'warning_issues': len(warning), 
                'info_issues': len(info),
                'repairs_applied': len(repairs) if repairs else 0,
                'issues': [
                    {
                        'node': i.node,
                        'type': i.issue_type,
                        'severity': i.severity,
                        'description': i.description,
                        'auto_fixable': i.auto_fixable
                    } for i in issues
                ]
            }
            
            with open(report, 'w') as f:
                json.dump(report_data, f, indent=2)
            
            click.echo(f"\n📄 Validation report saved to: {report}")
    
    except Exception as e:
        click.echo(f"❌ Validation failed: {e}")
        raise click.Abort()

@config_group.command(name='sync-all')
@click.option('--config', '-c', default=str(CONFIG_PATH), help='Configuration file path')
@click.option('--dry-run', '-d', is_flag=True, help='Show what would be changed without making changes')
def config_sync_all(config, dry_run):
    """🔄 Synchronize all node configurations with live state"""
    from .config_monitor import ConfigMonitor
    
    action = "Checking" if dry_run else "Synchronizing"
    click.echo(f"🔄 {action} all node configurations...")
    
    monitor = ConfigMonitor()
    
    try:
        if dry_run:
            # Use drift detection for dry run
            drift = monitor.detect_drift(config)
            
            if not drift:
                click.echo("✅ All configurations are in sync!")
                return
            
            click.echo(f"\n📋 Would update {len(set(d.node for d in drift))} nodes:")
            
            for drift_item in drift:
                click.echo(f"\n🖥️  {drift_item.node}:")
                click.echo(f"   Type: {drift_item.drift_type}")
                click.echo(f"   Current: {drift_item.config_state}")
                click.echo(f"   Live: {drift_item.live_state}")
                click.echo(f"   Auto-correctable: {'✅' if drift_item.auto_correctable else '❌'}")
        else:
            # Perform actual sync
            results = monitor.sync_all_nodes(config)
            
            click.echo(f"\n📊 Sync Results:")
            click.echo(f"   Total nodes: {results['total_nodes']}")
            click.echo(f"   Updated nodes: {results['updated_nodes']}")
            click.echo(f"   Updated node names: {', '.join(results['updated_node_names'])}")
            
            if results['updated_nodes'] > 0:
                click.echo(f"\n🎉 Successfully synchronized {results['updated_nodes']} nodes!")
            else:
                click.echo(f"\n✅ All nodes were already in sync!")
    
    except Exception as e:
        click.echo(f"❌ Sync failed: {e}")
        raise click.Abort()

@config_group.command(name='monitor')
@click.option('--config', '-c', default=str(CONFIG_PATH), help='Configuration file path')
@click.option('--interval', '-i', default=300, help='Check interval in seconds (default: 300)')
@click.option('--auto-fix', is_flag=True, help='Automatically fix detected drift')
def config_monitor(config, interval, auto_fix):
    """📡 Start continuous configuration monitoring"""
    from .config_monitor import ConfigMonitor
    
    click.echo(f"📡 Starting continuous configuration monitoring...")
    click.echo(f"   Check interval: {interval} seconds")
    click.echo(f"   Auto-fix enabled: {'✅' if auto_fix else '❌'}")
    click.echo(f"   Press Ctrl+C to stop")
    
    monitor = ConfigMonitor()
    
    try:
        monitor.monitor_continuous(config, interval, auto_fix)
    except KeyboardInterrupt:
        click.echo(f"\n⏹️  Monitoring stopped by user")
    except Exception as e:
        click.echo(f"❌ Monitoring failed: {e}")
        raise click.Abort()

@config_group.command(name='template')
@click.argument('action', type=click.Choice(['list', 'create', 'generate', 'export', 'import']))
@click.option('--name', '-n', help='Template name')
@click.option('--description', '-d', help='Template description')
@click.option('--stack', '-s', multiple=True, help='Supported stacks')
@click.option('--network', multiple=True, help='Supported networks')
@click.option('--file', '-f', help='File path for import/export/generation')
@click.option('--variables', help='Variables for template generation (JSON format)')
def config_template(action, name, description, stack, network, file, variables):
    """📝 Manage configuration templates"""
    from .config_templates import ConfigTemplateManager
    
    template_manager = ConfigTemplateManager()
    
    try:
        if action == 'list':
            templates = template_manager.list_templates()
            
            if not templates:
                click.echo("📝 No templates available")
                return
            
            click.echo(f"📝 Available templates ({len(templates)}):")
            
            for template_name, template in templates.items():
                click.echo(f"\n🔧 {template_name}")
                click.echo(f"   Description: {template.description}")
                click.echo(f"   Stacks: {', '.join(template.supported_stacks)}")
                click.echo(f"   Networks: {', '.join(template.supported_networks)}")
                click.echo(f"   Version: {template.version}")
        
        elif action == 'create':
            if not name:
                click.echo("❌ Template name is required for creation")
                raise click.Abort()
            
            # For demo, create a basic template
            basic_config = {
                "name": "{{node_name}}",
                "tailscale_domain": "{{node_name}}.ts.net",
                "ssh_user": "root",
                "ethereum_clients_enabled": True,
                "stack": list(stack) if stack else ["eth-docker"],
                "beacon_api_port": 5052
            }
            
            template = template_manager.create_template(
                name=name,
                description=description or "Custom template",
                base_config=basic_config,
                supported_stacks=list(stack) if stack else ["eth-docker"],
                supported_networks=list(network) if network else ["mainnet"]
            )
            
            click.echo(f"✅ Created template: {template.name}")
        
        elif action == 'generate':
            if not name:
                click.echo("❌ Template name is required for generation")
                raise click.Abort()
            
            # Parse variables
            var_dict = {}
            if variables:
                var_dict = json.loads(variables)
            
            # Generate configuration
            config = template_manager.generate_config_from_template(name, var_dict)
            
            if file:
                with open(file, 'w') as f:
                    yaml.dump(config, f, default_flow_style=False, indent=2)
                click.echo(f"💾 Generated configuration saved to: {file}")
            else:
                click.echo("🔧 Generated configuration:")
                click.echo(yaml.dump(config, default_flow_style=False, indent=2))
        
        elif action == 'export':
            if not name or not file:
                click.echo("❌ Template name and file path are required for export")
                raise click.Abort()
            
            template_manager.export_template(name, file)
            click.echo(f"📤 Template {name} exported to {file}")
        
        elif action == 'import':
            if not file:
                click.echo("❌ File path is required for import")
                raise click.Abort()
            
            template = template_manager.import_template(file)
            click.echo(f"📥 Template {template.name} imported successfully")
    
    except Exception as e:
        click.echo(f"❌ Template operation failed: {e}")
        raise click.Abort()

@config_group.command(name='summary')
@click.option('--config', '-c', default=str(CONFIG_PATH), help='Configuration file path')
def config_summary(config):
    """📊 Show configuration automation summary and statistics"""
    from .config_automation import ConfigAutomationSystem
    from .config_monitor import ConfigMonitor
    from .config_templates import ConfigTemplateManager
    
    click.echo("📊 Configuration Automation Summary\n")
    
    try:
        # Configuration status
        automation = ConfigAutomationSystem(config)
        validation_results = automation.validate_current_config(auto_repair=False)
        
        issues = validation_results[0]
        total_issues = len(issues)
        critical_issues = len([i for i in issues if i.severity == 'critical'])
        
        click.echo("🔧 Configuration Status:")
        click.echo(f"   Total issues: {total_issues}")
        click.echo(f"   Critical issues: {critical_issues}")
        click.echo(f"   Status: {'✅ Healthy' if total_issues == 0 else '⚠️ Needs attention'}")
        
        # Drift monitoring summary
        monitor = ConfigMonitor()
        monitor_summary = monitor.get_monitoring_summary()
        
        click.echo(f"\n📡 Drift Monitoring (24h):")
        click.echo(f"   Total drift events: {monitor_summary['total_drift_events_24h']}")
        click.echo(f"   Critical drift: {monitor_summary['critical_drift_24h']}")
        click.echo(f"   Nodes affected: {monitor_summary['nodes_with_drift_24h']}")
        click.echo(f"   Auto-correctable: {monitor_summary['auto_correctable_24h']}")
        
        # Template summary
        template_manager = ConfigTemplateManager()
        template_summary = template_manager.get_template_summary()
        
        click.echo(f"\n📝 Templates:")
        click.echo(f"   Total templates: {template_summary['total_templates']}")
        click.echo(f"   Available stacks: {', '.join(template_summary['templates_by_stack'].keys())}")
        
        # Node count from config
        with open(config, 'r') as f:
            config_data = yaml.safe_load(f)
        
        total_nodes = len(config_data.get('nodes', []))
        enabled_nodes = len([n for n in config_data.get('nodes', []) if n.get('ethereum_clients_enabled', True)])
        
        click.echo(f"\n🖥️  Cluster Overview:")
        click.echo(f"   Total nodes: {total_nodes}")
        click.echo(f"   Enabled nodes: {enabled_nodes}")
        click.echo(f"   Disabled nodes: {total_nodes - enabled_nodes}")
        
    except Exception as e:
        click.echo(f"❌ Failed to generate summary: {e}")
        raise click.Abort()

if __name__ == "__main__":
    cli()

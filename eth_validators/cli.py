import click
import yaml
import subprocess
import time
import csv
import json
from pathlib import Path
from tabulate import tabulate
import re
from . import performance
from .config import get_node_config, get_all_node_configs
from .performance import get_performance_summary
from .node_manager import get_node_status, upgrade_node_docker_clients, get_system_update_status, perform_system_upgrade, get_docker_client_versions
from .ai_analyzer import ValidatorLogAnalyzer
from .validator_sync import ValidatorSyncManager, get_active_validators_only
from .validator_editor import InteractiveValidatorEditor

CONFIG_PATH = Path(__file__).parent / 'config.yaml'

def _get_charon_version(ssh_target, tailscale_domain):
    """Get Charon version if it's running on the node"""
    try:
        # First try to get the actual running version by executing charon version
        cmd = f"ssh -o ConnectTimeout=10 -o BatchMode=yes {ssh_target} \"docker ps --format 'table {{{{.Names}}}}' | grep charon | head -1\""
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        
        if result.returncode == 0 and result.stdout.strip():
            container_name = result.stdout.strip()
            
            # Try to get actual version from the running container
            version_cmd = f"ssh -o ConnectTimeout=10 -o BatchMode=yes {ssh_target} \"docker exec {container_name} charon version 2>/dev/null | head -1 | awk '{{print $NF}}' || echo 'exec_failed'\""
            version_result = subprocess.run(version_cmd, shell=True, capture_output=True, text=True, timeout=10)
            
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
            image_cmd = f"ssh -o ConnectTimeout=10 -o BatchMode=yes {ssh_target} \"docker ps --format 'table {{{{.Names}}}}\\t{{{{.Image}}}}' | grep charon | head -1 | awk '{{print $2}}'\""
            image_result = subprocess.run(image_cmd, shell=True, capture_output=True, text=True, timeout=10)
            
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

# Validator Management Group
@cli.group(name='validator')
def validator_group():
    """👥 Validator lifecycle management and duty coordination"""
    pass

def _check_reboot_needed(ssh_user, tailscale_domain):
    """Check if a node needs a reboot by checking for reboot-required file"""
    try:
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
            
            clients = f"⚙️  {exec_client} + 🔗 {consensus_client}"

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
    container_cmd = f"ssh {ssh_target} \"docker ps --format 'table {{{{.Names}}}}\\t{{{{.Status}}}}' | grep -E 'validator|hyperdrive|charon'\""
    
    try:
        process = subprocess.run(container_cmd, shell=True, capture_output=True, text=True, timeout=15)
        if process.returncode == 0:
            lines = process.stdout.strip().split('\n')
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
        latest_charon = _get_latest_charon_version()
        table_data = []
        active_nodes = 0
        disabled_nodes = 0
        for node_cfg in nodes:
            name = node_cfg['name']
            stack = node_cfg.get('stack', ['eth-docker'])
            if isinstance(stack, str):
                stack = [stack]
            status_emoji = "🟢"
            status_text = "Active"
            exec_display = cons_display = val_display = charon_display = "-"
            exec_latest_display = cons_latest_display = val_latest_display = charon_latest_display = "-"
            exec_update = cons_update = val_update = charon_update = "-"
            # Disabled node logic
            if _is_stack_disabled(stack) or node_cfg.get('ethereum_clients_enabled') is False:
                status_emoji = "🔴"
                status_text = "Disabled"
                disabled_nodes += 1
            else:
                active_nodes += 1
                ssh_target = f"{node_cfg.get('ssh_user', 'root')}@{node_cfg['tailscale_domain']}"
                charon_version = _get_charon_version(ssh_target, node_cfg['tailscale_domain'])
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
                            exec_latest_display = exec_latest if exec_latest not in ["Unknown", "API Error", "Network Error"] else "-"
                            exec_update = '🔄' if exec_needs_update else '✅'
                            cons_display = f"{cons_client}/{cons_current}" if cons_client != "Unknown" else "-"
                            cons_latest_display = cons_latest if cons_latest not in ["Unknown", "API Error", "Network Error"] else "-"
                            cons_update = '🔄' if cons_needs_update else '✅'
                            val_display = f"{val_client}/{val_current}" if val_client not in ["Unknown", "Disabled", "-"] and val_current not in ["Unknown", "Not Running", "-"] else "-"
                            val_latest_display = val_latest if val_latest not in ["Unknown", "Not Running", "Disabled", "-"] else "-"
                            val_update = '🔄' if val_needs_update else '✅' if val_display != "-" else '-'
                            charon_display = charon_version if charon_version != "N/A" else "-"
                            charon_latest_display = latest_charon if charon_version != "N/A" else "-"
                            charon_update = '🔄' if charon_needs_update else '✅' if charon_version != "N/A" else '-'
                            table_data.append([
                                f"{status_emoji} {name}-{network_display_name}", status_text, exec_display, exec_latest_display, exec_update, cons_display, cons_latest_display, cons_update, val_display, val_latest_display, val_update, charon_display, charon_latest_display, charon_update
                            ])
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
                    exec_update = '🔄' if exec_needs_update else '✅'
                    cons_display = f"{cons_client}/{cons_current}" if cons_client != "Unknown" else "-"
                    cons_latest_display = cons_latest if cons_latest not in ["Unknown", "API Error", "Network Error"] else "-"
                    cons_update = '🔄' if cons_needs_update else '✅'
                    val_display = f"{val_client}/{val_current}" if val_client not in ["Unknown", "Disabled", "-"] and val_current not in ["Unknown", "Not Running", "-"] else "-"
                    val_latest_display = val_latest if val_latest not in ["Unknown", "Not Running", "Disabled", "-"] else "-"
                    val_update = '🔄' if val_needs_update else '✅' if val_display != "-" else '-'
                    charon_display = charon_version if charon_version != "N/A" else "-"
                    charon_latest_display = latest_charon if charon_version != "N/A" else "-"
                    charon_update = '🔄' if charon_needs_update else '✅' if charon_version != "N/A" else '-'
                    table_data.append([
                        f"{status_emoji} {name}", status_text, exec_display, exec_latest_display, exec_update, cons_display, cons_latest_display, cons_update, val_display, val_latest_display, val_update, charon_display, charon_latest_display, charon_update
                    ])
                except Exception as e:
                    table_data.append([
                        f"{status_emoji} {name}", status_text, 'Error', '-', '❌', 'Error', '-', '❌', 'Error', '-', '❌', '-', '-', '-'
                    ])
            # Disabled node row
            if status_text == "Disabled":
                table_data.append([
                    f"{status_emoji} {name}", status_text, '❌ No clients', '-', '-', '❌ No clients', '-', '-', '-', '-', '-', '-', '-', '-'
                ])
        headers = ['Node Name', 'Status', 'Execution', 'Exec Latest', 'Exec Update', 'Consensus', 'Cons Latest', 'Cons Update', 'Validator', 'Val Latest', 'Val Update', 'Charon', 'Charon Latest', 'Charon Update']
        click.echo("\nRendering table...")
        click.echo(tabulate(table_data, headers=headers, tablefmt='fancy_grid'))
        click.echo(f"\n📊 CLUSTER SUMMARY:")
        click.echo(f"  🟢 Active nodes: {active_nodes}")
        click.echo(f"  � Disabled nodes: {disabled_nodes}")
        click.echo(f"  � Total nodes: {len(nodes)}")
        click.echo(f"\n💡 Use 'node upgrade --all' to update all nodes.")
        click.echo("=" * 100)
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
    charon_version = _get_charon_version(ssh_target, node_cfg['tailscale_domain'])
    
    # Check if Ethereum clients are disabled
    stack = node_cfg.get('stack', 'eth-docker')
    
    if (_is_stack_disabled(stack) or not _has_ethereum_clients(node_cfg)):
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

if __name__ == "__main__":
    cli()

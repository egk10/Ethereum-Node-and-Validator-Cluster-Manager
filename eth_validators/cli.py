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

def _is_stack_disabled(stack):
    """Check if stack is disabled - supports both string and list format"""
    if isinstance(stack, list):
        return 'disabled' in stack
    else:
        return stack == 'disabled'

def _has_ethereum_clients(node_cfg):
    """Check if node has Ethereum clients configured"""
    # Check for clients in single network format
    exec_client = node_cfg.get('exec_client', '')
    consensus_client = node_cfg.get('consensus_client', '')
    has_clients = bool(exec_client and consensus_client)
    
    # If no clients at root level, check networks
    if not has_clients:
        networks = node_cfg.get('networks', {})
        for network_key, network_config in networks.items():
            net_exec = network_config.get('exec_client', '')
            net_consensus = network_config.get('consensus_client', '')
            if net_exec and net_consensus:
                has_clients = True
                break
    
    return has_clients

@click.group()
def cli():
    """🚀 Ethereum Node and Validator Cluster Manager"""
    pass

# AI Smart Performance Group
@cli.group(name='ai')
def ai_group():
    """🧠 AI-powered analysis and monitoring tools"""
    pass

# Performance Monitoring Group  
@cli.group(name='performance')
def performance_group():
    """📊 Validator performance monitoring and analysis"""
    pass

# Node Management Group
@cli.group(name='node')
def node_group():
    """🖥️ Node management and operations"""
    pass

# System Administration Group
@cli.group(name='system')
def system_group():
    """⚙️ System updates and maintenance"""
    pass

# Validator Management Group
@cli.group(name='validator')
def validator_group():
    """👥 Validator lifecycle and status management"""
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
    """List all configured nodes"""
    config = yaml.safe_load(CONFIG_PATH.read_text())
    nodes = config.get('nodes', [])
    
    if not nodes:
        click.echo("❌ No nodes found in configuration")
        return
    
    click.echo("🖥️  ETHEREUM NODE CLUSTER OVERVIEW")
    click.echo("=" * 80)
    
    # Prepare table data
    table_data = []
    active_nodes = 0
    disabled_nodes = 0
    
    # Track client diversity
    exec_clients = {}
    consensus_clients = {}
    
    for node in nodes:
        name = node['name']
        tailscale = node['tailscale_domain']
        ssh_user = node.get('ssh_user', 'root')
        exec_client = node.get('exec_client', '')
        consensus_client = node.get('consensus_client', '')
        stack = node.get('stack', ['eth-docker'])
        
        # Handle both old format (string) and new format (list)
        if isinstance(stack, str):
            stack = [stack]
        
        # Determine status
        if ('disabled' in stack or 
            (not exec_client and not consensus_client) or
            (exec_client == '' and consensus_client == '')):
            status_emoji = "🔴"
            status_text = "Disabled"
            disabled_nodes += 1
        else:
            status_emoji = "🟢"
            status_text = "Active"
            active_nodes += 1
            
            # Track client diversity (only for active nodes)
            if exec_client:
                exec_clients[exec_client] = exec_clients.get(exec_client, 0) + 1
            if consensus_client:
                consensus_clients[consensus_client] = consensus_clients.get(consensus_client, 0) + 1
        
        # Format client info with emojis
        if exec_client and consensus_client:
            clients = f"⚙️ {exec_client} + 🔗 {consensus_client}"
        elif exec_client:
            clients = f"⚙️ {exec_client} (exec only)"
        elif consensus_client:
            clients = f"🔗 {consensus_client} (consensus only)"
        else:
            clients = "❌ No clients"
        
        # Stack info with emojis - handle multiple stacks
        stack_emojis = {
            'eth-docker': '🐳',
            'disabled': '🚫',
            'rocketpool': '🚀',
            'obol': '🔗',
            'hyperdrive': '⚡',
            'charon': '🌐',
            'ssv': '📡',
            'stakewise': '🏦'
        }
        
        if 'disabled' in stack:
            stack_display = "🚫 disabled"
        else:
            # Create display for multiple stacks
            stack_parts = []
            for s in stack:
                emoji = stack_emojis.get(s.lower(), '⚙️')
                stack_parts.append(f"{emoji} {s}")
            stack_display = " + ".join(stack_parts)
        
        table_data.append([
            f"{status_emoji} {name}",
            status_text,
            clients,
            stack_display
        ])
    
    # Display table
    headers = ['Node Name', 'Status', 'Ethereum Clients', 'Stack']
    click.echo(tabulate(table_data, headers=headers, tablefmt='fancy_grid'))
    
    # Summary statistics
    click.echo(f"\n📊 CLUSTER SUMMARY:")
    click.echo(f"  🟢 Active nodes: {active_nodes}")
    click.echo(f"  🔴 Disabled nodes: {disabled_nodes}")
    click.echo(f"  📈 Total nodes: {len(nodes)}")
    
    # Client diversity analysis
    if exec_clients or consensus_clients:
        click.echo(f"\n🌐 CLIENT DIVERSITY:")
        if exec_clients:
            exec_total = sum(exec_clients.values())
            click.echo(f"  ⚙️  Execution clients:")
            for client, count in exec_clients.items():
                percentage = (count / exec_total) * 100
                click.echo(f"    • {client}: {count} node(s) ({percentage:.1f}%)")
        
        if consensus_clients:
            consensus_total = sum(consensus_clients.values())
            click.echo(f"  🔗 Consensus clients:")
            for client, count in consensus_clients.items():
                percentage = (count / consensus_total) * 100
                click.echo(f"    • {client}: {count} node(s) ({percentage:.1f}%)")
        
        # Diversity warning
        if exec_clients and len(exec_clients) == 1:
            click.echo(f"  ⚠️  WARNING: All execution clients are the same type!")
        if consensus_clients and len(consensus_clients) == 1:
            click.echo(f"  ⚠️  WARNING: All consensus clients are the same type!")
    
    # Quick access info
    click.echo(f"\n💡 QUICK ACCESS:")
    click.echo(f"  📋 Detailed status: python -m eth_validators node status <node_name>")
    click.echo(f"  🔧 Node analysis: python -m eth_validators node analyze <node_name>")
    click.echo(f"  🧠 AI analysis: python -m eth_validators ai analyze <node_name>")
    click.echo("=" * 80)
    

@node_group.command(name='status')
@click.argument('node', required=False)
@click.option('--all', 'show_all', is_flag=True, help="Show status for all nodes")
@click.option('--images', is_flag=True, help="Show full image names")
def status_cmd(node, show_all, images):
    """Show status of one or all nodes"""
    if show_all:
        # Show status for all nodes
        config = yaml.safe_load(CONFIG_PATH.read_text())
        nodes = config.get('nodes', [])
        
        if not nodes:
            click.echo("❌ No nodes found in configuration")
            return
            
        click.echo("🖥️  CLUSTER STATUS OVERVIEW")
        click.echo("=" * 80)
        
        for node_cfg in nodes:
            node_name = node_cfg['name']
            click.echo(f"\n📡 Node: {node_name}")
            click.echo("-" * 40)
            
            status_data = get_node_status(node_cfg)
            
            # Show brief status
            exec_status = status_data.get('execution_sync', 'Error')
            consensus_status = status_data.get('consensus_sync', 'Error')
            
            click.echo(f"Execution Client: {exec_status}")
            click.echo(f"Consensus Client: {consensus_status}")
            
    elif node:
        # Show detailed status for specific node
        print(f"Fetching status for {node}...")
        node_config = get_node_config(node)
        if not node_config:
            print(f"Node '{node}' not found in config.yaml.")
            return

        status_data = get_node_status(node_config)

        print("\n--- Docker Containers ---")
        print(status_data.get('docker_ps', 'Could not fetch docker status.'))

        print("\n--- Sync Status ---")
        table_data = [
            ["Execution Client", status_data.get('execution_sync', 'Error')],
            ["Consensus Client", status_data.get('consensus_sync', 'Error')]
        ]
        print(tabulate(table_data, headers=["Client", "Status"], tablefmt="plain"))
        
        if images:
            # Show container images
            node_cfg = get_node_config(node)
            if node_cfg:
                ssh_target = f"root@{node_cfg['tailscale_domain']}"
                compose_dir = node_cfg['eth_docker_path']
                img_cmd = f"ssh {ssh_target} \"cd {compose_dir} && docker compose images\""
                subprocess.run(img_cmd, shell=True)
    else:
        click.echo("❌ Please specify a node name or use --all flag")
        click.echo("Usage: eth-validators node status <node_name>")
        click.echo("       eth-validators node status --all")

@node_group.command(name='upgrade')
@click.argument('node', required=False)
@click.option('--all', 'upgrade_all', is_flag=True, help="Upgrade all nodes")
def upgrade_cmd(node, upgrade_all):
    """Run upgrade on one or all nodes"""
    config = yaml.safe_load(CONFIG_PATH.read_text())
    
    if upgrade_all:
        # Upgrade all nodes
        click.echo("🔄 Starting upgrade for all nodes...")
        
        for node_cfg in config.get('nodes', []):
            node_name = node_cfg['name']
            
            # Check if Ethereum clients are disabled
            stack = node_cfg.get('stack', 'eth-docker')
            if (_is_stack_disabled(stack) or not _has_ethereum_clients(node_cfg)):
                click.echo(f"⚪ Skipping {node_name} (Ethereum clients disabled)")
                continue
            
            click.echo(f"🔄 Upgrading {node_name}...")
            result = upgrade_node_docker_clients(node_cfg)
            
            if 'overall_success' in result:
                # Multi-network node
                if result['overall_success']:
                    click.echo(f"✅ {node_name} upgrade completed successfully for all networks")
                else:
                    click.echo(f"❌ {node_name} upgrade had some failures")
            else:
                # Single network node
                if result.get('upgrade_success'):
                    click.echo(f"✅ {node_name} upgrade completed successfully")
                else:
                    click.echo(f"❌ {node_name} upgrade failed")
                    if result.get('upgrade_error'):
                        click.echo(f"   Error: {result['upgrade_error']}")
                        
    elif node:
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
                        click.echo(f"    Error: {network_result['upgrade_error']}")
        else:
            # Single network node
            if result.get('upgrade_success'):
                click.echo(f"✅ {node} upgrade completed successfully")
            else:
                click.echo(f"❌ {node} upgrade failed")
                if result.get('upgrade_error'):
                    click.echo(f"   Error: {result['upgrade_error']}")
    else:
        click.echo("❌ Please specify a node name or use --all flag")
        click.echo("Usage: eth-validators node upgrade <node_name>")
        click.echo("       eth-validators node upgrade --all")

@node_group.command(name='versions')
@click.argument('node', required=False)
@click.option('--all', 'show_all', is_flag=True, help="Show versions for all nodes")
def versions_cmd(node, show_all):
    """Show client versions for one or all nodes"""
    config = yaml.safe_load(CONFIG_PATH.read_text())
    
    if show_all:
        # Show versions for all nodes (replacing versions-all)
        table = []
        
        click.echo("🔍 Fetching client versions and checking GitHub for latest releases...")
        
        for node_cfg in config.get('nodes', []):
            name = node_cfg['name']
            
            # Skip nodes with disabled eth-docker
            stack = node_cfg.get('stack', 'eth-docker')
            
            if (_is_stack_disabled(stack) or not _has_ethereum_clients(node_cfg)):
                click.echo(f"  ⚪ Skipping {name} (Ethereum clients disabled)")
                continue
                
            click.echo(f"  📡 Checking {name}...", nl=False)
            
            # Get versions using our Docker detection method
            try:
                version_info = get_docker_client_versions(node_cfg)
            except:
                version_info = {}
            
            click.echo(" ✅")
            
            # Extract version information
            exec_current = version_info.get('execution_current', 'N/A')
            exec_latest = version_info.get('execution_latest', 'Unknown')
            exec_client = version_info.get('execution_client', 'Unknown')
            exec_needs_update = version_info.get('execution_needs_update', False)
            
            cons_current = version_info.get('consensus_current', 'N/A')
            cons_latest = version_info.get('consensus_latest', 'Unknown')
            cons_client = version_info.get('consensus_client', 'Unknown')
            cons_needs_update = version_info.get('consensus_needs_update', False)
            
            # Format display
            exec_display = f"{exec_client}/{exec_current}" if exec_current != 'N/A' else 'N/A'
            cons_display = f"{cons_client}/{cons_current}" if cons_current != 'N/A' else 'N/A'
            
            # Status indicators
            exec_status = "🔄" if exec_needs_update else "✅"
            cons_status = "🔄" if cons_needs_update else "✅"
            
            table.append([
                name,
                f"{exec_status} {exec_display}",
                f"{cons_status} {cons_display}"
            ])
        
        if table:
            click.echo("\n📊 CLIENT VERSIONS OVERVIEW")
            click.echo("=" * 60)
            headers = ["Node", "Execution Client", "Consensus Client"]
            click.echo(tabulate(table, headers=headers, tablefmt="grid"))
        else:
            click.echo("❌ No active Ethereum nodes found")
            
    elif node:
        # Show versions for specific node
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
            click.echo(f"⚪ {node} has Ethereum clients disabled")
            return
        
        click.echo(f"🔍 Fetching versions for {node}...")
        
        try:
            version_info = get_docker_client_versions(node_cfg)
            
            click.echo(f"\n📊 CLIENT VERSIONS FOR {node.upper()}")
            click.echo("=" * 50)
            
            # Display execution client info
            exec_client = version_info.get('execution_client', 'Unknown')
            exec_current = version_info.get('execution_current', 'N/A')
            exec_latest = version_info.get('execution_latest', 'Unknown')
            exec_needs_update = version_info.get('execution_needs_update', False)
            
            click.echo(f"⚙️  Execution Client: {exec_client}")
            click.echo(f"   Current Version: {exec_current}")
            click.echo(f"   Latest Version: {exec_latest}")
            click.echo(f"   Status: {'🔄 Update Available' if exec_needs_update else '✅ Up to Date'}")
            
            # Display consensus client info
            cons_client = version_info.get('consensus_client', 'Unknown')
            cons_current = version_info.get('consensus_current', 'N/A')
            cons_latest = version_info.get('consensus_latest', 'Unknown')
            cons_needs_update = version_info.get('consensus_needs_update', False)
            
            click.echo(f"\n🔗 Consensus Client: {cons_client}")
            click.echo(f"   Current Version: {cons_current}")
            click.echo(f"   Latest Version: {cons_latest}")
            click.echo(f"   Status: {'🔄 Update Available' if cons_needs_update else '✅ Up to Date'}")
            
        except Exception as e:
            click.echo(f"❌ Error fetching versions: {e}")
    else:
        click.echo("❌ Please specify a node name or use --all flag")
        click.echo("Usage: eth-validators node versions <node_name>")
        click.echo("       eth-validators node versions --all")

# Now remove the old redundant commands that have been replaced
# Remove upgrade-all command (now handled by upgrade --all)
# We need to find and remove the old @node_group.command(name='upgrade-all')
        )
        output = result.stdout + result.stderr
        
        # Identify components
        exec_comp = node_cfg.get('exec_client', '')
        cons_comp = node_cfg.get('consensus_client', '')
        mev_comp = 'mev-boost'
        
        def find_version(output, keyword):
            lines = output.splitlines()
            
            # Handle Nethermind special case (multiline version info)
            if keyword.lower() == 'nethermind':
                for i, line in enumerate(lines):
                    if 'Nethermind version' in line and i + 1 < len(lines):
                        next_line = lines[i + 1].strip()
                        if next_line.startswith('Version:'):
                            version = next_line.split('Version:')[1].strip().split('+')[0]
                            return version
            
            # Handle Geth special case (multiline version info)
            if keyword.lower() == 'geth':
                for i, line in enumerate(lines):
                    if line.strip() == 'Geth' and i + 1 < len(lines):
                        next_line = lines[i + 1].strip()
                        if next_line.startswith('Version:'):
                            version = next_line.split('Version:')[1].strip().split('-')[0]
                            return version
            
            for line in lines:
                line = line.strip()
                if keyword.lower() in line.lower():
                    # Extract just version number
                    if keyword.lower() == 'reth' and 'reth-ethereum-cli Version:' in line:
                        version = line.split('Version:')[1].strip()
                        return version
                    elif keyword.lower() == 'besu' and 'besu/v' in line:
                        version = line.split('/v')[1].split('/')[0]
                        return version
                    elif keyword.lower() == 'lighthouse' and line.startswith('Lighthouse v'):
                        version = line.split('v')[1].split('-')[0]
                        return version
                    elif keyword.lower() == 'nimbus' and 'Nimbus beacon node v' in line:
                        version = line.split('v')[1].split('-')[0]
                        return version
                    elif keyword.lower() == 'teku' and 'teku/v' in line:
                        version = line.split('/v')[1].split('/')[0]
                        return version
                    elif keyword.lower() == 'grandine' and line.startswith('Grandine '):
                        version = line.split()[1].split('-')[0]
                        return version
                    elif keyword.lower() == 'prysm' and 'prysm' in line.lower():
                        return "(detected)"
                    elif keyword.lower() == 'lodestar' and 'lodestar' in line.lower():
                        return "(detected)"
            
            # Special case for MEV Boost
            if keyword.lower() == 'mev-boost':
                for line in lines:
                    if 'mev-boost v' in line:
                        version = line.split('mev-boost v')[1].strip()
                        return version
            
            return "N/A"
        
        # Get current versions
        exec_current = find_version(output, exec_comp)
        cons_current = find_version(output, cons_comp)
        mev_current = find_version(output, mev_comp)
        
        # Get latest versions from our version info
        exec_latest = version_info.get('execution_latest', 'Unknown')
        cons_latest = version_info.get('consensus_latest', 'Unknown') 
        exec_needs_update = version_info.get('execution_needs_update', False)
        cons_needs_update = version_info.get('consensus_needs_update', False)
        
        # Detect validator client stack from configured protocol in CSV or containers
        validator_client = "Unknown"
        validator_status = "❓"
        
        # Enhanced validator detection based on node name and known configurations
        def detect_validator_stack(node_name):
            # Map based on your current setup described
            validator_mapping = {
                'minipcamd': '🎯 VERO (CSM LIDO)',
                'minipcamd2': '🎯 VERO (CSM LIDO)', 
                'minipcamd3': '🎯 Multi-Stack (VERO+Obol+SW)',
                'orangepi5-plus': '🎯 Obol DVT (Etherfi)',
                'minitx': '🎯 Rocketpool',
                'laptop': '🎯 Eth-Docker Only',
                'opi5': '🎯 Unknown Stack'
            }
            return validator_mapping.get(node_name, '🎯 Unknown Stack')
        
        validator_client = detect_validator_stack(name)
        validator_status = "✅" if validator_client != '🎯 Unknown Stack' else "❓"
        
        # Format client names with emojis
        exec_display = f"⚡ {exec_comp.capitalize()}" if exec_comp else "❓ Unknown"
        cons_display = f"⛵ {cons_comp.capitalize()}" if cons_comp else "❓ Unknown"
        mev_display = "🚀 MEV-Boost"
        
        # Format versions with status
        exec_current_display = f"{exec_current}" if exec_current != "N/A" else "❌"
        cons_current_display = f"{cons_current}" if cons_current != "N/A" else "❌"
        mev_current_display = f"{mev_current}" if mev_current != "N/A" else "❌"
        
        exec_latest_display = exec_latest if exec_latest != "Unknown" else "❓"
        cons_latest_display = cons_latest if cons_latest != "Unknown" else "❓"
        
        # Status indicators with more prominent update warnings
        exec_status = "⚠️🔄" if exec_needs_update else "✅" if exec_current != "N/A" else "❌"
        cons_status = "⚠️🔄" if cons_needs_update else "✅" if cons_current != "N/A" else "❌"
        mev_status = "✅" if mev_current != "N/A" else "❌"
        
        # Special handling for some edge cases
        if exec_latest == "Network Error" or exec_latest == "Unknown":
            exec_status = "⚠️❓" if exec_current != "N/A" else "❌"
        if cons_latest == "Network Error" or cons_latest == "Unknown":
            cons_status = "⚠️❓" if cons_current != "N/A" else "❌"
        
        table.append([
            f"🖥️  {name}",
            exec_display,
            exec_current_display,
            exec_latest_display,
            exec_status,
            cons_display,
            cons_current_display, 
            cons_latest_display,
            cons_status,
            validator_client,
            validator_status,
            mev_display,
            mev_current_display,
            mev_status
        ])
        
        click.echo(" ✅")
    
    # Display results in a fun table format
    if table:
        headers = [
            '🎯 Node', 
            '⚡ Execution Client', 'Current', 'Latest', '📊',
            '⛵ Consensus Client', 'Current', 'Latest', '📊',
            '🎯 Validator Client', '📊',
            '🚀 MEV Boost', 'Version', '📊'
        ]
        
        click.echo("\n" + "="*120)
        click.echo("🎉 ETHEREUM VALIDATOR CLUSTER - CLIENT VERSIONS DASHBOARD 🎉")
        click.echo("="*120)
        click.echo(tabulate(table, headers=headers, tablefmt='fancy_grid'))
        
        # Fun summary with emojis
        total_nodes = len(table)
        exec_updates_needed = sum(1 for row in table if "🔄" in row[4])
        cons_updates_needed = sum(1 for row in table if "🔄" in row[8])
        exec_warnings = sum(1 for row in table if "❓" in row[4])
        cons_warnings = sum(1 for row in table if "❓" in row[8])
        validator_active = sum(1 for row in table if "✅" in row[10])
        all_good = exec_updates_needed == 0 and cons_updates_needed == 0
        
        click.echo("\n" + "🎊 CLUSTER SUMMARY 🎊")
        click.echo(f"📈 Total Nodes: {total_nodes}")
        click.echo(f"🎯 Active Validator Clients: {validator_active}")
        click.echo(f"⚠️🔄 Execution clients needing updates: {exec_updates_needed}")
        if exec_warnings > 0:
            click.echo(f"⚠️❓ Execution clients with warnings: {exec_warnings}")
        click.echo(f"⚠️🔄 Consensus clients needing updates: {cons_updates_needed}")
        if cons_warnings > 0:
            click.echo(f"⚠️❓ Consensus clients with warnings: {cons_warnings}")
        
        if all_good and exec_warnings == 0 and cons_warnings == 0:
            click.echo("🎉 🌟 ALL CLIENTS ARE UP TO DATE! 🌟 🎉")
        else:
            click.echo("🔧 Some clients need attention - use 'client-versions' for detailed comparison!")
            click.echo("💡 Run 'python -m eth_validators upgrade-all' to update all nodes")
        
        click.echo("="*120)
    else:
        click.echo("❌ No version information collected.")

@node_group.command(name='analyze')
@click.argument('node_name')
def analyze_node_cmd(node_name):
    """Analyze all validators for a specific node in detail"""
    config = yaml.safe_load(CONFIG_PATH.read_text())
    node_cfg = next(
        (n for n in config['nodes'] if n.get('tailscale_domain') == node_name or n.get('name') == node_name),
        None
    )
    if not node_cfg:
        click.echo(f"Node {node_name} not found")
        return
    
    click.echo(f"🔍 Analyzing all validators for {node_cfg['name']}...")
    
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
    """Fetch performance metrics for all validators"""
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


@node_group.command(name='upgrade-all')
def upgrade_all():
    """Upgrade all configured nodes with active Ethereum clients"""
    config = yaml.safe_load(CONFIG_PATH.read_text())
    for node_cfg in config.get('nodes', []):
        name = node_cfg['name']
        
        # Skip nodes with disabled eth-docker
        stack = node_cfg.get('stack', 'eth-docker')
        
        if (_is_stack_disabled(stack) or not _has_ethereum_clients(node_cfg)):
            click.echo(f"⚪ Skipping {name} (Ethereum clients disabled)")
            continue
            
        click.echo(f"Upgrading {name}...")
        ssh_target = f"{node_cfg.get('ssh_user','root')}@{node_cfg['tailscale_domain']}"
        eth_docker_path = node_cfg['eth_docker_path']
        cmd = (
            f"ssh {ssh_target} '"
            f"git config --global --add safe.directory {eth_docker_path} && "
            f"cd {eth_docker_path} && git checkout main && git pull && "
            "docker compose pull && docker compose build --pull && docker compose up -d'"
        )
        subprocess.run(cmd, shell=True)

@node_group.command(name='versions')
@click.argument('node')
def versions(node):
    """Show client versions for a node"""
    config = yaml.safe_load(CONFIG_PATH.read_text())
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
        click.echo(f"⚪ Node {node} has Ethereum clients disabled")
        return
        
    ssh_target = f"{node_cfg.get('ssh_user','root')}@{node_cfg['tailscale_domain']}"
    path = node_cfg['eth_docker_path']
    # Run full .ethd version remotely
    cmd = f"ssh {ssh_target} \"cd {path} && ./ethd version\""
    subprocess.run(cmd, shell=True)

@node_group.command(name='client-versions')
@click.argument('node_name', required=False)
def client_versions(node_name):
    """Check Ethereum client versions for Docker containers"""
    config = yaml.safe_load(CONFIG_PATH.read_text())
    nodes = config.get('nodes', [])
    
    if not nodes:
        click.echo("❌ No nodes configured. Please check your config.yaml file.")
        return
    
    # Filter nodes if specific node requested
    if node_name:
        nodes = [node for node in nodes if node['name'] == node_name]
        if not nodes:
            click.echo(f"❌ Node '{node_name}' not found in configuration.")
            available_nodes = [node['name'] for node in config.get('nodes', [])]
            click.echo(f"Available nodes: {', '.join(available_nodes)}")
            return
    
    # Collect version information for all nodes
    results = []
    for node in nodes:
        # Skip nodes with disabled eth-docker
        stack = node.get('stack', ['eth-docker'])
        
        # Handle both old format (string) and new format (list)
        if isinstance(stack, str):
            stack = [stack]
        exec_client = node.get('exec_client', '')
        consensus_client = node.get('consensus_client', '')
        networks = node.get('networks', {})
        ethereum_clients_enabled = node.get('ethereum_clients_enabled', True)
        
        # Check if clients are disabled
        is_disabled = (
            stack == ['disabled'] or 
            ethereum_clients_enabled is False or
            (not networks and not exec_client and not consensus_client) or
            (not networks and exec_client == '' and consensus_client == '')
        )
        
        if is_disabled:
            click.echo(f"⚪ Skipping {node['name']} (Ethereum clients disabled)")
            continue
            
        click.echo(f"Checking client versions for {node['name']}...")
        try:
            version_info = get_docker_client_versions(node)
            
            # Check if this is a multi-network result
            if 'mainnet' in version_info or 'testnet' in version_info:
                # Multi-network node (like eliedesk)
                for network_key, network_info in version_info.items():
                    exec_client = network_info.get('execution_client', 'Unknown')
                    exec_current = network_info.get('execution_current', 'Unknown')
                    exec_latest = network_info.get('execution_latest', 'Unknown')
                    exec_needs_update = network_info.get('execution_needs_update', False)
                    
                    cons_client = network_info.get('consensus_client', 'Unknown')
                    cons_current = network_info.get('consensus_current', 'Unknown')
                    cons_latest = network_info.get('consensus_latest', 'Unknown')
                    cons_needs_update = network_info.get('consensus_needs_update', False)
                    
                    # Get the actual network name (e.g., "hoodi", "sepolia") or fall back to key
                    network_display_name = network_info.get('network', network_key)
                    
                    # Format execution display
                    exec_display = f"{exec_client}/{exec_current}" if exec_current != "Unknown" else exec_client
                    exec_latest_display = exec_latest if exec_latest not in ["Unknown", "API Error", "Network Error"] else "-"
                    
                    # Format consensus display
                    cons_display = f"{cons_client}/{cons_current}" if cons_current != "Unknown" else cons_client
                    cons_latest_display = cons_latest if cons_latest not in ["Unknown", "API Error", "Network Error"] else "-"
                    
                    # For multi-network, show network name in node name
                    display_name = f"{node['name']}-{network_display_name}"
                    
                    # Add to results as list (same format as single-network nodes)
                    results.append([
                        display_name,                                    # Node
                        exec_display,                                    # Execution
                        exec_latest_display,                             # Latest
                        '🔄' if exec_needs_update else '✅',            # Status
                        cons_display,                                    # Consensus
                        cons_latest_display,                             # Latest
                        '🔄' if cons_needs_update else '✅',            # Status
                        "-",                                             # Validator
                        "-",                                             # Latest
                        "-"                                              # Status
                    ])
                continue
            
            # Standard single-network processing
            # Get client names and versions
            exec_client = version_info.get('execution_client', 'Unknown')
            exec_current = version_info.get('execution_current', 'Unknown')
            exec_latest = version_info.get('execution_latest', 'Unknown')
            exec_needs_update = version_info.get('execution_needs_update', False)
            
            cons_client = version_info.get('consensus_client', 'Unknown')
            cons_current = version_info.get('consensus_current', 'Unknown') 
            cons_latest = version_info.get('consensus_latest', 'Unknown')
            cons_needs_update = version_info.get('consensus_needs_update', False)
            
            val_client = version_info.get('validator_client', 'Unknown')
            val_current = version_info.get('validator_current', 'Unknown')
            val_latest = version_info.get('validator_latest', 'Unknown')
            val_needs_update = version_info.get('validator_needs_update', False)
            
            # Format compact client/version display
            if exec_client != "Unknown" and exec_current != "Unknown":
                exec_display = f"{exec_client}/{exec_current}"
            else:
                exec_display = "Unknown"
                
            if cons_client != "Unknown" and cons_current != "Unknown":
                cons_display = f"{cons_client}/{cons_current}"
            else:
                cons_display = "Unknown"
                
            if val_client != "Unknown" and val_current not in ["Unknown", "Not Running"] and val_client != "Disabled":
                val_display = f"{val_client}/{val_current}"
            else:
                val_display = "-"
            
            # Format latest versions compactly
            exec_latest_display = exec_latest if exec_latest != "Unknown" else "-"
            cons_latest_display = cons_latest if cons_latest != "Unknown" else "-"
            val_latest_display = val_latest if val_latest not in ["Unknown", "Not Running"] and val_client != "Disabled" else "-"
            
            # Add single row with all clients
            results.append([
                node['name'],
                exec_display,
                exec_latest_display,
                '🔄' if exec_needs_update else '✅',
                cons_display,
                cons_latest_display,
                '🔄' if cons_needs_update else '✅',
                val_display,
                val_latest_display,
                '🔄' if val_needs_update else '✅' if val_display != "-" else '-'
            ])
        except Exception as e:
            click.echo(f"❌ Error checking {node['name']}: {e}")
            results.append([node['name'], 'Error', '-', '❌', 'Error', '-', '❌', 'Error', '-', '❌'])
    
    # Display results in table format
    if results:
        headers = ['Node', 'Execution', 'Latest', '🔄', 'Consensus', 'Latest', '🔄', 'Validator', 'Latest', '🔄']
        click.echo("\n" + tabulate(results, headers=headers, tablefmt='grid'))
        
        # Summary
        nodes_needing_updates = set()
        exec_updates = 0
        cons_updates = 0
        val_updates = 0
        
        for result in results:
            if result[3] == '🔄':  # Execution Update column
                nodes_needing_updates.add(result[0])  # Node name
                exec_updates += 1
            if result[6] == '🔄':  # Consensus Update column  
                nodes_needing_updates.add(result[0])  # Node name
                cons_updates += 1
            if result[9] == '🔄':  # Validator Update column
                nodes_needing_updates.add(result[0])  # Node name
                val_updates += 1
        
        click.echo(f"\n📊 Summary:")
        if nodes_needing_updates:
            click.echo(f"🔄 Nodes with client updates available: {', '.join(sorted(nodes_needing_updates))}")
            if exec_updates > 0:
                click.echo(f"⚡ Execution clients needing updates: {exec_updates}")
            if cons_updates > 0:
                click.echo(f"⛵ Consensus clients needing updates: {cons_updates}")
            if val_updates > 0:
                click.echo(f"🔒 Validator clients needing updates: {val_updates}")
            click.echo(f"💡 Run 'python -m eth_validators upgrade <node>' to update specific nodes")
            click.echo(f"💡 Run 'python -m eth_validators upgrade-all' to update all nodes")
        else:
            click.echo("✅ All Ethereum clients are up to date!")
    else:
        click.echo("❌ No version information collected.")

@system_group.command(name='updates')
@click.argument('node', required=False)
def system_updates_cmd(node):
    """Check if Ubuntu system updates are available on nodes"""
    config = yaml.safe_load(CONFIG_PATH.read_text())
    
    if node:
        # Check single node
        node_cfg = next(
            (n for n in config['nodes'] if n.get('tailscale_domain') == node or n.get('name') == node),
            None
        )
        if not node_cfg:
            click.echo(f"Node {node} not found")
            return
        nodes_to_check = [node_cfg]
    else:
        # Check all nodes
        nodes_to_check = config.get('nodes', [])
    
    table_data = []
    reboot_needed_nodes = []
    for node_cfg in nodes_to_check:
        name = node_cfg['name']
        click.echo(f"Checking system updates for {name}...")
        update_status = get_system_update_status(node_cfg)
        
        updates_count = update_status.get('updates_available', 'Error')
        needs_update = "Yes" if update_status.get('needs_system_update', False) else "No"
        
        # Check reboot status
        ssh_user = node_cfg.get('ssh_user', 'root')
        tailscale = node_cfg['tailscale_domain']
        stack = node_cfg.get('stack', ['eth-docker'])
        
        # Skip disabled nodes for reboot check
        if isinstance(stack, str):
            stack = [stack]
        if 'disabled' in stack:
            reboot_status = "N/A"
        else:
            reboot_status_raw = _check_reboot_needed(ssh_user, tailscale)
            if reboot_status_raw == "🔄 Yes":
                reboot_status = "Yes"
                reboot_needed_nodes.append(node_cfg)
            elif reboot_status_raw == "✅ No":
                reboot_status = "No"
            else:
                reboot_status = "Unknown"
        
        table_data.append([name, updates_count, needs_update, reboot_status])
    
    headers = ["Node", "Updates Available", "Needs Update", "Needs Reboot"]
    click.echo("\n" + tabulate(table_data, headers=headers, tablefmt="github"))
    
    if any(row[2] == "Yes" for row in table_data):
        click.echo("\n⚠️  To install system updates, use:")
        click.echo("   python3 -m eth_validators system upgrade <node>")
        click.echo("   python3 -m eth_validators system upgrade --all")
    else:
        click.echo("\n✅ All nodes are up to date!")
    
    # Show reboot summary if any nodes need reboot
    if reboot_needed_nodes:
        click.echo(f"\n🔄 Nodes needing reboot: {len(reboot_needed_nodes)}")
        for node in reboot_needed_nodes:
            click.echo(f"  python3 -m eth_validators system reboot {node['name']}")
        click.echo("  python3 -m eth_validators system reboot-all")
        
        # Interactive prompt to reboot nodes
        if click.confirm(f"\n⚠️  Do you want to reboot all {len(reboot_needed_nodes)} node(s) that require it? This will temporarily interrupt services."):
            click.echo(f"\n🔄 Rebooting {len(reboot_needed_nodes)} node(s)...")
            for node in reboot_needed_nodes:
                click.echo(f"  🔄 Rebooting {node['name']}...")
                ssh_target = f"{node.get('ssh_user', 'root')}@{node['tailscale_domain']}"
                cmd = f"ssh {ssh_target} 'sudo reboot'"
                subprocess.run(cmd, shell=True)
            click.echo(f"✅ Reboot commands sent to all {len(reboot_needed_nodes)} node(s)")
        else:
            click.echo("❌ Reboot cancelled")

@system_group.command(name='upgrade')
@click.argument('node', required=False)
@click.option('--all', 'upgrade_all_nodes', is_flag=True, help='Upgrade all nodes (will check which need updates first)')
@click.option('--force', is_flag=True, help='Skip update check and force upgrade')
def system_upgrade_cmd(node, upgrade_all_nodes, force):
    """Perform Ubuntu system upgrade on nodes"""
    config = yaml.safe_load(CONFIG_PATH.read_text())
    
    if upgrade_all_nodes:
        # Check all nodes first, then let user choose
        all_nodes = config.get('nodes', [])
        if not all_nodes:
            click.echo("No nodes found in config.yaml")
            return
            
        if not force:
            # Check which nodes need updates
            click.echo("🔍 Checking which nodes need system updates...")
            nodes_needing_updates = []
            
            for node_cfg in all_nodes:
                name = node_cfg['name']
                click.echo(f"  Checking {name}...", nl=False)
                update_status = get_system_update_status(node_cfg)
                
                if update_status.get('needs_system_update', False):
                    updates_count = update_status.get('updates_available', 'Unknown')
                    nodes_needing_updates.append((node_cfg, updates_count))
                    click.echo(f" ✅ {updates_count} updates available")
                else:
                    click.echo(" ⚪ Up to date")
            
            if not nodes_needing_updates:
                click.echo("\n🎉 All nodes are already up to date!")
                return
            
            # Show summary and ask for confirmation
            click.echo(f"\n📋 Found {len(nodes_needing_updates)} nodes needing updates:")
            for node_cfg, count in nodes_needing_updates:
                click.echo(f"  • {node_cfg['name']}: {count} updates")
            
            # Ask if user wants to proceed with just these nodes
            if not click.confirm(f"\n⚠️  Upgrade these {len(nodes_needing_updates)} nodes?"):
                click.echo("Operation cancelled.")
                return
                
            nodes_to_upgrade = [node_cfg for node_cfg, _ in nodes_needing_updates]
        else:
            # Force mode: upgrade all nodes without checking
            click.echo("🚨 Force mode: Upgrading ALL nodes without checking...")
            if not click.confirm("⚠️  This will run 'sudo apt update && sudo apt upgrade -y' on ALL nodes. Continue?"):
                click.echo("Operation cancelled.")
                return
            nodes_to_upgrade = all_nodes
            
    elif node:
        # Single node upgrade
        node_cfg = next(
            (n for n in config['nodes'] if n.get('tailscale_domain') == node or n.get('name') == node),
            None
        )
        if not node_cfg:
            click.echo(f"Node {node} not found")
            return
            
        if not force:
            # Check if this single node needs updates
            click.echo(f"🔍 Checking if {node} needs updates...")
            update_status = get_system_update_status(node_cfg)
            updates_count = update_status.get('updates_available', 'Error')
            
            if not update_status.get('needs_system_update', False):
                click.echo(f"✅ {node} is already up to date!")
                if not click.confirm("Upgrade anyway?"):
                    return
            else:
                click.echo(f"📦 {node} has {updates_count} updates available")
        
        if not click.confirm(f"⚠️  Run 'sudo apt update && sudo apt upgrade -y' on {node}?"):
            click.echo("Operation cancelled.")
            return
            
        nodes_to_upgrade = [node_cfg]
    else:
        click.echo("Please specify a node name or use --all flag")
        click.echo("Examples:")
        click.echo("  python3 -m eth_validators system-upgrade laptop")
        click.echo("  python3 -m eth_validators system-upgrade --all")
        click.echo("  python3 -m eth_validators system-upgrade --all --force")
        return
    
    # Perform the upgrades
    for node_cfg in nodes_to_upgrade:
        name = node_cfg['name']
        click.echo(f"\n🔄 Upgrading system packages on {name}...")
        click.echo("Running: sudo apt update && sudo apt upgrade -y")
        
        upgrade_result = perform_system_upgrade(node_cfg)
        
        if upgrade_result.get('upgrade_success'):
            click.echo(f"✅ {name}: System upgrade completed successfully!")
        else:
            click.echo(f"❌ {name}: System upgrade failed!")
            if upgrade_result.get('upgrade_error'):
                click.echo(f"Error: {upgrade_result['upgrade_error']}")
        
        # Show some output for transparency
        if upgrade_result.get('upgrade_output'):
            output_lines = upgrade_result['upgrade_output'].splitlines()
            if len(output_lines) > 10:
                click.echo("... (showing last 10 lines of output)")
                for line in output_lines[-10:]:
                    click.echo(f"  {line}")
            else:
                for line in output_lines:
                    click.echo(f"  {line}")
    
    click.echo(f"\n🎉 Completed system upgrades for {len(nodes_to_upgrade)} node(s)!")

@system_group.command(name='reboot')
@click.argument('node')
def reboot_node(node):
    """Reboot a single node"""
    config = yaml.safe_load(CONFIG_PATH.read_text())
    node_cfg = next(
        (n for n in config['nodes'] if n.get('tailscale_domain') == node or n.get('name') == node),
        None
    )
    if not node_cfg:
        click.echo(f"❌ Node {node} not found")
        return
    
    # Confirm reboot
    if not click.confirm(f"⚠️  Are you sure you want to reboot {node_cfg['name']}? This will temporarily interrupt services."):
        click.echo("❌ Reboot cancelled")
        return
    
    click.echo(f"🔄 Rebooting {node_cfg['name']}...")
    ssh_target = f"{node_cfg.get('ssh_user', 'root')}@{node_cfg['tailscale_domain']}"
    cmd = f"ssh {ssh_target} 'sudo reboot'"
    subprocess.run(cmd, shell=True)
    click.echo(f"✅ Reboot command sent to {node_cfg['name']}")

@system_group.command(name='reboot-all')
def reboot_all_needed():
    """Reboot all nodes that need a restart"""
    config = yaml.safe_load(CONFIG_PATH.read_text())
    nodes = config.get('nodes', [])
    
    # Find nodes that need reboot
    reboot_needed = []
    for node in nodes:
        ssh_user = node.get('ssh_user', 'root')
        tailscale = node['tailscale_domain']
        stack = node.get('stack', ['eth-docker'])
        
        # Skip disabled nodes
        if isinstance(stack, str):
            stack = [stack]
        if 'disabled' in stack:
            continue
            
        reboot_status = _check_reboot_needed(ssh_user, tailscale)
        if reboot_status == "🔄 Yes":
            reboot_needed.append(node)
    
    if not reboot_needed:
        click.echo("✅ No nodes need a reboot!")
        return
    
    click.echo(f"🔄 Found {len(reboot_needed)} node(s) that need a reboot:")
    for node in reboot_needed:
        click.echo(f"  • {node['name']}")
    
    if not click.confirm(f"\n⚠️  Are you sure you want to reboot all {len(reboot_needed)} node(s)? This will temporarily interrupt services."):
        click.echo("❌ Reboot cancelled")
        return
    
    click.echo("\n🔄 Rebooting nodes...")
    for node in reboot_needed:
        click.echo(f"  🔄 Rebooting {node['name']}...")
        ssh_target = f"{node.get('ssh_user', 'root')}@{node['tailscale_domain']}"
        cmd = f"ssh {ssh_target} 'sudo reboot'"
        subprocess.run(cmd, shell=True)
    
    click.echo(f"✅ Reboot commands sent to all {len(reboot_needed)} node(s)")

@ai_group.command(name='analyze')
@click.argument('node_name')
@click.option('--container', help='Specific container to analyze (e.g., lighthouse-validator-client)')
@click.option('--hours', default=24, type=int, help='Hours of logs to analyze (default: 24)')
@click.option('--severity', default='INFO', help='Minimum log severity level (DEBUG, INFO, WARN, ERROR)')
def ai_analyze_cmd(node_name, container, hours, severity):
    """AI analysis of validator logs for performance insights"""
    config_data = yaml.safe_load(CONFIG_PATH.read_text())
    node_cfg = next(
        (n for n in config_data['nodes'] if n.get('tailscale_domain') == node_name or n.get('name') == node_name),
        None
    )
    if not node_cfg:
        click.echo(f"❌ Node {node_name} not found")
        return
    
    click.echo(f"🧠 Starting AI analysis for {node_cfg['name']}...")
    if container:
        click.echo(f"📊 Analyzing container: {container}")
    click.echo(f"🕐 Analyzing last {hours} hours of logs")
    click.echo(f"🔍 Minimum severity: {severity}")
    
    # Initialize AI analyzer
    analyzer = ValidatorLogAnalyzer()
    
    try:
        # Perform comprehensive analysis
        analysis_result = analyzer.analyze_node_logs(
            node_name=node_cfg['name'],
            hours=hours
        )
        
        # Display results
        _display_ai_analysis_results(analysis_result, node_cfg['name'])
        
    except Exception as e:
        click.echo(f"❌ AI analysis failed: {e}")

@ai_group.command(name='health')
@click.argument('node_name', required=False)
@click.option('--threshold', default=70, type=int, help='Health score threshold for alerts (default: 70)')
def ai_health_cmd(node_name, threshold):
    """Check AI health scores for validators"""
    config_data = yaml.safe_load(CONFIG_PATH.read_text())
    
    if node_name:
        nodes = [n for n in config_data['nodes'] if n.get('tailscale_domain') == node_name or n.get('name') == node_name]
        if not nodes:
            click.echo(f"❌ Node {node_name} not found")
            return
    else:
        nodes = config_data.get('nodes', [])
    
    click.echo("🏥 Performing AI health analysis across validator infrastructure...")
    
    # Initialize AI analyzer
    analyzer = ValidatorLogAnalyzer()
    health_data = []
    
    for node_cfg in nodes:
        # Skip disabled nodes
        if node_cfg.get('stack') == 'disabled':
            continue
            
        click.echo(f"  🔍 Analyzing {node_cfg['name']}...", nl=False)
        
        try:
            # Get health score for this node via comprehensive analysis
            analysis_result = analyzer.analyze_node_logs(
                node_name=node_cfg['name'],
                hours=24  # Last 24 hours
            )
            
            health_score = analysis_result.get('overall_health_score', 0)
            status_emoji = "🟢" if health_score >= 90 else "🟡" if health_score >= threshold else "🔴"
            
            # Get key metrics from analysis
            container_analyses = analysis_result.get('container_analyses', {})
            anomaly_count = 0
            error_count = 0
            warning_count = 0
            
            for container_data in container_analyses.values():
                if isinstance(container_data, dict):
                    anomaly_count += len(container_data.get('anomalies', []))
                    error_patterns = container_data.get('error_patterns', [])
                    error_count += len(error_patterns)
                    # Count warnings from pattern matches
                    pattern_matches = container_data.get('pattern_matches', {})
                    warning_count += pattern_matches.get('performance_warnings', 0)
            
            primary_concern = "Performance issues" if error_count > 5 else "Network issues" if anomaly_count > 3 else "None"
            
            health_data.append([
                f"{status_emoji} {node_cfg['name']}",
                f"{health_score:.1f}%",
                str(anomaly_count),
                str(error_count),
                str(warning_count),
                primary_concern
            ])
            
            click.echo(f" {status_emoji} {health_score:.1f}%")
            
        except Exception as e:
            health_data.append([
                f"❌ {node_cfg['name']}",
                "Error",
                "-",
                "-", 
                "-",
                str(e)[:50]
            ])
            click.echo(" ❌ Error")
    
    # Display health summary table
    if health_data:
        headers = ['Node', 'Health Score', 'Anomalies', 'Errors', 'Warnings', 'Primary Concern']
        click.echo("\n" + "="*100)
        click.echo("🏥 VALIDATOR INFRASTRUCTURE HEALTH DASHBOARD")
        click.echo("="*100)
        click.echo(tabulate(health_data, headers=headers, tablefmt='fancy_grid'))
        
        # Summary statistics
        healthy_nodes = sum(1 for row in health_data if "🟢" in row[0])
        warning_nodes = sum(1 for row in health_data if "🟡" in row[0])
        critical_nodes = sum(1 for row in health_data if "🔴" in row[0])
        
        click.echo(f"\n📊 Infrastructure Summary:")
        click.echo(f"🟢 Healthy nodes: {healthy_nodes}")
        click.echo(f"🟡 Warning nodes: {warning_nodes}")  
        click.echo(f"🔴 Critical nodes: {critical_nodes}")
        
        if critical_nodes > 0:
            click.echo(f"\n⚠️  {critical_nodes} node(s) need immediate attention!")
            click.echo("💡 Use 'ai-analyze <node>' for detailed analysis")
    else:
        click.echo("❌ No health data collected.")

@ai_group.command(name='patterns')
@click.argument('node_name')
@click.option('--days', default=7, type=int, help='Days of log history to analyze (default: 7)')
@click.option('--pattern-type', default='all', help='Pattern type: errors, warnings, performance, or all')
def ai_patterns_cmd(node_name, days, pattern_type):
    """Discover patterns in validator logs using AI"""
    config_data = yaml.safe_load(CONFIG_PATH.read_text())
    node_cfg = next(
        (n for n in config_data['nodes'] if n.get('tailscale_domain') == node_name or n.get('name') == node_name),
        None
    )
    if not node_cfg:
        click.echo(f"❌ Node {node_name} not found")
        return
    
    click.echo(f"🔍 Analyzing patterns for {node_cfg['name']} over last {days} days...")
    click.echo(f"🎯 Pattern focus: {pattern_type}")
    
    # Initialize AI analyzer
    analyzer = ValidatorLogAnalyzer()
    
    try:
        # Perform comprehensive analysis to get patterns
        analysis_result = analyzer.analyze_node_logs(
            node_name=node_cfg['name'],
            hours=days * 24
        )
        
        # Extract pattern information from analysis result
        patterns = {
            'temporal_patterns': [],
            'recurring_issues': [],
            'performance_patterns': {}
        }
        
        # Analyze container data for patterns
        container_analyses = analysis_result.get('container_analyses', {})
        for container_name, container_data in container_analyses.items():
            if isinstance(container_data, dict):
                # Extract temporal patterns from time analysis
                time_analysis = container_data.get('time_analysis', {})
                if time_analysis.get('logging_gaps'):
                    patterns['temporal_patterns'].append({
                        'description': f'{container_name}: Logging gaps detected',
                        'frequency': f"{len(time_analysis['logging_gaps'])} gaps",
                        'confidence': 85.0
                    })
                
                # Extract recurring issues from error patterns
                error_patterns = container_data.get('error_patterns', [])
                for error in error_patterns:
                    patterns['recurring_issues'].append({
                        'issue_type': error.get('category', 'Unknown'),
                        'count': 1,  # Single occurrence in this analysis
                        'impact': 'Medium' if 'failed' in error.get('category', '') else 'Low'
                    })
                
                # Extract performance patterns from pattern matches
                pattern_matches = container_data.get('pattern_matches', {})
                for pattern_type, count in pattern_matches.items():
                    if count > 0:
                        patterns['performance_patterns'][f'{container_name}_{pattern_type}'] = f"{count} occurrences"
        
        # Display pattern analysis results
        _display_pattern_analysis(patterns, node_cfg['name'], days, pattern_type)
        
    except Exception as e:
        click.echo(f"❌ Pattern analysis failed: {e}")

@ai_group.command(name='recommend')
@click.argument('node_name')
@click.option('--focus', default='performance', help='Recommendation focus: performance, reliability, security, or all')
def ai_recommend_cmd(node_name, focus):
    """Get AI recommendations for validator optimization"""
    config_data = yaml.safe_load(CONFIG_PATH.read_text())
    node_cfg = next(
        (n for n in config_data['nodes'] if n.get('tailscale_domain') == node_name or n.get('name') == node_name),
        None
    )
    if not node_cfg:
        click.echo(f"❌ Node {node_name} not found")
        return
    
    click.echo(f"🎯 Generating AI recommendations for {node_cfg['name']}...")
    click.echo(f"🔍 Focus area: {focus}")
    
    # Initialize AI analyzer
    analyzer = ValidatorLogAnalyzer()
    
    try:
        # Generate comprehensive analysis first
        analysis_result = analyzer.analyze_node_logs(
            node_name=node_cfg['name'],
            hours=48  # Last 48 hours for context
        )
        
        # Extract recommendations from analysis result
        recommendations = {
            'priority': [],
            'general': [],
            'configuration': []
        }
        
        # Use existing recommendations from analysis
        existing_recommendations = analysis_result.get('recommendations', [])
        
        # Categorize recommendations based on focus area and severity
        health_score = analysis_result.get('overall_health_score', 100)
        alerts = analysis_result.get('alerts', [])
        
        # Priority recommendations from critical alerts
        for alert in alerts:
            if alert.get('level') == 'critical':
                recommendations['priority'].append({
                    'title': 'Critical Issue Detected',
                    'description': alert.get('message', ''),
                    'action': alert.get('recommendation', 'Investigate immediately')
                })
        
        # General recommendations from existing analysis
        for rec in existing_recommendations:
            recommendations['general'].append({
                'title': 'Performance Optimization',
                'description': rec
            })
        
        # Configuration suggestions based on focus area
        if focus == 'performance' and health_score < 85:
            recommendations['configuration'].append('Consider increasing resource allocation')
            recommendations['configuration'].append('Review client configuration for optimization')
        elif focus == 'reliability' and health_score < 90:
            recommendations['configuration'].append('Implement redundancy measures')
            recommendations['configuration'].append('Set up monitoring alerts')
        elif focus == 'security':
            recommendations['configuration'].append('Review firewall and network security')
            recommendations['configuration'].append('Update client software regularly')
        
        # Display recommendations
        _display_recommendations(recommendations, node_cfg['name'], focus)
        
    except Exception as e:
        click.echo(f"❌ Recommendation generation failed: {e}")

def _display_ai_analysis_results(analysis_result, node_name):
    """Display comprehensive AI analysis results in a formatted way."""
    click.echo("\n" + "="*80)
    click.echo(f"🧠 AI ANALYSIS RESULTS: {node_name.upper()}")
    click.echo("="*80)
    
    # Overall health score
    health_score = analysis_result.get('health_score', {}).get('overall_score', 0)
    health_emoji = "🟢" if health_score >= 90 else "🟡" if health_score >= 70 else "🔴"
    click.echo(f"\n{health_emoji} Overall Health Score: {health_score:.1f}%")
    
    # Anomalies detected
    anomalies = analysis_result.get('anomalies', [])
    if anomalies:
        click.echo(f"\n⚠️  Anomalies Detected: {len(anomalies)}")
        for anomaly in anomalies[:5]:  # Show top 5
            click.echo(f"  • {anomaly.get('severity', 'UNKNOWN')}: {anomaly.get('description', 'No description')}")
        if len(anomalies) > 5:
            click.echo(f"  ... and {len(anomalies) - 5} more")
    else:
        click.echo(f"\n✅ No significant anomalies detected")
    
    # Error patterns
    error_patterns = analysis_result.get('error_patterns', {})
    if error_patterns.get('total_errors', 0) > 0:
        click.echo(f"\n🔴 Error Analysis:")
        click.echo(f"  Total errors: {error_patterns['total_errors']}")
        for pattern, count in error_patterns.get('patterns', {}).items():
            click.echo(f"  • {pattern}: {count} occurrences")
    
    # Performance insights
    performance_data = analysis_result.get('performance_insights', {})
    if performance_data:
        click.echo(f"\n📊 Performance Insights:")
        for metric, value in performance_data.items():
            click.echo(f"  • {metric}: {value}")
    
    # Recommendations
    recommendations = analysis_result.get('recommendations', [])
    if recommendations:
        click.echo(f"\n💡 AI Recommendations:")
        for i, rec in enumerate(recommendations[:3], 1):
            click.echo(f"  {i}. {rec}")
        if len(recommendations) > 3:
            click.echo(f"     ... and {len(recommendations) - 3} more suggestions")
    
    click.echo("="*80)

def _display_pattern_analysis(patterns, node_name, days, pattern_type):
    """Display pattern analysis results."""
    click.echo("\n" + "="*80)
    click.echo(f"🔍 PATTERN ANALYSIS: {node_name.upper()} ({days} days)")
    click.echo("="*80)
    
    if not patterns:
        click.echo("📊 No significant patterns detected in the specified timeframe.")
        return
    
    # Temporal patterns
    temporal = patterns.get('temporal_patterns', [])
    if temporal:
        click.echo(f"\n🕐 Temporal Patterns:")
        for pattern in temporal:
            click.echo(f"  • {pattern.get('description', 'Unknown pattern')}")
            click.echo(f"    Frequency: {pattern.get('frequency', 'Unknown')}")
            click.echo(f"    Confidence: {pattern.get('confidence', 0):.1f}%")
    
    # Recurring issues
    recurring = patterns.get('recurring_issues', [])
    if recurring:
        click.echo(f"\n🔄 Recurring Issues:")
        for issue in recurring:
            click.echo(f"  • {issue.get('issue_type', 'Unknown')}: {issue.get('count', 0)} times")
            if issue.get('impact'):
                click.echo(f"    Impact: {issue['impact']}")
    
    # Performance patterns
    performance = patterns.get('performance_patterns', {})
    if performance:
        click.echo(f"\n📈 Performance Patterns:")
        for metric, data in performance.items():
            click.echo(f"  • {metric}: {data}")
    
    click.echo("="*80)

@ai_group.command(name='dashboard')
@click.option('--port', default=8080, help='Port for the web dashboard (default: 8080)')
@click.option('--host', default='localhost', help='Host for the web dashboard (default: localhost)')
@click.option('--demo', is_flag=True, help='Start in demo mode without real analysis')
def ai_dashboard(port, host, demo):
    """Launch AI analysis web dashboard for monitoring"""
    import webbrowser
    import threading
    import time
    from pathlib import Path
    
    dashboard_server_path = Path(__file__).parent.parent / 'ai_dashboard_server.py'
    
    if not dashboard_server_path.exists():
        click.echo("❌ Dashboard server not found. Please ensure ai_dashboard_server.py is in the project root.")
        return
    
    click.echo("🧠 AI Validator Analysis Dashboard")
    click.echo("="*50)
    click.echo(f"🌐 Starting server on {host}:{port}...")
    
    if demo:
        click.echo("🎭 Demo mode enabled - using simulated data")
    else:
        click.echo("🚀 Real analysis mode - connecting to your validators")
    
    dashboard_url = f"http://{host}:{port}"
    click.echo(f"📊 Dashboard URL: {dashboard_url}")
    click.echo("🚀 Press Ctrl+C to stop the server")
    click.echo("="*50)
    
    # Auto-open browser after a short delay
    def open_browser():
        time.sleep(2)
        try:
            webbrowser.open(dashboard_url)
            click.echo(f"🌐 Opened browser to {dashboard_url}")
        except Exception as e:
            click.echo(f"⚠️  Could not auto-open browser: {e}")
            click.echo(f"📱 Please manually open: {dashboard_url}")
    
    browser_thread = threading.Thread(target=open_browser, daemon=True)
    browser_thread.start()
    
    # Start the dashboard server
    try:
        import subprocess
        import sys
        
        cmd = [sys.executable, str(dashboard_server_path), str(port)]
        if demo:
            cmd.append('--demo')
            
        subprocess.run(cmd)
        
    except KeyboardInterrupt:
        click.echo("\n🛑 Dashboard server stopped by user")
    except Exception as e:
        click.echo(f"❌ Failed to start dashboard server: {e}")
        click.echo("💡 Try running manually: python ai_dashboard_server.py")

@performance_group.command(name='deep')
@click.argument('node_name')
@click.option('--hours', default=6, help='Hours of data to analyze (default: 6)')
@click.option('--export', help='Export results to JSON file')
@click.option('--beacon-only', is_flag=True, help='Only extract beacon node performance data')
@click.option('--logs-only', is_flag=True, help='Only extract log performance data')
def performance_deep(node_name, hours, export, beacon_only, logs_only):
    """Deep performance analysis with beacon API integration"""
    import json
    from datetime import datetime
    
    click.echo("🔍 DEEP VALIDATOR PERFORMANCE ANALYSIS")
    click.echo("=" * 60)
    click.echo(f"🎯 Node: {node_name}")
    click.echo(f"⏱️  Analysis period: {hours} hours")
    click.echo(f"📊 Mode: {'Beacon only' if beacon_only else 'Logs only' if logs_only else 'Comprehensive'}")
    click.echo("=" * 60)
    
    try:
        from eth_validators.enhanced_performance_extractor import ValidatorPerformanceExtractor
        extractor = ValidatorPerformanceExtractor()
        
        start_time = datetime.now()
        click.echo("🚀 Starting deep performance analysis...")
        
        if beacon_only:
            # Get node config and validator indices
            node_config = None
            for node in extractor.config.get('nodes', []):
                if node.get('name') == node_name:
                    node_config = node
                    break
            
            if not node_config:
                click.echo(f"❌ Node {node_name} not found in configuration")
                return
            
            validator_indices = extractor._get_validator_indices_for_node(node_name)
            results = extractor.extract_beacon_node_performance(node_config, validator_indices)
            
        elif logs_only:
            node_config = None
            for node in extractor.config.get('nodes', []):
                if node.get('name') == node_name:
                    node_config = node
                    break
            
            if not node_config:
                click.echo(f"❌ Node {node_name} not found in configuration")
                return
                
            results = extractor.extract_log_performance_metrics(node_config, hours)
            
        else:
            # Comprehensive analysis
            results = extractor.extract_comprehensive_performance(node_name, hours=hours)
        
        analysis_time = (datetime.now() - start_time).total_seconds()
        click.echo(f"✅ Analysis completed in {analysis_time:.1f} seconds")
        
        # Display results
        _display_deep_performance_results(results, beacon_only, logs_only)
        
        # Export if requested
        if export:
            with open(export, 'w') as f:
                json.dump(results, f, indent=2)
            click.echo(f"💾 Results exported to: {export}")
            
    except ImportError:
        click.echo("❌ Enhanced performance extractor not available")
        click.echo("💡 Falling back to basic AI analysis...")
        
        # Fallback to AI analyzer
        from eth_validators.ai_analyzer import ValidatorLogAnalyzer
        analyzer = ValidatorLogAnalyzer()
        
        results = analyzer.analyze_node_logs(node_name, hours)
        _display_ai_analysis_results(results, node_name)
        
    except Exception as e:
        click.echo(f"❌ Deep performance analysis failed: {e}")

def _display_deep_performance_results(results, beacon_only=False, logs_only=False):
    """Display comprehensive performance analysis results"""
    if 'error' in results:
        click.echo(f"❌ Analysis failed: {results['error']}")
        return
    
    if not beacon_only and not logs_only:
        # Comprehensive results
        click.echo("\n📊 COMPREHENSIVE PERFORMANCE ANALYSIS")
        click.echo("=" * 50)
        
        # Overall summary
        summary = results.get('summary', {})
        overall_health = summary.get('overall_health_score', 0)
        health_emoji = "🟢" if overall_health >= 80 else "🟡" if overall_health >= 60 else "🔴"
        click.echo(f"\n{health_emoji} OVERALL HEALTH SCORE: {overall_health:.1f}/100")
        
        # Beacon node performance
        beacon_data = results.get('beacon_node_performance', {})
        if beacon_data and 'error' not in beacon_data:
            click.echo(f"\n🛰️  BEACON NODE PERFORMANCE:")
            
            # Node health
            node_info = beacon_data.get('beacon_node_info', {})
            if node_info:
                is_healthy = node_info.get('is_healthy', False)
                health_status = "Healthy ✅" if is_healthy else "Issues detected ⚠️"
                click.echo(f"  Status: {health_status}")
                
                version = node_info.get('version', {})
                if version:
                    click.echo(f"  Version: {version.get('version', 'Unknown')}")
            
            # Sync status
            sync_status = beacon_data.get('sync_status', {})
            if sync_status:
                if sync_status.get('is_syncing', False):
                    sync_pct = sync_status.get('sync_percentage', 0)
                    click.echo(f"  Sync: In progress ({sync_pct:.1f}%) 🔄")
                else:
                    click.echo(f"  Sync: Fully synced ✅")
            
            # Peer connectivity
            peer_info = beacon_data.get('peer_info', {})
            if peer_info:
                connected_peers = peer_info.get('connected_peers', 0)
                total_peers = peer_info.get('total_peers', 0)
                click.echo(f"  Peers: {connected_peers} connected / {total_peers} total 📡")
            
            # Validator performance
            validator_performance = beacon_data.get('validator_performance', {})
            if validator_performance:
                click.echo(f"  Validators: {len(validator_performance)} analyzed 👤")
                
                for idx, val_data in list(validator_performance.items())[:3]:  # Show first 3
                    if isinstance(val_data, dict):
                        status = val_data.get('status', 'unknown')
                        balance = val_data.get('balance')
                        click.echo(f"    {idx}: {status}")
                        if balance:
                            balance_eth = int(balance) / 1000000000  # Gwei to ETH
                            click.echo(f"      Balance: {balance_eth:.4f} ETH")
                        
                        perf_metrics = val_data.get('performance_metrics', {})
                        if perf_metrics:
                            client = perf_metrics.get('client', 'unknown')
                            hit_rate = perf_metrics.get('attestation_hit_percentage')
                            if hit_rate is not None:
                                click.echo(f"      Attestation success: {hit_rate:.1f}% ({client})")
        
        # Log performance
        log_data = results.get('log_performance', {})
        if log_data and 'error' not in log_data:
            click.echo(f"\n📋 LOG PERFORMANCE ANALYSIS:")
            
            for container, metrics in log_data.items():
                if 'error' in metrics:
                    continue
                
                click.echo(f"\n  📦 {container}:")
                
                # Attestation metrics
                attestation_metrics = metrics.get('attestation_performance', {})
                if attestation_metrics:
                    success_rate = attestation_metrics.get('success_rate')
                    successful = attestation_metrics.get('successful_attestations', 0)
                    failed = attestation_metrics.get('failed_attestations', 0)
                    
                    if success_rate is not None:
                        rate_emoji = "🟢" if success_rate >= 95 else "🟡" if success_rate >= 90 else "🔴"
                        click.echo(f"    {rate_emoji} Attestations: {successful} success, {failed} failed ({success_rate:.1f}%)")
                    
                    avg_distance = attestation_metrics.get('average_inclusion_distance')
                    if avg_distance:
                        click.echo(f"    📏 Avg inclusion distance: {avg_distance:.1f}")
                
                # Error analysis
                error_metrics = metrics.get('error_analysis', {})
                total_errors = error_metrics.get('total_errors', 0)
                critical_errors = error_metrics.get('critical_errors', 0)
                
                if total_errors > 0:
                    error_emoji = "🔴" if critical_errors > 0 else "🟡"
                    click.echo(f"    {error_emoji} Errors: {total_errors} total, {critical_errors} critical")
                    
                    # Show error categories
                    error_categories = error_metrics.get('error_categories', {})
                    for category, count in error_categories.items():
                        if count > 0:
                            click.echo(f"      {category}: {count}")
                
                # Resource metrics
                resource_metrics = metrics.get('resource_performance', {})
                memory_warnings = resource_metrics.get('memory_warnings', 0)
                disk_warnings = resource_metrics.get('disk_warnings', 0)
                
                if memory_warnings > 0 or disk_warnings > 0:
                    click.echo(f"    ⚠️  Resource warnings: {memory_warnings} memory, {disk_warnings} disk")
        
        # Alerts and recommendations
        alerts = summary.get('alerts', [])
        if alerts:
            click.echo(f"\n🚨 ALERTS:")
            for alert in alerts[:5]:  # Show first 5
                severity = alert.get('severity', 'info')
                message = alert.get('message', '')
                severity_emoji = "🔴" if severity == 'critical' else "🟡" if severity == 'warning' else "🔵"
                click.echo(f"  {severity_emoji} {message}")
        
        recommendations = summary.get('recommendations', [])
        if recommendations:
            click.echo(f"\n💡 RECOMMENDATIONS:")
            for rec in recommendations[:5]:  # Show first 5
                click.echo(f"  • {rec}")
    
    elif beacon_only:
        # Beacon-only results
        click.echo("\n🛰️  BEACON NODE PERFORMANCE ANALYSIS")
        click.echo("=" * 40)
        
        if 'error' in results:
            click.echo(f"❌ {results['error']}")
            return
        
        # Display beacon node specific data
        _display_beacon_performance(results)
    
    elif logs_only:
        # Logs-only results  
        click.echo("\n📋 LOG PERFORMANCE ANALYSIS")
        click.echo("=" * 30)
        
        if 'error' in results:
            click.echo(f"❌ {results['error']}")
            return
        
        # Display log specific data
        _display_log_performance(results)

def _display_beacon_performance(beacon_data):
    """Display beacon node performance data"""
    # Implementation for beacon-only display
    node_info = beacon_data.get('beacon_node_info', {})
    if node_info:
        click.echo(f"Health: {'✅ Healthy' if node_info.get('is_healthy') else '⚠️  Issues'}")
        
        version = node_info.get('version', {})
        if version:
            click.echo(f"Version: {version.get('version', 'Unknown')}")
    
    sync_status = beacon_data.get('sync_status', {})
    if sync_status:
        if sync_status.get('is_syncing'):
            pct = sync_status.get('sync_percentage', 0)
            click.echo(f"Sync: {pct:.1f}% complete 🔄")
        else:
            click.echo(f"Sync: Complete ✅")

def _display_log_performance(log_data):
    """Display log performance data"""
    click.echo(f"Containers analyzed: {len(log_data)}")
    
    for container, metrics in log_data.items():
        if 'error' in metrics:
            continue
        
        click.echo(f"\n📦 {container}:")
        
        # Quick summary
        total_lines = metrics.get('total_log_lines', 0)
        click.echo(f"  Total log lines: {total_lines:,}")
        
        # Attestation summary
        attestation_metrics = metrics.get('attestation_performance', {})
        if attestation_metrics:
            success_rate = attestation_metrics.get('success_rate')
            if success_rate is not None:
                click.echo(f"  Attestation success rate: {success_rate:.1f}%")
        
        # Error summary
        error_metrics = metrics.get('error_analysis', {})
        total_errors = error_metrics.get('total_errors', 0)
        if total_errors > 0:
            click.echo(f"  Total errors: {total_errors}")

@performance_group.command(name='live')
@click.argument('node_name')
@click.option('--interval', default=30, help='Update interval in seconds (default: 30)')
def performance_live(node_name, interval):
    """Live validator performance monitoring"""
    import time
    import os
    from datetime import datetime
    
    click.echo("📊 LIVE VALIDATOR PERFORMANCE MONITOR")
    click.echo("=" * 50)
    click.echo(f"🎯 Node: {node_name}")
    click.echo(f"🔄 Update interval: {interval} seconds")
    click.echo("=" * 50)
    click.echo("Press Ctrl+C to stop monitoring")
    click.echo()
    
    try:
        from eth_validators.enhanced_performance_extractor import ValidatorPerformanceExtractor
        extractor = ValidatorPerformanceExtractor()
        
        while True:
            # Clear screen
            os.system('clear' if os.name == 'posix' else 'cls')
            
            # Header
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            click.echo(f"📊 LIVE PERFORMANCE - {current_time}")
            click.echo("=" * 60)
            click.echo(f"🎯 Node: {node_name}")
            click.echo()
            
            try:
                # Quick performance check
                node_config = None
                for node in extractor.config.get('nodes', []):
                    if node.get('name') == node_name:
                        node_config = node
                        break
                
                if not node_config:
                    click.echo(f"❌ Node {node_name} not found")
                    break
                
                # Basic beacon check
                beacon_data = extractor._basic_beacon_health_check(node_config)
                
                if 'error' not in beacon_data:
                    health_status = "🟢 Healthy" if beacon_data.get('is_healthy') else "🔴 Issues"
                    click.echo(f"Beacon Node: {health_status}")
                    
                    sync_data = beacon_data.get('sync_status', {})
                    if sync_data:
                        if sync_data.get('is_syncing'):
                            click.echo(f"Sync: 🔄 In progress")
                        else:
                            click.echo(f"Sync: ✅ Complete")
                    
                    click.echo(f"Last check: {current_time}")
                else:
                    click.echo(f"❌ Beacon check failed: {beacon_data['error']}")
                
                # Quick log analysis (last 5 minutes)
                log_data = extractor.extract_log_performance_metrics(node_config, hours=0.083)  # 5 minutes
                
                click.echo("\n📋 Recent Activity (last 5 minutes):")
                if log_data and 'error' not in log_data:
                    for container, metrics in list(log_data.items())[:3]:  # Show first 3 containers
                        if 'error' in metrics:
                            continue
                        
                        attestation_metrics = metrics.get('attestation_performance', {})
                        error_metrics = metrics.get('error_analysis', {})
                        
                        successful = attestation_metrics.get('successful_attestations', 0)
                        failed = attestation_metrics.get('failed_attestations', 0)
                        total_errors = error_metrics.get('total_errors', 0)
                        
                        status_emoji = "🟢" if total_errors == 0 and failed == 0 else "🟡" if total_errors < 5 else "🔴"
                        click.echo(f"  {status_emoji} {container}: {successful} attestations, {total_errors} errors")
                
            except Exception as e:
                click.echo(f"❌ Monitor update failed: {e}")
            
            click.echo(f"\n⏰ Next update in {interval} seconds... (Ctrl+C to stop)")
            time.sleep(interval)
            
    except KeyboardInterrupt:
        click.echo("\n\n🛑 Live monitoring stopped by user")
    except Exception as e:
        click.echo(f"\n❌ Live monitoring failed: {e}")

@ai_group.command(name='hybrid')
@click.argument('node_name')
@click.option('--disable-ml', is_flag=True, help='Disable machine learning components')
@click.option('--disable-llm', is_flag=True, help='Disable LLM components')
@click.option('--hours', default=24, help='Hours of logs to analyze (default: 24)')
@click.option('--export', help='Export results to JSON file')
def ai_hybrid(node_name, disable_ml, disable_llm, hours, export):
    """Advanced hybrid AI analysis (Classical + ML + LLM)"""
    import json
    from datetime import datetime
    
    click.echo("🧠 HYBRID AI VALIDATOR ANALYSIS")
    click.echo("="*80)
    click.echo(f"🎯 Target: {node_name}")
    click.echo(f"⏱️  Timeframe: {hours} hours")
    
    # Show enabled components
    components = []
    components.append("🔧 Classical AI")
    if not disable_ml:
        components.append("🤖 Machine Learning")
    if not disable_llm:
        components.append("🧠 Large Language Model")
    
    click.echo(f"🚀 Active Components: {' + '.join(components)}")
    click.echo("="*80)
    
    try:
        # Try to import hybrid analyzer
        try:
            from eth_validators.hybrid_ai_analyzer import HybridValidatorAnalyzer
            analyzer = HybridValidatorAnalyzer(
                enable_ml=not disable_ml,
                enable_llm=not disable_llm
            )
            hybrid_available = True
        except ImportError as e:
            click.echo(f"⚠️  Hybrid AI not fully available: {e}")
            click.echo("📦 Falling back to classical AI analysis")
            from eth_validators.ai_analyzer import ValidatorLogAnalyzer
            analyzer = ValidatorLogAnalyzer()
            hybrid_available = False
        
        # Show system status
        if hybrid_available:
            status = analyzer.get_system_status()
            click.echo(f"\n📊 SYSTEM STATUS:")
            for component, state in status.items():
                icon = "✅" if state in ['Available', True] else "❌"
                click.echo(f"  {icon} {component}: {state}")
        
        click.echo(f"\n🔍 Starting analysis...")
        start_time = datetime.now()
        
        # Run analysis
        if hybrid_available:
            results = analyzer.analyze_node_comprehensive(node_name, hours)
        else:
            # Fallback to classical analysis
            results = analyzer.analyze_node_logs(node_name, hours)
            # Wrap in hybrid format
            results = {
                'timestamp': datetime.now().isoformat(),
                'node': node_name,
                'analysis_type': 'classical_only',
                'classical_ai': results,
                'combined_score': results.get('overall_health_score', 50),
                'hybrid_recommendations': results.get('recommendations', [])
            }
        
        analysis_time = (datetime.now() - start_time).total_seconds()
        click.echo(f"✅ Analysis completed in {analysis_time:.1f} seconds")
        
        # Display results
        _display_hybrid_results(results)
        
        # Export if requested
        if export:
            with open(export, 'w') as f:
                json.dump(results, f, indent=2)
            click.echo(f"💾 Results exported to: {export}")
            
    except Exception as e:
        click.echo(f"❌ Hybrid analysis failed: {e}")
        import traceback
        click.echo(f"🔍 Debug info: {traceback.format_exc()}")

def _display_hybrid_results(results):
    """Display hybrid AI analysis results"""
    click.echo("\n" + "="*80)
    click.echo("🧠 HYBRID AI ANALYSIS RESULTS")
    click.echo("="*80)
    
    # Combined score
    combined_score = results.get('combined_score', 0)
    score_color = "🟢" if combined_score >= 80 else "🟡" if combined_score >= 60 else "🔴"
    click.echo(f"\n{score_color} COMBINED HEALTH SCORE: {combined_score}/100")
    
    # Classical AI results
    classical = results.get('classical_ai', {})
    if classical:
        click.echo(f"\n🔧 CLASSICAL AI RESULTS:")
        click.echo(f"  📊 Health Score: {classical.get('overall_health_score', 'N/A')}/100")
        click.echo(f"  📦 Containers: {classical.get('containers_analyzed', 0)}")
        click.echo(f"  🚨 Alerts: {len(classical.get('alerts', []))}")
    
    # ML results
    ml = results.get('machine_learning', {})
    if ml and not ml.get('error'):
        click.echo(f"\n🤖 MACHINE LEARNING RESULTS:")
        anomaly = ml.get('anomaly_detection', {})
        if anomaly:
            anomaly_status = "🚨 ANOMALY DETECTED" if anomaly.get('is_anomaly') else "✅ Normal Pattern"
            click.echo(f"  {anomaly_status}")
            click.echo(f"  📊 ML Health Score: {ml.get('ml_health_score', 'N/A')}/100")
            click.echo(f"  🎯 Confidence: {anomaly.get('confidence', 'N/A')}%")
    
    # LLM results
    llm = results.get('llm_insights', {})
    if llm and not llm.get('error'):
        click.echo(f"\n🧠 LLM INSIGHTS:")
        if llm.get('summary'):
            click.echo(f"  📝 Summary: {llm['summary'][:200]}...")
        if llm.get('risk_assessment'):
            click.echo(f"  ⚡ Risk: {llm['risk_assessment']}")
    
    # Hybrid recommendations
    recommendations = results.get('hybrid_recommendations', [])
    if recommendations:
        click.echo(f"\n💡 HYBRID RECOMMENDATIONS:")
        for i, rec in enumerate(recommendations[:8], 1):
            click.echo(f"  {i}. {rec}")
    
    click.echo("="*80)

def _display_recommendations(recommendations, node_name, focus):
    """Display AI-generated recommendations."""
    click.echo("\n" + "="*80)
    click.echo(f"🎯 AI RECOMMENDATIONS: {node_name.upper()}")
    click.echo(f"Focus: {focus.upper()}")
    click.echo("="*80)
    
    if not recommendations:
        click.echo("✅ No specific recommendations at this time. System appears to be running optimally.")
        return
    
    # Priority recommendations
    priority = recommendations.get('priority', [])
    if priority:
        click.echo(f"\n🚨 HIGH PRIORITY:")
        for i, rec in enumerate(priority, 1):
            click.echo(f"  {i}. {rec.get('title', 'Unknown')}")
            click.echo(f"     {rec.get('description', 'No description')}")
            if rec.get('action'):
                click.echo(f"     Action: {rec['action']}")
    
    # General recommendations
    general = recommendations.get('general', [])
    if general:
        click.echo(f"\n💡 GENERAL RECOMMENDATIONS:")
        for i, rec in enumerate(general, 1):
            click.echo(f"  {i}. {rec.get('title', 'Unknown')}")
            if rec.get('description'):
                click.echo(f"     {rec['description']}")
    
    # Configuration suggestions
    config_suggestions = recommendations.get('configuration', [])
    if config_suggestions:
        click.echo(f"\n⚙️  CONFIGURATION SUGGESTIONS:")
        for suggestion in config_suggestions:
            click.echo(f"  • {suggestion}")
    
    click.echo("="*80)

# Backward Compatibility Aliases for commonly used commands
# Legacy list command removed - use 'node list' instead
    config = yaml.safe_load(CONFIG_PATH.read_text())
    nodes = config.get('nodes', [])
    
    if not nodes:
        click.echo("❌ No nodes found in configuration")
        return
    
    click.echo("🖥️  ETHEREUM NODE CLUSTER OVERVIEW")
    click.echo("=" * 80)
    
    # Prepare table data
    table_data = []
    active_nodes = 0
    disabled_nodes = 0
    
    # Track client diversity
    exec_clients = {}
    consensus_clients = {}
    
    for node in nodes:
        name = node['name']
        tailscale = node['tailscale_domain']
        ssh_user = node.get('ssh_user', 'root')
        exec_client = node.get('exec_client', '')
        consensus_client = node.get('consensus_client', '')
        stack = node.get('stack', ['eth-docker'])
        
        # Handle both old format (string) and new format (list)
        if isinstance(stack, str):
            stack = [stack]
        
        # Determine status
        if ('disabled' in stack or 
            (not exec_client and not consensus_client) or
            (exec_client == '' and consensus_client == '')):
            status_emoji = "🔴"
            status_text = "Disabled"
            disabled_nodes += 1
        else:
            status_emoji = "🟢"
            status_text = "Active"
            active_nodes += 1
            
            # Track client diversity (only for active nodes)
            if exec_client:
                exec_clients[exec_client] = exec_clients.get(exec_client, 0) + 1
            if consensus_client:
                consensus_clients[consensus_client] = consensus_clients.get(consensus_client, 0) + 1
        
        # Format client info with emojis
        if exec_client and consensus_client:
            clients = f"⚙️ {exec_client} + 🔗 {consensus_client}"
        elif exec_client:
            clients = f"⚙️ {exec_client} (exec only)"
        elif consensus_client:
            clients = f"🔗 {consensus_client} (consensus only)"
        else:
            clients = "❌ No clients"
        
        # Stack info with emojis - handle multiple stacks
        stack_emojis = {
            'eth-docker': '🐳',
            'disabled': '🚫',
            'rocketpool': '🚀',
            'obol': '🔗',
            'hyperdrive': '⚡',
            'charon': '🌐',
            'ssv': '📡',
            'stakewise': '🏦'
        }
        
        if 'disabled' in stack:
            stack_display = "🚫 disabled"
        else:
            # Create display for multiple stacks
            stack_parts = []
            for s in stack:
                emoji = stack_emojis.get(s.lower(), '⚙️')
                stack_parts.append(f"{emoji} {s}")
            stack_display = " + ".join(stack_parts)
        
        table_data.append([
            f"{status_emoji} {name}",
            status_text,
            clients,
            stack_display
        ])
    
    # Display table
    headers = ['Node Name', 'Status', 'Ethereum Clients', 'Stack']
    click.echo(tabulate(table_data, headers=headers, tablefmt='fancy_grid'))
    
    # Summary statistics
    click.echo(f"\n📊 CLUSTER SUMMARY:")
    click.echo(f"  🟢 Active nodes: {active_nodes}")
    click.echo(f"  🔴 Disabled nodes: {disabled_nodes}")
    click.echo(f"  📈 Total nodes: {len(nodes)}")
    
    # Client diversity analysis
    if exec_clients or consensus_clients:
        click.echo(f"\n🌐 CLIENT DIVERSITY:")
        if exec_clients:
            exec_total = sum(exec_clients.values())
            click.echo(f"  ⚙️  Execution clients:")
            for client, count in exec_clients.items():
                percentage = (count / exec_total) * 100
                click.echo(f"    • {client}: {count} node(s) ({percentage:.1f}%)")
        
        if consensus_clients:
            consensus_total = sum(consensus_clients.values())
            click.echo(f"  🔗 Consensus clients:")
            for client, count in consensus_clients.items():
                percentage = (count / consensus_total) * 100
                click.echo(f"    • {client}: {count} node(s) ({percentage:.1f}%)")
        
        # Diversity warning
        if exec_clients and len(exec_clients) == 1:
            click.echo(f"  ⚠️  WARNING: All execution clients are the same type!")
        if consensus_clients and len(consensus_clients) == 1:
            click.echo(f"  ⚠️  WARNING: All consensus clients are the same type!")
    
    # Quick access info
    click.echo(f"\n💡 QUICK ACCESS:")
    click.echo(f"  📋 Detailed status: python -m eth_validators node status <node_name>")
    click.echo(f"  🔧 Node analysis: python -m eth_validators node analyze <node_name>")
    click.echo(f"  🧠 AI analysis: python -m eth_validators ai analyze <node_name>")
    click.echo("=" * 80)

# ============================================================================
# VALIDATOR MANAGEMENT COMMANDS
# ============================================================================

@validator_group.command(name='sync')
@click.option('--nodes', help='Comma-separated list of node names to check (default: all active nodes)')
@click.option('--dry-run', is_flag=True, help='Show what would be updated without making changes')
def sync_validators(nodes, dry_run):
    """🔄 Sync validator CSV with current beacon node statuses"""
    
    node_list = nodes.split(',') if nodes else None
    
    if dry_run:
        click.echo("🔍 DRY RUN MODE - No changes will be made")
    
    try:
        manager = ValidatorSyncManager()
        
        if dry_run:
            # Just show what we would do
            validators = manager.load_current_csv()
            
            # Get nodes to check (same logic as actual sync)
            if node_list:
                target_nodes = [n for n in manager.config['nodes'] if n['name'] in node_list]
            else:
                target_nodes = [n for n in manager.config['nodes'] if n.get('stack') != 'disabled']
            
            click.echo(f"Would check {len(validators)} validators across {len(target_nodes)} nodes:")
            
            for node_config in target_nodes:
                node_validators = manager.get_validators_for_node(node_config['name'], validators)
                click.echo(f"  {node_config['name']}: {len(node_validators)} validators")
        else:
            result = manager.sync_validators(node_list)
            
            if not result.get('success'):
                click.echo(f"❌ Sync failed: {result.get('error')}")
                return
                
    except Exception as e:
        click.echo(f"❌ Error during sync: {e}")

@validator_group.command(name='status')
@click.option('--show-exited', is_flag=True, help='Include exited validators in the output')
@click.option('--node', help='Show validators for specific node only')
def validator_status(show_exited, node):
    """📊 Show current validator status summary"""
    
    try:
        # Try to get active validators first
        if show_exited:
            # Load all validators
            manager = ValidatorSyncManager()
            validators = manager.load_current_csv()
        else:
            # Get only active validators
            validators = get_active_validators_only()
            if not validators:
                # Fallback to all validators if filter fails
                manager = ValidatorSyncManager()
                validators = manager.load_current_csv()
        
        if not validators:
            click.echo("❌ No validators found in CSV")
            return
        
        # Filter by node if specified
        if node:
            validators = [v for v in validators if node in v.get('tailscale dns', '')]
            click.echo(f"📋 Validators on {node}:")
        else:
            click.echo("📋 VALIDATOR STATUS SUMMARY")
            click.echo("=" * 60)
        
        # Group by status
        status_counts = {}
        protocol_counts = {}
        node_counts = {}
        
        for validator in validators:
            # Count by status
            status = validator.get('current_status', 'unknown')
            status_counts[status] = status_counts.get(status, 0) + 1
            
            # Count by protocol
            protocol = validator.get('Protocol', 'unknown')
            protocol_counts[protocol] = protocol_counts.get(protocol, 0) + 1
            
            # Count by node
            node_domain = validator.get('tailscale dns', 'unknown')
            node_counts[node_domain] = node_counts.get(node_domain, 0) + 1
        
        # Display summary
        click.echo(f"\n📊 TOTAL VALIDATORS: {len(validators)}")
        
        if status_counts:
            click.echo(f"\n🔄 Status Distribution:")
            for status, count in sorted(status_counts.items()):
                click.echo(f"  • {status}: {count}")
        
        if protocol_counts:
            click.echo(f"\n🏢 Protocol Distribution:")
            for protocol, count in sorted(protocol_counts.items()):
                click.echo(f"  • {protocol}: {count}")
        
        if node_counts and not node:
            click.echo(f"\n🖥️ Node Distribution:")
            for node_domain, count in sorted(node_counts.items()):
                click.echo(f"  • {node_domain}: {count}")
        
        # Show filtering info
        if not show_exited:
            click.echo(f"\n💡 Showing active validators only. Use --show-exited to include all.")
            
    except Exception as e:
        click.echo(f"❌ Error getting validator status: {e}")

@validator_group.command(name='list-active')
@click.option('--format', type=click.Choice(['table', 'csv', 'json']), default='table', help='Output format')
@click.option('--protocol', help='Filter by protocol (e.g., CSM LIDO, Rocketpool)')
@click.option('--node', help='Filter by node name')
def list_active_validators(format, protocol, node):
    """📋 List all active validators with details"""
    
    try:
        validators = get_active_validators_only()
        
        if not validators:
            click.echo("❌ No active validators found")
            return
        
        # Apply filters
        if protocol:
            validators = [v for v in validators if protocol.lower() in v.get('Protocol', '').lower()]
        
        if node:
            validators = [v for v in validators if node in v.get('tailscale dns', '')]
        
        if not validators:
            click.echo("❌ No validators match the specified filters")
            return
        
        if format == 'table':
            # Create table data
            table_data = []
            for validator in validators:
                row = [
                    validator.get('validator index', ''),
                    validator.get('Protocol', ''),
                    validator.get('current_status', 'unknown'),
                    validator.get('tailscale dns', '').split('.')[0] if '.' in validator.get('tailscale dns', '') else validator.get('tailscale dns', ''),
                    validator.get('stack', '')
                ]
                table_data.append(row)
            
            headers = ['Index', 'Protocol', 'Status', 'Node', 'Stack']
            click.echo(tabulate(table_data, headers=headers, tablefmt='grid'))
            
        elif format == 'csv':
            # Print CSV format
            if validators:
                headers = list(validators[0].keys())
                click.echo(','.join(headers))
                for validator in validators:
                    row = [str(validator.get(h, '')) for h in headers]
                    click.echo(','.join(row))
                    
        elif format == 'json':
            import json
            click.echo(json.dumps(validators, indent=2))
        
        click.echo(f"\n📊 Total: {len(validators)} active validators")
        
    except Exception as e:
        click.echo(f"❌ Error listing validators: {e}")

@validator_group.command(name='edit')
def interactive_edit():
    """🎛️ Interactive validator editor for adding/editing validators"""
    
    try:
        from .validator_editor import main_menu
        main_menu()
        
    except KeyboardInterrupt:
        click.echo("\n👋 Editor closed")
    except Exception as e:
        click.echo(f"❌ Error in interactive editor: {e}")

@validator_group.command(name='add')
def add_validator():
    """🆕 Add a new validator interactively"""
    
    try:
        editor = InteractiveValidatorEditor()
        
        click.echo("🚀 QUICK ADD VALIDATOR")
        click.echo("=" * 40)
        
        new_validator = editor.interactive_add_validator()
        
        # Show preview
        click.echo(f"\n👀 PREVIEW NEW VALIDATOR:")
        for key, value in new_validator.items():
            if value:
                click.echo(f"  {key}: {value}")
        
        if click.confirm("\n💾 Save this validator?"):
            validators = editor.load_validators()
            validators.append(new_validator)
            
            editor.backup_csv()
            if editor.save_validators(validators):
                click.echo("🎉 New validator added successfully!")
                click.echo("💡 Use 'python -m eth_validators validator sync' to update status")
        else:
            click.echo("❌ Validator not saved")
            
    except KeyboardInterrupt:
        click.echo("\n❌ Add validator cancelled")
    except Exception as e:
        click.echo(f"❌ Error adding validator: {e}")

@validator_group.command(name='quick-add')
@click.option('--index', prompt='Validator Index', help='Validator index number')
@click.option('--pubkey', prompt='Public Key (0x...)', help='Validator public key')
@click.option('--protocol', prompt='Protocol', help='Staking protocol (e.g., CSM LIDO, Etherfi)')
@click.option('--stack', prompt='Stack', help='Technology stack (e.g., VERO, HYPERDRIVE, Obol)')
@click.option('--node', prompt='Node name', help='Target node name')
def quick_add_validator(index, pubkey, protocol, stack, node):
    """⚡ Quick add validator with command line options"""
    
    try:
        editor = InteractiveValidatorEditor()
        
        # Validate inputs
        if not editor.validate_validator_index(index):
            return
        
        if not editor.validate_pubkey(pubkey):
            return
        
        # Check if validator already exists
        validators = editor.load_validators()
        if any(str(v.get('validator index', '')) == str(index) for v in validators):
            if not click.confirm(f"⚠️ Validator {index} already exists. Overwrite?"):
                click.echo("❌ Operation cancelled")
                return
        
        # Create validator record
        new_validator = {
            'validator index': str(index),
            'validator public address': pubkey,
            'Protocol': protocol,
            'stack': stack,
            'tailscale dns': editor.get_node_domain(node),
            'current_status': 'unknown',
            'is_active': 'unknown', 
            'is_exited': 'false',
            'last_updated': str(int(time.time()))
        }
        
        # Show preview
        click.echo(f"\n👀 VALIDATOR PREVIEW:")
        click.echo(f"  Index: {index}")
        click.echo(f"  Protocol: {protocol}")
        click.echo(f"  Stack: {stack}")
        click.echo(f"  Node: {node} ({editor.get_node_domain(node)})")
        click.echo(f"  PubKey: {pubkey[:20]}...{pubkey[-10:]}")
        
        if click.confirm("\n💾 Add this validator?"):
            validators.append(new_validator)
            
            editor.backup_csv()
            if editor.save_validators(validators):
                click.echo("🎉 Validator added successfully!")
                click.echo("💡 Run 'python -m eth_validators validator sync' to update status")
        else:
            click.echo("❌ Validator not added")
            
    except Exception as e:
        click.echo(f"❌ Error adding validator: {e}")

@validator_group.command(name='import-csv')
@click.argument('file_path', type=click.Path(exists=True))
@click.option('--dry-run', is_flag=True, help='Preview import without making changes')
def import_validators_csv(file_path, dry_run):
    """📥 Import validators from CSV file"""
    
    try:
        # Basic CSV reading
        import csv
        validators_to_import = []
        with open(file_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                validators_to_import.append(dict(row))
        
        if not validators_to_import:
            click.echo("❌ No validators found in CSV file")
            return
        
        click.echo(f"📋 Found {len(validators_to_import)} validators to import")
        
        # Preview first few
        click.echo(f"\n👀 PREVIEW (first 5 validators):")
        for i, validator in enumerate(validators_to_import[:5]):
            click.echo(f"\n  Validator {i+1}:")
            for key, value in validator.items():
                if value:
                    click.echo(f"    {key}: {value}")
        
        if len(validators_to_import) > 5:
            click.echo(f"    ... and {len(validators_to_import) - 5} more")
        
        if dry_run:
            click.echo(f"\n🔍 DRY RUN: Would import {len(validators_to_import)} validators")
            return
        
        if not click.confirm(f"\n💾 Import {len(validators_to_import)} validators?"):
            click.echo("❌ Import cancelled")
            return
        
        # Load existing validators
        editor = InteractiveValidatorEditor()
        existing_validators = editor.load_validators()
        
        # Process imports
        imported_count = 0
        skipped_count = 0
        
        for validator_data in validators_to_import:
            # Ensure required fields
            index = validator_data.get('validator index', '').strip()
            if not index:
                click.echo(f"  ⚠️ Skipping validator without index")
                skipped_count += 1
                continue
            
            # Check if already exists
            if any(str(v.get('validator index', '')) == str(index) for v in existing_validators):
                click.echo(f"  ⚠️ Skipping existing validator {index}")
                skipped_count += 1
                continue
            
            # Add timestamp and status fields
            validator_data['last_updated'] = str(int(time.time()))
            if 'current_status' not in validator_data:
                validator_data['current_status'] = 'unknown'
            if 'is_active' not in validator_data:
                validator_data['is_active'] = 'unknown'
            if 'is_exited' not in validator_data:
                validator_data['is_exited'] = 'false'
            
            existing_validators.append(validator_data)
            imported_count += 1
            click.echo(f"  ✅ Imported validator {index}")
        
        # Save if any were imported
        if imported_count > 0:
            editor.backup_csv()
            if editor.save_validators(existing_validators):
                click.echo(f"\n🎉 Successfully imported {imported_count} validators!")
                click.echo(f"⚠️ Skipped {skipped_count} validators (duplicates or missing data)")
                click.echo("💡 Run 'python -m eth_validators validator sync' to update statuses")
        else:
            click.echo("❌ No validators were imported")
            
    except Exception as e:
        click.echo(f"❌ Error importing validators: {e}")

@validator_group.command(name='export')
@click.option('--format', type=click.Choice(['csv', 'json']), default='csv', help='Export format')
@click.option('--output', help='Output file path (default: auto-generated)')
@click.option('--active-only', is_flag=True, help='Export only active validators')
def export_validators(format, output, active_only):
    """📤 Export validators to file"""
    
    try:
        editor = InteractiveValidatorEditor()
        
        if active_only:
            from .validator_sync import get_active_validators_only
            validators = get_active_validators_only()
            suffix = "_active"
        else:
            validators = editor.load_validators()
            suffix = "_all"
        
        if not validators:
            click.echo("❌ No validators to export")
            return
        
        # Generate output filename if not provided
        if not output:
            timestamp = int(time.time())
            output = f"validators_export{suffix}_{timestamp}.{format}"
        
        if format == 'csv':
            # Export as CSV
            if not validators:
                click.echo("❌ No validators to export")
                return
            
            # Get all field names
            all_fields = set()
            for validator in validators:
                all_fields.update(validator.keys())
            
            ordered_fields = [
                'validator index', 'validator public address', 'Protocol', 'stack',
                'tailscale dns', 'current_status', 'is_active', 'is_exited'
            ]
            
            # Add remaining fields
            for field in sorted(all_fields):
                if field not in ordered_fields:
                    ordered_fields.append(field)
            
            with open(output, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=ordered_fields)
                writer.writeheader()
                for validator in validators:
                    row = {field: validator.get(field, '') for field in ordered_fields}
                    writer.writerow(row)
                    
        elif format == 'json':
            # Export as JSON
            import json
            with open(output, 'w') as f:
                json.dump(validators, f, indent=2)
        
        click.echo(f"📄 Exported {len(validators)} validators to {output}")
        
    except Exception as e:
        click.echo(f"❌ Error exporting validators: {e}")

@validator_group.command(name='search')
@click.argument('term', required=False)
def search_validators(term):
    """🔍 Search validators by index, protocol, node, or pubkey"""
    
    try:
        editor = InteractiveValidatorEditor()
        validators = editor.load_validators()
        
        if not validators:
            click.echo("❌ No validators found")
            return
        
        if not term:
            term = click.prompt("Enter search term")
        
        term = term.lower().strip()
        matches = []
        
        for validator in validators:
            searchable_text = ' '.join([
                str(validator.get('validator index', '')),
                validator.get('Protocol', ''),
                validator.get('tailscale dns', ''),
                validator.get('validator public address', ''),
                validator.get('stack', ''),
                validator.get('current_status', '')
            ]).lower()
            
            if term in searchable_text:
                matches.append(validator)
        
        if matches:
            click.echo(f"\n📊 SEARCH RESULTS ({len(matches)} found)")
            click.echo("=" * 50)
            
            table_data = []
            for validator in matches:
                table_data.append([
                    validator.get('validator index', ''),
                    validator.get('Protocol', '')[:20],
                    validator.get('tailscale dns', '').split('.')[0] if '.' in validator.get('tailscale dns', '') else validator.get('tailscale dns', ''),
                    validator.get('current_status', 'unknown'),
                    validator.get('validator public address', '')[:20] + '...'
                ])
            
            headers = ['Index', 'Protocol', 'Node', 'Status', 'PubKey']
            click.echo(tabulate(table_data, headers=headers, tablefmt='grid'))
            
            # Ask if user wants to edit any
            if click.confirm("\n✏️ Open interactive editor for these results?"):
                from .validator_editor import main_menu
                main_menu()
        else:
            click.echo(f"❌ No validators found matching '{term}'")
            
    except Exception as e:
        click.echo(f"❌ Error searching validators: {e}")

@validator_group.command(name='stats')
def validator_statistics():
    """📊 Show detailed validator statistics"""
    
    try:
        editor = InteractiveValidatorEditor()
        validators = editor.load_validators()
        
        if not validators:
            click.echo("❌ No validators found")
            return
        
        click.echo(f"\n📊 VALIDATOR STATISTICS")
        click.echo("=" * 60)
        click.echo(f"📋 Total validators: {len(validators)}")
        
        # Group by protocol
        protocols = {}
        for v in validators:
            protocol = v.get('Protocol', 'Unknown')
            protocols[protocol] = protocols.get(protocol, 0) + 1
        
        click.echo(f"\n🏢 By Protocol:")
        for protocol, count in sorted(protocols.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / len(validators)) * 100
            click.echo(f"  • {protocol}: {count} ({percentage:.1f}%)")
        
        # Group by node
        nodes = {}
        for v in validators:
            node_domain = v.get('tailscale dns', 'Unknown')
            node = node_domain.split('.')[0] if '.' in node_domain else node_domain
            nodes[node] = nodes.get(node, 0) + 1
        
        click.echo(f"\n🖥️ By Node:")
        for node, count in sorted(nodes.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / len(validators)) * 100
            click.echo(f"  • {node}: {count} ({percentage:.1f}%)")
        
        # Group by status
        statuses = {}
        for v in validators:
            status = v.get('current_status', 'unknown')
            statuses[status] = statuses.get(status, 0) + 1
        
        click.echo(f"\n🔄 By Status:")
        for status, count in sorted(statuses.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / len(validators)) * 100
            click.echo(f"  • {status}: {count} ({percentage:.1f}%)")
        
        # Group by stack
        stacks = {}
        for v in validators:
            stack = v.get('stack', 'Unknown')
            stacks[stack] = stacks.get(stack, 0) + 1
        
        click.echo(f"\n🏗️ By Stack:")
        for stack, count in sorted(stacks.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / len(validators)) * 100
            click.echo(f"  • {stack}: {count} ({percentage:.1f}%)")
        
        # Active vs Exited
        active_count = sum(1 for v in validators if v.get('is_exited', 'false').lower() != 'true')
        exited_count = len(validators) - active_count
        
        click.echo(f"\n⚡ Activity Status:")
        click.echo(f"  • Active: {active_count} ({(active_count/len(validators))*100:.1f}%)")
        click.echo(f"  • Exited: {exited_count} ({(exited_count/len(validators))*100:.1f}%)")
        
    except Exception as e:
        click.echo(f"❌ Error generating statistics: {e}")

if __name__ == "__main__":
    cli()
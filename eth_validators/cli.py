import click
import yaml
import subprocess
from pathlib import Path
from tabulate import tabulate
import re
from . import performance
from .config import get_node_config, get_all_node_configs
from .performance import get_performance_summary
from .node_manager import get_node_status, upgrade_node_docker_clients, get_system_update_status, perform_system_upgrade, get_docker_client_versions

CONFIG_PATH = Path(__file__).parent / 'config.yaml'

@click.group()
def cli():
    pass

@cli.command(name='list')
def list_cmd():
    """List all configured nodes"""
    config = yaml.safe_load(CONFIG_PATH.read_text())
    for node in config.get('nodes', []):
        click.echo(f"{node['name']}: ssh={node.get('ssh_user','root')}@{node['tailscale_domain']}, "
                   f"exec={node['exec_client']}, consensus={node['consensus_client']}")
    

@cli.command("status")
@click.argument('name')
@click.option('--images', is_flag=True, help="Show full image names.")
def status_cmd(name, images):
    """Show status of one node."""
    print(f"Fetching status for {name}...")
    node_config = get_node_config(name)
    if not node_config:
        print(f"Node '{name}' not found in config.yaml.")
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

@cli.command()
@click.argument('node')
@click.option('--images', is_flag=True, help='Also show container image versions')
def status(node, images):
    """Show status of a single node (by name or Tailscale domain)"""
    config = yaml.safe_load(CONFIG_PATH.read_text())
    node_cfg = next(
        (n for n in config['nodes'] if n.get('tailscale_domain') == node or n.get('name') == node),
        None
    )
    if not node_cfg:
        click.echo(f"Node {node} not found")
        return
    # SSH into node using ssh_user and run docker ps
    ssh_target = f"{node_cfg.get('ssh_user', 'root')}@{node_cfg['tailscale_domain']}"
    # Show running containers
    subprocess.run(['ssh', ssh_target, 'docker', 'ps'])
    if images:
        # Show all service images defined in compose
        compose_dir = node_cfg['eth_docker_path']
        img_cmd = (
            f"ssh {ssh_target} \"cd {compose_dir} && docker compose images\""
        )
        subprocess.run(img_cmd, shell=True)

@cli.command()
@click.argument('node')
def upgrade(node):
    """Run upgrade on a single node (by name or Tailscale domain)"""
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
    exec_client = node_cfg.get('exec_client', '')
    consensus_client = node_cfg.get('consensus_client', '')
    
    if (stack == 'disabled' or 
        (not exec_client and not consensus_client) or
        (exec_client == '' and consensus_client == '')):
        click.echo(f"⚪ Skipping {node} (Ethereum clients disabled)")
        return
        
    # SSH into node using ssh_user, pull new eth-docker, and restart
    ssh_target = f"{node_cfg.get('ssh_user', 'root')}@{node_cfg['tailscale_domain']}"
    cmd = (
        f"ssh {ssh_target} 'cd {node_cfg['eth_docker_path']} && git checkout main && git pull && "
        "docker compose pull && docker compose build --pull && docker compose up -d'"
    )
    subprocess.run(cmd, shell=True)

@cli.command(name='versions-all')
def versions_all():
    """Show client versions for all configured nodes in a fun table format with latest versions from GitHub"""
    config = yaml.safe_load(CONFIG_PATH.read_text())
    table = []
    
    click.echo("🔍 Fetching client versions and checking GitHub for latest releases...")
    
    for node_cfg in config.get('nodes', []):
        name = node_cfg['name']
        
        # Skip nodes with disabled eth-docker
        stack = node_cfg.get('stack', 'eth-docker')
        exec_client = node_cfg.get('exec_client', '')
        consensus_client = node_cfg.get('consensus_client', '')
        
        if (stack == 'disabled' or 
            (not exec_client and not consensus_client) or
            (exec_client == '' and consensus_client == '')):
            click.echo(f"  ⚪ Skipping {name} (Ethereum clients disabled)")
            continue
            
        click.echo(f"  📡 Checking {name}...", nl=False)
        
        ssh_target = f"{node_cfg.get('ssh_user','root')}@{node_cfg['tailscale_domain']}"
        path = node_cfg['eth_docker_path']
        
        # Fetch version output using ethd
        result = subprocess.run(
            f"ssh {ssh_target} \"cd {path} && ./ethd version\"",
            shell=True, capture_output=True, text=True
        )
        output = result.stdout + result.stderr
        
        # Also get versions using our Docker detection method for latest versions
        try:
            version_info = get_docker_client_versions(node_cfg)
        except:
            version_info = {}
        
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

@cli.command(name='analyze-node')
@click.argument('node_name')
def analyze_node_cmd(node_name):
    """
    Analyzes all validators for a specific node in detail, especially useful for multi-stack nodes.
    """
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

@cli.command(name='performance')
def performance_cmd():
    """
    Fetches and displays performance metrics for all validators, with color-coded
    alerts for potential issues.
    """
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


@cli.command(name='upgrade-all')
def upgrade_all():
    """Upgrade all configured nodes with active Ethereum clients"""
    config = yaml.safe_load(CONFIG_PATH.read_text())
    for node_cfg in config.get('nodes', []):
        name = node_cfg['name']
        
        # Skip nodes with disabled eth-docker
        stack = node_cfg.get('stack', 'eth-docker')
        exec_client = node_cfg.get('exec_client', '')
        consensus_client = node_cfg.get('consensus_client', '')
        
        if (stack == 'disabled' or 
            (not exec_client and not consensus_client) or
            (exec_client == '' and consensus_client == '')):
            click.echo(f"⚪ Skipping {name} (Ethereum clients disabled)")
            continue
            
        click.echo(f"Upgrading {name}...")
        ssh_target = f"{node_cfg.get('ssh_user','root')}@{node_cfg['tailscale_domain']}"
        cmd = (
            f"ssh {ssh_target} 'cd {node_cfg['eth_docker_path']} && git checkout main && git pull && "
            "docker compose pull && docker compose build --pull && docker compose up -d'"
        )
        subprocess.run(cmd, shell=True)

@cli.command()
@click.argument('node')
def versions(node):
    """Show client versions for a node (filtered via eth-docker .ethd version)"""
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
    exec_client = node_cfg.get('exec_client', '')
    consensus_client = node_cfg.get('consensus_client', '')
    
    if (stack == 'disabled' or 
        (not exec_client and not consensus_client) or
        (exec_client == '' and consensus_client == '')):
        click.echo(f"⚪ Node {node} has Ethereum clients disabled")
        return
        
    ssh_target = f"{node_cfg.get('ssh_user','root')}@{node_cfg['tailscale_domain']}"
    path = node_cfg['eth_docker_path']
    # Run full .ethd version remotely
    cmd = f"ssh {ssh_target} \"cd {path} && ./ethd version\""
    subprocess.run(cmd, shell=True)

@cli.command('client-versions')
@click.argument('node_name', required=False)
def client_versions(node_name):
    """Check Ethereum client versions (current vs latest) for Docker containers."""
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
        stack = node.get('stack', 'eth-docker')
        exec_client = node.get('exec_client', '')
        consensus_client = node.get('consensus_client', '')
        
        if (stack == 'disabled' or 
            (not exec_client and not consensus_client) or
            (exec_client == '' and consensus_client == '')):
            click.echo(f"⚪ Skipping {node['name']} (Ethereum clients disabled)")
            continue
            
        click.echo(f"Checking client versions for {node['name']}...")
        try:
            version_info = get_docker_client_versions(node)
            
            # Get client names and versions
            exec_client = version_info.get('execution_client', 'Unknown')
            exec_current = version_info.get('execution_current', 'Unknown')
            exec_latest = version_info.get('execution_latest', 'Unknown')
            exec_needs_update = version_info.get('execution_needs_update', False)
            
            cons_client = version_info.get('consensus_client', 'Unknown')
            cons_current = version_info.get('consensus_current', 'Unknown') 
            cons_latest = version_info.get('consensus_latest', 'Unknown')
            cons_needs_update = version_info.get('consensus_needs_update', False)
            
            # Format compact client/version display
            if exec_client != "Unknown" and exec_current != "Unknown":
                exec_display = f"{exec_client}/{exec_current}"
            else:
                exec_display = "Unknown"
                
            if cons_client != "Unknown" and cons_current != "Unknown":
                cons_display = f"{cons_client}/{cons_current}"
            else:
                cons_display = "Unknown"
            
            # Format latest versions compactly
            exec_latest_display = exec_latest if exec_latest != "Unknown" else "-"
            cons_latest_display = cons_latest if cons_latest != "Unknown" else "-"
            
            # Add single row with both clients
            results.append([
                node['name'],
                exec_display,
                exec_latest_display,
                '🔄' if exec_needs_update else '✅',
                cons_display,
                cons_latest_display,
                '🔄' if cons_needs_update else '✅'
            ])
        except Exception as e:
            click.echo(f"❌ Error checking {node['name']}: {e}")
            results.append([node['name'], 'Error', '-', '❌', 'Error', '-', '❌'])
    
    # Display results in table format
    if results:
        headers = ['Node', 'Execution', 'Latest', '🔄', 'Consensus', 'Latest', '🔄']
        click.echo("\n" + tabulate(results, headers=headers, tablefmt='grid'))
        
        # Summary
        nodes_needing_updates = set()
        exec_updates = 0
        cons_updates = 0
        
        for result in results:
            if result[3] == '🔄':  # Execution Update column
                nodes_needing_updates.add(result[0])  # Node name
                exec_updates += 1
            if result[6] == '🔄':  # Consensus Update column  
                nodes_needing_updates.add(result[0])  # Node name
                cons_updates += 1
        
        click.echo(f"\n📊 Summary:")
        if nodes_needing_updates:
            click.echo(f"🔄 Nodes with client updates available: {', '.join(sorted(nodes_needing_updates))}")
            if exec_updates > 0:
                click.echo(f"⚡ Execution clients needing updates: {exec_updates}")
            if cons_updates > 0:
                click.echo(f"⛵ Consensus clients needing updates: {cons_updates}")
            click.echo(f"💡 Run 'python -m eth_validators upgrade <node>' to update specific nodes")
            click.echo(f"💡 Run 'python -m eth_validators upgrade-all' to update all nodes")
        else:
            click.echo("✅ All Ethereum clients are up to date!")
    else:
        click.echo("❌ No version information collected.")

@cli.command(name='system-updates')
@click.argument('node', required=False)
def system_updates_cmd(node):
    """Check if Ubuntu system updates are available on nodes (does not install)"""
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
    for node_cfg in nodes_to_check:
        name = node_cfg['name']
        click.echo(f"Checking system updates for {name}...")
        update_status = get_system_update_status(node_cfg)
        
        updates_count = update_status.get('updates_available', 'Error')
        needs_update = "Yes" if update_status.get('needs_system_update', False) else "No"
        
        table_data.append([name, updates_count, needs_update])
    
    headers = ["Node", "Updates Available", "Needs Update"]
    click.echo("\n" + tabulate(table_data, headers=headers, tablefmt="github"))
    
    if any(row[2] == "Yes" for row in table_data):
        click.echo("\n⚠️  To install system updates, use:")
        click.echo("   python3 -m eth_validators system-upgrade <node>")
        click.echo("   python3 -m eth_validators system-upgrade --all")
    else:
        click.echo("\n✅ All nodes are up to date!")

@cli.command(name='system-upgrade')
@click.argument('node', required=False)
@click.option('--all', 'upgrade_all_nodes', is_flag=True, help='Upgrade all nodes (will check which need updates first)')
@click.option('--force', is_flag=True, help='Skip update check and force upgrade')
def system_upgrade_cmd(node, upgrade_all_nodes, force):
    """Perform Ubuntu system upgrade on nodes (sudo apt update && sudo apt upgrade -y)"""
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

if __name__ == "__main__":
    cli()
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
from .ai_analyzer import ValidatorLogAnalyzer

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

@cli.command(name='ai-analyze')
@click.argument('node_name')
@click.option('--container', help='Specific container to analyze (e.g., lighthouse-validator-client)')
@click.option('--hours', default=24, type=int, help='Hours of logs to analyze (default: 24)')
@click.option('--severity', default='INFO', help='Minimum log severity level (DEBUG, INFO, WARN, ERROR)')
def ai_analyze_cmd(node_name, container, hours, severity):
    """
    AI-powered analysis of validator logs for performance insights and anomaly detection.
    """
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

@cli.command(name='ai-health')
@click.argument('node_name', required=False)
@click.option('--threshold', default=70, type=int, help='Health score threshold for alerts (default: 70)')
def ai_health_cmd(node_name, threshold):
    """
    Check AI-calculated health scores for validators across nodes.
    """
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

@cli.command(name='ai-patterns')
@click.argument('node_name')
@click.option('--days', default=7, type=int, help='Days of log history to analyze (default: 7)')
@click.option('--pattern-type', default='all', help='Pattern type: errors, warnings, performance, or all')
def ai_patterns_cmd(node_name, days, pattern_type):
    """
    Discover and analyze patterns in validator logs using AI pattern recognition.
    """
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

@cli.command(name='ai-recommend')
@click.argument('node_name')
@click.option('--focus', default='performance', help='Recommendation focus: performance, reliability, security, or all')
def ai_recommend_cmd(node_name, focus):
    """
    Get AI-powered recommendations for validator optimization and issue resolution.
    """
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

if __name__ == "__main__":
    cli()
import click
import yaml
import subprocess
from pathlib import Path
from tabulate import tabulate
import re
from . import performance
from .config import get_node_config, get_all_node_configs
from .performance import get_performance_summary
from .node_manager import get_node_status

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
    # SSH into node using ssh_user, pull new eth-docker, and restart
    ssh_target = f"{node_cfg.get('ssh_user', 'root')}@{node_cfg['tailscale_domain']}"
    cmd = (
        f"ssh {ssh_target} 'cd {node_cfg['eth_docker_path']} && git checkout main && git pull && "
        "docker compose pull && docker compose build --pull && docker compose up -d'"
    )
    subprocess.run(cmd, shell=True)

@cli.command(name='versions-all')
def versions_all():
    """Show client versions for all configured nodes in a table"""
    config = yaml.safe_load(CONFIG_PATH.read_text())
    table = []
    for node_cfg in config.get('nodes', []):
        name = node_cfg['name']
        ssh_target = f"{node_cfg.get('ssh_user','root')}@{node_cfg['tailscale_domain']}"
        path = node_cfg['eth_docker_path']
        # Fetch version output
        result = subprocess.run(
            f"ssh {ssh_target} \"cd {path} && ./ethd version\"",
            shell=True, capture_output=True, text=True
        )
        output = result.stdout + result.stderr
        # Identify components
        exec_comp = node_cfg.get('exec_client', '')
        cons_comp = node_cfg.get('consensus_client', '')
        mev_comp = 'mev-boost'
        def find_version(output, keyword):
            lines = output.splitlines()
            for idx, line in enumerate(lines):
                if keyword.lower() in line.lower():
                    version_line = line.strip()
                    # capture next line if it contains version info
                    if idx + 1 < len(lines):
                        next_line = lines[idx+1].strip()
                        if next_line.lower().startswith('version') or re.match(r'v?\d', next_line):
                            version_line = f"{version_line} {next_line}"
                    return version_line
            return "N/A"
        exec_ver = find_version(output, exec_comp)
        cons_ver = find_version(output, cons_comp)
        mev_ver = find_version(output, mev_comp)
        table.append([name, exec_ver, cons_ver, mev_ver])
    # Print as table
    headers = ["Node", "Execution", "Consensus", "MEV Boost"]
    click.echo(tabulate(table, headers=headers, tablefmt="github"))

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
    """Upgrade all configured nodes"""
    config = yaml.safe_load(CONFIG_PATH.read_text())
    for node_cfg in config.get('nodes', []):
        name = node_cfg['name']
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
    ssh_target = f"{node_cfg.get('ssh_user','root')}@{node_cfg['tailscale_domain']}"
    path = node_cfg['eth_docker_path']
    # Run full .ethd version remotely
    cmd = f"ssh {ssh_target} \"cd {path} && ./ethd version\""
    subprocess.run(cmd, shell=True)

if __name__ == "__main__":
    cli()
import click
import yaml
import subprocess
import time
import csv
import json
import random
import os
from pathlib import Path
from tabulate import tabulate
import re
from datetime import datetime
from . import performance
from .config import get_node_config, get_all_node_configs
from .performance import get_performance_summary
from .node_manager import (
    get_node_status,
    upgrade_node_docker_clients,
    get_system_update_status,
    perform_system_upgrade,
    get_docker_client_versions,
    get_node_port_mappings,
    get_env_p2p_ports,
    get_compose_p2p_ports,
    run_command_on_node,
)
from .ai_analyzer import ValidatorLogAnalyzer
from .validator_sync import ValidatorSyncManager, get_active_validators_only
from .validator_editor import InteractiveValidatorEditor
from .validator_auto_discovery import ValidatorAutoDiscovery, auto_generate_validators_csv
from .simple_setup import SimpleSetupWizard, quick_start_new_user, show_next_steps

def get_config_path():
    """Find config.yaml in current directory first, then in eth_validators directory"""
    # First check current working directory (where user runs the command)
    current_dir_config = Path.cwd() / 'config.yaml'
    if current_dir_config.exists():
        return current_dir_config
    
    # Fallback to the default location (for backward compatibility)
    default_config = Path(__file__).parent / 'config.yaml'
    return default_config

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

def _detect_running_stacks(node_cfg):
    """Detect all running stacks/services on a node by checking docker containers"""
    detected_stacks = []
    
    try:
        # Get all running containers
        command = "docker ps --format 'table {{.Names}}\t{{.Image}}' | tail -n +2"
        result = _run_command(node_cfg, command)
        
        if result.returncode != 0 or not result.stdout.strip():
            return ["unknown"]
        
        containers = result.stdout.strip().split('\n')
        container_info = []
        
        for container_line in containers:
            # Handle both tab and space separated output
            if '\t' in container_line:
                name, image = container_line.split('\t', 1)
                container_info.append({'name': name.strip(), 'image': image.strip()})
            else:
                # Handle space-separated format
                parts = container_line.split()
                if len(parts) >= 2:
                    name = parts[0]
                    image = parts[1]
                    container_info.append({'name': name, 'image': image})
        
        # Detect different stacks based on container patterns
        stack_indicators = {
            'charon': ['charon', 'obolnetwork/charon'],
            'rocketpool': ['rocketpool', 'rocket-pool', 'rp_', 'rp-'],
            'hyperdrive': ['hyperdrive', 'nodeset'],
            'ssv': ['ssv', 'bloxstaking'],
            'lido-csm': ['lido', 'csm'],
            'stakewise': ['stakewise'],
            'eth-docker': ['eth-docker', 'ethereum/client-go', 'sigp/lighthouse', 'consensys/teku', 'status-im/nimbus-eth2', 'chainsafe/lodestar', 'prysmaticlabs/prysm-beacon-chain'],
            'nethermind': ['nethermind'],
            'besu': ['hyperledger/besu'],
            'geth': ['ethereum/client-go'],
            'reth': ['ghcr.io/paradigmxyz/reth'],
            'lighthouse': ['sigp/lighthouse'],
            'teku': ['consensys/teku'],
            'nimbus': ['nimbus'],
            'lodestar': ['chainsafe/lodestar'],
            'prysm': ['prysmaticlabs/prysm'],
            'vero': ['obolnetwork/vero', 'vouch', 'vero:']
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
        
        # Special logic to group clients under eth-docker if present
        client_stacks = ['nethermind', 'besu', 'geth', 'reth', 'lighthouse', 'teku', 'nimbus', 'lodestar', 'prysm']
        if 'eth-docker' in detected_stacks:
            # Remove individual client detections if eth-docker is present
            detected_stacks = [s for s in detected_stacks if s not in client_stacks]
        
        # Add back main detected clients for display
        main_clients = []
        for container in container_info:
            image_lower = container['image'].lower()
            if any(client in image_lower for client in ['nethermind', 'besu', 'geth', 'reth']):
                for client in ['nethermind', 'besu', 'geth', 'reth']:
                    if client in image_lower and client not in main_clients:
                        main_clients.append(client)
            if any(client in image_lower for client in ['lighthouse', 'teku', 'nimbus', 'lodestar', 'prysm']):
                for client in ['lighthouse', 'teku', 'nimbus', 'lodestar', 'prysm']:
                    if client in image_lower and client not in main_clients:
                        main_clients.append(client)
        
        # Final stack list
        if not detected_stacks:
            detected_stacks = ["unknown"]
        
        # Add main clients to the stack info for display purposes
        if main_clients:
            detected_stacks.extend(main_clients)
        
        return detected_stacks
        
    except Exception as e:
        return ["error"]

def _get_charon_version(ssh_target, tailscale_domain, node_cfg=None):
    """Get Charon version if it's running on the node"""
    try:
        # First try to get the actual running version by executing charon version
        command = "docker ps --format 'table {{.Names}}' | grep charon | grep -v lodestar | head -1"
        result = _run_command(node_cfg, command) if node_cfg else subprocess.run(f"ssh -o ConnectTimeout=10 -o BatchMode=yes {ssh_target} \"{command}\"", shell=True, capture_output=True, text=True, timeout=15)
        
        if result.returncode == 0 and result.stdout.strip():
            container_name = result.stdout.strip()
            
            # Try to get actual version from the running container
            version_command = f"docker exec {container_name} charon version 2>/dev/null | head -1 | awk '{{print $1}}' || echo 'exec_failed'"
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
@click.option('--reboot', is_flag=True, help='Automatically reboot nodes if required after upgrade')
def system_update(node, all, reboot):
    """Check for available Ubuntu system updates and optionally upgrade."""
    config = yaml.safe_load(get_config_path().read_text())
    
    if all and node:
        click.echo("❌ Cannot specify both --all and a node name")
        return
    elif not all and not node:
        click.echo("❌ Must specify either --all or a node name")
        return
    
    nodes_to_check = []
    if all:
        nodes_to_check = config.get('nodes', [])
    else:
        node_cfg = next(
            (n for n in config['nodes'] if n.get('tailscale_domain') == node or n.get('name') == node),
            None
        )
        if not node_cfg:
            click.echo(f"❌ Node {node} not found")
            return
        nodes_to_check.append(node_cfg)

    click.echo(f"🔄 Checking system update status for {'all configured' if all else node} nodes...")
    
    table_data = []
    nodes_needing_update = []
    nodes_needing_reboot = []
    processed_reboot_nodes = set()
    
    for i, node_cfg in enumerate(nodes_to_check):
        name = node_cfg['name']
        stack = node_cfg.get('stack', ['eth-docker'])
        
        if all:
            click.echo(f"📡 Checking {name}... ({i+1}/{len(nodes_to_check)})", nl=False, err=True)
        
        # Skip disabled nodes but still show them, UNLESS they have validator-only clients
        if _is_stack_disabled(stack):
            validator_info = _get_validator_only_clients(node_cfg)
            if not (validator_info and validator_info['has_clients']):
                if all:
                    table_data.append([f"🔴 {name}", "Disabled", "-", "-"])
                    click.echo(" ✓", err=True)
                else:
                    click.echo(f"⚪ Node {name} is disabled")
                continue
        
        try:
            status = get_system_update_status(node_cfg)
            updates_available = status.get('updates_available', 'Error')
            needs_update = status.get('needs_system_update', False)
            is_local = node_cfg.get('is_local', False)
            reboot_needed_before = _check_reboot_needed(node_cfg.get('ssh_user', 'root'), node_cfg['tailscale_domain'], is_local)
            
            if needs_update:
                nodes_needing_update.append(node_cfg)
            if isinstance(reboot_needed_before, str) and "Yes" in reboot_needed_before:
                nodes_needing_reboot.append(node_cfg)

            if all:
                if isinstance(updates_available, int):
                    update_count = updates_available
                    status_emoji = "🟡" if needs_update else "🟢"
                    status_text = f"Updates available ({update_count})" if needs_update else "Up to date"
                    table_data.append([
                        f"{status_emoji} {name}",
                        status_text,
                        f"{update_count} packages" if update_count > 0 else "None",
                        reboot_needed_before
                    ])
                else:
                    table_data.append([f"❌ {name}", f"Check failed: {updates_available}", "-", "❓ Unknown"])
                click.echo(" ✓", err=True)
            else: # single node display
                click.echo(f"\n📊 SYSTEM UPDATE STATUS: {name.upper()}")
                click.echo("=" * 50)
                if isinstance(updates_available, int):
                    update_count = updates_available
                    if needs_update:
                        click.echo(f"🟡 Status: Updates available ({update_count} packages)")
                        click.echo(f"📦 Available updates: {update_count}")
                        click.echo(f"🔄 Reboot needed: {reboot_needed_before}")
                    else:
                        click.echo(f"🟢 Status: Up to date")
                        click.echo(f"📦 Available updates: None")
                        click.echo(f"🔄 Reboot needed: {reboot_needed_before}")
                else:
                    click.echo(f"❌ Status: Check failed")
                    click.echo(f"📦 Error: {updates_available}")
                    click.echo(f"🔄 Reboot needed: {reboot_needed_before}")

        except Exception as e:
            if all:
                table_data.append([f"❌ {name}", f"Error: {str(e)[:30]}...", "-", "❓ Unknown"])
                click.echo(f" ❌ Error", err=True)
            else:
                click.echo(f"❌ Error checking system updates: {e}")

    if all:
        click.echo("\nRendering system update status table...")
        headers = ['Node', 'Update Status', 'Available Updates', 'Reboot Needed']
        click.echo(tabulate(table_data, headers=headers, tablefmt='fancy_grid'))

    if nodes_needing_update:
        node_names = [n['name'] for n in nodes_needing_update]
        click.echo(f"\n⚠️  Nodes needing system updates: {', '.join(node_names)}")
        
        # Use explicit input handling for better reliability
        import sys
        if sys.stdin.isatty():
            while True:
                try:
                    response = input(f"\n💡 Do you want to upgrade {len(node_names)} node(s) now? [y/N]: ").strip().lower()
                    if response in ['y', 'yes']:
                        should_upgrade = True
                        break
                    elif response in ['n', 'no', '']:
                        should_upgrade = False
                        break
                    else:
                        click.echo("❌ Please enter 'y' for yes or 'n' for no.")
                except (EOFError, KeyboardInterrupt):
                    click.echo("\nℹ️  Input cancelled by user.")
                    should_upgrade = False
                    break
                except Exception as e:
                    click.echo(f"❌ Input error: {e}")
                    should_upgrade = False
                    break
        else:
            # Non-interactive mode, default to no
            click.echo(f"\n⚠️  Non-interactive terminal detected. Skipping upgrade prompt (use --reboot to auto-upgrade).")
            should_upgrade = False

        if should_upgrade:
            click.echo("🔄 Upgrading system packages...")
            upgrade_results = []
            for i, node_cfg in enumerate(nodes_needing_update):
                name = node_cfg['name']
                click.echo(f"\n🔄 Upgrading {name}... ({i+1}/{len(nodes_needing_update)})")
                try:
                    result = perform_system_upgrade(node_cfg)
                    if result.get('upgrade_success', False):
                        click.echo(f"✅ {name} system upgrade completed successfully")
                        upgrade_results.append((name, True, None))
                        
                        is_local = node_cfg.get('is_local', False)
                        reboot_status = _check_reboot_needed(node_cfg.get('ssh_user', 'root'), node_cfg['tailscale_domain'], is_local)
                        if "Yes" in reboot_status:
                            if reboot:
                                click.echo(f"🔄 Rebooting {name}...")
                                if _initiate_reboot(node_cfg):
                                    click.echo(f"🔄 {name} reboot initiated")
                                else:
                                    click.echo(f"❌ Failed to initiate reboot for {name}. Please reboot manually.")
                                processed_reboot_nodes.add(name)
                            else:
                                if sys.stdin.isatty():
                                    while True:
                                        try:
                                            resp = input(f"🔄 {name} needs a reboot. Reboot now? [y/N]: ").strip().lower()
                                            if resp in ['y', 'yes']:
                                                click.echo(f"🔄 Rebooting {name}...")
                                                if _initiate_reboot(node_cfg):
                                                    click.echo(f"🔄 {name} reboot initiated")
                                                else:
                                                    click.echo(f"❌ Failed to initiate reboot for {name}. Please reboot manually.")
                                                processed_reboot_nodes.add(name)
                                                break
                                            elif resp in ['n', 'no', '']:
                                                click.echo(f"ℹ️  Skipping reboot for {name}. Reboot later if needed.")
                                                processed_reboot_nodes.add(name)
                                                break
                                            else:
                                                click.echo("❌ Please enter 'y' for yes or 'n' for no.")
                                        except (EOFError, KeyboardInterrupt):
                                            click.echo("\nℹ️  Reboot prompt cancelled. Skipping reboot.")
                                            processed_reboot_nodes.add(name)
                                            break
                                        except Exception as e:
                                            click.echo(f"❌ Input error: {e}. Skipping reboot.")
                                            processed_reboot_nodes.add(name)
                                            break
                                else:
                                    click.echo(f"⚠️  {name} needs a reboot. Re-run with --reboot or reboot manually.")
                                    processed_reboot_nodes.add(name)
                    else:
                        click.echo(f"❌ {name} system upgrade failed")
                        if result.get('upgrade_error'):
                            click.echo(f"   Error: {result['upgrade_error']}")
                        upgrade_results.append((name, False, result.get('upgrade_error')))
                except Exception as e:
                    click.echo(f"❌ {name} system upgrade failed with exception: {e}")
                    upgrade_results.append((name, False, str(e)))
            
            click.echo(f"\n📊 UPGRADE SUMMARY:")
            successful = [r for r in upgrade_results if r[1]]
            failed = [r for r in upgrade_results if not r[1]]
            if successful:
                click.echo(f"✅ Successful upgrades: {', '.join([r[0] for r in successful])}")
            if failed:
                click.echo(f"❌ Failed upgrades: {', '.join([r[0] for r in failed])}")
            click.echo(f"🎉 System upgrade process completed!")
        else:
            click.echo("ℹ️  System upgrade cancelled by user.")

    remaining_reboot_nodes = [n for n in nodes_needing_reboot if n['name'] not in processed_reboot_nodes]
    if remaining_reboot_nodes:
        import sys
        if sys.stdin.isatty():
            for node_cfg in remaining_reboot_nodes:
                name = node_cfg['name']
                while True:
                    try:
                        resp = input(f"🔄 {name} needs a reboot. Reboot now? [y/N]: ").strip().lower()
                        if resp in ['y', 'yes']:
                            click.echo(f"🔄 Rebooting {name}...")
                            if _initiate_reboot(node_cfg):
                                click.echo(f"🔄 {name} reboot initiated")
                            else:
                                click.echo(f"❌ Failed to initiate reboot for {name}. Please reboot manually.")
                            processed_reboot_nodes.add(name)
                            break
                        elif resp in ['n', 'no', '']:
                            click.echo(f"ℹ️  Skipping reboot for {name}. Reboot later if needed.")
                            processed_reboot_nodes.add(name)
                            break
                        else:
                            click.echo("❌ Please enter 'y' for yes or 'n' for no.")
                    except (EOFError, KeyboardInterrupt):
                        click.echo("\nℹ️  Reboot prompt cancelled. Skipping reboot.")
                        processed_reboot_nodes.add(name)
                        break
                    except Exception as e:
                        click.echo(f"❌ Input error: {e}. Skipping reboot.")
                        processed_reboot_nodes.add(name)
                        break
        else:
            node_list = ', '.join(n['name'] for n in remaining_reboot_nodes)
            click.echo(f"\n⚠️  The following node(s) require a reboot: {node_list}. Re-run with --reboot or reboot manually.")

# Validator Management Group
@cli.group(name='validator')
def validator_group():
    """👥 Validator lifecycle management and duty coordination"""
    pass

@validator_group.command(name='discover')
@click.option('--output', '-o', default='validators_auto_discovered.csv', help='Output CSV filename')
@click.option('--config', '-c', default=str(get_config_path()), help='Configuration file path')
@click.option('--verbose', '-v', is_flag=True, help='Show detailed discovery progress')
def validator_discover(output, config, verbose):
    """🔍 Auto-discover validators across all nodes and generate simplified CSV"""
    
    if verbose:
        import logging
        logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    
    click.echo("🔍 Starting validator auto-discovery across cluster...")
    click.echo("💡 This may take a moment as we scan all your nodes...")
    
    try:
        discovery = ValidatorAutoDiscovery(config)
        csv_path = discovery.generate_validators_csv(output)
        
        # Read and display summary
        with open(csv_path, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            validators = list(reader)
        
        if validators:
            click.echo(f"\n🎉 SUCCESS! Discovered {len(validators)} validators!")
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
            click.echo("💻 By Node:")
            for node, count in node_counts.items():
                click.echo(f"   🖥️  {node}: {count} validators")
            
            click.echo("\n🏗️  By Protocol:")
            for protocol, count in protocol_counts.items():
                click.echo(f"   📡 {protocol}: {count} validators")
                
            click.echo(f"\n🚀 Next Steps:")
            click.echo(f"   • View cluster overview: python3 -m eth_validators node list")
            click.echo(f"   • Check client versions: python3 -m eth_validators node versions --all")
            click.echo(f"   • View port mappings: python3 -m eth_validators node ports --all")
        else:
            click.echo("\n⚠️  No validators discovered")
            click.echo("\n🔍 Troubleshooting tips:")
            click.echo("   • Ensure your nodes are running and accessible via Tailscale")
            click.echo("   • Verify SSH access: ssh root@your-node.tailnet.ts.net")
            click.echo("   • Check if eth-docker is running: docker ps")
            click.echo("   • For debug info: add --verbose flag")
            click.echo("   • Need help? Check the QUICK_START_GUIDE.md")
            
    except Exception as e:
        click.echo(f"\n❌ Validator discovery failed: {e}")
        click.echo("\n🔧 Common solutions:")
        click.echo("   • Check your config.yaml file exists and is valid")
        click.echo("   • Verify network connectivity to your nodes")  
        click.echo("   • Run with --verbose for detailed error information")
        click.echo("   • See QUICK_START_GUIDE.md for setup instructions")
        if verbose:
            import traceback
            click.echo(f"\n🐛 Detailed error: {traceback.format_exc()}")
        if verbose:
            import traceback
            click.echo(f"\n🐛 Detailed error: {traceback.format_exc()}")
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

def _initiate_reboot(node_cfg):
    """Trigger a reboot for the given node configuration."""
    try:
        is_local = node_cfg.get('is_local', False)
        ssh_user = node_cfg.get('ssh_user', 'root')

        if is_local:
            reboot_cmd = 'reboot' if ssh_user == 'root' else 'sudo reboot'
        else:
            ssh_target = f"{ssh_user}@{node_cfg['tailscale_domain']}"
            if ssh_user == 'root':
                reboot_cmd = f"ssh -o ConnectTimeout=10 -o BatchMode=yes {ssh_target} 'reboot'"
            else:
                reboot_cmd = f"ssh -o ConnectTimeout=10 -o BatchMode=yes {ssh_target} 'sudo reboot'"

        result = subprocess.run(reboot_cmd, shell=True, timeout=20)
        return result.returncode == 0
    except Exception:
        return False

@node_group.command(name='list')
def list_cmd():
    """Display a live cluster overview with real-time client diversity analysis."""
    config = yaml.safe_load(get_config_path().read_text())
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
        
        # Stack info with emojis - use live detection when possible
        stack_emojis = {
            'eth-docker': '🐳', 'disabled': '🚫', 'rocketpool': '🚀', 'obol': '🔗',
            'hyperdrive': '⚡', 'charon': '🌐', 'ssv': '📡', 'stakewise': '🏦',
            'lido-csm': '🏦', 'eth-hoodi': '🧪', 'nethermind': '⚙️', 'besu': '⚙️',
            'geth': '⚙️', 'reth': '⚙️', 'lighthouse': '🔗', 'teku': '🔗',
            'nimbus': '🔗', 'lodestar': '🔗', 'prysm': '🔗', 'vero': '🔗'
        }
        
        # Try to detect running stacks live
        try:
            detected_stacks = _detect_running_stacks(node)
            if detected_stacks and detected_stacks != ["unknown"] and detected_stacks != ["error"]:
                # Use detected stacks instead of config
                main_stacks = []
                client_stacks = []
                
                for s in detected_stacks:
                    if s in ['eth-docker', 'rocketpool', 'obol', 'charon', 'hyperdrive', 'ssv', 'lido-csm', 'stakewise']:
                        main_stacks.append(s)
                    elif s in ['nethermind', 'besu', 'geth', 'reth', 'lighthouse', 'teku', 'nimbus', 'lodestar', 'prysm', 'vero']:
                        client_stacks.append(s)
                
                if main_stacks:
                    stack_parts = [f"{stack_emojis.get(s.lower(), '⚙️')} {s}" for s in main_stacks]
                    stack_display = " + ".join(stack_parts)
                else:
                    # Fallback to configured stack
                    if 'disabled' in stack:
                        stack_display = "🚫 disabled"
                    else:
                        stack_parts = [f"{stack_emojis.get(s.lower(), '⚙️')} {s}" for s in stack]
                        stack_display = " + ".join(stack_parts)
                
                # Store detected clients for diversity calculation
                detected_clients = {'execution': [], 'consensus': []}
                for client in client_stacks:
                    if client in ['nethermind', 'besu', 'geth', 'reth']:
                        detected_clients['execution'].append(client)
                    elif client in ['lighthouse', 'teku', 'nimbus', 'lodestar', 'prysm']:
                        detected_clients['consensus'].append(client)
            else:
                # Fallback to configured stack
                if 'disabled' in stack:
                    stack_display = "🚫 disabled"
                else:
                    stack_parts = [f"{stack_emojis.get(s.lower(), '⚙️')} {s}" for s in stack]
                    stack_display = " + ".join(stack_parts)
                detected_clients = None
        except:
            # Fallback to configured stack on error
            if 'disabled' in stack:
                stack_display = "🚫 disabled"
            else:
                stack_parts = [f"{stack_emojis.get(s.lower(), '⚙️')} {s}" for s in stack]
                stack_display = " + ".join(stack_parts)
            detected_clients = None

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
    
    config = yaml.safe_load(get_config_path().read_text())
    
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



@node_group.command(name='versions')
@click.argument('node', required=False)
@click.option('--all', is_flag=True, help='Show client versions for all configured nodes')
def versions(node, all):
    """Query live client versions, sync status, and container health via SSH/API"""
    config = yaml.safe_load(get_config_path().read_text())
    
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
                    Fore.LIGHTBLACK_EX + "No clients" + Style.RESET_ALL if exec_name != "-" else '-',
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
                                        updated_table_data.append([
                                            f"🟢 {name}-{network_display_name}", exec_display, cons_display, val_display, charon_display
                                        ])
                                else:
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
                                    updated_table_data.append([
                                        f"🟢 {name}", exec_display, cons_display, val_display, charon_display
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
            charon_display = charon_version if charon_version != "N/A" else "-"
            charon_latest_display = latest_charon if charon_version != "N/A" else "-"
            charon_update = '🔄' if charon_needs_update else '✅' if charon_version != "N/A" else '-'
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


@node_group.command(name='add-node')
def add_node_interactive():
    """🆕 Add a new node to the cluster using interactive wizard"""
    click.echo("🚀 Welcome to the Interactive Node Addition Wizard!")
    click.echo("=" * 60)
    
    config_path = get_config_path()
    
    # Load existing config
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f) or {}
    except FileNotFoundError:
        click.echo("❌ No config.yaml found. Please run 'python3 -m eth_validators quickstart' first.")
        return
    except Exception as e:
        click.echo(f"❌ Error loading config: {e}")
        return
    
    # Ensure nodes list exists
    if 'nodes' not in config:
        config['nodes'] = []
    
    click.echo("\n📝 Let's gather information about your new node...")
    
    # Step 1: Basic node information
    click.echo("\n🖥️  Step 1: Basic Node Information")
    click.echo("-" * 40)
    
    while True:
        node_name = click.prompt("Node name (e.g., 'laptop', 'server1')", type=str).strip()
        if node_name:
            # Check if node name already exists
            existing_names = [n.get('name', '') for n in config['nodes']]
            if node_name in existing_names:
                click.echo(f"❌ Node '{node_name}' already exists. Please choose a different name.")
                continue
            break
        click.echo("❌ Node name cannot be empty")
    
    # Ask if this is a local node
    is_local = click.confirm("Is this a local node (running on this machine)?", default=False)
    
    if is_local:
        tailscale_domain = "localhost"  # Use localhost for local nodes
        ssh_user = "local"  # Not used for local nodes
        click.echo("✅ Configured as local node (no SSH required)")
    else:
        while True:
            tailscale_domain = click.prompt("Tailscale domain (e.g., 'mynode.tailnet.ts.net')", type=str).strip()
            if tailscale_domain:
                # Check if domain already exists
                existing_domains = [n.get('tailscale_domain', '') for n in config['nodes']]
                if tailscale_domain in existing_domains:
                    click.echo(f"❌ Domain '{tailscale_domain}' already exists. Please choose a different domain.")
                    continue
                break
            click.echo("❌ Tailscale domain cannot be empty")
        
        ssh_user = click.prompt("SSH user", default="root", type=str).strip()
    
    # Step 2: Test connection
    click.echo("\n🔗 Step 2: Testing Connection")
    click.echo("-" * 40)
    
    test_node_cfg = {
        'name': node_name,
        'tailscale_domain': tailscale_domain,
        'ssh_user': ssh_user,
        'is_local': is_local
    }
    
    if is_local:
        click.echo("✅ Local node - no SSH connection needed")
    else:
        click.echo(f"Testing SSH connection to {ssh_user}@{tailscale_domain}...")
        test_result = _run_command(test_node_cfg, "echo 'Connection test successful'")
        
        if test_result.returncode != 0:
            click.echo(f"❌ Connection failed: {test_result.stderr}")
            if not click.confirm("Do you want to continue anyway?"):
                return
        else:
            click.echo("✅ Connection successful!")
    
    # Step 3: Detect running stacks
    click.echo("\n🔍 Step 3: Detecting Running Services")
    click.echo("-" * 40)
    
    detected_stacks = _detect_running_stacks(test_node_cfg)
    
    if detected_stacks:
        click.echo(f"✅ Detected stacks: {', '.join(detected_stacks)}")
        use_detected = click.confirm("Use these detected stacks?", default=True)
        
        if use_detected:
            stack = detected_stacks
        else:
            stack = _manual_stack_selection()
    else:
        click.echo("❓ No known stacks detected automatically.")
        if click.confirm("Would you like to manually select stacks?", default=True):
            stack = _manual_stack_selection()
        else:
            stack = ["eth-docker"]  # Default
    
    # Step 3.5: Auto-detect eth-docker path if eth-docker is in stack
    eth_docker_path = None
    if 'eth-docker' in stack:
        click.echo("\n🔍 Detecting eth-docker installation path...")
        common_paths = [
            '/home/egk/eth-docker',
            '/home/egk/eth-hoodi', 
            '/home/root/eth-docker',
            '/opt/eth-docker'
        ]
        
        for path in common_paths:
            test_cmd = f"test -d {path} && test -f {path}/docker-compose.yml"
            result = _run_command(test_node_cfg, test_cmd)
            if result.returncode == 0:
                eth_docker_path = path
                click.echo(f"✅ Found eth-docker at: {path}")
                break
        
        if not eth_docker_path:
            click.echo("❓ Could not auto-detect eth-docker path. Using default.")
            eth_docker_path = '/home/egk/eth-docker'
    
    # Step 4: Additional configuration
    click.echo("\n⚙️  Step 4: Additional Configuration")
    click.echo("-" * 40)
    
    ethereum_clients_enabled = True
    if 'disabled' in stack:
        ethereum_clients_enabled = False
    elif any(s in stack for s in ['obol', 'charon']):
        ethereum_clients_enabled = click.confirm(
            "Enable Ethereum execution/consensus clients?", 
            default=not any('charon' in str(detected_stacks))
        )
    
    # Create new node configuration
    new_node = {
        'name': node_name,
        'tailscale_domain': tailscale_domain,
        'ssh_user': ssh_user,
        'stack': stack,
        'ethereum_clients_enabled': ethereum_clients_enabled
    }
    
    # Add is_local flag if this is a local node
    if is_local:
        new_node['is_local'] = True
    
    # Add eth_docker_path if detected
    if eth_docker_path:
        new_node['eth_docker_path'] = eth_docker_path
    
    # Step 5: Summary and confirmation
    click.echo("\n📋 Step 5: Configuration Summary")
    click.echo("-" * 40)
    
    click.echo(f"Node Name: {node_name}")
    if is_local:
        click.echo(f"Type: Local Node")
    else:
        click.echo(f"Domain: {tailscale_domain}")
        click.echo(f"SSH User: {ssh_user}")
    click.echo(f"Detected Stacks: {', '.join(stack)}")
    if eth_docker_path:
        click.echo(f"eth-docker Path: {eth_docker_path}")
    click.echo(f"Ethereum Clients: {'Enabled' if ethereum_clients_enabled else 'Disabled'}")
    
    if not click.confirm("\nSave this configuration?", default=True):
        click.echo("❌ Configuration not saved.")
        return
    
    # Step 6: Save configuration
    click.echo("\n💾 Step 6: Saving Configuration")
    click.echo("-" * 40)
    
    try:
        # Add to nodes list
        config['nodes'].append(new_node)
        
        # Save to file
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        
        click.echo(f"✅ Node '{node_name}' added successfully!")
        click.echo(f"📁 Configuration saved to: {config_path}")
        
        # Step 7: Next steps
        click.echo("\n🎯 Next Steps")
        click.echo("-" * 40)
        click.echo(f"• Test the node: python3 -m eth_validators node list")
        click.echo(f"• Check versions: python3 -m eth_validators node versions {node_name}")
        click.echo(f"• View port mappings: python3 -m eth_validators node ports --all")
        
    except Exception as e:
        click.echo(f"❌ Error saving configuration: {e}")
        return


def _manual_stack_selection():
    """Interactive stack selection helper"""
    click.echo("\n🛠️  Available stacks:")
    stacks = [
        ("eth-docker", "Standard Ethereum client stack"),
        ("obol", "Obol Distributed Validator Technology (Charon)"),
        ("rocketpool", "Rocket Pool Node"),
        ("hyperdrive", "NodeSet Hyperdrive"),
        ("ssv", "SSV Network"),
        ("lido-csm", "Lido Community Staking Module"),
        ("stakewise", "StakeWise Protocol"),
        ("disabled", "No Ethereum clients (monitoring/utilities only)")
    ]
    
    for i, (stack, desc) in enumerate(stacks, 1):
        click.echo(f"{i}. {stack}: {desc}")
    
    selected_stacks = []
    
    while True:
        try:
            selection = click.prompt(
                "\nSelect stack numbers (comma-separated, e.g., '1,2')", 
                type=str
            ).strip()
            
            if not selection:
                break
                
            indices = [int(x.strip()) for x in selection.split(',')]
            for idx in indices:
                if 1 <= idx <= len(stacks):
                    stack_name = stacks[idx-1][0]
                    if stack_name not in selected_stacks:
                        selected_stacks.append(stack_name)
                else:
                    click.echo(f"❌ Invalid selection: {idx}")
                    continue
            
            if selected_stacks:
                click.echo(f"Selected: {', '.join(selected_stacks)}")
                break
            
        except ValueError:
            click.echo("❌ Please enter valid numbers separated by commas")
    
    return selected_stacks if selected_stacks else ["eth-docker"]


@node_group.command(name='ports')
@click.argument('node', required=False)
@click.option('--all', is_flag=True, help='Show port mappings for all configured nodes')
@click.option('--source', type=click.Choice(['docker','env','both']), default='both', show_default=True,
              help='Data source: docker (live), env (.env files), or both')
@click.option('--p2p-only', is_flag=True, help='Show only P2P ports (EL/CL: 30303,30304,9000,12000,13000)')
@click.option('--published-only', is_flag=True, help='Show only Docker-published ports (ignore .env entries)')
@click.option('--csv', is_flag=True, help='Output in CSV format')
def node_ports(node, all, source, p2p_only, published_only, csv):
    """List open/forwarded ports per node and detect conflicts across nodes on the same network."""
    config = yaml.safe_load(get_config_path().read_text())

    if all and node:
        click.echo("❌ Cannot specify both --all and a node name")
        return
    if not all and not node:
        click.echo("❌ Must specify either --all or a node name")
        return

    nodes = config.get('nodes', [])
    if not nodes:
        click.echo("❌ No nodes configured. Please check your config.yaml file.")
        return

    if not all:
        node_cfg = next((n for n in nodes if n.get('tailscale_domain') == node or n.get('name') == node), None)
        if not node_cfg:
            click.echo(f"❌ Node {node} not found")
            return
        nodes = [node_cfg]

    click.echo("🔎 Gathering port mappings...")

    per_node_tables = []
    conflicts = {}
    entries_all = []

    # For CSV output, collect all rows first
    csv_rows = []
    csv_headers = ['Node', 'Service', 'Container', 'Host Port', 'Container Port', 'Protocol', 'Source', 'Network', 'Exposure', 'Public IP']

    for i, ncfg in enumerate(nodes):
        name = ncfg.get('name', ncfg.get('tailscale_domain', f"node{i+1}"))
        stack = ncfg.get('stack', ['eth-docker'])
        if isinstance(stack, str):
            stack = [stack]

        # Skip disabled stacks, but still allow env-based ports if desired
        if 'disabled' in [s.lower() for s in stack]:
            click.echo(f"⚪ Skipping disabled node {name}")
            continue

        res = get_node_port_mappings(ncfg, source=source)
        entries = res.get('entries', [])
        errors = res.get('errors', [])

        # Apply filters
        if published_only:
            entries = [e for e in entries if e.get('source') == 'docker' and e.get('published')]
        if p2p_only:
            def _is_p2p_port_entry(e):
                hp = e.get('host_port')
                proto = e.get('proto', 'tcp')
                if hp is None:
                    return False
                try:
                    p = int(hp)
                except (ValueError, TypeError):
                    return False
                proto = str(proto).lower()

                # EL P2P ports (standard and custom forwarding range)
                if 30300 <= p <= 30400 and proto in ('tcp', 'udp'):
                    return True
                # CL P2P ports (standard and custom forwarding range)
                if 9000 <= p <= 9100 and proto in ('tcp', 'udp'):
                    return True
                # Charon DV ports (typically forwarded)
                if 3600 <= p <= 3700 and proto == 'tcp':
                    return True
                # Other common P2P ports
                if p in (12000, 13000) and proto in ('tcp', 'udp'):
                    return True

                return False
            entries = [e for e in entries if _is_p2p_port_entry(e)]

        # Build table rows for this node
        rows = []
        for e in entries:
            # Determine exposure type
            exposure = '🔒 Internal'
            host_port = e.get('host_port')
            if host_port is not None:
                # Check if this is a P2P port that requires router forwarding
                port_num = int(host_port) if str(host_port).isdigit() else 0
                proto = e.get('proto', 'tcp')
                
                # P2P ports that typically require public exposure
                if ((30300 <= port_num <= 30400 and proto in ('tcp', 'udp')) or  # EL P2P
                    (9000 <= port_num <= 9100 and proto in ('tcp', 'udp')) or    # CL P2P  
                    (3600 <= port_num <= 3700 and proto == 'tcp') or             # Charon DV
                    (12000 <= port_num <= 13000 and proto in ('tcp', 'udp'))):  # Other P2P
                    exposure = '🌐 Public P2P'
                else:
                    exposure = '🌐 Public Service'
            
            row = [
                e.get('service','-'),
                e.get('container','-'),
                e.get('host_port') if e.get('host_port') is not None else '-',
                e.get('container_port') if e.get('container_port') is not None else '-',
                e.get('proto','tcp'),
                e.get('source','-'),
                e.get('network','-'),
                exposure
            ]
            rows.append(row)

            # Track conflicts by host_port+proto within same network scope
            hp = e.get('host_port')
            proto = e.get('proto', 'tcp')
            net = e.get('network', '-')
            if hp is not None:
                key = (hp, proto, net)
                conflicts.setdefault(key, []).append({
                    'node': name,
                    'service': e.get('service','-'),
                    'container': e.get('container','-'),
                    'source': e.get('source','-')
                })
                entries_all.append({ 'node': name, **e })

        # Add to per_node_tables for rendering
        headers = ['Service', 'Container', 'Host Port', 'Container Port', 'Proto', 'Source', 'Network', 'Exposure']
        per_node_tables.append((name, rows, headers, errors, None, ncfg))

        # Add to CSV if requested
        if csv:
            for e in entries:
                # Determine exposure type for CSV
                exposure = 'Internal'
                host_port = e.get('host_port')
                if host_port is not None:
                    port_num = int(host_port) if str(host_port).isdigit() else 0
                    proto = e.get('proto', 'tcp')
                    
                    # P2P ports that typically require public exposure
                    if ((30300 <= port_num <= 30400 and proto in ('tcp', 'udp')) or  # EL P2P
                        (9000 <= port_num <= 9100 and proto in ('tcp', 'udp')) or    # CL P2P  
                        (3600 <= port_num <= 3700 and proto == 'tcp') or             # Charon DV
                        (12000 <= port_num <= 13000 and proto in ('tcp', 'udp'))):  # Other P2P
                        exposure = 'Public P2P'
                    else:
                        exposure = 'Public Service'
                
                csv_rows.append([
                    name,
                    e.get('service','-'),
                    e.get('container','-'),
                    e.get('host_port') if e.get('host_port') is not None else '-',
                    e.get('container_port') if e.get('container_port') is not None else '-',
                    e.get('proto','tcp'),
                    e.get('source','-'),
                    e.get('network','-'),
                    exposure,
                    'N/A'  # Public IP placeholder, will be filled later
                ])

    # Detect public IPs for each node
    public_ips = {}
    for i, ncfg in enumerate(nodes):
        name = ncfg.get('name', ncfg.get('tailscale_domain', f"node{i+1}"))
        try:
            result = run_command_on_node(name, "curl -s https://api.ipify.org", ncfg)
            if result and result.strip():
                public_ips[name] = result.strip()
            else:
                public_ips[name] = "unknown"
        except Exception as e:
            public_ips[name] = "unknown"

    # Update CSV rows with actual public IPs
    if csv:
        for i, row in enumerate(csv_rows):
            node_name = row[0]  # First column is node name
            row[9] = public_ips.get(node_name, "unknown")  # Update public IP column

    # CSV output mode
    if csv:
        import sys
        import csv as csv_module
        writer = csv_module.writer(sys.stdout)
        writer.writerow(csv_headers)
        for row in csv_rows:
            writer.writerow(row)
        return

    # Build P2P port usage matrix - get rows for each node
    p2p_ports = {}
    node_rows = {}  # Store rows for each node
    for name, rows_data, headers, errors, hint, ncfg in per_node_tables:
        node_rows[name] = rows_data
        p2p_ports[name] = set()
        for service, container, host_port, container_port, proto, source, network, exposure in rows_data:
            if host_port:
                try:
                    port_num = int(host_port)
                    # Check if this is a P2P port by service name OR port range
                    is_p2p_by_name = ('p2p' in service.lower() or 'discovery' in service.lower())
                    is_p2p_by_port = (
                        (30300 <= port_num <= 30400 and proto.lower() in ('tcp', 'udp')) or  # EL P2P
                        (9000 <= port_num <= 9100 and proto.lower() in ('tcp', 'udp')) or    # CL P2P
                        (3600 <= port_num <= 3700 and proto.lower() == 'tcp') or             # Charon P2P
                        (12000 <= port_num <= 13000 and proto.lower() in ('tcp', 'udp'))    # Other P2P
                    )
                    
                    if is_p2p_by_name or is_p2p_by_port:
                        p2p_ports[name].add(port_num)
                except (ValueError, TypeError):
                    pass

    # Group nodes by public IP
    ip_groups = {}
    for name, ip in public_ips.items():
        if ip not in ip_groups:
            ip_groups[ip] = []
        ip_groups[ip].append(name)

    # Color codes and symbols for visual indicators
    colors = ['\033[91m', '\033[92m', '\033[93m', '\033[94m', '\033[95m', '\033[96m']  # Red, Green, Yellow, Blue, Magenta, Cyan
    symbols = ['●', '▲', '■', '◆', '★', '♦']
    reset_color = '\033[0m'

    # Render per-node tables
    for name, rows, headers, errors, hint, ncfg in per_node_tables:
        # Add visual indicator for shared IP groups
        ip = public_ips.get(name, "unknown")
        group_nodes = ip_groups.get(ip, [])
        if len(group_nodes) > 1:
            group_index = list(ip_groups.keys()).index(ip) % len(symbols)
            color = colors[group_index % len(colors)]
            visual_indicator = f"{color}{symbols[group_index]}{reset_color}"
        else:
            visual_indicator = ""

        click.echo("\n" + "="*70)
        click.echo(f"🖥️  {name} {visual_indicator}- Port Mappings")
        click.echo("="*70)
        if ip != "unknown":
            click.echo(f"🌐 Public IP: {ip}")
        if len(group_nodes) > 1:
            other_nodes = [n for n in group_nodes if n != name]
            click.echo(f"🔗 Shared IP with: {', '.join(other_nodes)}")

        if rows:
            click.echo(tabulate(rows, headers=headers, tablefmt='fancy_grid', stralign='left', numalign='center'))
        else:
            click.echo("(no mappings found)")
        if errors:
            for err in errors:
                click.echo(f"⚠️  {err}")

    # Display P2P port usage matrix
    if p2p_only or not published_only:
        click.echo(f"\n{click.style('P2P Port Usage Matrix:', fg='cyan', bold=True)}")
        all_p2p_ports = sorted(set.union(*p2p_ports.values()) if p2p_ports.values() else set())

        if all_p2p_ports:
            # Build node config mapping for IP info
            node_configs = {ncfg.get('name', f"node{i+1}"): ncfg for i, ncfg in enumerate(nodes)}
            node_names = sorted(set(entry['node'] for entry in entries_all))

            # First, detect all public IPs once to avoid repeated SSH calls
            node_public_ips = {}
            for node_name in node_names:
                node_cfg = node_configs.get(node_name, {})
                public_ip = node_cfg.get('public_ip', node_cfg.get('external_ip', 'N/A'))

                # Auto-detect public IP if not configured
                if public_ip == 'N/A':
                    try:
                        from eth_validators.node_manager import run_command_on_node
                        result = run_command_on_node(node_name, "curl -s ifconfig.me || curl -s ipinfo.io/ip || curl -s icanhazip.com")
                        if result and result.strip():
                            public_ip = result.strip()
                    except Exception:
                        public_ip = 'N/A'

                node_public_ips[node_name] = public_ip

            # Group nodes by public IP
            public_ips = {}
            for node_name, public_ip in node_public_ips.items():
                if public_ip not in public_ips:
                    public_ips[public_ip] = []
                public_ips[public_ip].append(node_name)

            # Define color codes and symbols for visual indicators
            colors = ['\033[91m', '\033[92m', '\033[93m', '\033[94m', '\033[95m', '\033[96m']  # Red, Green, Yellow, Blue, Magenta, Cyan
            symbols = ['●', '▲', '■', '◆', '★', '♦']
            reset_color = '\033[0m'

            # Assign colors and symbols to public IPs
            ip_colors = {}
            ip_symbols = {}
            color_idx = 0
            symbol_idx = 0
            for public_ip in sorted(public_ips.keys()):
                if public_ip != 'N/A':
                    ip_colors[public_ip] = colors[color_idx % len(colors)]
                    if len(public_ips[public_ip]) > 1:  # Only mark shared IPs
                        ip_symbols[public_ip] = symbols[symbol_idx % len(symbols)]
                        symbol_idx += 1
                    color_idx += 1
                else:
                    ip_colors[public_ip] = ''  # No color for N/A

            # Build headers with visual indicators for IP groups
            matrix_headers = ['P2P Port']
            for node_name in node_names:
                public_ip = node_public_ips[node_name]
                symbol = ip_symbols.get(public_ip, '')

                if symbol:
                    # Use both color and symbol for shared IPs
                    color = ip_colors.get(public_ip, '')
                    header_name = f"{color}{symbol}{node_name}{reset_color}" if color else f"{symbol}{node_name}"
                else:
                    header_name = node_name

                matrix_headers.append(header_name)

            # Build matrix rows with color-coded checkmarks
            matrix_rows = []
            for port in all_p2p_ports:
                row = [str(port)]
                for node in node_names:
                    if port in p2p_ports[node]:
                        # Color code based on IP group
                        public_ip = node_public_ips.get(node, "unknown")
                        symbol = ip_symbols.get(public_ip, '')
                        color = ip_colors.get(public_ip, '')

                        if symbol:
                            # Use colored symbol for shared IPs to highlight conflicts
                            colored_checkmark = f"{color}{symbol}✓{reset_color}" if color else f"{symbol}✓"
                        else:
                            colored_checkmark = "✓"

                        row.append(colored_checkmark)
                    else:
                        row.append("")
                matrix_rows.append(row)

            # Print matrix with fancy formatting
            click.echo(tabulate(matrix_rows, headers=matrix_headers,
                               tablefmt='fancy_grid', stralign='center', numalign='center'))

            # Print IP information below matrix with color legend
            click.echo(f"\n📍 Node Network Information (Color & Symbol-coded by Public IP):")

            # Group nodes by public IP and show with colors and symbols
            for public_ip, nodes_list in sorted(public_ips.items()):
                if len(nodes_list) > 1:  # Only show groups with multiple nodes (potential conflicts)
                    color = ip_colors.get(public_ip, '')
                    symbol = ip_symbols.get(public_ip, '')
                    colored_ip = f"{color}{public_ip}{reset_color}" if color else public_ip
                    node_list = f"{color}{symbol}{', '.join(nodes_list)}{reset_color}" if color else f"{symbol}{', '.join(nodes_list)}"
                    click.echo(f"   🔴 SHARED PUBLIC IP {colored_ip}: {node_list}")
                    if public_ip != 'N/A':
                        click.echo(f"      ⚠️  These nodes compete for the same router ports! (Symbol: {symbol})")
                else:
                    # Single node per IP
                    node_name = nodes_list[0]
                    color = ip_colors.get(public_ip, '')
                    colored_ip = f"{color}{public_ip}{reset_color}" if color else public_ip
                    colored_node = f"{color}{node_name}{reset_color}" if color else node_name
                    click.echo(f"   ✅ UNIQUE PUBLIC IP {colored_ip}: {colored_node}")

            # Show detailed info for each node
            click.echo(f"\n📋 Detailed Node Information:")
            for node_name in node_names:
                node_cfg = node_configs.get(node_name, {})
                tailscale_ip = node_cfg.get('tailscale_domain', 'N/A')
                public_ip = node_public_ips[node_name]

                color = ip_colors.get(public_ip, '')
                symbol = ip_symbols.get(public_ip, '')
                prefix = f"{symbol} " if symbol else ""
                colored_name = f"{color}{prefix}{node_name}{reset_color}" if color else f"{prefix}{node_name}"
                click.echo(f"   • {colored_name}: Tailscale={tailscale_ip}, Public={public_ip}")

            click.echo("\nℹ️  Only P2P ports that require router forwarding are shown")
        else:
            click.echo("No P2P ports found")

    # Detect and show conflicts
    conflict_rows = []
    for (hp, proto, net), uses in conflicts.items():
        if len(uses) > 1:
            nodes_str = ", ".join(sorted({u['node'] for u in uses}))
            services_str = "; ".join([f"{u['node']}:{u['service']} ({u['source']})" for u in uses])
            conflict_rows.append([hp, proto, net, len(uses), nodes_str, services_str])

    click.echo("\n" + "="*70)
    click.echo("🚨 Port Conflicts Across Nodes")
    click.echo("="*70)
    if conflict_rows:
        click.echo(tabulate(conflict_rows, headers=['Host Port','Proto','Network','Count','Nodes','Details'],
                           tablefmt='fancy_grid', stralign='left', numalign='center'))
        click.echo(f"\n💡 To resolve conflicts, you can:")
        click.echo(f"   • Run 'python3 -m eth_validators node ports --all' to see all conflicts")
        click.echo(f"   • Manually edit .env files to change conflicting ports")
        click.echo(f"   • Use different port ranges for different nodes")
    else:
        click.echo("✅ No port conflicts detected!")

    # Summary table showing all nodes with their public IPs
    click.echo("\n" + "="*70)
    click.echo("🌐 Node Public IP Summary")
    click.echo("="*70)

    summary_rows = []
    for name, rows, headers, errors, hint, ncfg in per_node_tables:
        tailscale_ip = ncfg.get('tailscale_domain', 'N/A')
        public_ip = ncfg.get('public_ip', ncfg.get('external_ip', 'N/A'))

        # Auto-detect public IP if not configured
        if public_ip == 'N/A':
            try:
                from eth_validators.node_manager import run_command_on_node
                result = run_command_on_node(name, "curl -s ifconfig.me || curl -s ipinfo.io/ip || curl -s icanhazip.com")
                if result and result.strip():
                    public_ip = result.strip()
            except Exception:
                public_ip = 'N/A'

        summary_rows.append([name, tailscale_ip, public_ip])

    if summary_rows:
        click.echo(tabulate(summary_rows, headers=['Node','Tailscale Domain','Public IP'],
                           tablefmt='fancy_grid', stralign='left', numalign='center'))
    else:
        click.echo("No node information available")


# ====================================
# Configuration Automation Commands  
# ====================================

@config_group.command(name='validate')
@click.option('--config', '-c', default=str(get_config_path()), help='Configuration file path')
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


def _resolve_port_conflicts_interactive(conflicts, node_configs):
    """Interactive port conflict resolution with batched .env updates and service restarts"""
    import random
    import os
    import subprocess
    from pathlib import Path
    
    click.echo(f"\n🔍 Analyzing conflicts and suggesting solutions...")
    
    # Get all currently used ports across all nodes to avoid suggesting conflicts
    used_ports = set()
    for conflict in conflicts:
        used_ports.add(conflict['port'])
    
    # Add other known ports from the port mappings
    for node_name, node_cfg in node_configs.items():
        try:
            from eth_validators.node_manager import get_node_port_mappings
            port_data = get_node_port_mappings(node_cfg)
            for entry in port_data.get('entries', []):
                if entry.get('host_port'):
                    used_ports.add(int(entry['host_port']))
        except:
            pass
    
    all_suggestions = []  # Collect all approved changes
    
    for i, conflict in enumerate(conflicts, 1):
        port = conflict['port']
        protocol = conflict['protocol']
        nodes = conflict['nodes']
        
        click.echo(f"\n🔧 Conflict {i}/{len(conflicts)}: Port {port}/{protocol}")
        click.echo(f"   Conflicting nodes: {', '.join(nodes)}")
        
        # Suggest new ports for all but the first node
        suggestions = []
        for j, node_name in enumerate(nodes):
            if j == 0:
                # Keep the first node unchanged
                click.echo(f"   ✅ Keeping {node_name} on port {port}")
                continue
            
            # Find a new port for this node
            base_port = port
            new_port = _find_available_port(base_port, used_ports, protocol)
            used_ports.add(new_port)
            
            suggestions.append({
                'node': node_name,
                'current_port': port,
                'suggested_port': new_port,
                'protocol': protocol
            })
            
            click.echo(f"   🔄 Suggested for {node_name}: {port} → {new_port}")
        
        # Ask user for approval
        if suggestions:
            if click.confirm(f"   Apply these changes for port {port}/{protocol}?", default=True):
                all_suggestions.extend(suggestions)
                click.echo(f"   ✅ Changes approved for port {port}/{protocol}")
            else:
                click.echo(f"   ⏭️  Skipped port {port}/{protocol} changes")
    
    # Apply all changes in batch (without restarting services yet)
    resolved_conflicts = []
    nodes_to_restart = {}  # Store both node and network folder info
    
    if all_suggestions:
        click.echo(f"\n🔧 Applying all .env changes...")
        
        for suggestion in all_suggestions:
            # Determine if this is an Erigon Caplin port based on the conflict info
            port_source = None
            for conflict in conflicts:
                if (conflict['port'] == suggestion['current_port'] and 
                    suggestion['node'] in conflict['nodes'] and 
                    conflict.get('has_erigon_caplin')):
                    port_source = 'erigon_caplin_inspected'
                    break
            
            result = _apply_port_change_no_restart_with_path(suggestion['node'], node_configs.get(suggestion['node']), 
                                                  suggestion['current_port'], suggestion['suggested_port'], suggestion['protocol'], port_source)
            if result and result.get('success'):
                resolved_conflicts.append(suggestion)
                # Store the network folder that was modified
                nodes_to_restart[suggestion['node']] = result.get('network_folder')
                click.echo(f"   ✅ Updated .env: {suggestion['node']} {suggestion['current_port']} → {suggestion['suggested_port']}")
            else:
                click.echo(f"   ❌ Failed: {suggestion['node']} port change")
        
        # Now restart all affected services at once
        if nodes_to_restart:
            click.echo(f"\n🔄 Restarting services for nodes: {', '.join(sorted(nodes_to_restart.keys()))}")
            
            for node_name, network_folder in sorted(nodes_to_restart.items()):
                node_config = node_configs.get(node_name)
                if node_config:
                    click.echo(f"   🔄 Restarting {node_name} ({network_folder})...")
                    success = _restart_node_services_with_folder(node_config, network_folder)
                    if success:
                        click.echo(f"   ✅ Restarted: {node_name}")
                    else:
                        click.echo(f"   ⚠️  Restart may have failed: {node_name}")
    
    # Summary
    if resolved_conflicts:
        click.echo(f"\n🎉 \033[92mResolution Complete!\033[0m")
        click.echo(f"   Resolved {len(resolved_conflicts)} port conflicts")
        click.echo(f"   Modified nodes: {', '.join(set(r['node'] for r in resolved_conflicts))}")
        click.echo(f"\n💡 \033[93mNext steps:\033[0m")
        click.echo(f"   1. Check that services are running properly")
        click.echo(f"   2. Update your router port forwarding rules")
        click.echo(f"   3. Run the ports command again to verify no conflicts remain")
    else:
        click.echo(f"\n⚠️  No conflicts were resolved")


def _detect_system_network_issues():
    """Detect system-level network issues that could cause container instability"""
    import subprocess
    import re
    
    issues = []
    
    # Check UDP buffer sizes
    try:
        result = subprocess.run(['sysctl', '-n', 'net.core.rmem_max'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            rmem_max = int(result.stdout.strip())
            # Ethereum consensus needs ~7MB buffers, warn if less than 2MB
            if rmem_max < 2097152:  # 2MB
                issues.append(f"🔶 UDP receive buffer too small: {rmem_max//1024}KB (need >2MB for consensus)")
                issues.append("   Fix: sudo sysctl -w net.core.rmem_max=16777216")
    except:
        pass
    
    # Check for Tailscale port conflicts
    try:
        result = subprocess.run(['netstat', '-tulpn'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            tailscale_ports = []
            for line in result.stdout.split('\n'):
                if 'tsd' in line and ':8080' in line:
                    tailscale_ports.append('8080 (tsdproxyd)')
                elif 'tailscale' in line:
                    match = re.search(r':(\d+)', line)
                    if match:
                        tailscale_ports.append(match.group(1))
            
            if tailscale_ports:
                issues.append(f"🔶 Tailscale services using common ports: {', '.join(tailscale_ports)}")
                if '8080 (tsdproxyd)' in tailscale_ports:
                    issues.append("   This may conflict with container internal networking")
    except:
        pass
    
    # Check NAT/UPnP issues by looking at recent container logs
    try:
        result = subprocess.run(['docker', 'logs', '--tail=50', 'eth-sepolia-execution-1'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and 'NAT ExternalIP resolution has failed' in result.stdout:
            issues.append("🔶 NAT/UPnP router discovery failing (may cause P2P connectivity issues)")
            issues.append("   Consider setting --nat=extip:<your-public-ip> in Erigon config")
    except:
        pass
    
    return issues


def _find_available_port(base_port, used_ports, protocol):
    """Find an available port near the base port"""
    # Define port ranges for different protocols
    if 30300 <= base_port <= 30400:  # Execution client standard range
        search_range = range(30300, 30400)
    elif 32300 <= base_port <= 32400:  # Erigon extended P2P range
        search_range = range(32300, 32400)
    elif 42000 <= base_port <= 42100:  # Erigon discovery range
        search_range = range(42000, 42100)
    elif 9000 <= base_port <= 9100:  # Consensus client
        search_range = range(9000, 9100)
    elif 3600 <= base_port <= 3700:  # Charon range
        search_range = range(3600, 3700)
    else:
        # Generic range around base port
        search_range = range(base_port + 1, base_port + 100)
    
    # Try ports in order, starting from base_port + 1
    for port in search_range:
        if port not in used_ports:
            return port
    
    # If no port found in range, try random ports
    for _ in range(50):
        port = base_port + random.randint(1, 1000)
        if port not in used_ports and 1024 < port < 65535:
            return port
    
    # Fallback
    return base_port + 100


def _apply_port_change_no_restart_with_path(node_name, node_config, old_port, new_port, protocol, port_source=None):
    """Apply port change to .env file without restarting services - returns success and network folder info"""
    if not node_config:
        click.echo(f"   ❌ No config found for node {node_name}")
        return {'success': False}
    
    try:
        is_local = node_config.get('is_local', False)
        eth_docker_path = node_config.get('eth_docker_path', '/home/egk/eth-docker')
        
        # Determine the correct .env file based on port source and node
        env_file = f"{eth_docker_path}/.env"  # Default
        network_folder = eth_docker_path  # Default folder to restart
        
        # Special handling for Erigon Caplin ports
        if port_source and 'erigon_caplin' in port_source:
            # For eliedesk, we need to determine which network this Caplin port belongs to
            if node_name == 'eliedesk':
                # eliedesk runs sepolia (port 9004) and holesky networks
                if old_port == 9004:
                    network_folder = eth_docker_path.replace('eth-docker', 'eth-sepolia')
                    env_file = f"{network_folder}/.env"
                    click.echo(f"   🔍 Targeting built-in consensus port in sepolia network: {env_file}")
                elif old_port == 9014:  # If we later detect holesky
                    network_folder = eth_docker_path.replace('eth-docker', 'eth-hoodi')
                    env_file = f"{network_folder}/.env"
                    click.echo(f"   🔍 Targeting built-in consensus port in holesky network: {env_file}")
            elif node_name == 'ryzen7':
                # ryzen7 runs mainnet with port 9014
                if old_port == 9014:
                    network_folder = eth_docker_path  # Mainnet uses default eth-docker
                    env_file = f"{network_folder}/.env"
                    click.echo(f"   🔍 Targeting built-in consensus port in mainnet: {env_file}")
        
        # Determine which .env variable to change based on port range
        env_var = None
        if 30300 <= old_port <= 30400:  # Execution client standard range
            env_var = 'EL_P2P_PORT'
        elif 32300 <= old_port <= 32400:  # Erigon extended P2P range
            env_var = 'EL_P2P_PORT_2'
        elif 42000 <= old_port <= 42100:  # Erigon discovery range
            env_var = 'ERIGON_TORRENT_PORT'
        elif 9000 <= old_port <= 9100:  # Consensus client
            # Map specific consensus ports to correct env vars
            if old_port == 9000:
                env_var = 'PRYSM_PORT'
            elif old_port == 9001:
                env_var = 'CL_QUIC_PORT'  
            else:
                env_var = 'CL_P2P_PORT'
        elif 3600 <= old_port <= 3700:  # Charon
            env_var = 'CHARON_P2P_EXTERNAL_HOSTNAME_PORT'
        
        if not env_var:
            click.echo(f"   ⚠️  Unknown port type {old_port}, skipping .env update")
            return {'success': False}
        
        # Update .env file
        success = _update_env_file(node_config, env_file, env_var, str(new_port), is_local)
        return {'success': success, 'network_folder': network_folder}
        
    except Exception as e:
        click.echo(f"   ❌ Error updating .env for {node_name}: {e}")
        return {'success': False}


def _apply_port_change_no_restart(node_name, node_config, old_port, new_port, protocol, port_source=None):
    """Apply port change to .env file without restarting services"""
    if not node_config:
        click.echo(f"   ❌ No config found for node {node_name}")
        return False
    
    try:
        is_local = node_config.get('is_local', False)
        eth_docker_path = node_config.get('eth_docker_path', '/home/egk/eth-docker')
        
        # Determine the correct .env file based on port source and node
        env_file = f"{eth_docker_path}/.env"  # Default
        
        # Special handling for Erigon Caplin ports
        if port_source and 'erigon_caplin' in port_source:
            # For eliedesk, we need to determine which network this Caplin port belongs to
            if node_name == 'eliedesk':
                # eliedesk runs sepolia (port 9004) and holesky networks
                if old_port == 9004:
                    env_file = f"{eth_docker_path.replace('eth-docker', 'eth-sepolia')}/.env"
                    click.echo(f"   🔍 Targeting built-in consensus port in sepolia network: {env_file}")
                elif old_port == 9014:  # If we later detect holesky
                    env_file = f"{eth_docker_path.replace('eth-docker', 'eth-hoodi')}/.env"
                    click.echo(f"   🔍 Targeting built-in consensus port in holesky network: {env_file}")
            elif node_name == 'ryzen7':
                # ryzen7 runs mainnet with port 9014
                if old_port == 9014:
                    env_file = f"{eth_docker_path}/.env"  # Mainnet uses default eth-docker
                    click.echo(f"   🔍 Targeting built-in consensus port in mainnet: {env_file}")
        
        if is_local:
            pass  # env_file already set above
        else:
            ssh_user = node_config.get('ssh_user', 'root')
            tailscale_domain = node_config.get('tailscale_domain')
            # env_file path already determined above
        
        # Determine which .env variable to change based on port range
        env_var = None
        if 30300 <= old_port <= 30400:  # Execution client standard range
            env_var = 'EL_P2P_PORT'
        elif 32300 <= old_port <= 32400:  # Erigon extended P2P range
            env_var = 'EL_P2P_PORT_2'
        elif 42000 <= old_port <= 42100:  # Erigon discovery range
            env_var = 'ERIGON_TORRENT_PORT'
        elif 9000 <= old_port <= 9100:  # Consensus client
            # Map specific consensus ports to correct env vars
            if old_port == 9000:
                env_var = 'PRYSM_PORT'
            elif old_port == 9001:
                env_var = 'CL_QUIC_PORT'  
            else:
                env_var = 'CL_P2P_PORT'
        elif 3600 <= old_port <= 3700:  # Charon
            env_var = 'CHARON_P2P_EXTERNAL_HOSTNAME_PORT'
        
        if not env_var:
            click.echo(f"   ⚠️  Unknown port type {old_port}, skipping .env update")
            return False
        
        # Update .env file
        success = _update_env_file(node_config, env_file, env_var, str(new_port), is_local)
        return success
        
    except Exception as e:
        click.echo(f"   ❌ Error updating .env for {node_name}: {e}")
        return False


def _restart_node_services_with_folder(node_config, network_folder):
    """Restart services for a single node using the specified network folder"""
    try:
        is_local = node_config.get('is_local', False)
        
        return _restart_eth_docker(node_config, network_folder, is_local)
        
    except Exception as e:
        return False


def _restart_node_services(node_config):
    """Restart services for a single node"""
    try:
        is_local = node_config.get('is_local', False)
        eth_docker_path = node_config.get('eth_docker_path', '/home/egk/eth-docker')
        
        return _restart_eth_docker(node_config, eth_docker_path, is_local)
        
    except Exception as e:
        return False


def _apply_port_change(node_name, node_config, old_port, new_port, protocol):
    """Apply port change to node's .env file and restart services"""
    try:
        is_local = node_config.get('is_local', False)
        eth_docker_path = node_config.get('eth_docker_path', '/home/egk/eth-docker')
        
        if is_local:
            env_file = os.path.join(eth_docker_path, '.env')
        else:
            # For remote nodes, we'll need to SSH
            ssh_user = node_config.get('ssh_user', 'root')
            tailscale_domain = node_config.get('tailscale_domain')
            env_file = f"{eth_docker_path}/.env"
        
        # Determine which .env variable to change based on port range
        env_var = None
        if 30300 <= old_port <= 30400:  # Execution client standard range
            env_var = 'EL_P2P_PORT'
        elif 32300 <= old_port <= 32400:  # Erigon extended P2P range
            env_var = 'EL_P2P_PORT_2'
        elif 42000 <= old_port <= 42100:  # Erigon discovery range
            env_var = 'ERIGON_TORRENT_PORT'
        elif 9000 <= old_port <= 9100:  # Consensus client
            # Map specific consensus ports to correct env vars
            if old_port == 9000:
                env_var = 'PRYSM_PORT'
            elif old_port == 9001:
                env_var = 'CL_QUIC_PORT'  
            else:
                env_var = 'CL_P2P_PORT'
        elif 3600 <= old_port <= 3700:  # Charon
            env_var = 'CHARON_P2P_EXTERNAL_HOSTNAME_PORT'
        
        if not env_var:
            click.echo(f"   ⚠️  Unknown port type {old_port}, skipping .env update")
            return False
        
        # Update .env file
        success = _update_env_file(node_config, env_file, env_var, str(new_port), is_local)
        if not success:
            return False
        
        # Restart eth-docker services
        success = _restart_eth_docker(node_config, eth_docker_path, is_local)
        return success
        
    except Exception as e:
        click.echo(f"   ❌ Error applying port change: {e}")
        return False


def _update_env_file(node_config, env_file, env_var, new_value, is_local):
    """Update .env file with new port value"""
    try:
        if is_local:
            # Local file update
            if os.path.exists(env_file):
                with open(env_file, 'r') as f:
                    content = f.read()
                
                # Update or add the variable
                lines = content.split('\n')
                updated = False
                for i, line in enumerate(lines):
                    if line.startswith(f"{env_var}="):
                        lines[i] = f"{env_var}={new_value}"
                        updated = True
                        break
                
                if not updated:
                    lines.append(f"{env_var}={new_value}")
                
                with open(env_file, 'w') as f:
                    f.write('\n'.join(lines))
                
                return True
            else:
                click.echo(f"   ⚠️  .env file not found: {env_file}")
                return False
        else:
            # Remote file update via SSH
            ssh_user = node_config.get('ssh_user', 'root')
            tailscale_domain = node_config.get('tailscale_domain')
            
            # Create a sed command to update the .env file
            sed_cmd = f"sed -i 's/^{env_var}=.*$/{env_var}={new_value}/' {env_file}"
            add_cmd = f"grep -q '^{env_var}=' {env_file} || echo '{env_var}={new_value}' >> {env_file}"
            
            ssh_cmd = f"ssh {ssh_user}@{tailscale_domain} '{sed_cmd} && {add_cmd}'"
            
            result = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True)
            return result.returncode == 0
            
    except Exception as e:
        click.echo(f"   ❌ Error updating .env file: {e}")
        return False


def _restart_eth_docker(node_config, eth_docker_path, is_local):
    """Restart eth-docker services with proper down/up cycle for port rebinding"""
    try:
        if is_local:
            # Local restart - prefer ./ethd if available, fallback to docker compose
            ethd_script = os.path.join(eth_docker_path, 'ethd')
            if os.path.exists(ethd_script) and os.access(ethd_script, os.X_OK):
                # Use ./ethd down && ./ethd up -d
                down_result = subprocess.run(['./ethd', 'down'], 
                                           cwd=eth_docker_path, capture_output=True, text=True)
                if down_result.returncode != 0:
                    click.echo(f"   ⚠️  ./ethd down failed: {down_result.stderr}")
                    return False
                
                up_result = subprocess.run(['./ethd', 'up', '-d'], 
                                         cwd=eth_docker_path, capture_output=True, text=True)
                return up_result.returncode == 0
            else:
                # Fallback to docker compose
                down_result = subprocess.run(['docker', 'compose', 'down'], 
                                           cwd=eth_docker_path, capture_output=True, text=True)
                if down_result.returncode != 0:
                    click.echo(f"   ⚠️  Docker compose down failed: {down_result.stderr}")
                    return False
                
                up_result = subprocess.run(['docker', 'compose', 'up', '-d'], 
                                         cwd=eth_docker_path, capture_output=True, text=True)
                return up_result.returncode == 0
        else:
            # Remote restart via SSH - prefer ./ethd if available
            ssh_user = node_config.get('ssh_user', 'root')
            tailscale_domain = node_config.get('tailscale_domain')
            
            # Check if ./ethd exists and use it, otherwise fallback to docker compose
            check_cmd = f"ssh {ssh_user}@{tailscale_domain} 'cd {eth_docker_path} && test -x ./ethd'"
            check_result = subprocess.run(check_cmd, shell=True, capture_output=True, text=True)
            
            if check_result.returncode == 0:
                # Use ./ethd down && ./ethd up -d
                ssh_cmd = f"ssh {ssh_user}@{tailscale_domain} 'cd {eth_docker_path} && ./ethd down && ./ethd up -d'"
            else:
                # Fallback to docker compose
                ssh_cmd = f"ssh {ssh_user}@{tailscale_domain} 'cd {eth_docker_path} && docker compose down && docker compose up -d'"
            
            result = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True)
            return result.returncode == 0
            
    except Exception as e:
        click.echo(f"   ❌ Error restarting services: {e}")
        return False

# New comprehensive node status command
@node_group.command(name='status')
@click.option('--all', is_flag=True, help='Show status for all configured nodes')
@click.option('--csv', is_flag=True, help='Output in CSV format')
def node_status(all, csv):
    """📊 Show comprehensive node status with ports, IPs, and peer counts"""
    config = yaml.safe_load(get_config_path().read_text())
    nodes = config.get('nodes', [])
    
    if not nodes:
        click.echo("❌ No nodes found in configuration")
        return
    
    if not all:
        click.echo("❌ Use --all flag to show status for all nodes")
        click.echo("Usage: python3 -m eth_validators node status --all")
        return
    
    click.echo("📊 ETHEREUM NODE COMPREHENSIVE STATUS")
    click.echo("=" * 120)
    click.echo("🔄 Fetching live data from all nodes... (this may take a moment)")
    
    table_data = []
    
    for i, node in enumerate(nodes):
        name = node['name']
        hostname = node['tailscale_domain']
        
        click.echo(f"📡 Processing {name}... ({i+1}/{len(nodes)})", nl=False, err=True)
        
        # Get local IP (router IP, not Tailscale)
        try:
            # Try multiple methods to get the local IP
            ip_methods = [
                "ip route get 8.8.8.8 | awk '{print $7}' | head -1",  # Get IP for external route
                "hostname -I | awk '{print $1}'",  # Get first IP from hostname
                "ip addr show | grep 'inet ' | grep -v '127.0.0.1' | grep -v '::1' | awk '{print $2}' | cut -d/ -f1 | head -1"  # Get first non-loopback IP
            ]
            
            local_ip = "❓ Unknown"
            for method in ip_methods:
                ip_result = _run_command(node, method)
                if ip_result.returncode == 0 and ip_result.stdout.strip():
                    candidate_ip = ip_result.stdout.strip()
                    # Validate it's a proper IP (not default route)
                    if candidate_ip and not candidate_ip.startswith("1.0.0.0") and len(candidate_ip.split('.')) == 4:
                        local_ip = candidate_ip
                        break
        except:
            local_ip = "❓ Unknown"
        
        # Get P2P ports from consensus client
        p2p_ports = "❓ Unknown"
        try:
            # Try to get just the port numbers, not the full mapping
            p2p_result = _run_command(node, "docker port eth-docker-consensus-1 2>/dev/null | grep -E '900[0-9]|9200|9300|9401' | sed 's/.*://' | sort -n | uniq | tr '\n' ' ' | sed 's/ $//'")
            if p2p_result.returncode == 0 and p2p_result.stdout.strip():
                ports = p2p_result.stdout.strip().split()
                if ports:
                    p2p_ports = ', '.join(ports)
            else:
                # Try alternative container names
                for container in ['consensus-1', 'beacon-1', 'lighthouse-beacon-1', 'prysm-beacon-1', 'teku-1']:
                    alt_result = _run_command(node, f"docker port eth-docker-{container} 2>/dev/null | grep -E '900[0-9]|9200|9300|9401' | sed 's/.*://' | sort -n | uniq | tr '\n' ' ' | sed 's/ $//'")
                    if alt_result.returncode == 0 and alt_result.stdout.strip():
                        ports = alt_result.stdout.strip().split()
                        if ports:
                            p2p_ports = ', '.join(ports)
                        break
        except:
            pass
        
        # Get execution ports
        exec_ports = "❓ Unknown"
        try:
            exec_result = _run_command(node, "docker port eth-docker-execution-1 2>/dev/null | grep -E '303[0-9][0-9]|8545|8546' | sed 's/.*://' | sort -n | uniq | tr '\n' ' ' | sed 's/ $//'")
            if exec_result.returncode == 0 and exec_result.stdout.strip():
                ports = exec_result.stdout.strip().split()
                if ports:
                    exec_ports = ', '.join(ports)
            else:
                # Try alternative container names
                for container in ['execution-1', 'geth-1', 'nethermind-1', 'besu-1', 'reth-1']:
                    alt_result = _run_command(node, f"docker port eth-docker-{container} 2>/dev/null | grep -E '303[0-9][0-9]|8545|8546' | sed 's/.*://' | sort -n | uniq | tr '\n' ' ' | sed 's/ $//'")
                    if alt_result.returncode == 0 and alt_result.stdout.strip():
                        ports = alt_result.stdout.strip().split()
                        if ports:
                            exec_ports = ', '.join(ports)
                        break
        except:
            pass
        
        # Get peer count from consensus logs
        peer_count = "❓ Unknown"
        try:
            # Try different log patterns for different clients
            log_commands = [
                # Lighthouse
                "docker logs eth-docker-consensus-1 --tail 20 2>/dev/null | grep -i 'connected peers' | tail -1 | grep -o '[0-9]\\+' | tail -1",
                # Prysm
                "docker logs eth-docker-consensus-1 --tail 20 2>/dev/null | grep -i 'peer' | grep -o '[0-9]\\+/[0-9]\\+' | tail -1",
                # Teku
                "docker logs eth-docker-consensus-1 --tail 20 2>/dev/null | grep -i 'peer' | grep -o '[0-9]\\+' | tail -1",
                # Lodestar
                "docker logs eth-docker-consensus-1 --tail 20 2>/dev/null | grep -i 'connected' | grep -o '[0-9]\\+' | tail -1",
                # Nimbus
                "docker logs eth-docker-consensus-1 --tail 20 2>/dev/null | grep -i 'peers' | grep -o '[0-9]\\+' | tail -1",
                # Try alternative container names
                "docker logs eth-docker-beacon-1 --tail 20 2>/dev/null | grep -i 'peer' | tail -1 | grep -o '[0-9]\\+/[0-9]\\+' | tail -1",
                "docker logs eth-docker-lighthouse-beacon-1 --tail 20 2>/dev/null | grep -i 'connected peers' | tail -1 | grep -o '[0-9]\\+' | tail -1",
                "docker logs eth-docker-teku-1 --tail 20 2>/dev/null | grep -i 'peer' | tail -1 | grep -o '[0-9]\\+' | tail -1"
            ]
            
            for cmd in log_commands:
                peer_result = _run_command(node, cmd)
                if peer_result.returncode == 0 and peer_result.stdout.strip():
                    peer_info = peer_result.stdout.strip()
                    if peer_info and peer_info != "0":
                        # If it's already in format like "50/100", use it
                        if '/' in peer_info:
                            peer_count = peer_info
                        else:
                            # Try to get max peers from config or use default
                            try:
                                max_peers_result = _run_command(node, "docker logs eth-docker-consensus-1 --tail 50 2>/dev/null | grep -i 'max.*peer' | tail -1 | grep -o '[0-9]\\+' | tail -1")
                                if max_peers_result.returncode == 0 and max_peers_result.stdout.strip():
                                    max_peers = max_peers_result.stdout.strip()
                                    peer_count = f"{peer_info}/{max_peers}"
                                else:
                                    peer_count = peer_info
                            except:
                                peer_count = peer_info
                        break
        except:
            pass
        
        # Determine status based on data availability
        if local_ip != "❓ Unknown" and p2p_ports != "❓ Unknown":
            status = "✅ Active"
        elif local_ip != "❓ Unknown":
            status = "⚠️ Limited"
        else:
            status = "❌ Offline"
        
        table_data.append([
            name,
            hostname,
            local_ip,
            p2p_ports,
            exec_ports,
            peer_count,
            status
        ])
        
        click.echo(" ✓", err=True)
    
    # Output in requested format
    if csv:
        import csv
        click.echo("Node,Hostname,Local IP,P2P Ports,Execution Ports,Peer Count,Status")
        for row in table_data:
            click.echo(",".join(str(cell) for cell in row))
    else:
        click.echo("\nRendering comprehensive status table...")
        headers = ['Node Name', 'Hostname', 'Local IP', 'P2P Ports', 'Execution Ports', 'Peers', 'Status']
        click.echo(tabulate(table_data, headers=headers, tablefmt='fancy_grid'))
    
    click.echo(f"\n📊 SUMMARY:")
    active_count = sum(1 for row in table_data if "✅" in row[-1])
    limited_count = sum(1 for row in table_data if "⚠️" in row[-1])
    offline_count = sum(1 for row in table_data if "❌" in row[-1])
    
    click.echo(f"  ✅ Active nodes: {active_count}")
    click.echo(f"  ⚠️ Limited nodes: {limited_count}")
    click.echo(f"  ❌ Offline nodes: {offline_count}")
    click.echo(f"  📈 Total nodes: {len(nodes)}")
    
    click.echo(f"\n💡 Use 'node status --csv' for CSV output")
    click.echo("=" * 120)

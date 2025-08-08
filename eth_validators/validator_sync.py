#!/usr/bin/env python3
"""
Validator CSV Sync Tool
Automatically updates validators_vs_hardware.csv with current validator statuses
and filters out exited validators from analysis
"""

import requests
import csv
import json
import yaml
import time
from pathlib import Path
from typing import List, Dict, Set, Tuple
import click

def get_config_path():
    """Find config.yaml in current directory first, then in eth_validators directory"""
    # First check current working directory (where user runs the command)
    current_dir_config = Path.cwd() / 'config.yaml'
    if current_dir_config.exists():
        return current_dir_config
    
    # Fallback to the default location (for backward compatibility)
    default_config = Path(__file__).parent / 'config.yaml'
    return default_config

class ValidatorSyncManager:
    def __init__(self, config_path: str = None):
        """Initialize the validator sync manager"""
        if config_path is None:
            config_path = get_config_path()
        
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.csv_path = Path(__file__).parent / 'validators_vs_hardware.csv'
        self.backup_path = Path(__file__).parent / f'validators_vs_hardware_backup_{int(time.time())}.csv'
        
    def get_beacon_api_url(self, node_config: Dict) -> str:
        """Get the beacon API URL for a node"""
        port = node_config.get('beacon_api_port', 5052)
        domain = node_config['tailscale_domain']
        return f"http://{domain}:{port}"
    
    def fetch_validator_status(self, node_config: Dict, validator_indices: List[int]) -> Dict[int, Dict]:
        """Fetch validator status from beacon node API"""
        beacon_url = self.get_beacon_api_url(node_config)
        
        if not validator_indices:
            return {}
        
        # Split into chunks of 50 to avoid URL length limits
        chunk_size = 50
        all_statuses = {}
        
        for i in range(0, len(validator_indices), chunk_size):
            chunk = validator_indices[i:i + chunk_size]
            indices_str = ','.join(map(str, chunk))
            
            try:
                url = f"{beacon_url}/eth/v1/beacon/states/head/validators"
                params = {'id': indices_str}
                
                response = requests.get(url, params=params, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    validators = data.get('data', [])
                    
                    for validator in validators:
                        index = int(validator['index'])
                        status = validator['status']
                        balance = validator['balance']
                        
                        all_statuses[index] = {
                            'status': status,
                            'balance': balance,
                            'is_active': status in ['active_ongoing', 'active_exiting', 'active_slashed'],
                            'is_exited': status in ['exited_unslashed', 'exited_slashed', 'withdrawal_possible', 'withdrawal_done']
                        }
                        
                    click.echo(f"  ✅ Fetched status for {len(validators)} validators from {node_config['name']}")
                    
                else:
                    click.echo(f"  ❌ Failed to fetch validators from {node_config['name']}: HTTP {response.status_code}")
                    
            except Exception as e:
                click.echo(f"  ❌ Error fetching from {node_config['name']}: {e}")
                
        return all_statuses
    
    def load_current_csv(self) -> List[Dict]:
        """Load the current CSV data"""
        validators = []
        
        try:
            with open(self.csv_path, 'r', newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    # Clean up the row
                    cleaned_row = {}
                    for key, value in row.items():
                        # Remove any trailing spaces from keys
                        clean_key = key.strip() if key else ''
                        cleaned_row[clean_key] = value.strip() if value else ''
                    validators.append(cleaned_row)
                    
        except FileNotFoundError:
            click.echo(f"❌ CSV file not found: {self.csv_path}")
            return []
        except Exception as e:
            click.echo(f"❌ Error reading CSV: {e}")
            return []
            
        click.echo(f"📋 Loaded {len(validators)} validators from CSV")
        return validators
    
    def backup_csv(self):
        """Create a backup of the current CSV"""
        try:
            import shutil
            import time
            
            timestamp = int(time.time())
            backup_path = Path(__file__).parent / f'validators_vs_hardware_backup_{timestamp}.csv'
            shutil.copy2(self.csv_path, backup_path)
            click.echo(f"💾 Backup created: {backup_path}")
            
        except Exception as e:
            click.echo(f"⚠️  Could not create backup: {e}")
    
    def update_csv_with_statuses(self, validators: List[Dict], status_updates: Dict[str, Dict[int, Dict]]) -> List[Dict]:
        """Update validators list with current statuses"""
        updated_validators = []
        
        for validator in validators:
            try:
                index = int(validator.get('validator index', '').strip())
                node_domain = validator.get('tailscale dns', '').strip()
                
                # Find status update for this validator
                status_info = None
                for node_name, node_statuses in status_updates.items():
                    if index in node_statuses:
                        status_info = node_statuses[index]
                        break
                
                if status_info:
                    # Add status information to the validator record
                    validator['current_status'] = status_info['status']
                    validator['is_active'] = str(status_info['is_active'])
                    validator['is_exited'] = str(status_info['is_exited'])
                    validator['last_updated'] = str(int(time.time()))
                    
                    # Only include non-exited validators
                    if not status_info['is_exited']:
                        updated_validators.append(validator)
                    else:
                        click.echo(f"  🚫 Excluding exited validator {index} ({status_info['status']})")
                else:
                    # Keep validator if we couldn't get status (might be on different node)
                    validator['current_status'] = 'unknown'
                    validator['is_active'] = 'unknown'
                    validator['is_exited'] = 'false'  # Conservative approach
                    updated_validators.append(validator)
                    
            except ValueError:
                # Skip rows with invalid validator index
                click.echo(f"  ⚠️  Skipping row with invalid validator index: {validator}")
                continue
        
        click.echo(f"📊 Updated CSV: {len(validators)} → {len(updated_validators)} validators (removed {len(validators) - len(updated_validators)} exited)")
        return updated_validators
    
    def save_updated_csv(self, validators: List[Dict]):
        """Save the updated CSV"""
        if not validators:
            click.echo("❌ No validators to save")
            return
        
        try:
            # Get all possible field names
            all_fields = set()
            for validator in validators:
                all_fields.update(validator.keys())
            
            # Define field order
            priority_fields = [
                'validator index', 'validator public address', 'Protocol', 'stack',
                'tailscale dns', 'AI Monitoring containers1', 'AI Monitoring containers2',
                'AI Monitoring containers3', 'AI Monitoring containers4', 'AI Monitoring containers5',
                'current_status', 'is_active', 'is_exited', 'last_updated'
            ]
            
            # Arrange fields with priority first, then others
            ordered_fields = []
            for field in priority_fields:
                if field in all_fields:
                    ordered_fields.append(field)
                    all_fields.remove(field)
            
            # Add remaining fields
            ordered_fields.extend(sorted(all_fields))
            
            # Write the CSV
            with open(self.csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=ordered_fields)
                writer.writeheader()
                
                for validator in validators:
                    # Ensure all fields are present
                    row = {field: validator.get(field, '') for field in ordered_fields}
                    writer.writerow(row)
            
            click.echo(f"✅ Updated CSV saved with {len(validators)} active validators")
            
        except Exception as e:
            click.echo(f"❌ Error saving CSV: {e}")
    
    def get_validators_for_node(self, node_name: str, validators: List[Dict]) -> List[int]:
        """Get validator indices for a specific node"""
        node_validators = []
        
        for validator in validators:
            tailscale_dns = validator.get('tailscale dns', '').strip()
            
            # Match by node name in tailscale domain
            if node_name in tailscale_dns:
                try:
                    index = int(validator.get('validator index', '').strip())
                    node_validators.append(index)
                except ValueError:
                    continue
        
        return node_validators
    
    def sync_validators(self, nodes: List[str] = None) -> Dict:
        """Sync validator statuses for specified nodes or all nodes"""
        click.echo("🔄 VALIDATOR CSV SYNC STARTING")
        click.echo("=" * 60)
        
        # Load current CSV
        validators = self.load_current_csv()
        if not validators:
            return {'error': 'No validators loaded from CSV'}
        
        # Create backup
        self.backup_csv()
        
        # Get nodes to check
        if nodes:
            target_nodes = [n for n in self.config['nodes'] if n['name'] in nodes]
        else:
            target_nodes = [n for n in self.config['nodes'] if n.get('stack') != 'disabled']
        
        if not target_nodes:
            return {'error': 'No active nodes found'}
        
        click.echo(f"🎯 Checking {len(target_nodes)} nodes")
        
        # Fetch statuses from each node
        all_status_updates = {}
        
        for node_config in target_nodes:
            node_name = node_config['name']
            click.echo(f"\n📡 Processing {node_name}...")
            
            # Get validators for this node
            node_validator_indices = self.get_validators_for_node(node_name, validators)
            
            if not node_validator_indices:
                click.echo(f"  ℹ️  No validators found for {node_name}")
                continue
            
            click.echo(f"  📊 Found {len(node_validator_indices)} validators")
            
            # Fetch statuses
            statuses = self.fetch_validator_status(node_config, node_validator_indices)
            
            if statuses:
                all_status_updates[node_name] = statuses
        
        # Update CSV with new statuses
        if all_status_updates:
            updated_validators = self.update_csv_with_statuses(validators, all_status_updates)
            self.save_updated_csv(updated_validators)
            
            # Generate summary
            total_checked = sum(len(statuses) for statuses in all_status_updates.values())
            exited_count = len(validators) - len(updated_validators)
            
            summary = {
                'success': True,
                'nodes_checked': len(all_status_updates),
                'validators_checked': total_checked,
                'validators_remaining': len(updated_validators),
                'validators_removed': exited_count,
                'backup_created': True
            }
            
            click.echo(f"\n✅ SYNC COMPLETE")
            click.echo(f"📊 Summary:")
            click.echo(f"  • Nodes checked: {summary['nodes_checked']}")
            click.echo(f"  • Validators checked: {summary['validators_checked']}")
            click.echo(f"  • Active validators: {summary['validators_remaining']}")
            click.echo(f"  • Exited validators removed: {summary['validators_removed']}")
            
            return summary
        else:
            return {'error': 'No status updates retrieved from any node'}

def get_active_validators_only() -> List[Dict]:
    """Get only active validators from the CSV (helper function for other modules)"""
    csv_path = Path(__file__).parent / 'validators_vs_hardware.csv'
    active_validators = []
    
    try:
        with open(csv_path, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                # Clean up the row
                cleaned_row = {}
                for key, value in row.items():
                    clean_key = key.strip() if key else ''
                    cleaned_row[clean_key] = value.strip() if value else ''
                
                # Only include if not explicitly marked as exited
                is_exited = cleaned_row.get('is_exited', 'false').lower()
                current_status = cleaned_row.get('current_status', '')
                
                # Exclude if explicitly exited or has exited status
                if (is_exited != 'true' and 
                    not any(exit_status in current_status.lower() for exit_status in 
                           ['exited', 'withdrawal_possible', 'withdrawal_done'])):
                    active_validators.append(cleaned_row)
                    
    except Exception as e:
        click.echo(f"Warning: Could not filter active validators: {e}")
        # Fallback to loading all
        return []
    
    return active_validators

if __name__ == "__main__":
    import time
    
    @click.command()
    @click.option('--nodes', help='Comma-separated list of node names to check (default: all active nodes)')
    @click.option('--dry-run', is_flag=True, help='Show what would be updated without making changes')
    def sync_command(nodes, dry_run):
        """Sync validator CSV with current beacon node statuses"""
        
        node_list = nodes.split(',') if nodes else None
        
        if dry_run:
            click.echo("🔍 DRY RUN MODE - No changes will be made")
        
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
                exit(1)
    
    sync_command()

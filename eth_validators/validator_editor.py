#!/usr/bin/env python3
"""
Interactive Validator Editor
Provides interactive tools for managing validators_vs_hardware.csv
including adding new validators, editing existing ones, and bulk operations
"""

import csv
import yaml
import json
import time
from pathlib import Path
from typing import List, Dict, Optional
import click
from tabulate import tabulate
import re

def get_config_path():
    """Find config.yaml in current directory first, then in eth_validators directory"""
    # First check current working directory (where user runs the command)
    current_dir_config = Path.cwd() / 'config.yaml'
    if current_dir_config.exists():
        return current_dir_config
    
    # Fallback to the default location (for backward compatibility)
    default_config = Path(__file__).parent / 'config.yaml'
    return default_config

class InteractiveValidatorEditor:
    def __init__(self, config_path: str = None):
        """Initialize the interactive validator editor"""
        if config_path is None:
            config_path = get_config_path()
        
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.csv_path = Path(__file__).parent / 'validators_vs_hardware.csv'
        self.backup_path = Path(__file__).parent / f'validators_vs_hardware_backup_{int(time.time())}.csv'
        
        # Get available nodes and protocols from config and existing CSV
        self.available_nodes = [n['name'] for n in self.config['nodes'] if n.get('stack') != 'disabled']
        self.available_protocols = self._get_available_protocols()
        self.available_stacks = self._get_available_stacks()
        
    def _get_available_protocols(self) -> List[str]:
        """Get list of protocols from existing CSV"""
        protocols = set()
        try:
            validators = self.load_validators()
            for validator in validators:
                protocol = validator.get('Protocol', '').strip()
                if protocol:
                    protocols.add(protocol)
        except:
            pass
        
        # Add common protocols if not present
        common_protocols = [
            'CSM LIDO', '102 CSM LIDO', '188 CSM LIDO',
            'Etherfi', 'Rocketpool', 'Stakewise', 'node set sw',
            'Stakewise Brazilpracima vault'
        ]
        protocols.update(common_protocols)
        return sorted(list(protocols))
    
    def _get_available_stacks(self) -> List[str]:
        """Get list of stacks from existing CSV and config"""
        stacks = set()
        try:
            validators = self.load_validators()
            for validator in validators:
                stack = validator.get('stack', '').strip()
                if stack:
                    stacks.add(stack)
        except:
            pass
        
        # Add stacks from config
        for node in self.config['nodes']:
            stack = node.get('stack', '').strip()
            if stack and stack != 'disabled':
                stacks.add(stack)
        
        # Add common stacks
        common_stacks = ['VERO', 'HYPERDRIVE', 'Obol', 'eth-docker', 'SSV']
        stacks.update(common_stacks)
        return sorted(list(stacks))
    
    def load_validators(self) -> List[Dict]:
        """Load validators from CSV"""
        validators = []
        try:
            with open(self.csv_path, 'r', newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    cleaned_row = {}
                    for key, value in row.items():
                        clean_key = key.strip() if key else ''
                        cleaned_row[clean_key] = value.strip() if value else ''
                    validators.append(cleaned_row)
        except FileNotFoundError:
            click.echo(f"❌ CSV file not found: {self.csv_path}")
        except Exception as e:
            click.echo(f"❌ Error reading CSV: {e}")
        return validators
    
    def backup_csv(self):
        """Create backup before making changes"""
        try:
            import shutil
            import time
            timestamp = int(time.time())
            backup_path = Path(__file__).parent / f'validators_vs_hardware_backup_{timestamp}.csv'
            shutil.copy2(self.csv_path, backup_path)
            click.echo(f"💾 Backup created: {backup_path}")
        except Exception as e:
            click.echo(f"⚠️ Could not create backup: {e}")
    
    def save_validators(self, validators: List[Dict]):
        """Save validators to CSV"""
        if not validators:
            click.echo("❌ No validators to save")
            return False
        
        try:
            # Get all field names
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
            
            ordered_fields = []
            for field in priority_fields:
                if field in all_fields:
                    ordered_fields.append(field)
                    all_fields.remove(field)
            ordered_fields.extend(sorted(all_fields))
            
            with open(self.csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=ordered_fields)
                writer.writeheader()
                for validator in validators:
                    row = {field: validator.get(field, '') for field in ordered_fields}
                    writer.writerow(row)
            
            click.echo(f"✅ CSV updated with {len(validators)} validators")
            return True
            
        except Exception as e:
            click.echo(f"❌ Error saving CSV: {e}")
            return False
    
    def get_node_domain(self, node_name: str) -> str:
        """Get tailscale domain for a node"""
        for node in self.config['nodes']:
            if node['name'] == node_name:
                return node.get('tailscale_domain', '')
        return f"{node_name}.velociraptor-scylla.ts.net"
    
    def validate_validator_index(self, index_str: str) -> Optional[int]:
        """Validate and return validator index"""
        try:
            index = int(index_str.strip())
            if index < 0:
                click.echo("❌ Validator index must be positive")
                return None
            return index
        except ValueError:
            click.echo("❌ Invalid validator index format")
            return None
    
    def validate_pubkey(self, pubkey: str) -> bool:
        """Validate validator public key format"""
        pubkey = pubkey.strip()
        if not pubkey.startswith('0x'):
            click.echo("❌ Public key must start with '0x'")
            return False
        if len(pubkey) != 98:  # 0x + 96 hex chars
            click.echo("❌ Public key must be 98 characters long (0x + 96 hex)")
            return False
        if not re.match(r'^0x[a-fA-F0-9]{96}$', pubkey):
            click.echo("❌ Public key contains invalid characters")
            return False
        return True
    
    def interactive_add_validator(self) -> Dict:
        """Interactive process to add a new validator"""
        click.echo("\n🆕 ADD NEW VALIDATOR")
        click.echo("=" * 50)
        
        validator = {}
        
        # Validator Index
        while True:
            index_input = click.prompt("📊 Validator Index", type=str)
            index = self.validate_validator_index(index_input)
            if index is not None:
                # Check if already exists
                existing = self.load_validators()
                if any(str(v.get('validator index', '')) == str(index) for v in existing):
                    if click.confirm(f"⚠️ Validator {index} already exists. Overwrite?"):
                        validator['validator index'] = str(index)
                        break
                else:
                    validator['validator index'] = str(index)
                    break
        
        # Public Key
        while True:
            pubkey = click.prompt("🔑 Validator Public Key (0x...)")
            if self.validate_pubkey(pubkey):
                validator['validator public address'] = pubkey
                break
        
        # Protocol selection
        click.echo(f"\n📋 Available Protocols:")
        for i, protocol in enumerate(self.available_protocols, 1):
            click.echo(f"  {i}. {protocol}")
        click.echo(f"  {len(self.available_protocols) + 1}. Custom (enter manually)")
        
        while True:
            try:
                choice = click.prompt("Select Protocol", type=int)
                if 1 <= choice <= len(self.available_protocols):
                    validator['Protocol'] = self.available_protocols[choice - 1]
                    break
                elif choice == len(self.available_protocols) + 1:
                    custom_protocol = click.prompt("Enter custom protocol name")
                    validator['Protocol'] = custom_protocol.strip()
                    break
                else:
                    click.echo("❌ Invalid choice")
            except ValueError:
                click.echo("❌ Please enter a number")
        
        # Stack selection
        click.echo(f"\n🏗️ Available Stacks:")
        for i, stack in enumerate(self.available_stacks, 1):
            click.echo(f"  {i}. {stack}")
        click.echo(f"  {len(self.available_stacks) + 1}. Custom (enter manually)")
        
        while True:
            try:
                choice = click.prompt("Select Stack", type=int)
                if 1 <= choice <= len(self.available_stacks):
                    validator['stack'] = self.available_stacks[choice - 1]
                    break
                elif choice == len(self.available_stacks) + 1:
                    custom_stack = click.prompt("Enter custom stack name")
                    validator['stack'] = custom_stack.strip()
                    break
                else:
                    click.echo("❌ Invalid choice")
            except ValueError:
                click.echo("❌ Please enter a number")
        
        # Node selection
        click.echo(f"\n🖥️ Available Nodes:")
        for i, node in enumerate(self.available_nodes, 1):
            click.echo(f"  {i}. {node}")
        click.echo(f"  {len(self.available_nodes) + 1}. Custom (enter manually)")
        
        while True:
            try:
                choice = click.prompt("Select Node", type=int)
                if 1 <= choice <= len(self.available_nodes):
                    node_name = self.available_nodes[choice - 1]
                    validator['tailscale dns'] = self.get_node_domain(node_name)
                    break
                elif choice == len(self.available_nodes) + 1:
                    custom_node = click.prompt("Enter custom tailscale domain")
                    validator['tailscale dns'] = custom_node.strip()
                    break
                else:
                    click.echo("❌ Invalid choice")
            except ValueError:
                click.echo("❌ Please enter a number")
        
        # AI Monitoring containers (optional)
        click.echo(f"\n🤖 AI Monitoring Containers (optional, press Enter to skip):")
        for i in range(1, 6):
            container = click.prompt(f"  Container {i}", default="", show_default=False)
            if container.strip():
                validator[f'AI Monitoring containers{i}'] = container.strip()
        
        # Status fields (for new validators)
        validator['current_status'] = 'unknown'
        validator['is_active'] = 'unknown'
        validator['is_exited'] = 'false'
        validator['last_updated'] = str(int(time.time()))
        
        return validator
    
    def interactive_edit_validator(self, validators: List[Dict]) -> List[Dict]:
        """Interactive editing of existing validators"""
        if not validators:
            click.echo("❌ No validators found")
            return validators
        
        # Show existing validators
        click.echo(f"\n📋 EXISTING VALIDATORS ({len(validators)} total)")
        click.echo("=" * 60)
        
        # Create table for display
        table_data = []
        for i, validator in enumerate(validators[:20]):  # Show first 20
            table_data.append([
                i + 1,
                validator.get('validator index', ''),
                validator.get('Protocol', '')[:20],
                validator.get('tailscale dns', '').split('.')[0] if '.' in validator.get('tailscale dns', '') else validator.get('tailscale dns', ''),
                validator.get('current_status', 'unknown')
            ])
        
        headers = ['#', 'Index', 'Protocol', 'Node', 'Status']
        click.echo(tabulate(table_data, headers=headers, tablefmt='grid'))
        
        if len(validators) > 20:
            click.echo(f"\n... and {len(validators) - 20} more validators")
        
        while True:
            try:
                choice = click.prompt(f"\n🔧 Enter validator # to edit (1-{len(validators)}) or 'q' to quit", type=str)
                if choice.lower() == 'q':
                    break
                
                index = int(choice) - 1
                if 0 <= index < len(validators):
                    validator = validators[index]
                    click.echo(f"\n✏️ EDITING VALIDATOR {validator.get('validator index', 'Unknown')}")
                    click.echo("=" * 50)
                    
                    # Show current values and allow editing
                    fields_to_edit = [
                        'validator index', 'validator public address', 'Protocol', 
                        'stack', 'tailscale dns'
                    ]
                    
                    for field in fields_to_edit:
                        current_value = validator.get(field, '')
                        new_value = click.prompt(f"{field}", default=current_value)
                        if new_value != current_value:
                            validator[field] = new_value
                            validator['last_updated'] = str(int(time.time()))
                    
                    # Container editing
                    if click.confirm("Edit AI Monitoring containers?"):
                        for i in range(1, 6):
                            field = f'AI Monitoring containers{i}'
                            current_value = validator.get(field, '')
                            new_value = click.prompt(f"  {field}", default=current_value, show_default=False)
                            validator[field] = new_value.strip()
                    
                    click.echo("✅ Validator updated")
                else:
                    click.echo("❌ Invalid validator number")
                    
            except ValueError:
                if choice.lower() != 'q':
                    click.echo("❌ Please enter a number or 'q'")
        
        return validators
    
    def search_validators(self, validators: List[Dict]) -> List[Dict]:
        """Search and filter validators"""
        if not validators:
            click.echo("❌ No validators found")
            return []
        
        click.echo(f"\n🔍 SEARCH VALIDATORS")
        click.echo("=" * 30)
        
        search_term = click.prompt("Enter search term (index, protocol, node name, or pubkey)")
        search_term = search_term.lower().strip()
        
        matches = []
        for validator in validators:
            # Search in multiple fields
            searchable_text = ' '.join([
                str(validator.get('validator index', '')),
                validator.get('Protocol', ''),
                validator.get('tailscale dns', ''),
                validator.get('validator public address', ''),
                validator.get('stack', ''),
                validator.get('current_status', '')
            ]).lower()
            
            if search_term in searchable_text:
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
        else:
            click.echo("❌ No matches found")
        
        return matches
    
    def bulk_operations(self, validators: List[Dict]) -> List[Dict]:
        """Perform bulk operations on validators"""
        if not validators:
            click.echo("❌ No validators found")
            return validators
        
        click.echo(f"\n⚡ BULK OPERATIONS")
        click.echo("=" * 30)
        click.echo("1. Update protocol for multiple validators")
        click.echo("2. Update stack for multiple validators")
        click.echo("3. Move validators to different node")
        click.echo("4. Mark validators as exited")
        click.echo("5. Update AI monitoring containers")
        click.echo("6. Back to main menu")
        
        try:
            choice = click.prompt("Select operation", type=int)
            
            if choice == 1:
                # Update protocol
                new_protocol = click.prompt("Enter new protocol name")
                filter_term = click.prompt("Update validators containing (leave empty for all)", default="")
                
                count = 0
                for validator in validators:
                    if not filter_term or filter_term.lower() in str(validator).lower():
                        validator['Protocol'] = new_protocol
                        validator['last_updated'] = str(int(time.time()))
                        count += 1
                
                click.echo(f"✅ Updated {count} validators")
                
            elif choice == 2:
                # Update stack
                new_stack = click.prompt("Enter new stack name")
                filter_term = click.prompt("Update validators containing (leave empty for all)", default="")
                
                count = 0
                for validator in validators:
                    if not filter_term or filter_term.lower() in str(validator).lower():
                        validator['stack'] = new_stack
                        validator['last_updated'] = str(int(time.time()))
                        count += 1
                
                click.echo(f"✅ Updated {count} validators")
                
            elif choice == 3:
                # Move to different node
                click.echo("Available nodes:")
                for i, node in enumerate(self.available_nodes, 1):
                    click.echo(f"  {i}. {node}")
                
                node_choice = click.prompt("Select target node", type=int)
                if 1 <= node_choice <= len(self.available_nodes):
                    target_node = self.available_nodes[node_choice - 1]
                    target_domain = self.get_node_domain(target_node)
                    
                    filter_term = click.prompt("Move validators containing (leave empty for all)", default="")
                    
                    count = 0
                    for validator in validators:
                        if not filter_term or filter_term.lower() in str(validator).lower():
                            validator['tailscale dns'] = target_domain
                            validator['last_updated'] = str(int(time.time()))
                            count += 1
                    
                    click.echo(f"✅ Moved {count} validators to {target_node}")
                
            elif choice == 4:
                # Mark as exited
                filter_term = click.prompt("Mark validators containing as exited")
                if click.confirm(f"⚠️ Mark all validators containing '{filter_term}' as exited?"):
                    count = 0
                    for validator in validators:
                        if filter_term.lower() in str(validator).lower():
                            validator['current_status'] = 'exited_unslashed'
                            validator['is_active'] = 'false'
                            validator['is_exited'] = 'true'
                            validator['last_updated'] = str(int(time.time()))
                            count += 1
                    
                    click.echo(f"✅ Marked {count} validators as exited")
                    
        except ValueError:
            click.echo("❌ Invalid choice")
        
        return validators

def main_menu():
    """Main interactive menu"""
    import time
    
    editor = InteractiveValidatorEditor()
    
    while True:
        click.echo(f"\n🎛️ INTERACTIVE VALIDATOR MANAGER")
        click.echo("=" * 60)
        click.echo("1. 📋 View all validators")
        click.echo("2. 🆕 Add new validator")
        click.echo("3. ✏️ Edit existing validator")
        click.echo("4. 🔍 Search validators")
        click.echo("5. ⚡ Bulk operations")
        click.echo("6. 💾 Export to JSON")
        click.echo("7. 📊 Statistics")
        click.echo("8. 🚪 Exit")
        
        try:
            choice = click.prompt("\nSelect option", type=int)
            
            if choice == 1:
                # View all validators
                validators = editor.load_validators()
                if validators:
                    click.echo(f"\n📋 ALL VALIDATORS ({len(validators)} total)")
                    click.echo("=" * 60)
                    
                    table_data = []
                    for validator in validators[:50]:  # Show first 50
                        table_data.append([
                            validator.get('validator index', ''),
                            validator.get('Protocol', '')[:25],
                            validator.get('tailscale dns', '').split('.')[0] if '.' in validator.get('tailscale dns', '') else validator.get('tailscale dns', ''),
                            validator.get('current_status', 'unknown'),
                            validator.get('stack', '')[:15]
                        ])
                    
                    headers = ['Index', 'Protocol', 'Node', 'Status', 'Stack']
                    click.echo(tabulate(table_data, headers=headers, tablefmt='grid'))
                    
                    if len(validators) > 50:
                        click.echo(f"\n... and {len(validators) - 50} more validators")
                        click.echo("💡 Use search to find specific validators")
                
            elif choice == 2:
                # Add new validator
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
                
            elif choice == 3:
                # Edit existing validator
                validators = editor.load_validators()
                validators = editor.interactive_edit_validator(validators)
                
                if click.confirm("\n💾 Save changes?"):
                    editor.backup_csv()
                    if editor.save_validators(validators):
                        click.echo("🎉 Changes saved successfully!")
                
            elif choice == 4:
                # Search validators
                validators = editor.load_validators()
                matches = editor.search_validators(validators)
                
                if matches and click.confirm("\n✏️ Edit any of these validators?"):
                    edited = editor.interactive_edit_validator(matches)
                    
                    # Update the original list
                    match_indices = {v.get('validator index'): v for v in edited}
                    for i, validator in enumerate(validators):
                        index = validator.get('validator index')
                        if index in match_indices:
                            validators[i] = match_indices[index]
                    
                    if click.confirm("💾 Save changes?"):
                        editor.backup_csv()
                        if editor.save_validators(validators):
                            click.echo("🎉 Changes saved successfully!")
                
            elif choice == 5:
                # Bulk operations
                validators = editor.load_validators()
                validators = editor.bulk_operations(validators)
                
                if click.confirm("\n💾 Save changes?"):
                    editor.backup_csv()
                    if editor.save_validators(validators):
                        click.echo("🎉 Bulk changes saved successfully!")
                
            elif choice == 6:
                # Export to JSON
                validators = editor.load_validators()
                if validators:
                    export_file = Path(__file__).parent / f'validators_export_{int(time.time())}.json'
                    with open(export_file, 'w') as f:
                        json.dump(validators, f, indent=2)
                    click.echo(f"📄 Exported {len(validators)} validators to {export_file}")
                
            elif choice == 7:
                # Statistics
                validators = editor.load_validators()
                if validators:
                    click.echo(f"\n📊 STATISTICS")
                    click.echo("=" * 30)
                    click.echo(f"Total validators: {len(validators)}")
                    
                    # Group by protocol
                    protocols = {}
                    for v in validators:
                        protocol = v.get('Protocol', 'Unknown')
                        protocols[protocol] = protocols.get(protocol, 0) + 1
                    
                    click.echo(f"\nBy Protocol:")
                    for protocol, count in sorted(protocols.items()):
                        click.echo(f"  {protocol}: {count}")
                    
                    # Group by node
                    nodes = {}
                    for v in validators:
                        node = v.get('tailscale dns', 'Unknown').split('.')[0] if '.' in v.get('tailscale dns', '') else v.get('tailscale dns', 'Unknown')
                        nodes[node] = nodes.get(node, 0) + 1
                    
                    click.echo(f"\nBy Node:")
                    for node, count in sorted(nodes.items()):
                        click.echo(f"  {node}: {count}")
                    
                    # Group by status
                    statuses = {}
                    for v in validators:
                        status = v.get('current_status', 'unknown')
                        statuses[status] = statuses.get(status, 0) + 1
                    
                    click.echo(f"\nBy Status:")
                    for status, count in sorted(statuses.items()):
                        click.echo(f"  {status}: {count}")
                
            elif choice == 8:
                click.echo("👋 Goodbye!")
                break
                
            else:
                click.echo("❌ Invalid choice")
                
        except ValueError:
            click.echo("❌ Please enter a number")
        except KeyboardInterrupt:
            click.echo("\n👋 Goodbye!")
            break

if __name__ == "__main__":
    import time
    main_menu()

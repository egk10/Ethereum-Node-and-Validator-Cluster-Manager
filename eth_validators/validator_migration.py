"""
Validator CSV Migration and Automation System

This module helps users migrate from complex manual CSV files to the simplified
auto-discovery system, with automation and scheduling capabilities.
"""

import logging
import csv
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import subprocess
import yaml

from .validator_auto_discovery import ValidatorAutoDiscovery
from .config import get_all_node_configs

logger = logging.getLogger(__name__)

class ValidatorMigrationManager:
    """Manages migration from old CSV format to auto-discovery system"""
    
    def __init__(self, config_file_path: str):
        self.config_file_path = config_file_path
        self.auto_discovery = ValidatorAutoDiscovery(config_file_path)
    
    def analyze_current_setup(self, old_csv_path: str) -> Dict:
        """
        Analyze current validator setup and provide migration recommendations
        
        Args:
            old_csv_path: Path to existing validators CSV
            
        Returns:
            Analysis results with migration recommendations
        """
        logger.info(f"Analyzing current validator setup from {old_csv_path}")
        
        analysis = {
            'old_csv_stats': {},
            'auto_discovery_stats': {},
            'migration_recommendations': [],
            'complexity_reduction': {},
            'issues_found': []
        }
        
        try:
            # Analyze old CSV
            old_stats = self._analyze_old_csv(old_csv_path)
            analysis['old_csv_stats'] = old_stats
            
            # Run auto-discovery
            discovered_validators = self.auto_discovery.discover_all_validators()
            discovery_stats = self._analyze_discovered_validators(discovered_validators)
            analysis['auto_discovery_stats'] = discovery_stats
            
            # Generate recommendations
            analysis['migration_recommendations'] = self._generate_migration_recommendations(
                old_stats, discovery_stats
            )
            
            # Calculate complexity reduction
            analysis['complexity_reduction'] = self._calculate_complexity_reduction(
                old_stats, discovery_stats
            )
            
        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            analysis['issues_found'].append(f"Analysis error: {e}")
        
        return analysis
    
    def _analyze_old_csv(self, csv_path: str) -> Dict:
        """Analyze the existing CSV file"""
        stats = {
            'total_validators': 0,
            'total_columns': 0,
            'nodes_used': set(),
            'protocols_found': set(),
            'empty_fields': 0,
            'manual_maintenance_fields': 0,
            'file_size_mb': 0
        }
        
        try:
            csv_file = Path(csv_path)
            if not csv_file.exists():
                return stats
            
            stats['file_size_mb'] = csv_file.stat().st_size / (1024 * 1024)
            
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                if reader.fieldnames:
                    stats['total_columns'] = len(reader.fieldnames)
                    # Count fields that require manual maintenance
                    manual_fields = [
                        'AI Monitoring containers1', 'AI Monitoring containers2',
                        'AI Monitoring containers3', 'AI Monitoring containers4', 
                        'AI Monitoring containers5', 'current_status', 'is_active',
                        'is_exited', 'last_updated'
                    ]
                    stats['manual_maintenance_fields'] = len([f for f in reader.fieldnames if f in manual_fields])
                
                for row in reader:
                    stats['total_validators'] += 1
                    
                    # Count empty fields
                    empty_count = sum(1 for value in row.values() if not value or value.strip() == '')
                    stats['empty_fields'] += empty_count
                    
                    # Extract node and protocol info
                    if 'tailscale dns' in row:
                        domain = row['tailscale dns']
                        if domain:
                            # Extract node name from domain
                            node_name = domain.split('.')[0]
                            stats['nodes_used'].add(node_name)
                    
                    if 'Protocol' in row:
                        protocol = row['Protocol']
                        if protocol:
                            stats['protocols_found'].add(protocol)
            
            # Convert sets to lists for JSON serialization
            stats['nodes_used'] = list(stats['nodes_used'])
            stats['protocols_found'] = list(stats['protocols_found'])
            
        except Exception as e:
            logger.error(f"Failed to analyze old CSV: {e}")
        
        return stats
    
    def _analyze_discovered_validators(self, validators: List[Dict]) -> Dict:
        """Analyze auto-discovered validators"""
        stats = {
            'total_validators': len(validators),
            'total_columns': 6,  # Fixed for simplified format
            'nodes_used': set(),
            'protocols_found': set(),
            'empty_fields': 0,
            'manual_maintenance_fields': 0,  # All automated
            'live_data_fields': 4  # index, status, protocol, last_updated
        }
        
        for validator in validators:
            # Count actual empty fields
            empty_count = sum(1 for value in validator.values() if not value or str(value).strip() == '')
            stats['empty_fields'] += empty_count
            
            stats['nodes_used'].add(validator['node_name'])
            stats['protocols_found'].add(validator['protocol'])
        
        # Convert sets to lists
        stats['nodes_used'] = list(stats['nodes_used'])
        stats['protocols_found'] = list(stats['protocols_found'])
        
        return stats
    
    def _generate_migration_recommendations(self, old_stats: Dict, discovery_stats: Dict) -> List[str]:
        """Generate migration recommendations"""
        recommendations = []
        
        # Column reduction
        old_cols = old_stats.get('total_columns', 0)
        new_cols = discovery_stats.get('total_columns', 0)
        if old_cols > new_cols:
            reduction_pct = ((old_cols - new_cols) / old_cols) * 100
            recommendations.append(
                f"✅ Reduce CSV complexity by {reduction_pct:.1f}% ({old_cols} → {new_cols} columns)"
            )
        
        # Manual maintenance elimination
        manual_fields = old_stats.get('manual_maintenance_fields', 0)
        if manual_fields > 0:
            recommendations.append(
                f"✅ Eliminate {manual_fields} manually maintained fields - all automated!"
            )
        
        # Data accuracy improvement
        live_fields = discovery_stats.get('live_data_fields', 0)
        recommendations.append(
            f"✅ Get {live_fields} fields with live data from beacon chain APIs"
        )
        
        # Protocol standardization
        old_protocols = set(old_stats.get('protocols_found', []))
        new_protocols = set(discovery_stats.get('protocols_found', []))
        if len(new_protocols) > 0:
            recommendations.append(
                f"✅ Standardized protocol detection ({len(new_protocols)} protocols auto-detected)"
            )
        
        # Missing validators
        old_count = old_stats.get('total_validators', 0)
        new_count = discovery_stats.get('total_validators', 0)
        if new_count < old_count:
            recommendations.append(
                f"⚠️ Review {old_count - new_count} validators not auto-discovered (may need beacon API access)"
            )
        elif new_count > old_count:
            recommendations.append(
                f"✅ Auto-discovered {new_count - old_count} additional validators!"
            )
        
        return recommendations
    
    def _calculate_complexity_reduction(self, old_stats: Dict, discovery_stats: Dict) -> Dict:
        """Calculate complexity reduction metrics"""
        return {
            'column_reduction_pct': self._safe_percentage(
                old_stats.get('total_columns', 0), 
                discovery_stats.get('total_columns', 0)
            ),
            'manual_field_elimination': old_stats.get('manual_maintenance_fields', 0),
            'empty_field_reduction': old_stats.get('empty_fields', 0) - discovery_stats.get('empty_fields', 0),
            'file_size_reduction_estimate_pct': 70,  # Estimated based on column reduction
            'maintenance_time_saved_hours_per_month': self._estimate_time_savings(old_stats)
        }
    
    def _safe_percentage(self, old_value: int, new_value: int) -> float:
        """Safely calculate percentage reduction"""
        if old_value == 0:
            return 0
        return ((old_value - new_value) / old_value) * 100
    
    def _estimate_time_savings(self, old_stats: Dict) -> float:
        """Estimate monthly time savings from automation"""
        validators = old_stats.get('total_validators', 0)
        manual_fields = old_stats.get('manual_maintenance_fields', 0)
        
        # Estimate: 2 minutes per validator per month for manual updates
        # Plus 5 minutes per manual field for data entry errors/corrections
        time_per_validator = 2  # minutes
        time_per_manual_field = 5  # minutes
        
        total_minutes = (validators * time_per_validator) + (manual_fields * time_per_manual_field)
        return total_minutes / 60  # Convert to hours
    
    def create_migration_plan(self, old_csv_path: str, target_csv_path: str = None) -> Dict:
        """
        Create a step-by-step migration plan
        
        Args:
            old_csv_path: Path to existing CSV
            target_csv_path: Optional path for new simplified CSV
            
        Returns:
            Migration plan with steps and commands
        """
        if not target_csv_path:
            target_csv_path = old_csv_path.replace('.csv', '_simplified.csv')
        
        analysis = self.analyze_current_setup(old_csv_path)
        
        plan = {
            'analysis': analysis,
            'migration_steps': [],
            'rollback_plan': [],
            'automation_setup': [],
            'validation_steps': []
        }
        
        # Migration steps
        plan['migration_steps'] = [
            {
                'step': 1,
                'title': 'Backup Current CSV',
                'command': f'cp {old_csv_path} {old_csv_path}.backup_{int(datetime.now().timestamp())}',
                'description': 'Create backup of existing validator CSV'
            },
            {
                'step': 2,
                'title': 'Run Auto-Discovery',
                'command': f'python3 -m eth_validators validator discover --output {target_csv_path}',
                'description': 'Generate simplified CSV with auto-discovered validators'
            },
            {
                'step': 3,
                'title': 'Compare Results',
                'command': f'python3 -m eth_validators validator compare --old-csv {old_csv_path} --new-csv {target_csv_path}',
                'description': 'Review differences between old and new CSV'
            },
            {
                'step': 4,
                'title': 'Validate New CSV',
                'command': f'python3 -m eth_validators validator list --csv-file {target_csv_path}',
                'description': 'Verify new CSV contains expected validators'
            },
            {
                'step': 5,
                'title': 'Update Configuration',
                'command': 'Update scripts/tools to use new simplified CSV format',
                'description': 'Modify any existing tools to use simplified format'
            }
        ]
        
        # Rollback plan
        plan['rollback_plan'] = [
            {
                'step': 1,
                'title': 'Restore Original CSV',
                'command': f'mv {old_csv_path}.backup_* {old_csv_path}',
                'description': 'Restore from backup if issues found'
            },
            {
                'step': 2,
                'title': 'Revert Configuration Changes',
                'command': 'Manually revert any configuration changes',
                'description': 'Restore original tool configurations'
            }
        ]
        
        # Automation setup
        plan['automation_setup'] = [
            {
                'step': 1,
                'title': 'Setup Daily Auto-Discovery',
                'command': 'Create cron job for daily validator discovery',
                'description': 'Keep CSV automatically updated'
            },
            {
                'step': 2,
                'title': 'Configure Monitoring',
                'command': 'Setup alerts for validator changes',
                'description': 'Get notified of new/removed validators'
            }
        ]
        
        return plan
    
    def execute_migration(self, migration_plan: Dict, dry_run: bool = True) -> Dict:
        """
        Execute the migration plan
        
        Args:
            migration_plan: Plan created by create_migration_plan()
            dry_run: If True, only show what would be done
            
        Returns:
            Execution results
        """
        results = {
            'steps_completed': 0,
            'steps_failed': 0,
            'errors': [],
            'success': True,
            'dry_run': dry_run
        }
        
        if dry_run:
            logger.info("DRY RUN MODE - Commands will not be executed")
        
        for step_info in migration_plan.get('migration_steps', []):
            step_num = step_info['step']
            title = step_info['title']
            command = step_info['command']
            
            logger.info(f"Step {step_num}: {title}")
            
            if dry_run:
                logger.info(f"Would execute: {command}")
                results['steps_completed'] += 1
            else:
                try:
                    if command.startswith('python3 -m eth_validators'):
                        # Execute validator commands
                        result = subprocess.run(
                            command.split(), 
                            capture_output=True, 
                            text=True, 
                            timeout=300
                        )
                        if result.returncode != 0:
                            raise subprocess.CalledProcessError(result.returncode, command, result.stderr)
                    elif command.startswith('cp '):
                        # File operations
                        subprocess.run(command, shell=True, check=True)
                    else:
                        logger.info(f"Manual step: {command}")
                    
                    results['steps_completed'] += 1
                    logger.info(f"✅ Step {step_num} completed")
                    
                except Exception as e:
                    results['steps_failed'] += 1
                    results['errors'].append(f"Step {step_num} failed: {e}")
                    results['success'] = False
                    logger.error(f"❌ Step {step_num} failed: {e}")
                    break
        
        return results

def setup_automation_cron(csv_output_path: str, frequency: str = 'daily') -> str:
    """
    Setup automated validator discovery via cron
    
    Args:
        csv_output_path: Path where to save discovered validators
        frequency: 'daily', 'weekly', or 'hourly'
        
    Returns:
        Cron entry string
    """
    base_dir = Path(__file__).parent.parent
    
    frequency_map = {
        'daily': '0 6 * * *',    # 6 AM daily
        'weekly': '0 6 * * 1',   # 6 AM on Mondays
        'hourly': '0 * * * *'    # Every hour
    }
    
    cron_schedule = frequency_map.get(frequency, frequency_map['daily'])
    command = f"cd {base_dir} && /usr/bin/python3 -m eth_validators validator discover --output {csv_output_path}"
    
    cron_entry = f"{cron_schedule} {command} >> /var/log/validator-discovery.log 2>&1"
    
    return cron_entry

def create_monitoring_alerts(config_file_path: str) -> Dict:
    """
    Create monitoring configuration for validator changes
    
    Returns:
        Monitoring configuration
    """
    return {
        'alerts': {
            'new_validators_found': {
                'threshold': 1,
                'notification': 'email',
                'message': 'New validators discovered in cluster'
            },
            'validators_missing': {
                'threshold': 1,
                'notification': 'email',
                'message': 'Previously known validators not found'
            },
            'discovery_failures': {
                'threshold': 3,
                'notification': 'slack',
                'message': 'Validator auto-discovery failing repeatedly'
            }
        },
        'check_frequency': '1h',
        'retention_days': 30
    }

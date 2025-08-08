"""
AI-powered log analyzer for Ethereum validators.
Uses machine learning algorithms to analyze container logs and detect patterns,
anomalies, and performance issues automatically.
Enhanced with comprehensive beacon node performance data extraction.
"""
import re
import subprocess
import json
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import statistics
from typing import Dict, List, Tuple, Any
import yaml
from pathlib import Path

def get_config_path():
    """Find config.yaml in current directory first, then in eth_validators directory"""
    # First check current working directory (where user runs the command)
    current_dir_config = Path.cwd() / 'config.yaml'
    if current_dir_config.exists():
        return current_dir_config
    
    # Fallback to the default location (for backward compatibility)
    default_config = Path(__file__).parent / 'config.yaml'
    return default_config

class ValidatorLogAnalyzer:
    """AI-powered analyzer for validator and consensus client logs with enhanced performance extraction."""
    
    def __init__(self):
        self.log_patterns = {
            # Performance indicators
            'attestation_success': [
                r'Successfully published attestation',
                r'Attestation sent',
                r'Published attestation',
                r'Submitted attestation'
            ],
            'attestation_failed': [
                r'Failed to publish attestation',
                r'Attestation.*failed',
                r'Could not submit attestation',
                r'Error.*attestation'
            ],
            'block_proposal': [
                r'Successfully published block',
                r'Block.*published',
                r'Produced block',
                r'Block proposal.*success'
            ],
            'block_proposal_failed': [
                r'Failed to publish block',
                r'Block.*failed',
                r'Could not produce block',
                r'Error.*block.*proposal'
            ],
            'sync_issues': [
                r'Syncing',
                r'Not synced',
                r'Behind.*head',
                r'Catching up',
                r'sync.*lag'
            ],
            'peer_issues': [
                r'No peers',
                r'Disconnected.*peer',
                r'Peer.*timeout',
                r'Connection.*failed',
                r'peer.*error'
            ],
            'network_issues': [
                r'Network.*error',
                r'Connection.*timeout',
                r'DNS.*failed',
                r'Unable to connect',
                r'Request.*timeout'
            ],
            'memory_issues': [
                r'Out of memory',
                r'Memory.*limit',
                r'OOM',
                r'Allocation.*failed',
                r'Memory.*error'
            ],
            'disk_issues': [
                r'Disk.*full',
                r'No space left',
                r'Disk.*error',
                r'I/O.*error',
                r'Storage.*failed'
            ],
            'performance_warnings': [
                r'Slow.*response',
                r'High.*latency',
                r'Performance.*warning',
                r'Timeout.*exceeded',
                r'Processing.*slow'
            ]
        }
        
        # Severity scoring
        self.severity_weights = {
            'attestation_failed': 10,
            'block_proposal_failed': 15,
            'sync_issues': 8,
            'peer_issues': 6,
            'network_issues': 7,
            'memory_issues': 12,
            'disk_issues': 13,
            'performance_warnings': 5,
            'attestation_success': -2,  # Positive indicators
            'block_proposal': -3
        }

    def analyze_node_logs(self, node_name: str, hours: int = 24) -> Dict[str, Any]:
        """Analyze logs from all containers on a node for the specified time period."""
        try:
            # Load node configuration
            with open(get_config_path(), 'r') as f:
                config = yaml.safe_load(f)
            
            node_config = None
            for node in config.get('nodes', []):
                if node.get('name') == node_name:
                    node_config = node
                    break
            
            if not node_config:
                return {'error': f'Node {node_name} not found in configuration'}
            
            ssh_target = f"{node_config.get('ssh_user', 'root')}@{node_config['tailscale_domain']}"
            
            # Get container list
            containers = self._get_ethereum_containers(ssh_target)
            
            analysis_results = {
                'node': node_name,
                'analysis_period_hours': hours,
                'timestamp': datetime.now().isoformat(),
                'containers_analyzed': len(containers),
                'container_analyses': {},
                'overall_health_score': 0,
                'alerts': [],
                'recommendations': [],
                'performance_insights': {},
                'beacon_performance': {}  # New: Beacon node performance data
            }
            
            # Enhanced performance analysis with beacon node data
            try:
                beacon_performance = self._extract_beacon_performance(node_config)
                analysis_results['beacon_performance'] = beacon_performance
            except Exception as e:
                analysis_results['beacon_performance'] = {'error': f'Beacon analysis failed: {e}'}
            
            total_severity = 0
            container_count = 0
            
            for container in containers:
                container_analysis = self._analyze_container_logs(ssh_target, container, hours)
                analysis_results['container_analyses'][container] = container_analysis
                
                if container_analysis.get('severity_score') is not None:
                    total_severity += container_analysis['severity_score']
                    container_count += 1
            
            # Calculate overall health score (0-100, higher is better)
            if container_count > 0:
                avg_severity = total_severity / container_count
                # Convert severity to health score (invert and normalize)
                health_score = max(0, min(100, 100 - (avg_severity * 2)))
                
                # Factor in beacon performance if available
                if 'error' not in analysis_results['beacon_performance']:
                    beacon_health = self._calculate_beacon_health_score(analysis_results['beacon_performance'])
                    health_score = (health_score + beacon_health) / 2
                
                analysis_results['overall_health_score'] = round(health_score, 1)
            
            # Generate insights and recommendations
            analysis_results['alerts'] = self._generate_alerts(analysis_results)
            analysis_results['recommendations'] = self._generate_recommendations(analysis_results)
            analysis_results['performance_insights'] = self._generate_performance_insights(analysis_results)
            
            return analysis_results
            
        except Exception as e:
            return {'error': f'Analysis failed: {str(e)}'}

    def _extract_beacon_performance(self, node_config: Dict[str, Any]) -> Dict[str, Any]:
        """Extract performance data from beacon node API"""
        try:
            from .enhanced_performance_extractor import ValidatorPerformanceExtractor
            extractor = ValidatorPerformanceExtractor()
            
            # Get validator indices for this node
            validator_indices = extractor._get_validator_indices_for_node(node_config.get('name'))
            
            # Extract beacon performance data
            beacon_data = extractor.extract_beacon_node_performance(node_config, validator_indices)
            
            return beacon_data
            
        except ImportError:
            # Fallback to basic beacon API queries if enhanced extractor not available
            return self._basic_beacon_health_check(node_config)
        except Exception as e:
            return {'error': str(e)}

    def _basic_beacon_health_check(self, node_config: Dict[str, Any]) -> Dict[str, Any]:
        """Basic beacon node health check as fallback"""
        try:
            ssh_target = f"{node_config.get('ssh_user', 'root')}@{node_config['tailscale_domain']}"
            beacon_port = node_config.get('beacon_api_port', 5052)
            
            # Simple health check via curl
            health_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} 'curl -s --max-time 5 http://localhost:{beacon_port}/eth/v1/node/health'"
            result = subprocess.run(health_cmd, shell=True, capture_output=True, text=True, timeout=15)
            
            is_healthy = result.returncode == 0
            
            # Get sync status
            sync_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} 'curl -s --max-time 5 http://localhost:{beacon_port}/eth/v1/node/syncing'"
            sync_result = subprocess.run(sync_cmd, shell=True, capture_output=True, text=True, timeout=15)
            
            sync_data = {}
            if sync_result.returncode == 0:
                try:
                    sync_data = json.loads(sync_result.stdout).get('data', {})
                except:
                    pass
            
            return {
                'basic_health_check': True,
                'is_healthy': is_healthy,
                'sync_status': sync_data,
                'health_check_timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            return {'error': str(e)}

    def _calculate_beacon_health_score(self, beacon_data: Dict[str, Any]) -> float:
        """Calculate health score from beacon node data"""
        if 'error' in beacon_data:
            return 50.0  # Neutral score if beacon data unavailable
        
        score = 100.0
        
        # Check basic health
        if not beacon_data.get('is_healthy', True):
            score -= 30
        
        # Check sync status
        sync_status = beacon_data.get('sync_status', {})
        if sync_status.get('is_syncing', False):
            # Penalize based on sync distance
            sync_distance = sync_status.get('sync_distance', 0)
            if sync_distance > 100:  # Behind by more than 100 slots
                score -= min(40, sync_distance / 10)
        
        # Check peer connectivity (if available)
        peer_info = beacon_data.get('peer_info', {})
        if peer_info:
            connected_peers = peer_info.get('connected_peers', 0)
            if connected_peers < 8:  # Minimum recommended peers
                score -= (8 - connected_peers) * 5
        
        # Check validator performance (if available)
        validator_performance = beacon_data.get('validator_performance', {})
        if validator_performance:
            for validator_data in validator_performance.values():
                if isinstance(validator_data, dict) and 'performance_metrics' in validator_data:
                    perf_metrics = validator_data['performance_metrics']
                    
                    # Factor in attestation success rate
                    if 'attestation_hit_percentage' in perf_metrics:
                        hit_rate = perf_metrics['attestation_hit_percentage']
                        if hit_rate is not None and hit_rate < 95:
                            score -= (95 - hit_rate) * 2
        
        return max(0, score)

    def _get_ethereum_containers(self, ssh_target: str) -> List[str]:
        """Get list of Ethereum-related containers on the node."""
        try:
            cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} 'docker ps --format \"{{{{.Names}}}}\" | grep -E \"(consensus|execution|validator|beacon|nimbus|lighthouse|teku|prysm|lodestar|geth|nethermind|besu|reth|erigon|charon|mev)\"'"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
            
            if result.returncode == 0:
                return [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]
            return []
            
        except Exception:
            return []

    def _analyze_container_logs(self, ssh_target: str, container: str, hours: int) -> Dict[str, Any]:
        """Analyze logs from a specific container using AI pattern matching."""
        try:
            # Get logs from the specified time period
            since_time = datetime.now() - timedelta(hours=hours)
            since_str = since_time.strftime('%Y-%m-%dT%H:%M:%S')
            
            cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {ssh_target} 'docker logs {container} --since {since_str} 2>&1'"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                return {'error': f'Failed to get logs for {container}'}
            
            log_lines = result.stdout.split('\n')
            return self._perform_ai_analysis(log_lines, container)
            
        except Exception as e:
            return {'error': f'Container analysis failed: {str(e)}'}

    def _perform_ai_analysis(self, log_lines: List[str], container: str) -> Dict[str, Any]:
        """Perform AI-powered analysis on log lines."""
        pattern_matches = defaultdict(int)
        severity_score = 0
        timestamps = []
        error_patterns = []
        
        # Pattern matching with frequency analysis
        for line in log_lines:
            # Extract timestamp if available
            timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2}[\s T]\d{2}:\d{2}:\d{2})', line)
            if timestamp_match:
                try:
                    timestamps.append(datetime.fromisoformat(timestamp_match.group(1).replace(' ', 'T')))
                except:
                    pass
            
            # Check against all patterns
            for category, patterns in self.log_patterns.items():
                for pattern in patterns:
                    if re.search(pattern, line, re.IGNORECASE):
                        pattern_matches[category] += 1
                        severity_score += self.severity_weights.get(category, 0)
                        
                        # Collect error patterns for detailed analysis
                        if 'failed' in category or 'issues' in category:
                            error_patterns.append({
                                'category': category,
                                'line': line.strip()[:200],  # Truncate long lines
                                'pattern': pattern
                            })
        
        # Time-based analysis
        time_analysis = self._analyze_temporal_patterns(timestamps, pattern_matches)
        
        # Anomaly detection
        anomalies = self._detect_anomalies(pattern_matches, log_lines)
        
        return {
            'container': container,
            'total_log_lines': len(log_lines),
            'pattern_matches': dict(pattern_matches),
            'severity_score': severity_score,
            'error_patterns': error_patterns[-10:],  # Last 10 errors
            'time_analysis': time_analysis,
            'anomalies': anomalies,
            'health_indicators': self._calculate_health_indicators(pattern_matches)
        }

    def _analyze_temporal_patterns(self, timestamps: List[datetime], pattern_matches: Dict[str, int]) -> Dict[str, Any]:
        """Analyze temporal patterns in the logs."""
        if not timestamps:
            return {'error': 'No timestamps found in logs'}
        
        timestamps.sort()
        
        # Calculate event frequency
        total_time = (timestamps[-1] - timestamps[0]).total_seconds() / 3600  # hours
        event_rate = len(timestamps) / max(total_time, 0.1)  # events per hour
        
        # Find gaps in logging (potential issues)
        gaps = []
        for i in range(1, len(timestamps)):
            gap = (timestamps[i] - timestamps[i-1]).total_seconds() / 60  # minutes
            if gap > 10:  # Gap longer than 10 minutes
                gaps.append({
                    'start': timestamps[i-1].isoformat(),
                    'end': timestamps[i].isoformat(),
                    'duration_minutes': round(gap, 1)
                })
        
        return {
            'first_log': timestamps[0].isoformat() if timestamps else None,
            'last_log': timestamps[-1].isoformat() if timestamps else None,
            'total_events': len(timestamps),
            'event_rate_per_hour': round(event_rate, 2),
            'logging_gaps': gaps[:5]  # Top 5 gaps
        }

    def _detect_anomalies(self, pattern_matches: Dict[str, int], log_lines: List[str]) -> List[Dict[str, Any]]:
        """Detect anomalies using simple statistical analysis."""
        anomalies = []
        
        # Check for unusual error rates
        total_logs = len(log_lines)
        if total_logs > 0:
            error_categories = ['attestation_failed', 'block_proposal_failed', 'sync_issues', 'peer_issues']
            
            for category in error_categories:
                error_count = pattern_matches.get(category, 0)
                error_rate = (error_count / total_logs) * 100
                
                # Define thresholds for anomalies
                thresholds = {
                    'attestation_failed': 5.0,  # 5% error rate is concerning
                    'block_proposal_failed': 2.0,  # 2% block proposal failure is high
                    'sync_issues': 10.0,  # 10% sync issues
                    'peer_issues': 15.0   # 15% peer issues
                }
                
                if error_rate > thresholds.get(category, 5.0):
                    anomalies.append({
                        'type': 'high_error_rate',
                        'category': category,
                        'error_rate_percent': round(error_rate, 2),
                        'error_count': error_count,
                        'severity': 'high' if error_rate > thresholds[category] * 2 else 'medium'
                    })
        
        # Check for repeated error patterns
        error_lines = [line for line in log_lines if any(keyword in line.lower() for keyword in ['error', 'failed', 'timeout', 'exception'])]
        if error_lines:
            error_counter = Counter(error_lines)
            repeated_errors = [(error, count) for error, count in error_counter.most_common(5) if count > 3]
            
            for error, count in repeated_errors:
                anomalies.append({
                    'type': 'repeated_error',
                    'error_message': error[:100],  # Truncate
                    'occurrences': count,
                    'severity': 'high' if count > 10 else 'medium'
                })
        
        return anomalies

    def _calculate_health_indicators(self, pattern_matches: Dict[str, int]) -> Dict[str, Any]:
        """Calculate health indicators based on pattern matches."""
        success_count = pattern_matches.get('attestation_success', 0) + pattern_matches.get('block_proposal', 0)
        failure_count = pattern_matches.get('attestation_failed', 0) + pattern_matches.get('block_proposal_failed', 0)
        
        total_operations = success_count + failure_count
        success_rate = (success_count / total_operations * 100) if total_operations > 0 else 0
        
        return {
            'success_operations': success_count,
            'failed_operations': failure_count,
            'success_rate_percent': round(success_rate, 2),
            'sync_stability': 'stable' if pattern_matches.get('sync_issues', 0) < 5 else 'unstable',
            'peer_connectivity': 'good' if pattern_matches.get('peer_issues', 0) < 3 else 'poor',
            'resource_health': 'healthy' if pattern_matches.get('memory_issues', 0) + pattern_matches.get('disk_issues', 0) < 2 else 'concerning'
        }

    def _generate_alerts(self, analysis: Dict[str, Any]) -> List[Dict[str, str]]:
        """Generate alerts based on analysis results."""
        alerts = []
        
        # Overall health check
        if analysis['overall_health_score'] < 50:
            alerts.append({
                'level': 'critical',
                'message': f"Overall health score is low: {analysis['overall_health_score']}/100",
                'recommendation': 'Immediate investigation required'
            })
        elif analysis['overall_health_score'] < 75:
            alerts.append({
                'level': 'warning',
                'message': f"Health score below optimal: {analysis['overall_health_score']}/100",
                'recommendation': 'Monitor closely and consider improvements'
            })
        
        # Container-specific alerts
        for container, container_analysis in analysis['container_analyses'].items():
            if isinstance(container_analysis, dict) and 'anomalies' in container_analysis:
                for anomaly in container_analysis['anomalies']:
                    if anomaly.get('severity') == 'high':
                        alerts.append({
                            'level': 'critical',
                            'message': f"{container}: {anomaly.get('type', 'Unknown anomaly')}",
                            'recommendation': f"Check {container} logs immediately"
                        })
        
        return alerts

    def _generate_recommendations(self, analysis: Dict[str, Any]) -> List[str]:
        """Generate actionable recommendations based on analysis."""
        recommendations = []
        
        # Analyze common issues across containers
        all_patterns = defaultdict(int)
        for container_analysis in analysis['container_analyses'].values():
            if isinstance(container_analysis, dict) and 'pattern_matches' in container_analysis:
                for pattern, count in container_analysis['pattern_matches'].items():
                    all_patterns[pattern] += count
        
        # Generate recommendations based on patterns
        if all_patterns.get('sync_issues', 0) > 10:
            recommendations.append("Consider checking network connectivity and peer connections")
        
        if all_patterns.get('memory_issues', 0) > 0:
            recommendations.append("Monitor memory usage and consider increasing allocated memory")
        
        if all_patterns.get('disk_issues', 0) > 0:
            recommendations.append("Check disk space and consider cleanup or expansion")
        
        if all_patterns.get('peer_issues', 0) > 5:
            recommendations.append("Review firewall settings and network configuration")
        
        if analysis['overall_health_score'] < 80:
            recommendations.append("Schedule maintenance window to address accumulated issues")
        
        return recommendations

    def _generate_performance_insights(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Generate performance insights using AI analysis."""
        insights = {
            'efficiency_trend': 'stable',
            'resource_utilization': 'normal',
            'network_performance': 'good',
            'predicted_issues': []
        }
        
        # Analyze efficiency patterns
        total_success = 0
        total_failures = 0
        
        for container_analysis in analysis['container_analyses'].values():
            if isinstance(container_analysis, dict) and 'health_indicators' in container_analysis:
                indicators = container_analysis['health_indicators']
                total_success += indicators.get('success_operations', 0)
                total_failures += indicators.get('failed_operations', 0)
        
        if total_success + total_failures > 0:
            overall_success_rate = (total_success / (total_success + total_failures)) * 100
            if overall_success_rate > 95:
                insights['efficiency_trend'] = 'excellent'
            elif overall_success_rate > 85:
                insights['efficiency_trend'] = 'good'
            elif overall_success_rate > 70:
                insights['efficiency_trend'] = 'declining'
            else:
                insights['efficiency_trend'] = 'poor'
                insights['predicted_issues'].append('Performance degradation detected')
        
        return insights


def analyze_validator_performance_ai(node_name: str = None, hours: int = 24) -> Dict[str, Any]:
    """Main function to perform AI-powered validator performance analysis."""
    analyzer = ValidatorLogAnalyzer()
    
    if node_name:
        # Analyze specific node
        return analyzer.analyze_node_logs(node_name, hours)
    else:
        # Analyze all nodes
        try:
            with open(get_config_path(), 'r') as f:
                config = yaml.safe_load(f)
            
            results = {}
            for node in config.get('nodes', []):
                node_name = node.get('name')
                if node_name and node.get('stack') != 'disabled':
                    results[node_name] = analyzer.analyze_node_logs(node_name, hours)
            
            return results
            
        except Exception as e:
            return {'error': f'Multi-node analysis failed: {str(e)}'}

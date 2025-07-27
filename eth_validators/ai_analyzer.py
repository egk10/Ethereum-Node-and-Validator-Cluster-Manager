"""
AI-powered log analyzer for Ethereum validators.
Uses machine learning algorithms to analyze container logs and detect patterns,
anomalies, and performance issues automatically.
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

CONFIG_PATH = Path(__file__).parent / 'config.yaml'

class ValidatorLogAnalyzer:
    """AI-powered analyzer for validator and consensus client logs."""
    
    def __init__(self, config=None):
        self.config = config or {}
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
            with open(CONFIG_PATH, 'r') as f:
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
                'performance_insights': {}
            }
            
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
                analysis_results['overall_health_score'] = round(health_score, 1)
            
            # Generate insights and recommendations
            analysis_results['alerts'] = self._generate_alerts(analysis_results)
            analysis_results['recommendations'] = self._generate_recommendations(analysis_results)
            analysis_results['performance_insights'] = self._generate_performance_insights(analysis_results)
            
            return analysis_results
            
        except Exception as e:
            return {'error': f'Analysis failed: {str(e)}'}

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
            with open(CONFIG_PATH, 'r') as f:
                config = yaml.safe_load(f)
            
            results = {}
            for node in config.get('nodes', []):
                node_name = node.get('name')
                if node_name and node.get('stack') != 'disabled':
                    results[node_name] = analyzer.analyze_node_logs(node_name, hours)
            
            return results
            
        except Exception as e:
            return {'error': f'Multi-node analysis failed: {str(e)}'}

    # Additional methods required by CLI integration
    def analyze_node_performance(self, node_name: str, hours: int = 24, container_filter: str = None, min_severity: str = 'INFO') -> Dict[str, Any]:
        """Analyze node performance with comprehensive AI analysis."""
        try:
            # Get node configuration
            node_cfg = self._get_node_config(node_name)
            if not node_cfg:
                return {'error': f'Node {node_name} not found in configuration'}
            
            # Perform basic log analysis
            basic_analysis = self.analyze_node_logs(node_name, hours)
            
            # Add AI-specific enhancements
            enhanced_analysis = {
                'node_name': node_name,
                'analysis_period_hours': hours,
                'timestamp': datetime.now().isoformat(),
                'basic_analysis': basic_analysis,
                'health_score': self._calculate_comprehensive_health_score(basic_analysis),
                'anomalies': self._detect_comprehensive_anomalies(basic_analysis),
                'error_patterns': self._analyze_error_patterns(basic_analysis),
                'performance_insights': self._generate_performance_insights(basic_analysis),
                'recommendations': self._generate_recommendations(basic_analysis)
            }
            
            return enhanced_analysis
            
        except Exception as e:
            return {'error': f'Analysis failed: {str(e)}'}

    def calculate_health_score(self, node_name: str, hours: int = 24) -> Dict[str, Any]:
        """Calculate comprehensive health score for a node."""
        try:
            analysis = self.analyze_node_logs(node_name, hours)
            health_data = self._calculate_health_indicators(analysis.get('pattern_matches', {}))
            
            # Calculate overall score
            overall_score = health_data.get('overall_health_score', 0)
            
            # Determine primary concern
            primary_concern = 'None'
            if overall_score < 70:
                pattern_matches = analysis.get('pattern_matches', {})
                error_count = sum(pattern_matches.get(key, 0) for key in pattern_matches if 'error' in key or 'failed' in key)
                if error_count > 0:
                    primary_concern = f'{error_count} errors detected'
                else:
                    primary_concern = 'Performance degradation'
            
            return {
                'overall_score': overall_score,
                'anomalies': self._detect_anomalies(analysis.get('pattern_matches', {}), analysis.get('recent_logs', [])),
                'error_patterns': {'total_errors': sum(analysis.get('pattern_matches', {}).get(key, 0) for key in analysis.get('pattern_matches', {}) if 'error' in key)},
                'warning_patterns': {'total_warnings': sum(analysis.get('pattern_matches', {}).get(key, 0) for key in analysis.get('pattern_matches', {}) if 'warning' in key)},
                'primary_concern': primary_concern
            }
            
        except Exception as e:
            return {'overall_score': 0, 'error': str(e), 'primary_concern': 'Analysis failed'}

    def detect_temporal_patterns(self, node_name: str, hours: int = 24, pattern_type: str = 'all') -> Dict[str, Any]:
        """Detect temporal patterns in logs."""
        try:
            analysis = self.analyze_node_logs(node_name, hours)
            
            # Extract temporal data
            timestamps = analysis.get('timestamps', [])
            pattern_matches = analysis.get('pattern_matches', {})
            
            temporal_analysis = self._analyze_temporal_patterns(timestamps, pattern_matches)
            
            # Filter by pattern type if specified
            if pattern_type != 'all':
                filtered_patterns = {}
                for key, value in temporal_analysis.items():
                    if pattern_type.lower() in key.lower():
                        filtered_patterns[key] = value
                temporal_analysis = filtered_patterns
            
            return {
                'temporal_patterns': [
                    {
                        'description': f'Pattern detected in {key}',
                        'frequency': f'{value} occurrences',
                        'confidence': min(100, (value / hours) * 10)  # Simple confidence calculation
                    }
                    for key, value in temporal_analysis.items() if value > 0
                ],
                'recurring_issues': [
                    {
                        'issue_type': key,
                        'count': value,
                        'impact': 'High' if value > hours else 'Medium' if value > hours/2 else 'Low'
                    }
                    for key, value in pattern_matches.items() if 'error' in key or 'failed' in key
                ],
                'performance_patterns': temporal_analysis
            }
            
        except Exception as e:
            return {'error': str(e)}

    def generate_recommendations(self, node_name: str, focus_area: str = 'performance', hours: int = 48) -> Dict[str, Any]:
        """Generate AI-powered recommendations."""
        try:
            analysis = self.analyze_node_logs(node_name, hours)
            pattern_matches = analysis.get('pattern_matches', {})
            
            priority_recommendations = []
            general_recommendations = []
            config_suggestions = []
            
            # Analyze based on focus area
            if focus_area in ['performance', 'all']:
                # Performance recommendations
                success_rate = self._calculate_success_rate(pattern_matches)
                if success_rate < 95:
                    priority_recommendations.append({
                        'title': 'Low Attestation Success Rate',
                        'description': f'Current success rate: {success_rate:.1f}%',
                        'action': 'Check network connectivity and beacon node sync status'
                    })
                
                if pattern_matches.get('sync_issues', 0) > 0:
                    priority_recommendations.append({
                        'title': 'Sync Issues Detected',
                        'description': 'Node experiencing synchronization problems',
                        'action': 'Restart consensus client and check peer connections'
                    })
            
            if focus_area in ['reliability', 'all']:
                # Reliability recommendations
                error_count = sum(pattern_matches.get(key, 0) for key in pattern_matches if 'error' in key)
                if error_count > hours:  # More than 1 error per hour
                    priority_recommendations.append({
                        'title': 'High Error Rate',
                        'description': f'{error_count} errors in {hours} hours',
                        'action': 'Review error logs and consider client update'
                    })
            
            # General recommendations
            general_recommendations.extend(self._generate_recommendations(analysis))
            
            # Configuration suggestions
            if pattern_matches.get('memory_warnings', 0) > 0:
                config_suggestions.append('Consider increasing memory allocation for containers')
            if pattern_matches.get('peer_issues', 0) > 0:
                config_suggestions.append('Review firewall and port configuration')
            
            return {
                'priority': priority_recommendations,
                'general': [{'title': rec, 'description': ''} for rec in general_recommendations],
                'configuration': config_suggestions
            }
            
        except Exception as e:
            return {'error': str(e)}

    def _get_node_config(self, node_name: str) -> Dict[str, Any]:
        """Get node configuration from config."""
        if not self.config:
            return None
        
        nodes = self.config.get('nodes', [])
        for node in nodes:
            if node.get('name') == node_name or node.get('tailscale_domain') == node_name:
                return node
        return None

    def _calculate_comprehensive_health_score(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate comprehensive health score."""
        return self._calculate_health_indicators(analysis.get('pattern_matches', {}))

    def _detect_comprehensive_anomalies(self, analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Detect comprehensive anomalies."""
        return self._detect_anomalies(analysis.get('pattern_matches', {}), analysis.get('recent_logs', []))

    def _analyze_error_patterns(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze error patterns in detail."""
        pattern_matches = analysis.get('pattern_matches', {})
        error_patterns = {}
        total_errors = 0
        
        for key, count in pattern_matches.items():
            if 'error' in key or 'failed' in key:
                error_patterns[key] = count
                total_errors += count
        
        return {
            'total_errors': total_errors,
            'patterns': error_patterns
        }

    def _calculate_success_rate(self, pattern_matches: Dict[str, int]) -> float:
        """Calculate overall success rate."""
        success = pattern_matches.get('attestation_success', 0)
        failed = pattern_matches.get('attestation_failed', 0)
        total = success + failed
        
        if total == 0:
            return 100.0
        
        return (success / total) * 100

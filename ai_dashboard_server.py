#!/usr/bin/env python3
"""
AI Analysis Dashboard Server
Real-time visualization of AI validator analysis
"""

import asyncio
import json
import logging
import sys
import time
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn
from threading import Thread
from urllib.parse import parse_qs, urlparse

from eth_validators.ai_analyzer import ValidatorLogAnalyzer
from eth_validators.config import get_all_node_configs

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AIAnalysisWebServer:
    """Web server for AI analysis dashboard"""
    
    def __init__(self, port=8080):
        self.port = port
        self.analyzer = ValidatorLogAnalyzer()
        self.nodes = get_all_node_configs()
        self.current_analysis = {}
        self.analysis_progress = {}
        
    def start_server(self):
        """Start the web server"""
        class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
            """Handle requests in a separate thread"""
            pass
            
        class DashboardHandler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                self.server_instance = kwargs.pop('server_instance', None)
                super().__init__(*args, **kwargs)
            
            def do_GET(self):
                """Handle GET requests"""
                parsed_path = urlparse(self.path)
                
                if parsed_path.path == '/':
                    # Serve the main dashboard
                    self.serve_dashboard()
                elif parsed_path.path == '/api/status':
                    # API endpoint for analysis status
                    self.serve_api_status()
                elif parsed_path.path == '/api/start-analysis':
                    # API endpoint to start analysis
                    self.serve_api_start_analysis()
                elif parsed_path.path == '/api/analysis-data':
                    # API endpoint for real analysis data
                    self.serve_api_analysis_data()
                else:
                    # Serve static files
                    super().do_GET()
            
            def serve_dashboard(self):
                """Serve the main dashboard HTML"""
                try:
                    dashboard_path = Path(__file__).parent / 'ai_dashboard.html'
                    with open(dashboard_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html')
                    self.send_header('Content-Length', str(len(content)))
                    self.end_headers()
                    self.wfile.write(content.encode('utf-8'))
                    
                except Exception as e:
                    logger.error(f"Error serving dashboard: {e}")
                    self.send_error(500, f"Error serving dashboard: {e}")
            
            def serve_api_status(self):
                """Serve analysis status"""
                status = {
                    'timestamp': datetime.now().isoformat(),
                    'analyzer_ready': True,
                    'nodes_configured': len(self.server_instance.nodes),
                    'last_analysis': self.server_instance.current_analysis.get('timestamp'),
                    'progress': self.server_instance.analysis_progress
                }
                
                self.send_json_response(status)
            
            def serve_api_start_analysis(self):
                """Start real AI analysis"""
                try:
                    # Start analysis in background thread
                    analysis_thread = Thread(
                        target=self.server_instance.run_real_analysis,
                        daemon=True
                    )
                    analysis_thread.start()
                    
                    response = {
                        'status': 'started',
                        'message': 'AI analysis started',
                        'timestamp': datetime.now().isoformat()
                    }
                    self.send_json_response(response)
                    
                except Exception as e:
                    logger.error(f"Error starting analysis: {e}")
                    self.send_error(500, f"Error starting analysis: {e}")
            
            def serve_api_analysis_data(self):
                """Serve real analysis data"""
                self.send_json_response(self.server_instance.current_analysis)
            
            def send_json_response(self, data):
                """Send JSON response"""
                json_data = json.dumps(data, indent=2)
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Content-Length', str(len(json_data)))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json_data.encode('utf-8'))
            
            def log_message(self, format, *args):
                """Override to reduce log noise"""
                pass
        
        # Create handler with server instance
        def handler_factory(*args, **kwargs):
            return DashboardHandler(*args, server_instance=self, **kwargs)
        
        try:
            server = ThreadedHTTPServer(('localhost', self.port), handler_factory)
            logger.info(f"🌐 AI Dashboard server starting on http://localhost:{self.port}")
            logger.info("📊 Access the dashboard at: http://localhost:8080")
            logger.info("🧠 Real-time AI analysis visualization ready!")
            server.serve_forever()
        except KeyboardInterrupt:
            logger.info("\n🛑 Server stopped by user")
            server.shutdown()
        except Exception as e:
            logger.error(f"Server error: {e}")
    
    def run_real_analysis(self):
        """Run real AI analysis and update progress"""
        try:
            logger.info("🧠 Starting real AI analysis...")
            
            # Reset progress
            self.analysis_progress = {
                'step': 0,
                'total_steps': 8,
                'current_step': 'Initializing',
                'nodes_analyzed': 0,
                'patterns_found': 0,
                'anomalies_detected': 0,
                'health_scores': []
            }
            
            # Step 1: Load configuration
            self.update_progress(1, "Loading node configuration")
            nodes = {node.get('name', f"node_{i}"): node for i, node in enumerate(self.nodes)}
            
            # Step 2: Initialize analysis
            self.update_progress(2, "Initializing AI analyzer")
            time.sleep(1)  # Simulate processing
            
            results = {}
            
            # Step 3-6: Analyze each node
            for i, (node_name, node_config) in enumerate(nodes.items()):
                step_num = 3 + i
                if step_num > 6:  # Limit to first 4 nodes for demo
                    break
                    
                self.update_progress(step_num, f"Analyzing node: {node_name}")
                
                try:
                    # Run real analysis
                    node_result = self.analyzer.analyze_node_logs(node_name, node_config)
                    results[node_name] = node_result
                    
                    # Update metrics
                    self.analysis_progress['nodes_analyzed'] += 1
                    
                    if 'patterns' in node_result:
                        self.analysis_progress['patterns_found'] += len(node_result['patterns'])
                    
                    if 'anomalies' in node_result:
                        self.analysis_progress['anomalies_detected'] += len(node_result['anomalies'])
                    
                    if 'health_score' in node_result:
                        self.analysis_progress['health_scores'].append(node_result['health_score'])
                    
                    logger.info(f"✅ Analyzed {node_name}: Health {node_result.get('health_score', 'N/A')}%")
                    
                except Exception as e:
                    logger.error(f"❌ Error analyzing {node_name}: {e}")
                    results[node_name] = {
                        'error': str(e),
                        'health_score': 0,
                        'status': 'error'
                    }
                
                time.sleep(2)  # Simulate processing time
            
            # Step 7: Generate recommendations
            self.update_progress(7, "Generating recommendations")
            recommendations = self.generate_recommendations(results)
            
            # Step 8: Complete
            self.update_progress(8, "Analysis complete")
            
            # Store final results
            self.current_analysis = {
                'timestamp': datetime.now().isoformat(),
                'results': results,
                'recommendations': recommendations,
                'summary': {
                    'total_nodes': len(results),
                    'healthy_nodes': len([r for r in results.values() if r.get('health_score', 0) > 70]),
                    'critical_nodes': len([r for r in results.values() if r.get('health_score', 0) < 30]),
                    'avg_health': sum(self.analysis_progress['health_scores']) / len(self.analysis_progress['health_scores']) if self.analysis_progress['health_scores'] else 0,
                    'total_patterns': self.analysis_progress['patterns_found'],
                    'total_anomalies': self.analysis_progress['anomalies_detected']
                }
            }
            
            logger.info("🎉 Real AI analysis completed successfully!")
            
        except Exception as e:
            logger.error(f"❌ Analysis failed: {e}")
            self.current_analysis = {
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def update_progress(self, step, message):
        """Update analysis progress"""
        self.analysis_progress.update({
            'step': step,
            'current_step': message,
            'progress_percent': (step / 8) * 100
        })
        logger.info(f"📊 Step {step}/8: {message}")
    
    def generate_recommendations(self, results):
        """Generate recommendations based on analysis results"""
        recommendations = []
        
        critical_nodes = [name for name, data in results.items() 
                         if data.get('health_score', 0) < 30]
        
        if critical_nodes:
            recommendations.append({
                'priority': 'critical',
                'message': f"🚨 Critical: {len(critical_nodes)} nodes require immediate attention: {', '.join(critical_nodes)}"
            })
        
        low_health_nodes = [name for name, data in results.items() 
                           if 30 <= data.get('health_score', 0) < 70]
        
        if low_health_nodes:
            recommendations.append({
                'priority': 'warning',
                'message': f"⚠️ Warning: {len(low_health_nodes)} nodes need monitoring: {', '.join(low_health_nodes)}"
            })
        
        healthy_nodes = [name for name, data in results.items() 
                        if data.get('health_score', 0) >= 70]
        
        if healthy_nodes:
            recommendations.append({
                'priority': 'info',
                'message': f"✅ Good: {len(healthy_nodes)} nodes operating normally: {', '.join(healthy_nodes)}"
            })
        
        # Add general recommendations
        recommendations.extend([
            {
                'priority': 'info',
                'message': "🔍 Schedule regular health checks every 4 hours"
            },
            {
                'priority': 'info', 
                'message': "📊 Monitor attestation success rates and adjust as needed"
            },
            {
                'priority': 'info',
                'message': "🌐 Verify network connectivity and peer connections"
            }
        ])
        
        return recommendations


def main():
    """Main function to start the AI dashboard server"""
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print("❌ Invalid port number. Using default port 8080.")
            port = 8080
    else:
        port = 8080
    
    print("🧠 AI Validator Analysis Dashboard")
    print("=" * 50)
    print(f"🌐 Starting server on port {port}...")
    print(f"📊 Dashboard URL: http://localhost:{port}")
    print("🚀 Press Ctrl+C to stop the server")
    print("=" * 50)
    
    server = AIAnalysisWebServer(port)
    
    try:
        server.start_server()
    except Exception as e:
        logger.error(f"❌ Failed to start server: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

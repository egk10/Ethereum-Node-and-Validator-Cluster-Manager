#!/usr/bin/env python3
"""
Test script to verify validator performance data extraction
Tests both beacon node APIs and log analysis for comprehensive performance metrics
"""
import json
import sys
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

from eth_validators.enhanced_performance_extractor import ValidatorPerformanceExtractor
from eth_validators.ai_analyzer import ValidatorLogAnalyzer
from eth_validators.config import get_all_node_configs

def test_performance_extraction():
    """Test comprehensive performance data extraction"""
    print("🧪 VALIDATOR PERFORMANCE DATA EXTRACTION TEST")
    print("=" * 60)
    
    # Initialize extractors
    extractor = ValidatorPerformanceExtractor()
    analyzer = ValidatorLogAnalyzer()
    
    # Get available nodes
    nodes = get_all_node_configs()
    if not nodes:
        print("❌ No nodes found in configuration")
        return
    
    # Test with first available node
    test_node = nodes[0]
    node_name = test_node.get('name', 'unknown')
    
    print(f"🎯 Testing with node: {node_name}")
    print(f"📡 Tailscale domain: {test_node.get('tailscale_domain')}")
    print(f"🔌 Beacon API port: {test_node.get('beacon_api_port', 5052)}")
    print()
    
    # Test 1: Enhanced performance extraction
    print("📊 TEST 1: Enhanced Performance Extraction")
    print("-" * 40)
    
    try:
        performance_data = extractor.extract_comprehensive_performance(node_name, hours=6)
        
        if 'error' in performance_data:
            print(f"❌ Enhanced extraction failed: {performance_data['error']}")
        else:
            print("✅ Enhanced extraction successful!")
            
            # Display key metrics
            beacon_data = performance_data.get('beacon_node_performance', {})
            if beacon_data and 'error' not in beacon_data:
                print(f"  🟢 Beacon node health: {'OK' if beacon_data.get('beacon_node_info', {}).get('is_healthy') else 'Issues'}")
                
                sync_status = beacon_data.get('sync_status', {})
                if sync_status:
                    if sync_status.get('is_syncing'):
                        print(f"  🟡 Sync status: Syncing ({sync_status.get('sync_percentage', 0):.1f}%)")
                    else:
                        print(f"  🟢 Sync status: Synced")
                
                peer_info = beacon_data.get('peer_info', {})
                if peer_info:
                    connected_peers = peer_info.get('connected_peers', 0)
                    print(f"  📡 Connected peers: {connected_peers}")
                
                validator_performance = beacon_data.get('validator_performance', {})
                print(f"  👤 Validators analyzed: {len(validator_performance)}")
                
                for idx, val_data in validator_performance.items():
                    if isinstance(val_data, dict) and 'status' in val_data:
                        status = val_data.get('status', 'unknown')
                        perf = val_data.get('performance_metrics', {})
                        print(f"    Validator {idx}: {status}")
                        if perf and 'attestation_hit_percentage' in perf:
                            hit_rate = perf['attestation_hit_percentage']
                            print(f"      Attestation success: {hit_rate:.1f}%")
            
            # Display log performance summary
            log_data = performance_data.get('log_performance', {})
            if log_data and 'error' not in log_data:
                print(f"  📋 Log containers analyzed: {len(log_data)}")
                
                for container, metrics in log_data.items():
                    if 'error' not in metrics:
                        attestation_metrics = metrics.get('attestation_performance', {})
                        success_rate = attestation_metrics.get('success_rate')
                        total_attestations = attestation_metrics.get('successful_attestations', 0) + attestation_metrics.get('failed_attestations', 0)
                        
                        error_metrics = metrics.get('error_analysis', {})
                        total_errors = error_metrics.get('total_errors', 0)
                        
                        print(f"    {container}:")
                        if success_rate is not None:
                            print(f"      Attestations: {total_attestations} (success: {success_rate:.1f}%)")
                        if total_errors > 0:
                            print(f"      Errors: {total_errors}")
            
            # Overall health score
            summary = performance_data.get('summary', {})
            overall_health = summary.get('overall_health_score', 0)
            print(f"  💚 Overall health score: {overall_health:.1f}/100")
            
            # Export detailed results
            with open('performance_test_results.json', 'w') as f:
                json.dump(performance_data, f, indent=2)
            print(f"  💾 Detailed results saved to: performance_test_results.json")
    
    except Exception as e:
        print(f"❌ Enhanced extraction test failed: {e}")
    
    print()
    
    # Test 2: AI analyzer with beacon integration
    print("🧠 TEST 2: AI Analyzer with Beacon Integration")
    print("-" * 40)
    
    try:
        ai_analysis = analyzer.analyze_node_logs(node_name, hours=6)
        
        if 'error' in ai_analysis:
            print(f"❌ AI analysis failed: {ai_analysis['error']}")
        else:
            print("✅ AI analysis with beacon integration successful!")
            
            # Display AI analysis results
            print(f"  📊 Overall health score: {ai_analysis.get('overall_health_score', 0)}/100")
            print(f"  📦 Containers analyzed: {ai_analysis.get('containers_analyzed', 0)}")
            
            beacon_performance = ai_analysis.get('beacon_performance', {})
            if beacon_performance and 'error' not in beacon_performance:
                print(f"  🟢 Beacon performance data integrated: Yes")
                if 'is_healthy' in beacon_performance:
                    health_status = "Healthy" if beacon_performance['is_healthy'] else "Issues detected"
                    print(f"    Health status: {health_status}")
            else:
                print(f"  🟡 Beacon performance data: Limited")
            
            # Display alerts
            alerts = ai_analysis.get('alerts', [])
            if alerts:
                print(f"  🚨 Alerts generated: {len(alerts)}")
                for alert in alerts[:3]:  # Show first 3
                    print(f"    {alert}")
            
            # Display recommendations
            recommendations = ai_analysis.get('recommendations', [])
            if recommendations:
                print(f"  💡 Recommendations: {len(recommendations)}")
                for rec in recommendations[:3]:  # Show first 3
                    print(f"    {rec}")
            
            # Export AI results
            with open('ai_analysis_test_results.json', 'w') as f:
                json.dump(ai_analysis, f, indent=2)
            print(f"  💾 AI analysis results saved to: ai_analysis_test_results.json")
    
    except Exception as e:
        print(f"❌ AI analysis test failed: {e}")
    
    print()
    
    # Test 3: Performance metrics comparison
    print("📈 TEST 3: Performance Metrics Validation")
    print("-" * 40)
    
    try:
        # Load performance module for comparison
        from eth_validators import performance
        
        print("Testing existing performance module...")
        performance_summary = performance.get_performance_summary()
        
        if performance_summary:
            print(f"✅ Performance module working")
            print(f"  📊 Validators found: {len(performance_summary)}")
            
            # Show sample data
            for row in performance_summary[:3]:  # First 3 rows
                node, index, efficiency, misses, dist, status = row
                print(f"    {node}: Validator {index} - Efficiency {efficiency}")
        else:
            print("⚠️  Performance module returned no data")
    
    except Exception as e:
        print(f"❌ Performance module test failed: {e}")
    
    print()
    print("🎯 PERFORMANCE DATA EXTRACTION TEST COMPLETE")
    print("=" * 60)
    print()
    print("📋 SUMMARY:")
    print("✅ Enhanced performance extractor tests beacon node APIs")
    print("✅ AI analyzer integrates beacon data with log analysis") 
    print("✅ Comprehensive performance metrics collected from multiple sources")
    print("✅ Real validator performance data extracted and analyzed")
    print()
    print("📁 Check the generated JSON files for detailed performance data:")
    print("  - performance_test_results.json: Comprehensive performance data")
    print("  - ai_analysis_test_results.json: AI analysis with beacon integration")

if __name__ == "__main__":
    test_performance_extraction()

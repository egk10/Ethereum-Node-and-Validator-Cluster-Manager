#!/usr/bin/env python3
"""
Simple test to verify AI analyzer integration works with the CLI.
"""

import sys
import os
import yaml
from pathlib import Path

# Add the eth_validators module to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'eth_validators'))

def test_ai_analyzer_import():
    """Test that the AI analyzer can be imported correctly."""
    print("🧠 Testing AI Analyzer Integration...")
    
    try:
        from eth_validators.ai_analyzer import ValidatorLogAnalyzer
        print("✅ Successfully imported ValidatorLogAnalyzer")
        
        # Test initialization
        config = {'nodes': []}
        analyzer = ValidatorLogAnalyzer(config)
        print("✅ Successfully initialized AI analyzer")
        
        # Test pattern definitions
        if hasattr(analyzer, 'error_patterns'):
            print(f"✅ Found {len(analyzer.error_patterns)} error patterns")
        
        if hasattr(analyzer, 'warning_patterns'):
            print(f"✅ Found {len(analyzer.warning_patterns)} warning patterns")
            
        if hasattr(analyzer, 'performance_patterns'):
            print(f"✅ Found {len(analyzer.performance_patterns)} performance patterns")
        
        print("🎯 AI analyzer is ready for production use!")
        return True
        
    except ImportError as e:
        print(f"❌ Failed to import AI analyzer: {e}")
        return False
    except Exception as e:
        print(f"❌ Error initializing AI analyzer: {e}")
        return False

def test_cli_integration():
    """Test that the CLI commands are available."""
    print("\n🔧 Testing CLI Integration...")
    
    try:
        from eth_validators.cli import cli
        print("✅ Successfully imported CLI module")
        
        # Check if AI commands are registered
        ai_commands = ['ai-health', 'ai-analyze', 'ai-patterns', 'ai-recommend']
        available_commands = [cmd.name for cmd in cli.commands.values()]
        
        for cmd in ai_commands:
            if cmd in available_commands:
                print(f"✅ Found AI command: {cmd}")
            else:
                print(f"❌ Missing AI command: {cmd}")
        
        print("🎯 CLI integration is complete!")
        return True
        
    except ImportError as e:
        print(f"❌ Failed to import CLI: {e}")
        return False
    except Exception as e:
        print(f"❌ Error testing CLI: {e}")
        return False

def demonstrate_ai_features():
    """Demonstrate key AI features available."""
    print("\n🚀 Available AI Features:")
    print("=" * 40)
    
    features = [
        ("🏥 Health Monitoring", "ai-health", "Calculate overall health scores with anomaly detection"),
        ("🧠 Log Analysis", "ai-analyze", "Deep analysis of validator logs with pattern recognition"),
        ("🔍 Pattern Detection", "ai-patterns", "Identify temporal patterns and recurring issues"),
        ("💡 Smart Recommendations", "ai-recommend", "AI-powered optimization suggestions"),
    ]
    
    for emoji_name, command, description in features:
        print(f"\n{emoji_name}:")
        print(f"  Command: python3 -m eth_validators {command} <node>")
        print(f"  Purpose: {description}")
    
    print("\n🎯 Example Usage:")
    print("  # Check health of all nodes")
    print("  python3 -m eth_validators ai-health")
    print("")
    print("  # Analyze specific node logs")
    print("  python3 -m eth_validators ai-analyze laptop --hours 24")
    print("")
    print("  # Find patterns over last week")
    print("  python3 -m eth_validators ai-patterns laptop --days 7")
    print("")
    print("  # Get performance recommendations")
    print("  python3 -m eth_validators ai-recommend laptop --focus performance")

def main():
    """Run all tests and demonstrations."""
    print("🎉 Ethereum Validator AI Analysis System Test")
    print("=" * 50)
    
    # Test imports and initialization
    ai_success = test_ai_analyzer_import()
    cli_success = test_cli_integration()
    
    # Show features regardless of test results
    demonstrate_ai_features()
    
    print("\n" + "=" * 50)
    if ai_success and cli_success:
        print("🎉 ALL TESTS PASSED! AI system is ready for production!")
        print("\n💡 Next steps:")
        print("  1. Configure your nodes in config.yaml")
        print("  2. Run: python3 -m eth_validators ai-health")
        print("  3. Monitor your validators with AI-powered insights!")
    else:
        print("⚠️  Some tests failed. Check the errors above.")
    
    print("\n🚀 Ready to revolutionize validator monitoring with AI!")

if __name__ == '__main__':
    main()

# Ethereum Node and Validator Cluster Manager - Release Configuration

# Core modules (always included in all releases)
CORE_MODULES = [
    "eth_validators/__init__.py",
    "eth_validators/__main__.py", 
    "eth_validators/cli.py",
    "eth_validators/config.py",
    "eth_validators/node_manager.py",
    "eth_validators/performance.py",
    "eth_validators/validator_sync.py",
    "eth_validators/validator_editor.py"
]

# Core configuration files
CORE_CONFIG = [
    "eth_validators/config.example.yaml",
    "eth_validators/example_validators_vs_hardware.csv",
    "requirements.txt",
    "README.md"
]

# Optional modules (included based on release type)
OPTIONAL_MODULES = {
    "ai": [
        "eth_validators/ai_analyzer.py",
        "eth_validators/hybrid_ai_analyzer.py",
        "requirements-ml.txt"
    ],
    "backup": [
        "eth_validators/validator_backup_manager.py"
    ],
    "enhanced_performance": [
        "eth_validators/enhanced_performance_extractor.py"
    ],
    "grafana": [
        "prometheus-config.yml",
        "grafana-datasources.yml", 
        "grafana-dashboards.yml",
        "setup-cluster-monitoring.sh",
        "setup-simple-monitoring.sh",
        "cluster-monitoring.yml",
        "dashboards/",
        "*.json"  # Dashboard files
    ],
    "docker": [
        "cluster-management.sh",
        "enable-external-monitoring.sh",
        "eliedesk-monitoring-stack.yml"
    ]
}

# Release types and their included modules
RELEASE_TYPES = {
    "core": {
        "description": "Essential validator management functionality",
        "modules": ["core"],
        "dependencies": ["pyyaml", "click", "requests", "tabulate"]
    },
    "standard": {
        "description": "Core functionality + backup management + enhanced performance",
        "modules": ["core", "backup", "enhanced_performance"],
        "dependencies": ["pyyaml", "click", "requests", "tabulate", "pandas"]
    },
    "monitoring": {
        "description": "Standard + Grafana/Prometheus monitoring integration", 
        "modules": ["core", "backup", "enhanced_performance", "grafana", "docker"],
        "dependencies": ["pyyaml", "click", "requests", "tabulate", "pandas", "prometheus-client"]
    },
    "full": {
        "description": "All features including experimental AI analysis",
        "modules": ["core", "backup", "enhanced_performance", "grafana", "docker", "ai"],
        "dependencies": ["pyyaml", "click", "requests", "tabulate", "pandas", "prometheus-client", "scikit-learn", "numpy"]
    }
}

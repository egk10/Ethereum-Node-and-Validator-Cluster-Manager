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

# Optional modules (kept as buckets; unified release includes all where available)
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
        "config/grafana-datasources.yml",
        "config/grafana-dashboards.yml",
        "config/prometheus-config.yml",
        "dashboards/"
    ],
    "docker": [
        "scripts/build_docker.sh"
    ]
}

# Single unified release configuration
RELEASE_TYPES = {
    "unified": {
        "description": "Unified release with core features and optional modules when present.",
        "modules": ["core", "backup", "enhanced_performance", "grafana", "docker", "ai"],
        "dependencies": [
            "pyyaml", "click", "requests", "tabulate", "pandas", "prometheus-client", "scikit-learn", "numpy"
        ]
    }
}

#!/usr/bin/env bash
set -euo pipefail

# Cleanup script for obsolete files
files=(
  ai_analysis_test_results.json
  performance_test_results.json
  hybrid_results.json
  quickstart_test_results.sh
  TEST_RESULTS_SUMMARY.md
  demo_add_node.sh
  demo_complete_system.py
  demo_new_user_workflow.sh
  demo_validator_migration.sh
  config.example.yaml
  config.sample.yaml
  INSTALL_v1.0.6.md
  GITHUB_RELEASE_GUIDE.md
  GITHUB_RELEASE_SUMMARY.md
  GITHUB_SUCCESS.md
  VALIDATOR_MIGRATION_GUIDE.md
  VALIDATOR_PERFORMANCE_CONFIRMATION.md
  TESTE_USUARIO_NOVO_RELATORIO.md
  validators_auto_discovered.csv
  eth_validators/demo_validators_discovery.csv
  eth_validators/improved_test.csv
  install.bat
)

echo "🧹 Cleaning up obsolete files..."
for f in "${files[@]}"; do
  if [[ -e $f ]]; then
    rm -v "$f"
  fi
done

echo "✅ Cleanup complete."

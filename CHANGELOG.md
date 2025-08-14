# Changelog

All notable changes to this project will be documented here.

## [1.2.0] - 2025-08-14
### Added
- **Multi-validator support**: New "Validator 2" column displays secondary validators for complex node configurations
- **Stack naming**: Validator origins now show stack context (eth-docker-vero, charon-lodestar, etc.)
- **Enhanced table structure**: Expanded from 10 to 12 columns with improved alignment and formatting
- **Dual validator detection**: Automatic identification of nodes running multiple validator clients
- **Container detection improvements**: Enhanced logic to properly distinguish consensus vs validator clients

### Fixed
- **Version detection bug**: Fixed stakewise validator clients being misidentified as consensus clients
- **Upgrade workflow**: Enhanced eth-docker upgrade commands with proper local image rebuilds
- **Container exclusion logic**: Added `_vc` pattern exclusion to prevent validator client misclassification
- **nodeset consensus version**: Resolved stuck 1.32.0→1.33.0 status issue

### Changed
- **Table layout**: Multi-validator nodes now display both primary and secondary validators clearly
- **Version reporting**: Improved accuracy for complex node configurations with multiple stacks
- **Upgrade process**: Added `docker compose build --pull` for proper local image updates

## [1.1.4] - 2025-08-12
### Fixed
- Release packaging: include `eth_validators/validator_auto_discovery.py` and `eth_validators/simple_setup.py` to prevent ModuleNotFoundError on fresh installs.
- tools/build_release: minor README header emoji fix.
### Changed
- README: remove Docker section/badge; simplify install to fresh-folder + quickstart; reduce repetition.
## [1.1.1] - 2025-08-12
### Changed
- Docs: Make Quickstart the source of truth for generating `config.yaml` (interactive prompt).
- README: Simplified install/run steps; prefer latest unified release and `quickstart`.
- Build/Release scripts: Replace manual `config.example.yaml` copy with `quickstart` guidance.
- CI Release notes: Reference `python3 -m eth_validators quickstart`.

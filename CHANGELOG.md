# Changelog

All notable changes to this project will be documented here.

## [Unreleased]
### Changed
- **BREAKING:** Replaced raw git/docker commands with `ethd update --non-interactive` during client upgrades
  - Fixes recurring file ownership issues where git ran as root instead of directory owner (egk)
  - Uses ethd's built-in owner detection and permission management
  - Increases upgrade timeout from 300s to 600s to account for ethd's additional validation checks
  - All new files created during upgrades now maintain correct egk:egk ownership
  - Eliminates need for post-upgrade permission fixes

### Added
- New validation function `_validate_ethd_exists()` to ensure ethd is available before upgrade
- New documentation: `docs/ETHD_UPDATE_INTEGRATION.md` explaining the integration and file ownership behavior

### Fixed
- File ownership conflicts during cluster upgrades (resolves recurring Permission Denied errors)
- Root-owned files being created by git operations during upgrades

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

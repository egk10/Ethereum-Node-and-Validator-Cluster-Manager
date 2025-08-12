# Changelog

All notable changes to this project will be documented here.

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

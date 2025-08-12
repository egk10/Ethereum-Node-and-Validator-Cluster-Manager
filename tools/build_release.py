#!/usr/bin/env python3
"""
Ethereum Node and Validator Cluster Manager - Release Builder
Builds a unified release zip with quickstart-based configuration guidance.
"""

import argparse
import os
import shutil
import zipfile
from pathlib import Path
from glob import glob
from release_config import CORE_MODULES, CORE_CONFIG, OPTIONAL_MODULES, RELEASE_TYPES


class ReleaseBuilder:
    def __init__(self, version: str = "1.0.0") -> None:
        self.version = version
        # Project root is the repo root (parent of tools/)
        self.project_root = Path(__file__).resolve().parent.parent
        self.build_dir = self.project_root / "tools" / "dist"

    def clean_build_dir(self) -> None:
        if self.build_dir.exists():
            shutil.rmtree(self.build_dir)
        self.build_dir.mkdir(parents=True, exist_ok=True)

    def _copy_file(self, src: Path, dst: Path) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    def copy_core_files(self, target_dir: Path) -> None:
        for rel in CORE_MODULES + CORE_CONFIG:
            src = self.project_root / rel
            if src.exists():
                self._copy_file(src, target_dir / rel)

    def copy_optional_files(self, target_dir: Path, modules: list[str]) -> None:
        for name in modules:
            if name not in OPTIONAL_MODULES:
                continue
            for rel in OPTIONAL_MODULES[name]:
                if rel.endswith("/"):
                    src_dir = (self.project_root / rel).resolve()
                    if src_dir.exists():
                        dst_dir = (target_dir / rel).resolve()
                        shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)
                elif "*" in rel:
                    for src in glob(str(self.project_root / rel)):
                        src_path = Path(src)
                        dst = target_dir / rel.replace("*", src_path.name)
                        self._copy_file(src_path, dst)
                else:
                    src = self.project_root / rel
                    if src.exists():
                        self._copy_file(src, target_dir / rel)

    def create_requirements_file(self, target_dir: Path, dependencies: list[str]) -> None:
        req = target_dir / "requirements.txt"
        req.parent.mkdir(parents=True, exist_ok=True)
        with open(req, "w") as f:
            for dep in dependencies:
                f.write(dep + "\n")

    def create_setup_script(self, target_dir: Path, release_type: str) -> None:
        content = f"""#!/bin/bash
# Ethereum Node and Validator Cluster Manager - {release_type.title()} Release v{self.version}
# Installation Script
set -e

echo "🚀 Installing Ethereum Node and Validator Cluster Manager ({release_type.title()} Release)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ Python 3 is required but not found"; exit 1
fi

echo "📦 Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

echo "📦 Installing dependencies..."
pip install -r requirements.txt

chmod +x eth_validators/*.py || true

echo "✅ Installation complete!"
echo ""
echo "🎯 Usage:"
echo "   source venv/bin/activate"
echo "   python3 -m eth_validators --help"
echo ""
echo "📋 Generate your config via: python3 -m eth_validators quickstart"
echo "💡 See README.md for detailed setup instructions"
"""
        setup_file = target_dir / "install.sh"
        with open(setup_file, "w") as f:
            f.write(content)
        os.chmod(setup_file, 0o755)

    def create_readme(self, target_dir: Path, release_type: str, description: str) -> None:
        content = f"""# Ethereum Node and Validator Cluster Manager
## {release_type.title()} Release v{self.version}

{description}

### 🚀 Quick Start

```bash
./install.sh
python3 -m eth_validators quickstart
python3 -m eth_validators --help
```

### � Configuration
- Run `python3 -m eth_validators quickstart` to generate `config.yaml` interactively.
- Edit the generated `config.yaml` as needed.
"""
        with open(target_dir / "README.md", "w") as f:
            f.write(content)

    def build_release(self, release_type: str) -> Path:
        if release_type not in RELEASE_TYPES:
            raise ValueError(f"Unknown release type: {release_type}")

        info = RELEASE_TYPES[release_type]
        name = f"ethereum-validator-manager-{release_type}-v{self.version}"
        release_dir = self.build_dir / name

        print(f"🔨 Building {release_type} release at {release_dir}...")
        release_dir.mkdir(parents=True, exist_ok=True)

        self.copy_core_files(release_dir)
        modules = [m for m in info["modules"] if m != "core"]
        self.copy_optional_files(release_dir, modules)
        self.create_requirements_file(release_dir, info["dependencies"])
        self.create_setup_script(release_dir, release_type)
        self.create_readme(release_dir, release_type, info["description"])

        zip_path = self.build_dir / f"{name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for root, _, files in os.walk(release_dir):
                for file in files:
                    p = Path(root) / file
                    z.write(p, p.relative_to(release_dir))
        print(f"✅ Created {zip_path}")
        return zip_path

    def build_all(self) -> list[Path]:
        self.clean_build_dir()
        out: list[Path] = []
        for rtype in RELEASE_TYPES.keys():
            out.append(self.build_release(rtype))
        return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Ethereum Validator Manager releases")
    parser.add_argument("--version", default="1.0.0", help="Release version")
    parser.add_argument("--type", choices=list(RELEASE_TYPES.keys()) + ["all"], default="unified",
                        help="Release type to build")
    args = parser.parse_args()

    builder = ReleaseBuilder(args.version)
    if args.type == "all":
        files = builder.build_all()
        print(f"\n🎉 Built {len(files)} release(s)")
        for f in files:
            print(f"   📦 {f}")
    else:
        path = builder.build_release(args.type)
        print(f"\n🎉 Built release: {path}")


if __name__ == "__main__":
    main()

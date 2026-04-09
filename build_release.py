# MIT License
# Build a Blender Extension release zip from the current directory.
# Usage: python3 build_release.py [--output-dir <dir>] [--dev]
#
# Reads version from blender_manifest.toml.
# Output: cats-blender-plugin-<version>.zip

import os
import sys
import zipfile
import tomllib
import argparse
from pathlib import Path

ADDON_DIR = Path(__file__).parent

EXCLUDE_DIRS = {
    '.git',
    '__pycache__',
    'tests',
    'workflows',
}

EXCLUDE_FILES = {
    'build_release.py',
    '.gitignore',
    '.gitattributes',
    '.travis.yml',
}

EXCLUDE_SUFFIXES = {
    '.pyc',
    '.pyo',
    '.swp',
    '.swo',
}


def should_include(path: Path) -> bool:
    rel = path.relative_to(ADDON_DIR)
    parts = rel.parts

    for part in parts:
        if part in EXCLUDE_DIRS:
            return False

    if path.is_file():
        if path.name in EXCLUDE_FILES:
            return False
        if path.suffix in EXCLUDE_SUFFIXES:
            return False

    return True


def collect_files() -> list[Path]:
    files = []
    for path in sorted(ADDON_DIR.rglob('*')):
        if path.is_file() and should_include(path):
            files.append(path)
    return files


def build(output_dir: Path, dev: bool):
    with open(ADDON_DIR / 'blender_manifest.toml', 'rb') as f:
        manifest = tomllib.load(f)

    version = manifest['version']
    addon_id = manifest['id']

    if dev:
        version = version + '-dev'

    zip_name = f"{addon_id}-{version}.zip"
    zip_path = output_dir / zip_name

    output_dir.mkdir(parents=True, exist_ok=True)

    files = collect_files()

    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in files:
            arcname = file_path.relative_to(ADDON_DIR)
            zf.write(file_path, arcname)
            print(f"  + {arcname}")

    size_kb = zip_path.stat().st_size / 1024
    print(f"\nBuilt: {zip_path}  ({size_kb:.1f} KB, {len(files)} files)")
    return zip_path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Build Cats Blender Plugin release zip')
    parser.add_argument('--output-dir', default='dist', help='Output directory (default: dist/)')
    parser.add_argument('--dev', action='store_true', help='Append -dev suffix to version')
    args = parser.parse_args()

    build(Path(args.output_dir), args.dev)

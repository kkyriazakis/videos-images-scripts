#!/usr/bin/env python3
"""Update metadata for a single file based on its filename.

Renamed (and typo fixed) from `update_metadata_from_filename.py`.
"""
from pathlib import Path
import subprocess
import argparse
import sys
import json


def get_exiftool():
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        import tools_config
        return getattr(tools_config, "EXIFTOOL", None)
    except Exception:
        cfg_path = root / "tools_config.json"
        if cfg_path.exists():
            return json.loads(cfg_path.read_text(encoding="utf-8")).get("exiftool")
    return None


def main():
    parser = argparse.ArgumentParser(description="Update metadata for a single file from filename")
    parser.add_argument("file", help="Path to the file to update")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    exif = get_exiftool() or "exiftool"
    cmd = [
        exif, "-overwrite_original",
        "-FileCreateDate<FileName",
        "-FileModifyDate<FileName",
        "-XMP:DateCreated<FileName",
        "-XMP:CreateDate<FileName",
        "-XMP:DateTimeOriginal<FileName",
        "-d", "%Y:%m:%d %H:%M:%S",
        str(Path(args.file))
    ]
    if args.dry_run:
        print(" ".join(cmd))
        return
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Set metadata + created date from modified date (recursively).

This is the renamed version of the previous `set_metadata_from_modified.py`.
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
    parser = argparse.ArgumentParser(description="Set metadata + created date from modified date")
    parser.add_argument("target", nargs="?", default='.', help="Target directory or file")
    parser.add_argument("--dry-run", action="store_true", help="Print the command instead of running")
    args = parser.parse_args()
    exif = get_exiftool() or "exiftool"
    cmd = [
        exif, "-r", "-overwrite_original", "-P",
        "-FileCreateDate<FileModifyDate",
        "-DateTimeOriginal<FileModifyDate",
        "-CreateDate<FileModifyDate",
        str(Path(args.target))
    ]
    if args.dry_run:
        print(" ".join(cmd))
        return
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()

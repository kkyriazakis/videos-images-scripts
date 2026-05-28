#!/usr/bin/env python3
"""Normalize filenames by replacing whitespace/dashes/parentheses with dots
and collapsing consecutive dots.

Usage:
    python filename_normalize.py "path/to/folder" [--dry]
"""
import argparse
import re
import sys
from pathlib import Path


def sanitize_filename(filename: str) -> str:
    # Replace whitespace, dashes, and parenthesis with dots
    sanitized = re.sub(r'[\s\-()]+', '.', filename)
    # Collapse consecutive dots
    sanitized = re.sub(r'\.+', '.', sanitized)
    # Remove leading/trailing dots
    return sanitized.strip('.')


def parse_args():
    p = argparse.ArgumentParser(description="Normalize filenames in a directory (recursively)")
    p.add_argument('folder', help='Target folder to process')
    p.add_argument('--dry', action='store_true', help='Print actions without renaming')
    return p.parse_args()


def main():
    args = parse_args()
    folder = Path(args.folder).resolve()
    if not folder.is_dir():
        print(f"[ERROR] Not a directory: {folder}")
        sys.exit(1)

    all_files = sorted([f for f in folder.rglob('*') if f.is_file()])
    if not all_files:
        print('No files found.')
        return

    renamed = 0
    for f in all_files:
        original = f.name
        parts = original.rsplit('.', 1)
        if len(parts) == 2:
            stem, ext = parts
            new_name = sanitize_filename(stem) + '.' + ext
        else:
            new_name = sanitize_filename(original)

        if new_name != original:
            new_path = f.parent / new_name
            if args.dry:
                print(f"DRY: {f} -> {new_path}")
            else:
                try:
                    f.rename(new_path)
                    print(f"Renamed: {original} -> {new_name}")
                    renamed += 1
                except Exception as e:
                    print(f"[ERROR] Failed to rename {original}: {e}")
        else:
            print(f"Skipped: {original} (no change)")

    if not args.dry:
        print(f"\nDone. {renamed} file(s) renamed.")


if __name__ == '__main__':
    main()

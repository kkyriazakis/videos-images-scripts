#!/usr/bin/env python3
"""Replace a substring in filenames (recursively).

Supports removing the substring by providing only the OLD value (i.e. NEW omitted).

Usage:
    python filename_replace.py "path/to/folder" --replace OLD [NEW]
Examples:
    python filename_replace.py . --replace "English-SDH-SRT" "English-SDH"
    python filename_replace.py . --replace "unwanted_text"    # removes occurrences
"""
import argparse
import sys
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser(description='Replace OLD with NEW in filenames (NEW optional -> removal)')
    p.add_argument('folder', help='Target folder to process')
    p.add_argument('--replace', nargs='+', metavar=('OLD', 'NEW'), help='Provide OLD [NEW]. If NEW omitted, OLD will be removed')
    p.add_argument('--dry', action='store_true', help='Print actions without renaming')
    return p.parse_args()


def main():
    args = parse_args()
    folder = Path(args.folder).resolve()
    if not folder.is_dir():
        print(f"[ERROR] Not a directory: {folder}")
        sys.exit(1)

    if not args.replace:
        print('[ERROR] --replace OLD [NEW] is required')
        sys.exit(1)

    if len(args.replace) == 1:
        old = args.replace[0]
        new = ''
    elif len(args.replace) == 2:
        old, new = args.replace
    else:
        print('[ERROR] --replace accepts one or two arguments: OLD [NEW]')
        sys.exit(1)

    if not old:
        print('[ERROR] OLD value for --replace cannot be empty')
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
            new_name = stem.replace(old, new) + '.' + ext
        else:
            new_name = original.replace(old, new)

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

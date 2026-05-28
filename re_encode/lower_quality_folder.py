#!/usr/bin/env python3
"""
lower_quality_folder.py
Batch wrapper that runs lower_quality.py on each video file in a folder.

Usage examples:
    python lower_quality_folder.py /path/to/folder --quality 70
    python lower_quality_folder.py /path/to/folder --quality 60 --recursive --dry-run
"""

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_EXTS = {'.mkv', '.mp4', '.m4v', '.mov', '.webm', '.avi', '.m2ts', '.ts'}


def find_files(folder: Path, exts: set, recursive: bool):
    if recursive:
        for p in folder.rglob('*'):
            if p.is_file() and p.suffix.lower() in exts:
                yield p
    else:
        for p in folder.iterdir():
            if p.is_file() and p.suffix.lower() in exts:
                yield p


def main():
    parser = argparse.ArgumentParser(description='Batch-process videos with lower_quality.py')
    parser.add_argument('folder', help='Folder to scan for video files')
    parser.add_argument('--quality', type=float, default=70.0)
    parser.add_argument('--recursive', action='store_true', help='Recurse into subfolders')
    parser.add_argument('--exts', nargs='+', default=None, help='Additional file extensions to include (e.g. .mkv .mp4)')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--skip-existing', action='store_true', help='Skip files whose output already exists')
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.exists():
        print(f'[ERROR] Folder not found: {folder}')
        sys.exit(1)
    exts = set(DEFAULT_EXTS)
    if args.exts:
        for e in args.exts:
            if not e.startswith('.'):
                e = '.' + e
            exts.add(e.lower())

    script = Path(__file__).resolve().parent / 'lower_quality.py'
    if not script.exists():
        print(f'[ERROR] Cannot find lower_quality.py at: {script}')
        sys.exit(1)

    files = list(find_files(folder, exts, args.recursive))
    if not files:
        print('[INFO] No matching files found.')
        return

    print(f'[INFO] Found {len(files)} files to process (quality={args.quality}%)')
    failed = 0
    for f in files:
        out = f.parent / f'{f.stem}_q{int(args.quality)}{f.suffix}'
        if args.skip_existing and out.exists():
            print(f'[SKIP] Output exists, skipping: {f.name}')
            continue
        cmd = [sys.executable, str(script), str(f), '--quality', str(args.quality)]
        print(f'[RUN] {" ".join(cmd)}')
        if args.dry_run:
            continue
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f'[ERROR] Failed processing {f}: {e}')
            failed += 1

    if failed:
        print(f'[DONE] Completed with {failed} failures.')
        sys.exit(2)
    else:
        print('[DONE] All files processed.')


if __name__ == '__main__':
    main()

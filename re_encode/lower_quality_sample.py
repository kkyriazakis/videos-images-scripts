#!/usr/bin/env python3
"""
lower_quality_sample.py
Extracts a 5-minute sample from the middle of an MKV file,
then re-encodes it at a reduced quality percentage for preview.

Usage:
    python lower_quality_sample.py "F:\got_no_hdr\Season5\S05E01 - The Wars To Come.mkv" --quality 70 --duration 60
"""
import argparse
import subprocess
import json
import sys
from pathlib import Path

from lower_quality import FFMPEG, FFPROBE, reencode


def get_duration(input_path: str) -> float:
    """Return total duration of the file in seconds."""
    cmd = [
        FFPROBE, "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        input_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


def make_sample(input_path: str, quality_pct: float, sample_duration: float = 300.0,
                output_path: str | None = None):
    input_p = Path(input_path)
    if not input_p.exists():
        print(f"[ERROR] File not found: {input_path}")
        sys.exit(1)

    total_duration = get_duration(input_path)
    print(f"[INFO] Total duration : {total_duration:.1f}s  ({total_duration / 60:.1f} min)")

    sample_duration = min(sample_duration, total_duration)
    start_time = max(0.0, (total_duration / 2.0) - (sample_duration / 2.0))

    print(f"[INFO] Sample start   : {start_time:.1f}s")
    print(f"[INFO] Sample duration: {sample_duration:.1f}s  ({sample_duration / 60:.1f} min)")

    if output_path is None:
        output_path = str(
            input_p.parent / f"{input_p.stem}_sample_q{int(quality_pct)}{input_p.suffix}"
        )

    temp_path = str(input_p.parent / f"{input_p.stem}_TEMP_sample{input_p.suffix}")

    try:
        print(f"[INFO] Cutting sample into temp file (stream-copy) ...")
        cut_cmd = [
            FFMPEG, "-y",
            "-ss", str(start_time),
            "-i", input_path,
            "-t", str(sample_duration),
            "-map", "0",
            "-c", "copy",
            temp_path,
        ]
        subprocess.run(cut_cmd, check=True)

        print(f"[INFO] Passing temp file to lower_quality.reencode() ...")
        reencode(temp_path, quality_pct, output_path)

    finally:
        Path(temp_path).unlink(missing_ok=True)
        print(f"[INFO] Temp file removed.")

    print(f"[DONE] Sample saved to: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract a middle sample from an MKV and re-encode at reduced quality."
    )
    parser.add_argument("input", help="Path to the source MKV file.")
    parser.add_argument("--quality", type=float, default=70.0,
                        help="Target quality percentage (default: 70).")
    parser.add_argument("--duration", type=float, default=300.0,
                        help="Sample duration in seconds (default: 300 = 5 minutes).")
    parser.add_argument("--output", default=None,
                        help="Output file path (optional; auto-generated if omitted).")
    args = parser.parse_args()

    make_sample(args.input, args.quality, args.duration, args.output)
#!/usr/bin/env python3
"""
lower_quality.py
Re-encodes an MKV file at a percentage of its original quality.
All audio tracks, subtitle tracks, and attachments are preserved.

Usage:
    python lower_quality.py <input.mkv> [--quality 70]
"""

import argparse
import subprocess
import json
import sys
from pathlib import Path

# Load tool paths from repository config (tools_config.json / tools_config.py)
p = Path(__file__).resolve().parent
while True:
    if (p / "tools_config.py").exists() or (p / "tools_config.json").exists():
        sys.path.insert(0, str(p))
        break
    if p.parent == p:
        break
    p = p.parent

try:
    from tools_config import FFMPEG, FFPROBE, MKVMERGE
except Exception as e:
    print(f"[ERROR] Failed to load tools_config: {e}")
    print("Create a tools_config.json in the repository root with keys: ffmpeg, ffprobe, mkvmerge")
    sys.exit(1)

# Quality percentage → CRF mapping for x264/x265
# CRF 0 = lossless, CRF 51 = worst quality
# 100% quality ≈ CRF 18 (visually near-lossless)
# We map PERCENTAGE linearly: higher % = lower CRF (better quality)
CRF_BEST  = 18   # corresponds to 100% quality
CRF_WORST = 48   # corresponds to 0% quality


def get_video_codec(input_path: str) -> str:
    """Detect the video codec of the input file."""
    cmd = [
        FFPROBE, "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-select_streams", "v:0",
        input_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    info = json.loads(result.stdout)
    streams = info.get("streams", [])
    if not streams:
        raise ValueError("No video stream found in input file.")
    return streams[0].get("codec_name", "h264")


def probe_streams(input_path: str) -> list:
    """Return all stream info for informational logging."""
    cmd = [
        FFPROBE, "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        input_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout).get("streams", [])


def quality_to_crf(percentage: float) -> int:
    """Convert a quality percentage (0–100) to a CRF value."""
    percentage = max(0.0, min(100.0, percentage))
    crf = CRF_WORST - (percentage / 100.0) * (CRF_WORST - CRF_BEST)
    return round(crf)


def reencode(input_path: str, quality_pct: float, output_path: str | None = None):
    input_p = Path(input_path)
    if not input_p.exists():
        print(f"[ERROR] File not found: {input_path}")
        sys.exit(1)

    if output_path is None:
        output_path = str(input_p.parent / f"{input_p.stem}_q{int(quality_pct)}{input_p.suffix}")

    crf = quality_to_crf(quality_pct)

    # Detect codec to pick the right encoder
    src_codec = get_video_codec(input_path)
    encoder = "libx265" if "hevc" in src_codec or "h265" in src_codec else "libx264"

    # Log all streams that will be carried over
    streams = probe_streams(input_path)
    for s in streams:
        idx       = s.get("index")
        codec     = s.get("codec_name", "?")
        stype     = s.get("codec_type", "?")
        lang      = s.get("tags", {}).get("language", "")
        title     = s.get("tags", {}).get("title", "")
        label     = f"  stream #{idx}: {stype:8s}  codec={codec:10s}  lang={lang:5s}  title={title}"
        print(label)

    print(f"[INFO] Input  : {input_path}")
    print(f"[INFO] Output : {output_path}")
    print(f"[INFO] Quality: {quality_pct}%  →  CRF {crf}  (encoder: {encoder})")

    cmd = [
        FFMPEG, "-y",
        "-i", input_path,
        "-map", "0",             # include EVERY stream from the input
        "-c:v", encoder,         # re-encode video only
        "-crf", str(crf),
        "-preset", "medium",
        "-c:a", "copy",          # copy all audio tracks unchanged
        "-c:s", "copy",          # copy all subtitle tracks unchanged
        "-c:t", "copy",          # copy attachments (fonts, etc.)
        output_path,
    ]

    subprocess.run(cmd, check=True)
    print(f"[DONE] Saved to: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-encode an MKV at a given quality percentage.")
    parser.add_argument("input", help="Path to the source MKV file.")
    parser.add_argument("--quality", type=float, default=70.0,
                        help="Target quality as a percentage of the original (default: 70).")
    parser.add_argument("--output", default=None,
                        help="Output file path (optional; auto-generated if omitted).")
    args = parser.parse_args()

    reencode(args.input, args.quality, args.output)
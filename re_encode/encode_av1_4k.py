#!/usr/bin/env python3
"""
encode_av1.py
Re-encodes an MKV file using AV1 video at a fixed bitrate, and re-encodes
audio to Opus 5.1 at a fixed bitrate. Source resolution is left untouched.
Subtitle tracks and attachments are preserved.

Usage:
    python encode_av1.py <input.mkv> [--v-bitrate 21000k] [--a-bitrate 128k]
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


def get_audio_stream_indices(streams: list) -> list:
    """Return the ffmpeg-relative index of each audio stream (0-based, per stream type)."""
    return [i for i, s in enumerate(streams) if s.get("codec_type") == "audio"]


def reencode(input_path: str, v_bitrate: str, a_bitrate: str, output_path: str | None = None):
    input_p = Path(input_path)
    if not input_p.exists():
        print(f"[ERROR] File not found: {input_path}")
        sys.exit(1)

    if output_path is None:
        output_path = str(input_p.parent / f"{input_p.stem}_av1{input_p.suffix}")

    # Log all streams that will be carried over
    streams = probe_streams(input_path)
    audio_indices = get_audio_stream_indices(streams)
    for s in streams:
        idx   = s.get("index")
        codec = s.get("codec_name", "?")
        stype = s.get("codec_type", "?")
        lang  = s.get("tags", {}).get("language", "")
        title = s.get("tags", {}).get("title", "")
        chans = s.get("channels", "")
        label = f"  stream #{idx}: {stype:8s}  codec={codec:10s}  lang={lang:5s}  ch={chans!s:3s}  title={title}"
        print(label)

    print(f"[INFO] Input   : {input_path}")
    print(f"[INFO] Output  : {output_path}")
    print(f"[INFO] Video   : AV1 (libsvtav1), native resolution, {v_bitrate} target bitrate")
    print(f"[INFO] Audio   : Opus, 5.1 (6ch), {a_bitrate} per track, {len(audio_indices)} audio stream(s)")

    cmd = [
        FFMPEG, "-y",
        "-i", input_path,
        "-map", "0",                          # include EVERY stream from the input
        "-c:v", "libsvtav1",                  # AV1 encode, source resolution untouched
        "-b:v", v_bitrate,                    # VBR target bitrate
        "-pix_fmt", "yuv420p10le",            # 10-bit is standard practice for AV1/4K
        "-c:a", "libopus",                    # re-encode audio to Opus
        "-b:a", a_bitrate,
        "-ac", "6",                           # force 5.1 (6 channels)
        "-c:s", "copy",                       # copy all subtitle tracks unchanged
        "-c:t", "copy",                       # copy attachments (fonts, etc.)
        output_path,
    ]

    subprocess.run(cmd, check=True)
    print(f"[DONE] Saved to: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-encode an MKV to 4K AV1 + Opus 5.1.")
    parser.add_argument("input", help="Path to the source MKV file.")
    parser.add_argument("--v-bitrate", default="21000k",
                        help="Target video bitrate for AV1 (default: 21000k).")
    parser.add_argument("--a-bitrate", default="128k",
                        help="Target audio bitrate per Opus track (default: 128k).")
    parser.add_argument("--output", default=None,
                        help="Output file path (optional; auto-generated if omitted).")
    args = parser.parse_args()

    reencode(args.input, args.v_bitrate, args.a_bitrate, args.output)
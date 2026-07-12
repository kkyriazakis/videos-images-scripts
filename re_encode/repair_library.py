#!/usr/bin/env python3
import json
import shutil
import subprocess
import sys
from pathlib import Path

p = Path(__file__).resolve().parent
while True:
    if (p / "tools_config.py").exists() or (p / "tools_config.json").exists():
        sys.path.insert(0, str(p))
        break
    if p.parent == p:
        break
    p = p.parent
from tools_config import FFMPEG, FFPROBE

VIDEO_EXTS = {".mkv", ".mp4"}
CRF = "16"          # near-visually-lossless; lower = higher quality/bigger file
PRESET = "slow"     # better quality-per-bit than "medium", still reasonable speed

def get_video_info(path: Path):
    cmd = [FFPROBE, "-v", "quiet", "-print_format", "json",
           "-show_streams", "-select_streams", "v:0", str(path)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    streams = json.loads(result.stdout).get("streams", [])
    if not streams:
        return "h264", "yuv420p"
    s = streams[0]
    return s.get("codec_name", "h264"), s.get("pix_fmt", "yuv420p")

def reencode(path: Path):
    codec, pix_fmt = get_video_info(path)
    encoder = "libx265" if codec in ("hevc", "h265") else "libx264"

    tmp = path.with_name(path.stem + ".reencode.tmp.mkv")
    final_path = path.with_suffix(".mkv")   # always .mkv, no matter the input ext

    print(f"\nProcessing: {path}  [{codec}, {pix_fmt}] -> {encoder} -> {final_path.name}")

    cmd = [
        FFMPEG, "-y",
        "-err_detect", "ignore_err",
        "-fflags", "+genpts",
        "-i", str(path),
        "-map", "0:v",
        "-map", "0:a",
        "-map", "0:s?",
        "-c:v", encoder,
        "-b:v", "4000k",
        "-maxrate", "4800k",
        "-bufsize", "8000k",
        "-preset", PRESET,
        "-pix_fmt", "yuv420p",
        "-profile:v", "high" if encoder == "libx264" else "main",
        "-level", "4.1",
        "-c:a", "copy",
        "-c:s", "copy",
        "-max_muxing_queue_size", "9999",
        str(tmp),
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
        print("Failed - leaving original untouched.")
        tmp.unlink(missing_ok=True)
        return

    # sanity check: new file must decode cleanly before we touch the original
    check = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(tmp), "-map", "0:v:0", "-f", "null", "-"],
        capture_output=True, text=True
    )
    if check.returncode != 0 or check.stderr.strip():
        print("Output failed integrity check - leaving original untouched.")
        tmp.unlink(missing_ok=True)
        return

    backup = path.with_name(path.name + ".bak")
    shutil.move(str(path), str(backup))
    shutil.move(str(tmp), str(final_path))
    backup.unlink()
    print(f"Done -> {final_path.name}")

def main():
    if len(sys.argv) != 2:
        print(f"Usage: {Path(sys.argv[0]).name} <folder>")
        sys.exit(1)
    root = Path(sys.argv[1])
    files = sorted(f for ext in VIDEO_EXTS for f in root.rglob(f"*{ext}"))
    print(f"Found {len(files)} files.")
    for file in files:
        try:
            reencode(file)
        except Exception as e:
            print(f"Error processing {file}: {e}")
    print("\nFinished.")

if __name__ == "__main__":
    main()
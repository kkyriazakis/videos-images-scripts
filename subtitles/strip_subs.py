# python strip_subs.py "F:\torr\marv\Ant-Man.mkv"

import subprocess
import json
import sys
import shutil
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
    from tools_config import FFPROBE, MKVMERGE
except Exception as e:
    print(f"[ERROR] Failed to load tools_config: {e}")
    print("Create a tools_config.json in the repository root with keys: ffmpeg, ffprobe, mkvmerge")
    sys.exit(1)


def has_subtitles(path: Path):
    r = subprocess.run(
        [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_streams", str(path)],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        return None
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "subtitle":
            return True
    return False


def strip_subs(src: Path):
    subtitle_state = has_subtitles(src)
    if subtitle_state is False:
        print(f"  No subtitle tracks found: {src.name} — skipping.")
        return

    if subtitle_state is None:
        print(f"  [WARN] Could not inspect tracks for {src.name}; stripping anyway.")

    tmp = src.with_name(src.stem + "._nosubs.mkv")
    out = src.with_suffix(".mkv")

    print(f"  Stripping subs: {src.name}")
    r = subprocess.run(
        [MKVMERGE, "-q", "-o", str(tmp), "--no-subtitles", str(src)],
        capture_output=True
    )
    if r.returncode == 0:
        shutil.move(str(tmp), str(out))
        if src.suffix.lower() != ".mkv" and src.exists():
            src.unlink()
            print(f"  Removed original {src.name}")
        print(f"  Done -> {out.name}")
    else:
        print(f"  [ERROR] mkvmerge failed — {src.name} unchanged.")
        if tmp.exists():
            tmp.unlink()


def main():
    if len(sys.argv) < 2:
        print("Usage: python strip_subs.py <file.mkv|file.mp4>")
        sys.exit(1)

    src = Path(sys.argv[1]).resolve()
    if not src.is_file():
        print(f"[ERROR] File not found: {src}")
        sys.exit(1)

    strip_subs(src)


if __name__ == "__main__":
    main()

# python extract_subs.py "F:\torr\marv\Ant-Man.mkv"

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
    from tools_config import FFMPEG, FFPROBE
except Exception as e:
    print(f"[ERROR] Failed to load tools_config: {e}")
    print("Create a tools_config.json in the repository root with keys: ffmpeg, ffprobe, mkvmerge")
    sys.exit(1)

STRIP_SCRIPT = Path(__file__).parent / "strip_subs.py"

CODEC_EXT = {
    "subrip":   "srt",
    "srt":      "srt",
    "mov_text": "srt",
    "ass":      "ass",
    "ssa":      "ass",
    "webvtt":   "vtt",
}

# Codecs that require transcoding instead of stream copy
TRANSCODE_CODEC = {
    "mov_text": "srt",
}

SKIP_CODECS = {"hdmv_pgs_subtitle", "pgssub", "dvd_subtitle", "dvb_subtitle"}


def get_subtitle_tracks(path: Path):
    result = subprocess.run(
        [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_streams", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    data = json.loads(result.stdout)
    tracks = []
    for s in data.get("streams", []):
        if s.get("codec_type") != "subtitle":
            continue
        codec = s.get("codec_name", "unknown")
        lang  = s.get("tags", {}).get("language", "und")
        title = s.get("tags", {}).get("title", "")
        tracks.append({"index": s["index"], "codec": codec, "lang": lang, "title": title})
    return tracks


def extract_subs(src: Path):
    src = src.resolve()
    if not src.exists():
        print(f"[ERROR] File not found: {src}")
        sys.exit(1)

    print(f"\nProcessing: {src.name}")
    tracks = get_subtitle_tracks(src)

    if not tracks:
        print("  No subtitle tracks found.")
        return

    extracted_any = False

    for t in tracks:
        idx   = t["index"]
        codec = t["codec"]
        lang  = t["lang"]
        title = t["title"]

        if codec in SKIP_CODECS:
            print(f"  [SKIP] idx={idx} ({codec}) — bitmap subtitle, unsupported")
            continue

        ext = CODEC_EXT.get(codec, "srt")
        sub_codec = TRANSCODE_CODEC.get(codec, "copy")

        safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in title).strip("_")
        suffix = f".{lang}.{safe_title}.{ext}" if safe_title else f".{lang}.{ext}"
        out = src.with_name(src.stem + suffix)

        if out.exists():
            out = src.with_name(f"{src.stem}.{lang}.{idx}.{ext}")

        print(f"  Extracting idx={idx} ({codec}, {lang}) -> {out.name}")
        r = subprocess.run(
            [FFMPEG, "-v", "quiet", "-i", str(src), "-map", f"0:{idx}", "-c:s", sub_codec, str(out)],
            capture_output=True
        )
        if r.returncode == 0:
            extracted_any = True
        else:
            print(f"  [WARN] Failed to extract idx={idx}")

    if extracted_any:
        subprocess.run([sys.executable, str(STRIP_SCRIPT), str(src)])


def main():
    if len(sys.argv) < 2:
        print("Usage: python extract_subs.py <file.mkv|file.mp4>")
        sys.exit(1)

    src = Path(sys.argv[1]).resolve()
    if not src.is_file():
        print(f"[ERROR] File not found: {src}")
        sys.exit(1)

    extract_subs(src)


if __name__ == "__main__":
    main()
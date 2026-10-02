#!/usr/bin/env python3
"""
encode_av1_4k.py
Re-encodes ONLY the video codec of an MKV to AV1 (libsvtav1). Everything else
is carried over bit-for-bit:

  - Resolution, sample/display aspect ratio: untouched (no scale/crop filters),
    so IMAX / variable aspect ratio / 4:3 / anamorphic sources stay as they are.
  - Frame rate / timestamps: passed through (VFR safe).
  - Audio tracks: stream-copied (codec, channels, bitrate unchanged).
  - Subtitles, attachments (fonts, cover art), chapters, metadata: copied.
  - HDR10: color primaries / transfer / matrix / range and mastering display +
    content light level metadata are passed through to the AV1 stream.

Limitations (warned about at runtime):
  - Dolby Vision RPU and HDR10+ dynamic metadata cannot be carried into AV1 by
    ffmpeg; the HDR10 base layer is kept. DV profile 5 (no HDR10 base layer)
    is refused unless --force is given, since colors would be wrong.

After encoding the output is probed and compared against the source; the
script exits non-zero if anything other than the video codec changed.

Usage:
    python encode_av1_4k.py <input.mkv> [--v-bitrate 21000k] [--output out.mkv] [--force]
    python encode_av1_4k.py "F:\torr\out\The Gentlemen.mkv" --v-bitrate 21000k --output "F:\torr\out\The Gentlemen_enc.mkv"
"""

import argparse
import subprocess
import json
import sys
from fractions import Fraction
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
    """Return all stream info (including stream-level side data)."""
    cmd = [
        FFPROBE, "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        input_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout).get("streams", [])


def probe_first_frame_side_data(input_path: str, stream_index: int) -> list:
    """Return side data of the first decoded frame of a stream (HDR metadata often lives here)."""
    cmd = [
        FFPROBE, "-v", "quiet",
        "-print_format", "json",
        "-select_streams", str(stream_index),
        "-read_intervals", "%+#1",
        "-show_frames",
        "-show_entries", "frame=side_data_list",
        input_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return []
    frames = json.loads(result.stdout or "{}").get("frames", [])
    return frames[0].get("side_data_list", []) if frames else []


def is_real_video(s: dict) -> bool:
    """Video stream that is not cover art / an attached picture."""
    return (s.get("codec_type") == "video"
            and not s.get("disposition", {}).get("attached_pic", 0))


def _f(v) -> float:
    return float(Fraction(str(v)))


def find_side_data(side_data: list, kind: str) -> dict | None:
    for sd in side_data:
        if kind.lower() in sd.get("side_data_type", "").lower():
            return sd
    return None


def build_hdr_params(stream: dict, frame_side_data: list) -> tuple[list, list]:
    """Return (svtav1 params, warnings) for passing HDR static metadata through."""
    side = stream.get("side_data_list", []) + frame_side_data
    params, warnings = [], []

    mdcv = find_side_data(side, "Mastering display")
    if mdcv and "red_x" in mdcv:
        params.append(
            "mastering-display="
            f"G({_f(mdcv['green_x']):.4f},{_f(mdcv['green_y']):.4f})"
            f"B({_f(mdcv['blue_x']):.4f},{_f(mdcv['blue_y']):.4f})"
            f"R({_f(mdcv['red_x']):.4f},{_f(mdcv['red_y']):.4f})"
            f"WP({_f(mdcv['white_point_x']):.4f},{_f(mdcv['white_point_y']):.4f})"
            f"L({_f(mdcv['max_luminance']):.4f},{_f(mdcv['min_luminance']):.4f})"
        )

    cll = find_side_data(side, "Content light level")
    if cll and "max_content" in cll:
        params.append(f"content-light={int(cll['max_content'])},{int(cll['max_average'])}")

    if find_side_data(side, "SMPTE2094-40") or find_side_data(side, "HDR10+"):
        warnings.append("HDR10+ dynamic metadata present - it will be dropped (static HDR10 is kept).")

    dovi = find_side_data(side, "DOVI configuration")
    if dovi:
        profile = dovi.get("dv_profile")
        compat = dovi.get("dv_bl_signal_compatibility_id")
        if profile == 5 or compat == 0:
            warnings.append(f"DOLBY VISION profile {profile} has no HDR10/SDR base layer - "
                            "output colors WILL be wrong. Use --force to encode anyway.")
        else:
            warnings.append(f"Dolby Vision profile {profile} RPU will be dropped; "
                            "the HDR10/HLG/SDR base layer is kept.")

    if stream.get("color_transfer") in ("smpte2084", "arib-std-b67"):
        params.insert(0, "enable-hdr=1")

    return params, warnings


def summarize(s: dict) -> dict:
    """Properties that must be identical between source and output."""
    t = s.get("codec_type")
    d = {"type": t, "lang": s.get("tags", {}).get("language")}
    if is_real_video(s):
        d.update(width=s.get("width"), height=s.get("height"),
                 sar=s.get("sample_aspect_ratio", "1:1"),
                 fps=s.get("r_frame_rate"),
                 color_primaries=s.get("color_primaries"),
                 color_transfer=s.get("color_transfer"),
                 color_space=s.get("color_space"),
                 color_range=s.get("color_range"))
    elif t == "audio":
        d.update(codec=s.get("codec_name"), channels=s.get("channels"),
                 layout=s.get("channel_layout"), sample_rate=s.get("sample_rate"),
                 profile=s.get("profile"))
    else:
        d.update(codec=s.get("codec_name"))
    return d


def verify(src_streams: list, output_path: str) -> bool:
    out_streams = probe_streams(output_path)
    ok = True
    if len(src_streams) != len(out_streams):
        print(f"[FAIL] Stream count changed: {len(src_streams)} -> {len(out_streams)}")
        return False
    for a, b in zip(src_streams, out_streams):
        sa, sb = summarize(a), summarize(b)
        for key in sa:
            # Unset source color tags may legitimately be written as defaults.
            if key.startswith("color_") and sa[key] in (None, "unknown"):
                continue
            if sa[key] != sb.get(key):
                print(f"[FAIL] stream #{a.get('index')} {key}: {sa[key]} -> {sb.get(key)}")
                ok = False
        if is_real_video(b) and b.get("codec_name") != "av1":
            print(f"[FAIL] stream #{b.get('index')} is not AV1 ({b.get('codec_name')})")
            ok = False
    return ok


def reencode(input_path: str, v_bitrate: str, output_path: str | None = None, force: bool = False):
    input_p = Path(input_path)
    if not input_p.exists():
        print(f"[ERROR] File not found: {input_path}")
        sys.exit(1)

    if output_path is None:
        output_path = str(input_p.parent / f"{input_p.stem}_av1{input_p.suffix}")

    streams = probe_streams(input_path)
    for s in streams:
        idx   = s.get("index")
        codec = s.get("codec_name", "?")
        stype = s.get("codec_type", "?")
        lang  = s.get("tags", {}).get("language", "")
        title = s.get("tags", {}).get("title", "")
        chans = s.get("channels", "")
        extra = f"  {s.get('width')}x{s.get('height')} {s.get('color_transfer', '')}" if is_real_video(s) else ""
        print(f"  stream #{idx}: {stype:10s}  codec={codec:10s}  lang={lang:5s}  ch={chans!s:3s}  title={title}{extra}")

    video_streams = [s for s in streams if is_real_video(s)]
    if not video_streams:
        print("[ERROR] No video stream found.")
        sys.exit(1)

    cmd = [
        FFMPEG, "-y",
        "-i", input_path,
        "-map", "0",                          # include EVERY stream from the input
        "-c", "copy",                         # copy everything by default (audio, subs, attachments, cover art)
        "-map_metadata", "0",
        "-map_chapters", "0",
        "-fps_mode", "passthrough",           # keep original timestamps / frame rate
        "-max_muxing_queue_size", "4096",
    ]

    abort = False
    for s in video_streams:
        i = s["index"]                        # with -map 0, output index == input index
        hdr_params, warnings = build_hdr_params(s, probe_first_frame_side_data(input_path, i))
        for w in warnings:
            print(f"[WARN] stream #{i}: {w}")
            if "WILL be wrong" in w and not force:
                abort = True

        pix_fmt = s.get("pix_fmt", "")
        if "422" in pix_fmt or "444" in pix_fmt:
            print(f"[WARN] stream #{i}: source is {pix_fmt}; SVT-AV1 only supports 4:2:0, chroma will be subsampled.")

        cmd += [
            f"-c:{i}", "libsvtav1",           # AV1 encode, no filters -> resolution untouched
            f"-b:{i}", v_bitrate,
            f"-pix_fmt:{i}", "yuv420p10le",   # 10-bit (required to keep HDR, harmless for SDR)
        ]
        # Explicitly carry color signalling so it can't be lost or defaulted
        for opt, key in (("color_primaries", "color_primaries"),
                         ("color_trc", "color_transfer"),
                         ("colorspace", "color_space"),
                         ("color_range", "color_range"),
                         ("chroma_sample_location", "chroma_location")):
            val = s.get(key)
            if val and val != "unknown" and val != "unspecified":
                cmd += [f"-{opt}:{i}", val]
        if hdr_params:
            cmd += [f"-svtav1-params:{i}", ":".join(hdr_params)]

        print(f"[INFO] Video #{i}: AV1 {v_bitrate}, {s.get('width')}x{s.get('height')} "
              f"SAR {s.get('sample_aspect_ratio', '1:1')}, transfer={s.get('color_transfer', 'unknown')}"
              + (f", HDR params: {':'.join(hdr_params)}" if hdr_params else ""))

    if abort:
        print("[ERROR] Aborting to avoid a broken encode (see warnings above).")
        sys.exit(2)

    cmd.append(output_path)

    print(f"[INFO] Input   : {input_path}")
    print(f"[INFO] Output  : {output_path}")
    print("[INFO] Audio / subtitles / attachments / chapters: copied unchanged")

    subprocess.run(cmd, check=True)

    print("[INFO] Verifying output against source...")
    if not verify(streams, output_path):
        print("[ERROR] Output differs from source in more than the video codec (see above).")
        sys.exit(3)
    print(f"[DONE] Verified and saved to: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-encode only the video of an MKV to AV1; copy everything else.")
    parser.add_argument("input", help="Path to the source MKV file.")
    parser.add_argument("--v-bitrate", default="21000k",
                        help="Target video bitrate for AV1 (default: 21000k).")
    parser.add_argument("--output", default=None,
                        help="Output file path (optional; auto-generated if omitted).")
    parser.add_argument("--force", action="store_true",
                        help="Encode even if the source is Dolby Vision without an HDR10 base layer.")
    args = parser.parse_args()

    reencode(args.input, args.v_bitrate, args.output, args.force)

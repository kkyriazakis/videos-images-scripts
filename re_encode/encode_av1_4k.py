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
        requires --test for a random one-minute conversion preview, then --force
        for a full color-aware conversion with libplacebo.
    - Converted Dolby Vision produces HDR10-compatible BT.2020/PQ video, not
        Dolby Vision. Static mastering metadata is not invented if absent.
    - Sources shorter than one minute use their full duration for --test.

After encoding the output is probed and compared against the source; the
script exits non-zero if anything other than the video codec or explicitly
converted Dolby Vision color properties changed.

Usage:
    python encode_av1_4k.py <input.mkv> [--v-bitrate 21000k] [--output out.mkv] [--test | --force]
    python encode_av1_4k.py "input_path" --v-bitrate 22000k --output "output_path"
"""

import argparse
import subprocess
import json
import math
import random
import sys
import tempfile
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


def probe_duration(input_path: str) -> float:
    """Return a finite positive duration for choosing a test segment."""
    result = subprocess.run([
        FFPROBE, "-v", "error", "-show_entries", "format=duration",
        "-of", "json", input_path,
    ], capture_output=True, text=True, check=True)
    duration = float(json.loads(result.stdout)["format"]["duration"])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Source duration must be finite and positive")
    return duration


def probe_first_frame_side_data(input_path: str, stream_index: int, start_time: float = 0) -> list:
    """Return side data of the first decoded frame of a stream (HDR metadata often lives here)."""
    cmd = [
        FFPROBE, "-v", "quiet",
        "-print_format", "json",
        "-select_streams", str(stream_index),
        "-read_intervals", f"{start_time}%+#1",
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


DOVI_HDR_FILTER = (
    "libplacebo=apply_dolbyvision=1:colorspace=bt2020nc:"
    "color_primaries=bt2020:color_trc=smpte2084:range=tv:format=yuv420p10le"
)
HDR_COLOR_PROPERTIES = {
    "color_primaries": "bt2020",
    "color_transfer": "smpte2084",
    "color_space": "bt2020nc",
    "color_range": "tv",
}
# Dolby Vision mastering primaries default to P3-D65 when no L9 metadata is present.
P3_D65_PRIMARIES = "G(0.2650,0.6900)B(0.1500,0.0600)R(0.6800,0.3200)WP(0.3127,0.3290)"


def pq_to_nits(code: int, bits: int = 12) -> float:
    e = (code / ((1 << bits) - 1)) ** (1 / 78.84375)
    return 10000 * (max(e - 0.8359375, 0) / (18.8515625 - 18.6875 * e)) ** (1 / 0.1593017578125)


def dovi_mastering_display(frame_side_data: list) -> str | None:
    meta = find_side_data(frame_side_data, "Dolby Vision Metadata")
    if not meta or not meta.get("source_max_pq"):
        return None
    max_nits = pq_to_nits(meta["source_max_pq"])
    min_nits = pq_to_nits(meta.get("source_min_pq", 0))
    return f"mastering-display={P3_D65_PRIMARIES}L({max_nits:.4f},{min_nits:.4f})"


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
            warnings.append(f"Dolby Vision profile {profile} has no HDR10/SDR base layer; "
                            "a plain re-encode would have wrong colors.\n"
                            "  --test   convert a random 1-minute segment to check colors\n"
                            "  --force  run the full color-converted encode\n")
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


def verify(src_streams: list, output_path: str, converted_indices: set | None = None) -> bool:
    out_streams = probe_streams(output_path)
    converted_indices = converted_indices or set()
    ok = True
    if len(src_streams) != len(out_streams):
        print(f"[FAIL] Stream count changed: {len(src_streams)} -> {len(out_streams)}")
        return False
    for a, b in zip(src_streams, out_streams):
        sa, sb = summarize(a), summarize(b)
        converted = a.get("index") in converted_indices
        if converted:
            sa.update(HDR_COLOR_PROPERTIES, pix_fmt="yuv420p10le")
            sb["pix_fmt"] = b.get("pix_fmt")
            side = b.get("side_data_list", []) + probe_first_frame_side_data(output_path, b["index"])
            if any("dovi" in data.get("side_data_type", "").lower()
                   or "dolby vision" in data.get("side_data_type", "").lower() for data in side):
                print(f"[FAIL] stream #{b.get('index')} still signals Dolby Vision after conversion")
                ok = False
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


def reencode(input_path: str, v_bitrate: str, output_path: str | None = None,
             force: bool = False, dovi_to_hdr10: bool = False, test: bool = False):
    input_p = Path(input_path)
    if not input_p.exists():
        print(f"[ERROR] File not found: {input_path}")
        sys.exit(1)

    if test and force:
        print("[ERROR] Choose --test for a preview or --force for a full encode, not both.")
        sys.exit(2)

    start_time = 0.0
    test_duration = None
    if test:
        try:
            duration = probe_duration(input_path)
        except (ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
            print(f"[ERROR] Cannot choose a test segment: {error}")
            sys.exit(2)
        test_duration = min(60.0, duration)
        start_time = random.uniform(0.0, max(0.0, duration - test_duration))
        print(f"[INFO] Test segment: {start_time:.3f}s to {start_time + test_duration:.3f}s "
              f"({test_duration:.3f}s).")

    if output_path is None:
        suffix = "_av1_test" if test else "_av1"
        output_path = str(input_p.parent / f"{input_p.stem}{suffix}{input_p.suffix}")

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

    remux_attachments = any(s.get("disposition", {}).get("attached_pic", 0) for s in streams)
    excluded_indices = {
        s["index"] for s in streams
        if remux_attachments and (s.get("codec_type") == "attachment"
                                  or s.get("disposition", {}).get("attached_pic", 0))
    }
    output_indices = {
        s["index"]: output_index
        for output_index, s in enumerate(s for s in streams if s["index"] not in excluded_indices)
    }
    cmd = [
        FFMPEG, "-y",
        *(["-ss", f"{start_time:.6f}"] if test else []),
        "-i", input_path,
        "-map", "0",                          # include EVERY stream from the input
        "-c", "copy",                         # copy everything by default (audio, subs, attachments, cover art)
        "-map_metadata", "0",
        "-map_chapters", "0",
        "-fps_mode", "passthrough",           # keep original timestamps / frame rate
        "-max_muxing_queue_size", "4096",
    ]
    if test:
        cmd += ["-ss", "0", "-t", f"{test_duration:.6f}"]
    for excluded_index in sorted(excluded_indices):
        cmd += ["-map", f"-0:{excluded_index}"]

    abort = False
    converted_indices = set()
    for s in video_streams:
        i = s["index"]
        output_index = output_indices[i]
        frame_side = (probe_first_frame_side_data(input_path, i, start_time) if test
                  else probe_first_frame_side_data(input_path, i))
        dovi = find_side_data(s.get("side_data_list", []) + frame_side, "DOVI configuration")
        convert_dovi = (test or force) and dovi is not None and dovi.get("dv_profile") == 5
        hdr_params, warnings = build_hdr_params(s, frame_side)
        if convert_dovi:
            if not find_side_data(frame_side, "Dolby Vision Metadata"):
                print(f"[ERROR] stream #{i}: decoder did not expose Dolby Vision metadata; "
                      "cannot safely convert profile 5.")
                sys.exit(2)
            subprocess.run([
                FFMPEG, "-v", "error",
                *(["-ss", f"{start_time:.6f}"] if test else []),
                "-i", input_path, "-map", f"0:{i}",
                "-vf", DOVI_HDR_FILTER, "-frames:v", "1", "-f", "null", "-",
            ], check=True)
            converted_indices.add(i)
            mastering = dovi_mastering_display(frame_side)
            hdr_params = [mastering] if mastering else []
            warnings = []
            print(f"[INFO] Video #{i}: applying Dolby Vision profile 5 metadata with libplacebo; "
                  "output is BT.2020/PQ HDR, not Dolby Vision.")
        for w in warnings:
            print(f"[WARN] stream #{i}: {w}")
            if "no HDR10/SDR base layer" in w:
                abort = True

        pix_fmt = s.get("pix_fmt", "")
        if "422" in pix_fmt or "444" in pix_fmt:
            print(f"[WARN] stream #{i}: source is {pix_fmt}; SVT-AV1 only supports 4:2:0, chroma will be subsampled.")

        cmd += [
            f"-c:{output_index}", "libsvtav1",
            f"-b:{output_index}", v_bitrate,
            f"-pix_fmt:{output_index}", "yuv420p10le",
        ]
        if convert_dovi:
            cmd += [f"-filter:{output_index}", DOVI_HDR_FILTER]
        color_stream = {**s, **HDR_COLOR_PROPERTIES} if convert_dovi else s
        # Explicitly carry color signalling so it can't be lost or defaulted
        for opt, key in (("color_primaries", "color_primaries"),
                         ("color_trc", "color_transfer"),
                         ("colorspace", "color_space"),
                         ("color_range", "color_range"),
                         ("chroma_sample_location", "chroma_location")):
            val = color_stream.get(key)
            if val and val != "unknown" and val != "unspecified":
                cmd += [f"-{opt}:{output_index}", val]
        if hdr_params:
            cmd += [f"-svtav1-params:{output_index}", ":".join(hdr_params)]

        print(f"[INFO] Video #{i}: AV1 {v_bitrate}, {s.get('width')}x{s.get('height')} "
              f"SAR {s.get('sample_aspect_ratio', '1:1')}, transfer={color_stream.get('color_transfer', 'unknown')}"
              + (f", HDR params: {':'.join(hdr_params)}" if hdr_params else ""))

    if abort:
        print("[ERROR] Aborting to avoid a broken encode. Rerun with --test or --force.\n")
        sys.exit(2)

    cmd.append(output_path)

    print(f"[INFO] Input   : {input_path}")
    print(f"[INFO] Output  : {output_path}")
    print("[INFO] Audio / subtitles / attachments / chapters: copied unchanged")

    if remux_attachments:
        with tempfile.TemporaryDirectory(prefix="av1-remux-", dir=Path(output_path).parent) as directory:
            cmd[-1] = str(Path(directory) / "encoded.mkv")
            subprocess.run(cmd, check=True)
            subprocess.run([
                MKVMERGE, "-o", output_path, cmd[-1],
                "--no-video", "--no-audio", "--no-subtitles", "--no-buttons",
                "--no-chapters", "--no-global-tags", "--no-track-tags", input_path,
            ], check=True)
    else:
        subprocess.run(cmd, check=True)

    print("[INFO] Verifying output against source...")
    if not verify(streams, output_path, converted_indices):
        print("[ERROR] Output differs from the expected codec/color conversion or copied streams (see above).")
        sys.exit(3)
    print(f"[DONE] Verified and saved to: {output_path}")
    if test:
        print("[INFO] Watch the test segment to verify colors and quality, then use --force for the full encode.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-encode only the video of an MKV to AV1; copy everything else.")
    parser.add_argument("input", help="Path to the source MKV file.")
    parser.add_argument("--v-bitrate", default="21000k", help="Target video bitrate for AV1 (default: 21000k).")
    parser.add_argument("--output", default=None, help="Output file path (optional; auto-generated if omitted).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--test", action="store_true", help="Convert a random one-minute segment for visual verification.")
    mode.add_argument("--force", action="store_true", help="Run the full encode with Dolby Vision profile 5 color conversion.")
    parser.add_argument("--dovi-to-hdr10", action="store_true", help="Legacy flag; use --test or --force for profile 5.")
    args = parser.parse_args()
    reencode(args.input, args.v_bitrate, args.output, args.force, args.dovi_to_hdr10, args.test)

#!/usr/bin/env python3
"""
encode_hevc_4k.py
Re-encodes ONLY the video codec of a file to HEVC Main10 (NVENC by default,
or libx265 with --encoder x265). Everything else is carried over unchanged:

  - Resolution, aspect ratio, frame rate / timestamps: untouched.
  - Audio, subtitles, attachments (fonts, cover art), chapters, metadata: copied.
  - HDR10: color tags, mastering display and content light level are written
    to the HEVC stream. HLG and SDR keep their color tags.
  - Dolby Vision profile 5 (no HDR10 base layer) is converted to HDR10 with
    libplacebo; requires --test (random one-minute preview) or --force.
  - Other Dolby Vision profiles: the RPU is dropped and the HDR10/HLG/SDR base
    layer is kept, so the output is plain HDR10 HEVC.

The output is written to a .partial file, verified against the source, and only
then renamed to the final name.

Usage:
    python encode_hevc_4k.py <input> [--encoder nvenc|x265] [--crf 23] [--preset P] [--v-bitrate 30000k] [--output out.mkv] [--test | --force]
"""

import argparse
import json
import math
import os
import random
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

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
MKVPROPEDIT = str(Path(MKVMERGE).with_name(Path(MKVMERGE).name.replace("mkvmerge", "mkvpropedit")))


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
P3_D65 = {"G": (0.265, 0.69), "B": (0.15, 0.06), "R": (0.68, 0.32), "WP": (0.3127, 0.329)}
MP4_LIKE = {".mp4", ".m4v", ".mov"}
# Keeps detail and dark-scene gradients in film content.
FILM_TUNING = ["aq-mode=3", "no-sao=1", "deblock=-1,-1"]
# HEVC Level 5.1 Main tier peak, so CRF spikes stay playable on TVs and phones.
LEVEL51_VBV = ["vbv-maxrate=40000", "vbv-bufsize=40000"]
DEFAULT_PRESETS = {"nvenc": "p7", "x265": "slow"}


def probe_streams(input_path: str) -> list:
    result = subprocess.run([
        FFPROBE, "-v", "quiet", "-print_format", "json", "-show_streams", input_path,
    ], capture_output=True, text=True, check=True)
    return json.loads(result.stdout).get("streams", [])


def probe_duration(input_path: str) -> float:
    result = subprocess.run([
        FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "json", input_path,
    ], capture_output=True, text=True, check=True)
    duration = float(json.loads(result.stdout)["format"]["duration"])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Source duration must be finite and positive")
    return duration


COLOR_KEYS = ("color_primaries", "color_transfer", "color_space", "color_range")


def probe_first_frame(input_path: str, stream_index: int, start_time: float = 0) -> dict:
    """First decoded frame: side data (HDR metadata) and bitstream color tags."""
    result = subprocess.run([
        FFPROBE, "-v", "quiet", "-print_format", "json",
        "-select_streams", str(stream_index),
        "-read_intervals", f"{start_time}%+#1",
        "-show_frames", "-show_entries", "frame=side_data_list," + ",".join(COLOR_KEYS),
        input_path,
    ], capture_output=True, text=True)
    if result.returncode != 0:
        return {}
    frames = json.loads(result.stdout or "{}").get("frames", [])
    return frames[0] if frames else {}


def is_real_video(s: dict) -> bool:
    """Video stream that is not cover art (attached picture or a still-image track)."""
    return (s.get("codec_type") == "video"
            and not s.get("disposition", {}).get("attached_pic", 0)
            and s.get("codec_name") not in ("mjpeg", "png", "bmp", "webp"))


def _f(v) -> float:
    return float(Fraction(str(v)))


def find_side_data(side_data: list, kind: str) -> dict | None:
    for sd in side_data:
        if kind.lower() in sd.get("side_data_type", "").lower():
            return sd
    return None


def has_dovi(side_data: list) -> bool:
    return any("dovi" in sd.get("side_data_type", "").lower()
               or "dolby vision" in sd.get("side_data_type", "").lower() for sd in side_data)


def needs_dovi_conversion(dovi: dict | None) -> bool:
    return bool(dovi) and (dovi.get("dv_profile") == 5 or dovi.get("dv_bl_signal_compatibility_id") == 0)


def pq_to_nits(code: int, bits: int = 12) -> float:
    e = (code / ((1 << bits) - 1)) ** (1 / 78.84375)
    return 10000 * (max(e - 0.8359375, 0) / (18.8515625 - 18.6875 * e)) ** (1 / 0.1593017578125)


def x265_master_display(primaries: dict, max_nits: float, min_nits: float) -> str:
    # x265 units: chromaticity 0.00002, luminance 0.0001 cd/m2
    xy = "".join(f"{k}({round(x * 50000)},{round(y * 50000)})" for k, (x, y) in primaries.items())
    return f"master-display={xy}L({round(max_nits * 10000)},{round(min_nits * 10000)})"


def dovi_mastering_nits(frame_side_data: list) -> tuple[float, float] | None:
    meta = find_side_data(frame_side_data, "Dolby Vision Metadata")
    if not meta or not meta.get("source_max_pq"):
        return None
    return pq_to_nits(meta["source_max_pq"]), pq_to_nits(meta.get("source_min_pq", 0))


def mkv_mastering_props(max_nits: float, min_nits: float) -> list:
    """mkvpropedit arguments for P3-D65 mastering display in the track header."""
    names = {"R": "red", "G": "green", "B": "blue"}
    args = []
    for k, (x, y) in P3_D65.items():
        prefix = "white-coordinates" if k == "WP" else f"chromaticity-coordinates-{names[k]}"
        args += ["--set", f"{prefix}-x={x}", "--set", f"{prefix}-y={y}"]
    return args + ["--set", f"max-luminance={max_nits:.4f}", "--set", f"min-luminance={min_nits:.4f}"]


def build_x265_params(color_transfer: str | None, side: list) -> list:
    params = []
    if color_transfer == "smpte2084":
        params += ["hdr10=1", "hdr10-opt=1"]

    mdcv = find_side_data(side, "Mastering display")
    if mdcv and "red_x" in mdcv:
        prims = {k: (_f(mdcv[f"{c}_x"]), _f(mdcv[f"{c}_y"]))
                 for k, c in (("G", "green"), ("B", "blue"), ("R", "red"), ("WP", "white_point"))}
        params.append(x265_master_display(prims, _f(mdcv["max_luminance"]), _f(mdcv["min_luminance"])))

    cll = find_side_data(side, "Content light level")
    if cll and "max_content" in cll:
        params.append(f"max-cll={int(cll['max_content'])},{int(cll['max_average'])}")

    if color_transfer in ("smpte2084", "arib-std-b67"):
        params.append("repeat-headers=1")
    return params


def build_warnings(side: list) -> list:
    warnings = []
    if find_side_data(side, "SMPTE2094-40") or find_side_data(side, "HDR10+"):
        warnings.append("HDR10+ dynamic metadata may not be kept; static HDR10 metadata is kept.")
    dovi = find_side_data(side, "DOVI configuration")
    if needs_dovi_conversion(dovi):
        warnings.append(f"Dolby Vision profile {dovi.get('dv_profile')} has no HDR10/SDR base layer; "
                        "a plain re-encode would have wrong colors.\n"
                        "  --test   convert a random 1-minute segment to check colors\n"
                        "  --force  run the full color-converted encode\n")
    elif dovi:
        warnings.append(f"Dolby Vision profile {dovi.get('dv_profile')} RPU will be dropped; "
                        "the HDR10/HLG/SDR base layer is kept.")
    return warnings


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


def verify(src_streams: list, output_path: str, converted_indices: set) -> bool:
    out_streams = probe_streams(output_path)
    ok = True
    if len(src_streams) != len(out_streams):
        print(f"[FAIL] Stream count changed: {len(src_streams)} -> {len(out_streams)}")
        return False
    for a, b in zip(src_streams, out_streams):
        sa, sb = summarize(a), summarize(b)
        if a.get("index") in converted_indices:
            sa.update(HDR_COLOR_PROPERTIES)
        for key in sa:
            # Unset source color tags may legitimately be written as defaults.
            if key.startswith("color_") and sa[key] in (None, "unknown"):
                continue
            if sa[key] != sb.get(key):
                print(f"[FAIL] stream #{a.get('index')} {key}: {sa[key]} -> {sb.get(key)}")
                ok = False
        if is_real_video(b):
            if b.get("codec_name") != "hevc" or b.get("pix_fmt") != "yuv420p10le":
                print(f"[FAIL] stream #{b.get('index')} is not HEVC Main10 "
                      f"({b.get('codec_name')}, {b.get('pix_fmt')})")
                ok = False
            side = b.get("side_data_list", []) + probe_first_frame(output_path, b["index"]).get("side_data_list", [])
            if has_dovi(side):
                print(f"[FAIL] stream #{b.get('index')} still signals Dolby Vision")
                ok = False
    return ok


def reencode(input_path: str, v_bitrate: str | None = None, output_path: str | None = None,
             force: bool = False, test: bool = False, crf: float = 23, preset: str | None = None,
             encoder: str = "nvenc"):
    preset = preset or DEFAULT_PRESETS[encoder]
    input_p = Path(input_path)
    if not input_p.exists():
        print(f"[ERROR] File not found: {input_path}")
        sys.exit(1)

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
        suffix = "_hevc_test" if test else "_hevc"
        output_path = str(input_p.parent / f"{input_p.stem}{suffix}{input_p.suffix}")
    output_p = Path(output_path)
    partial_path = str(output_p.with_name(f"{output_p.stem}.partial{output_p.suffix}"))

    streams = probe_streams(input_path)
    for s in streams:
        extra = f"  {s.get('width')}x{s.get('height')} {s.get('color_transfer', '')}" if is_real_video(s) else ""
        print(f"  stream #{s.get('index')}: {s.get('codec_type', '?'):10s}  "
              f"codec={s.get('codec_name', '?'):10s}  lang={s.get('tags', {}).get('language', ''):5s}  "
              f"ch={s.get('channels', '')!s:3s}  title={s.get('tags', {}).get('title', '')}{extra}")

    video_streams = [s for s in streams if is_real_video(s)]
    if not video_streams:
        print("[ERROR] No video stream found.")
        sys.exit(1)

    # FFmpeg turns MKV cover art into a video track; restore attachments with mkvmerge instead.
    remux_attachments = (output_p.suffix.lower() == ".mkv"
                         and any(s.get("disposition", {}).get("attached_pic", 0) for s in streams))
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
        "-map", "0",
        "-c", "copy",
        "-map_metadata", "0",
        "-map_chapters", "0",
        "-fps_mode", "passthrough",
        "-max_muxing_queue_size", "4096",
    ]
    if test:
        # Output-side -ss trims copied-audio pre-roll so the segment stays one minute.
        cmd += ["-ss", "0", "-t", f"{test_duration:.6f}"]
    for excluded_index in sorted(excluded_indices):
        cmd += ["-map", f"-0:{excluded_index}"]

    abort = False
    converted_indices = set()
    mkv_edits = []
    for s in video_streams:
        i = s["index"]
        out_i = output_indices[i]
        frame = probe_first_frame(input_path, i, start_time)
        frame_side = frame.get("side_data_list", [])
        # Some files signal color only in the bitstream, not the container.
        s = {**s, **{k: frame[k] for k in COLOR_KEYS
                     if s.get(k) in (None, "unknown", "unspecified") and frame.get(k) not in (None, "unknown")}}
        side = s.get("side_data_list", []) + frame_side
        convert_dovi = (test or force) and needs_dovi_conversion(find_side_data(side, "DOVI configuration"))
        warnings = build_warnings(side)

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
            color_stream = {**s, **HDR_COLOR_PROPERTIES}
            mastering = dovi_mastering_nits(frame_side)
            x265_params = build_x265_params("smpte2084", [])
            if mastering:
                x265_params.append(x265_master_display(P3_D65, *mastering))
                if encoder == "nvenc":
                    if output_p.suffix.lower() == ".mkv":
                        mkv_edits += ["--edit", f"track:@{out_i + 1}", *mkv_mastering_props(*mastering)]
                    else:
                        print(f"[WARN] stream #{i}: NVENC cannot write mastering metadata into "
                              f"{output_p.suffix}; use .mkv or --encoder x265.")
            warnings = []
            print(f"[INFO] Video #{i}: applying Dolby Vision profile 5 metadata with libplacebo; "
                  "output is HDR10, not Dolby Vision.")
        else:
            color_stream = s
            x265_params = build_x265_params(s.get("color_transfer"), side)

        for w in warnings:
            print(f"[WARN] stream #{i}: {w}")
            if "no HDR10/SDR base layer" in w:
                abort = True

        pix_fmt = s.get("pix_fmt", "")
        if "422" in pix_fmt or "444" in pix_fmt:
            print(f"[WARN] stream #{i}: source is {pix_fmt}; output is 4:2:0, chroma will be subsampled.")

        if encoder == "nvenc":
            # Source HDR10 mastering/CLL frame side data is passed through by NVENC itself.
            cmd += [
                f"-c:{out_i}", "hevc_nvenc",
                f"-preset:{out_i}", preset, f"-tune:{out_i}", "hq",
                f"-rc:{out_i}", "vbr",
                *([f"-b:{out_i}", v_bitrate] if v_bitrate else [f"-cq:{out_i}", str(crf), f"-b:{out_i}", "0"]),
                f"-maxrate:{out_i}", "40M", f"-bufsize:{out_i}", "40M",
                f"-multipass:{out_i}", "2", f"-rc-lookahead:{out_i}", "32",
                f"-spatial-aq:{out_i}", "1", f"-temporal-aq:{out_i}", "1",
                f"-bf:{out_i}", "4", f"-b_ref_mode:{out_i}", "middle",
                f"-pix_fmt:{out_i}", "p010le",
                f"-profile:{out_i}", "main10",
            ]
        else:
            cmd += [
                f"-c:{out_i}", "libx265",
                f"-preset:{out_i}", preset,
                *([f"-b:{out_i}", v_bitrate] if v_bitrate else [f"-crf:{out_i}", str(crf)]),
                f"-pix_fmt:{out_i}", "yuv420p10le",
                f"-profile:{out_i}", "main10",
                f"-dolbyvision:{out_i}", "0",
            ]
        if output_p.suffix.lower() in MP4_LIKE:
            cmd += [f"-tag:{out_i}", "hvc1"]
        if convert_dovi:
            cmd += [f"-filter:{out_i}", DOVI_HDR_FILTER]
        for opt, key in (("color_primaries", "color_primaries"),
                         ("color_trc", "color_transfer"),
                         ("colorspace", "color_space"),
                         ("color_range", "color_range"),
                         ("chroma_sample_location", "chroma_location")):
            val = color_stream.get(key)
            if val and val not in ("unknown", "unspecified"):
                cmd += [f"-{opt}:{out_i}", val]
        x265_params = FILM_TUNING + ([] if v_bitrate else LEVEL51_VBV) + x265_params
        if encoder == "x265":
            cmd += [f"-x265-params:{out_i}", ":".join(x265_params)]

        rate = v_bitrate or f"{'CQ' if encoder == 'nvenc' else 'CRF'} {crf}"
        print(f"[INFO] Video #{i}: HEVC Main10 {encoder} {rate} preset {preset}, {s.get('width')}x{s.get('height')} "
              f"SAR {s.get('sample_aspect_ratio', '1:1')}, transfer={color_stream.get('color_transfer', 'unknown')}"
              + (f", x265: {':'.join(x265_params)}" if encoder == "x265" else ""))

    if abort:
        print("[ERROR] Aborting to avoid a broken encode. Rerun with --test or --force.\n")
        sys.exit(2)

    cmd.append(partial_path)

    print(f"[INFO] Input   : {input_path}")
    print(f"[INFO] Output  : {output_path}")
    print("[INFO] Audio / subtitles / attachments / chapters: copied unchanged")

    if remux_attachments:
        with tempfile.TemporaryDirectory(prefix="hevc-remux-", dir=output_p.parent) as directory:
            cmd[-1] = str(Path(directory) / "encoded.mkv")
            subprocess.run(cmd, check=True)
            # mkvmerge exit code 1 means warnings only
            if subprocess.run([
                MKVMERGE, "-o", partial_path, cmd[-1],
                "--no-video", "--no-audio", "--no-subtitles", "--no-buttons",
                "--no-chapters", "--no-global-tags", "--no-track-tags", input_path,
            ]).returncode > 1:
                print("[ERROR] mkvmerge failed while restoring attachments.")
                sys.exit(3)
    else:
        subprocess.run(cmd, check=True)

    if mkv_edits and subprocess.run([MKVPROPEDIT, partial_path, *mkv_edits]).returncode > 1:
        print("[ERROR] mkvpropedit failed while writing mastering metadata.")
        sys.exit(3)

    print("[INFO] Verifying output against source...")
    if not verify(streams, partial_path, converted_indices):
        print(f"[ERROR] Output differs from the expected result (see above). Kept for inspection: {partial_path}")
        sys.exit(3)
    os.replace(partial_path, output_path)
    print(f"[DONE] Verified and saved to: {output_path}")
    if test:
        print("[INFO] Watch the test segment to verify colors and quality, then use --force for the full encode.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-encode only the video to HEVC Main10 (HDR10 aware); copy everything else.")
    parser.add_argument("input", help="Path to the source file.")
    parser.add_argument("--encoder", choices=("nvenc", "x265"), default="nvenc",
                        help="nvenc: fast GPU encode (default). x265: smaller files, much slower.")
    parser.add_argument("--crf", type=float, default=23, help="Constant quality (NVENC CQ / x265 CRF), lower = better/larger (default: 23, matches AV1 21000k).")
    parser.add_argument("--preset", default=None, help="Encoder preset (default: p7 for nvenc, slow for x265).")
    parser.add_argument("--v-bitrate", default=None, help="Fixed average bitrate instead of CRF, e.g. 30000k.")
    parser.add_argument("--output", default=None, help="Output file path (optional; auto-generated if omitted).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--test", action="store_true", help="Convert a random one-minute segment for visual verification.")
    mode.add_argument("--force", action="store_true", help="Run the full encode, including Dolby Vision profile 5 conversion.")
    args = parser.parse_args()
    reencode(args.input, args.v_bitrate, args.output, args.force, args.test, args.crf, args.preset, args.encoder)

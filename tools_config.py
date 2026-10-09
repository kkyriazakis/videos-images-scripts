import json
import sys
from pathlib import Path

# Platform-specific config names, tried before the generic tools_config.json
_PLATFORM_CONFIGS = {
    "linux": "tools_config_linux.json",
}


def _config_names():
    names = [n for prefix, n in _PLATFORM_CONFIGS.items() if sys.platform.startswith(prefix)]
    names.append("tools_config.json")
    return names


def _find_config():
    for name in _config_names():
        p = Path(__file__).resolve().parent
        while True:
            cfg = p / name
            if cfg.exists():
                return cfg
            if p.parent == p:
                break
            p = p.parent
    return None


_cfg_path = _find_config()
if not _cfg_path:
    raise FileNotFoundError(
        f"No tools config found (looked for: {', '.join(_config_names())}). Create one in the repository root "
            "or a parent directory of the scripts with keys: ffmpeg, ffprobe, mkvmerge, exiftool"
    )

try:
    _cfg = json.loads(_cfg_path.read_text(encoding="utf-8"))
except Exception as e:
    raise RuntimeError(f"Failed to parse {_cfg_path.name} at {_cfg_path}: {e}")

# Ensure required keys are present in the JSON config
required = ("ffmpeg", "ffprobe", "mkvmerge", "exiftool")
missing = [k for k in required if k not in _cfg or not _cfg[k]]
if missing:
    raise KeyError(f"{_cfg_path.name} missing required keys: {', '.join(missing)}")

FFMPEG = _cfg["ffmpeg"]
FFPROBE = _cfg["ffprobe"]
MKVMERGE = _cfg["mkvmerge"]
EXIFTOOL = _cfg["exiftool"]

# Expose raw config dict as `cfg`
cfg = _cfg

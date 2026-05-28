import json
from pathlib import Path


def _find_config():
    p = Path(__file__).resolve().parent
    while True:
        cfg = p / "tools_config.json"
        if cfg.exists():
            return cfg
        if p.parent == p:
            break
        p = p.parent
    return None


_cfg_path = _find_config()
if not _cfg_path:
    raise FileNotFoundError(
        "tools_config.json not found. Create a tools_config.json in the repository root "
            "or a parent directory of the scripts with keys: ffmpeg, ffprobe, mkvmerge, exiftool"
    )

try:
    _cfg = json.loads(_cfg_path.read_text(encoding="utf-8"))
except Exception as e:
    raise RuntimeError(f"Failed to parse tools_config.json at {_cfg_path}: {e}")

# Ensure required keys are present in the JSON config
required = ("ffmpeg", "ffprobe", "mkvmerge", "exiftool")
missing = [k for k in required if k not in _cfg or not _cfg[k]]
if missing:
    raise KeyError(f"tools_config.json missing required keys: {', '.join(missing)}")

FFMPEG = _cfg["ffmpeg"]
FFPROBE = _cfg["ffprobe"]
MKVMERGE = _cfg["mkvmerge"]
EXIFTOOL = _cfg["exiftool"]

# Expose raw config dict as `cfg`
cfg = _cfg

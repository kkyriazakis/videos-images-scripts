# python strip_subs_batch.py "F:\torr\marv"

import sys
import subprocess
from pathlib import Path

STRIP_SCRIPT = Path(__file__).parent / "strip_subs.py"


def main():
    if len(sys.argv) < 2:
        print("Usage: python strip_subs_batch.py <folder>")
        sys.exit(1)

    folder = Path(sys.argv[1]).resolve()
    if not folder.is_dir():
        print(f"[ERROR] Not a directory: {folder}")
        sys.exit(1)

    files = sorted(
        f for f in folder.rglob("*")
        if f.suffix.lower() in (".mkv", ".mp4")
        and not f.stem.endswith("._nosubs")
    )

    if not files:
        print("No MKV/MP4 files found.")
        sys.exit(0)

    print(f"Found {len(files)} file(s) in: {folder}\n")

    for f in files:
        subprocess.run([sys.executable, str(STRIP_SCRIPT), str(f)])

    print("\nAll done.")


if __name__ == "__main__":
    main()

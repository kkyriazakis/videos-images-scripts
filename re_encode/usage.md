# Usage examples for lower_quality scripts

## Single file

```bash
python lower_quality.py "F:\\got_no_hdr\\Season5\\S05E01 - The Wars To Come.mkv" --quality 70
# Output: creates "S05E01 - The Wars To Come_q70.mkv" next to the input
```

## Folder (batch) — wrapper script

```bash
python lower_quality_folder.py "F:\\got_no_hdr\\Season5" --quality 70
# Recurse into subfolders:
python lower_quality_folder.py "F:\\got_no_hdr" --quality 70 --recursive

```

Notes:

- Extensions scanned by default: .mkv .mp4 .m4v .mov .webm .avi .m2ts .ts

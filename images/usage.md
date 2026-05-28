# Images scripts for common ExifTool operations

This folder contains small Python wrappers around `exiftool` for common tasks
from `cmd_rename.txt`. Each script locates the repository `tools_config.json`
to read the `exiftool` path (key `exiftool`). If not present, the system
`exiftool` command is used.

Usage: run the scripts from the repository root or anywhere. Examples:

```bash
python images/modified_to_metadata.py "C:\\path\\to\\photos"
python images/metadata_to_modified.py "C:\\path\\to\\photos"
python images/date_taken_to_filename.py "C:\\path\\to\\photos"
python images/date_taken_to_filename_vid.py "C:\\path\\to\\videos"
python images/filename_to_metadata.py "C:\\path\\to\\file.jpg"
```

Each script supports `--dry-run` to print the underlying `exiftool` command.

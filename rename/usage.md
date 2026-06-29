# Rename utilities

Examples

```bash
python rename/filename_normalize.py "X:\\path\\to\\folder" --dry
python rename/filename_normalize.py "X:\\path\\to\\folder"

python rename/filename_replace.py "X:\\path\\to\\folder" --replace "OLD" "NEW"
python rename/filename_replace.py "X:\\path\\to\\folder" --replace "OLD"    # removes OLD
python rename/filename_replace.py "X:\\path\\to\\folder" --replace "OLD" "NEW" --dry

# Pattern script: pattern is hardcoded inside the script; open it and edit
# `OLD_NAME_PATTERN` / `NEW_NAME_FORMAT` before running.
python rename/filename_pattern_replace.py
```

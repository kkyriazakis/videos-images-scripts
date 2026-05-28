Rename utilities
================

Small helpers for batch renaming files in a directory tree.

Scripts
- `filename_normalize.py`: normalize filenames by replacing whitespace, dashes and
  parentheses with dots and collapsing consecutive dots.
- `filename_replace.py`: replace a substring in filenames. If `NEW` is omitted,
  occurrences of `OLD` are removed.
- `filename_pattern_replace.py`: ad-hoc script with a hard-coded pattern. Edit
  the `OLD_NAME_PATTERN` / `NEW_NAME_FORMAT` constants in the script before use.

Common options
- `--dry`: print the actions that would be taken without renaming files.

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

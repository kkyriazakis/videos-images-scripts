import os
import re
from pathlib import Path

# Configuration: Set the pattern and new name format here
OLD_NAME_PATTERN = r'__show-S06E(\d+)\.mp4'
# OLD_NAME_PATTERN = r'tv-show-s02e(\d+)\.mp4'

NEW_NAME_FORMAT = 'show-S06E{1}.mp4'

EP_OFFSET = 0

PATH = Path('X:\\scripts\\voe-dl\\undone')

def mass_rename():
    """Rename files matching the pattern to the new format"""
    
    # Get current directory
    current_dir = PATH
    
    # Compile the pattern
    pattern = re.compile(OLD_NAME_PATTERN)
    
    # Find all matching files
    renamed_count = 0
    for file_path in current_dir.iterdir():
        if file_path.is_file():
            match = pattern.match(file_path.name)
            if match:
                # Format new name using captured groups (1-indexed: {1}, {2}, etc.)
                groups = match.groups()
                new_name = NEW_NAME_FORMAT
                for i, group in enumerate(groups, start=1):
                    ep_number = int(group) - EP_OFFSET
                    ep_number = str(ep_number).zfill(2)
                    new_name = new_name.replace(f'{{{i}}}', ep_number)
                new_path = current_dir / new_name
                
                # Check if target already exists
                if new_path.exists():
                    print(f'SKIP: {file_path.name} -> {new_name} (target already exists)')
                else:
                    try:
                        file_path.rename(new_path)
                        print(f'RENAMED: {file_path.name} -> {new_name}')
                        renamed_count += 1
                    except Exception as e:
                        print(f'ERROR renaming {file_path.name}: {e}')
    
    print(f'\nTotal files renamed: {renamed_count}')

if __name__ == '__main__':
    mass_rename()


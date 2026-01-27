#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script to rename directories under chara/ to replace special characters with underscores.
Then runs generate_character_index.py to update name_to_path.json
"""

import os
import re
import subprocess
from pathlib import Path


def sanitize_dirname(name):
    """
    Replace special characters in directory name with underscores.
    Keeps Chinese characters, alphanumeric, and underscores.
    Special characters to replace: 〔〕【】（）()[]・/\:*?"<>|／
    """
    # Characters that are problematic in file paths or URLs
    # Including fullwidth slash ／ (U+FF0F)
    special_chars = r'[\〔\〕\【\】\（\）\(\)\[\]\・\/\\:\*\?"<>\|／]'
    
    # Replace special characters with underscores
    new_name = re.sub(special_chars, '_', name)
    
    # Remove multiple consecutive underscores
    new_name = re.sub(r'_+', '_', new_name)
    
    # Remove leading/trailing underscores
    new_name = new_name.strip('_')
    
    return new_name


def rename_directories():
    """Rename all directories under chara/ that contain special characters."""
    chara_dir = Path("chara")
    
    if not chara_dir.exists():
        print("Error: chara/ directory not found!")
        return False
    
    renamed_count = 0
    
    # Get all directories and sort them (to handle nested cases if any)
    directories = sorted([d for d in chara_dir.iterdir() if d.is_dir()])
    
    for dir_path in directories:
        old_name = dir_path.name
        new_name = sanitize_dirname(old_name)
        
        if old_name != new_name:
            new_path = dir_path.parent / new_name
            
            # Check if target path already exists
            if new_path.exists():
                print(f"Warning: Cannot rename '{old_name}' -> '{new_name}' (target exists)")
                continue
            
            try:
                dir_path.rename(new_path)
                print(f"Renamed: '{old_name}' -> '{new_name}'")
                renamed_count += 1
            except Exception as e:
                print(f"Error renaming '{old_name}': {e}")
    
    return renamed_count


def update_index():
    """Run generate_character_index.py to update name_to_path.json"""
    print("\n" + "="*50)
    print("Running generate_character_index.py...")
    print("="*50 + "\n")
    
    try:
        result = subprocess.run(
            ["python", "generate_character_index.py"],
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
        print(result.stdout)
        if result.stderr:
            print("Errors:", result.stderr)
        return result.returncode == 0
    except Exception as e:
        print(f"Error running generate_character_index.py: {e}")
        return False


def main():
    print("="*50)
    print("Renaming directories with special characters...")
    print("="*50 + "\n")
    
    renamed_count = rename_directories()
    
    print(f"\nRenamed {renamed_count} directories.")
    
    # Update the index files
    update_index()
    
    print("\nDone!")


if __name__ == "__main__":
    main()
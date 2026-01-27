#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script to remove spaces from directory names in chara/ folder.
After renaming, it will automatically run generate_character_index.py
to update name_to_path.json and characters_info.json.
"""

import os
from pathlib import Path


def remove_spaces_from_directories() -> int:
    chara_dir = Path("chara")
    
    if not chara_dir.exists():
        print("Error: chara/ directory not found!")
        return 0
    
    renamed_count = 0
    
    # Get all subdirectories in chara/
    for char_folder in sorted(chara_dir.iterdir()):
        if not char_folder.is_dir():
            continue
        
        folder_name = char_folder.name
        
        # Check if folder name contains spaces
        if ' ' in folder_name:
            # Create new name by removing all spaces
            new_name = folder_name.replace(' ', '')
            new_path = chara_dir / new_name
            
            # Check if target path already exists
            if new_path.exists():
                print(f"Warning: Cannot rename '{folder_name}' -> '{new_name}' (target already exists)")
                continue
            
            # Rename the directory
            try:
                char_folder.rename(new_path)
                print(f"Renamed: '{folder_name}' -> '{new_name}'")
                renamed_count += 1
            except Exception as e:
                print(f"Error renaming '{folder_name}': {e}")
    
    print(f"\nTotal directories renamed: {renamed_count}")
    return renamed_count


def main():
    print("=" * 60)
    print("Removing spaces from directory names in chara/")
    print("=" * 60)
    
    renamed_count = remove_spaces_from_directories()
    
    if renamed_count > 0:
        print("\n" + "=" * 60)
        print("Now running generate_character_index.py to update JSON files...")
        print("=" * 60)
        
        # Import and run the generate_character_index script
        import generate_character_index
        generate_character_index.main()
    else:
        print("\nNo directories needed renaming. JSON files not updated.")


if __name__ == "__main__":
    main()
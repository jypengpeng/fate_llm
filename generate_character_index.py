#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script to traverse all character data.json files and generate two index JSON files:
1. name_to_path.json - Maps Chinese names to their directory paths
2. characters_info.json - Contains all character info (中文名, 职阶, 召唤关联词, 性格相性简述)
"""

import os
import json
from pathlib import Path


def main():
    chara_dir = Path("chara")
    
    # Dictionary to store name to path mapping
    name_to_path = {}
    
    # List to store all character info
    characters_info = []
    
    # Traverse all subdirectories in chara/
    for char_folder in sorted(chara_dir.iterdir()):
        if not char_folder.is_dir():
            continue
        
        data_file = char_folder / "data.json"
        
        if not data_file.exists():
            print(f"Warning: No data.json found in {char_folder}")
            continue
        
        try:
            with open(data_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error reading {data_file}: {e}")
            continue
        except Exception as e:
            print(f"Error reading {data_file}: {e}")
            continue
        
        # Extract required fields
        chinese_name = data.get("中文名", "")
        job_class = data.get("职阶", "")
        summon_keywords = data.get("召唤关联词", [])
        personality_summary = data.get("性格相性简述", "")
        
        if not chinese_name:
            print(f"Warning: No 中文名 found in {data_file}")
            continue
        
        # Get the folder name (directory name under chara/)
        folder_name = char_folder.name
        
        # Add to name_to_path mapping
        # The path format is: chara/{folder_name}/data.json
        name_to_path[chinese_name] = f"chara/{folder_name}/data.json"
        
        # Add to characters_info list
        char_info = {
            "中文名": chinese_name,
            "职阶": job_class,
            "召唤关联词": summon_keywords,
            "性格相性简述": personality_summary
        }
        characters_info.append(char_info)
        
        print(f"Processed: {chinese_name} ({job_class})")
    
    # Write name_to_path.json
    with open("name_to_path.json", "w", encoding="utf-8") as f:
        json.dump(name_to_path, f, ensure_ascii=False, indent=4)
    print(f"\nGenerated name_to_path.json with {len(name_to_path)} entries")
    
    # Write characters_info.json
    with open("characters_info.json", "w", encoding="utf-8") as f:
        json.dump(characters_info, f, ensure_ascii=False, indent=4)
    print(f"Generated characters_info.json with {len(characters_info)} entries")


if __name__ == "__main__":
    main()
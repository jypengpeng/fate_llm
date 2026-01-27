#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
遍历chara下面所有角色的data.json，在资料列表中过滤出同时有"阶级"和"种类"的一行，
然后将其插入到"宝具"和"人型"的中间，叫做"宝具描述"。
"""

import os
import json
import re
from collections import OrderedDict

def find_np_description(materials_list):
    """
    从资料列表中查找同时包含"阶级"和"种类"的条目
    返回: (匹配的条目列表, 匹配数量)
    """
    matches = []
    for item in materials_list:
        if "阶级" in item and "种类" in item:
            matches.append(item)
    return matches

def insert_after_key(ordered_dict, target_key, new_key, new_value):
    """
    在OrderedDict中，在target_key后面插入新的键值对
    """
    new_dict = OrderedDict()
    for key, value in ordered_dict.items():
        new_dict[key] = value
        if key == target_key:
            new_dict[new_key] = new_value
    return new_dict

def process_character(data_path):
    """
    处理单个角色的data.json
    返回: (状态码, 描述)
        状态码: 0=成功, 1=无匹配, 2=多个匹配, 3=已存在, 4=错误
    """
    try:
        with open(data_path, 'r', encoding='utf-8') as f:
            data = json.load(f, object_pairs_hook=OrderedDict)
        
        # 检查是否已经存在"宝具描述"字段
        if "宝具描述" in data:
            return (3, "已存在宝具描述字段")
        
        # 检查必要的字段
        if "资料列表" not in data:
            return (4, "缺少资料列表字段")
        if "宝具" not in data:
            return (4, "缺少宝具字段")
        if "人型" not in data:
            return (4, "缺少人型字段")
        
        # 查找匹配的条目
        matches = find_np_description(data["资料列表"])
        
        if len(matches) == 0:
            return (1, "未找到同时包含阶级和种类的条目")
        elif len(matches) > 2:
            return (2, f"找到{len(matches)}个匹配条目")
        
        # 一个或两个匹配，合并后插入宝具描述
        np_description = "\n\n".join(matches)
        new_data = insert_after_key(data, "宝具", "宝具描述", np_description)
        
        # 写回文件
        with open(data_path, 'w', encoding='utf-8') as f:
            json.dump(new_data, f, ensure_ascii=False, indent=4)
        
        return (0, "成功添加宝具描述")
        
    except json.JSONDecodeError as e:
        return (4, f"JSON解析错误: {e}")
    except Exception as e:
        return (4, f"处理错误: {e}")

def main():
    chara_dir = "chara"
    
    # 统计
    stats = {
        "成功": [],
        "无匹配": [],
        "多匹配": [],
        "已存在": [],
        "错误": []
    }
    
    # 遍历所有角色文件夹
    if not os.path.exists(chara_dir):
        print(f"错误: 找不到目录 {chara_dir}")
        return
    
    for char_name in os.listdir(chara_dir):
        char_path = os.path.join(chara_dir, char_name)
        if not os.path.isdir(char_path):
            continue
        
        data_path = os.path.join(char_path, "data.json")
        if not os.path.exists(data_path):
            continue
        
        status, message = process_character(data_path)
        
        if status == 0:
            stats["成功"].append((char_name, message))
        elif status == 1:
            stats["无匹配"].append((char_name, message))
        elif status == 2:
            stats["多匹配"].append((char_name, message))
        elif status == 3:
            stats["已存在"].append((char_name, message))
        else:
            stats["错误"].append((char_name, message))
    
    # 输出总结
    print("=" * 60)
    print("处理完成 - 总结报告")
    print("=" * 60)
    
    total = sum(len(v) for v in stats.values())
    print(f"\n总共处理: {total} 个角色")
    
    print(f"\n[OK] 成功: {len(stats['成功'])} 个")
    
    print(f"\n[SKIP] 已存在宝具描述: {len(stats['已存在'])} 个")
    if stats["已存在"]:
        for name, msg in stats["已存在"]:
            print(f"   - {name}")
    
    print(f"\n[WARN] 无匹配 (没有找到同时包含阶级和种类的条目): {len(stats['无匹配'])} 个")
    if stats["无匹配"]:
        for name, msg in stats["无匹配"]:
            print(f"   - {name}")
    
    print(f"\n[WARN] 多匹配 (找到超过2个匹配条目): {len(stats['多匹配'])} 个")
    if stats["多匹配"]:
        for name, msg in stats["多匹配"]:
            print(f"   - {name}: {msg}")
    
    print(f"\n[ERROR] 错误: {len(stats['错误'])} 个")
    if stats["错误"]:
        for name, msg in stats["错误"]:
            print(f"   - {name}: {msg}")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()
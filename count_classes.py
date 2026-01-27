import os
import json
from collections import Counter

def count_classes():
    """统计所有角色的职阶分布"""
    chara_dir = "chara"
    class_counter = Counter()
    
    # 遍历chara目录下的所有子目录
    for name in os.listdir(chara_dir):
        data_path = os.path.join(chara_dir, name, "data.json")
        
        # 检查data.json是否存在
        if os.path.exists(data_path):
            try:
                with open(data_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                # 获取职阶字段
                if "职阶" in data:
                    class_name = data["职阶"]
                    class_counter[class_name] += 1
                else:
                    print(f"警告: {name} 的 data.json 中没有'职阶'字段")
                    
            except json.JSONDecodeError as e:
                print(f"错误: 无法解析 {data_path}: {e}")
            except Exception as e:
                print(f"错误: 读取 {data_path} 时出错: {e}")
    
    # 输出统计结果
    print("=" * 50)
    print("职阶统计结果")
    print("=" * 50)
    print(f"\n总共有 {len(class_counter)} 种不同的职阶\n")
    
    # 按出现次数降序排列
    print("按出现次数排序:")
    print("-" * 30)
    for class_name, count in class_counter.most_common():
        print(f"  {class_name}: {count} 次")
    
    print("-" * 30)
    print(f"总计: {sum(class_counter.values())} 个角色")
    
    return class_counter

if __name__ == "__main__":
    count_classes()
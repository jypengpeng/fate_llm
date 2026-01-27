import requests

def save_all_servants(filename="servants_list.txt"):
    api_url = "https://fgo.wiki/api.php"
    
    # 初始化参数
    params = {
        "action": "query",
        "format": "json",
        "list": "categorymembers",
        "cmtitle": "Category:从者",
        "cmlimit": "500"
    }

    all_names = []
    
    print("正在从 Mooncell 获取英灵列表...")

    # 使用循环处理分页逻辑（以防以后从者超过500个）
    while True:
        try:
            response = requests.get(api_url, params=params, timeout=10)
            data = response.json()
            
            members = data.get('query', {}).get('categorymembers', [])
            for member in members:
                name = member['title']
                # 过滤掉一些系统页面或模板页面
                if not any(exclude in name for exclude in ["Category:", "Template:", "Data:", "列表"]):
                    all_names.append(name)
            
            # 检查是否还有下一页
            if 'continue' in data:
                params.update(data['continue'])
            else:
                break
                
        except Exception as e:
            print(f"发生错误: {e}")
            break

    # 写入文件
    if all_names:
        # 使用 utf-8-sig 编码，确保在 Windows 记事本打开不乱码
        with open(filename, "w", encoding="utf-8-sig") as f:
            for name in all_names:
                f.write(name + "\n")
        
        print(f"🎉 成功！已抓取 {len(all_names)} 个英灵。")
        print(f"📁 结果已保存至: {filename}")
    else:
        print("❌ 未获取到任何数据。")

if __name__ == "__main__":
    save_all_servants()
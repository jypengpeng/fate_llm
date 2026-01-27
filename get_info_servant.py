import requests
import re
import os
import json
import time

# --- 配置参数 ---
BASE_DIR = "chara"
LIST_FILE = "servants_list.txt"
API_URL = "https://fgo.wiki/api.php"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def get_image_url(filename):
    """
    通过文件名获取真实的图片下载链接
    """
    if not filename: return None
    # 补全文件名格式，Mooncell 通常使用 .png 或 .jpg
    file_title = f"File:{filename}.png"
    params = {
        "action": "query",
        "prop": "imageinfo",
        "titles": file_title,
        "iiprop": "url",
        "format": "json"
    }
    try:
        res = requests.get(API_URL, params=params, headers=HEADERS, timeout=10).json()
        pages = res.get("query", {}).get("pages", {})
        for k, v in pages.items():
            if "imageinfo" in v:
                return v["imageinfo"][0]["url"]
    except:
        return None
    return None

def download_file(url, save_path):
    """
    下载文件到指定路径
    """
    try:
        r = requests.get(url, headers=HEADERS, stream=True, timeout=30)
        if r.status_code == 200:
            with open(save_path, 'wb') as f:
                for chunk in r.iter_content(1024):
                    f.write(chunk)
            return True
    except:
        pass
    return False

def parse_wikitext(content):
    """
    解析 Wikitext 核心逻辑
    """
    result = {}
    # 1. 基础字段提取
    basic_fields = [
        "中文名", "日文名", "英文名", "中文战斗名", "日文战斗名", "中文卡面名", "日文卡面名", "英文卡面名",
        "属性1", "属性2", "性别", "身高", "体重", "副属性", "职阶", 
        "筋力", "耐久", "敏捷", "魔力", "幸运", "宝具", "人型", "被EA特攻", "昵称"
    ]
    for field in basic_fields:
        pattern = r"\|" + field + r"\s*=\s*(.*?)(?:\n|\||\}\})"
        match = re.search(pattern, content)
        if match:
            result[field] = match.group(1).strip()

    # 2. 动态列表提取
    # 特性
    result["特性"] = []
    i = 1
    while True:
        pattern = r"\|特性" + str(i) + r"\s*=\s*(.*?)(?:\n|\||\}\})"
        match = re.search(pattern, content)
        if match and match.group(1).strip():
            result["特性"].append(match.group(1).strip())
            i += 1
        else: break

    # 立绘与文件名
    result["卡面立绘"] = []
    i = 1
    while True:
        l_pattern = r"\|立绘" + str(i) + r"\s*=\s*(.*?)(?:\n|\||\}\})"
        f_pattern = r"\|文件" + str(i) + r"\s*=\s*(.*?)(?:\n|\||\}\})"
        l_match = re.search(l_pattern, content)
        f_match = re.search(f_pattern, content)
        if l_match and f_match:
            result["卡面立绘"].append({
                "名称": l_match.group(1).strip(),
                "文件名": f_match.group(1).strip()
            })
            i += 1
        else: break

    # 个人资料与详情
    detail_match = re.search(r"\|详情\s*=\s*(.*?)(?=\n\|详情日文|\|资料1)", content, re.DOTALL)
    if detail_match:
        result["详情描述"] = detail_match.group(1).strip()

    result["资料列表"] = []
    i = 1
    while True:
        pattern = r"\|资料" + str(i) + r"\s*=\s*(.*?)(?=\n\|资料" + str(i) + r"日文|\|资料" + str(i+1) + r"|\}\}|\|资料" + str(i) + r"条件)"
        c_match = re.search(pattern, content, re.DOTALL)
        if c_match:
            result["资料列表"].append(c_match.group(1).strip())
            i += 1
        else: break

    # 3. 宝具解析
    np_blocks = re.findall(r"\{\{宝具(.*?)\}\}", content, re.DOTALL)
    result["宝具列表"] = []
    for block in np_blocks:
        np_info = {}
        for f in ["中文名", "国服上标", "日文名", "日服上标", "卡色", "类型", "阶级", "种类"]:
            m = re.search(r"\|" + f + r"\s*=\s*(.*?)(?:\n|\|)", block)
            if m: np_info[f] = m.group(1).strip()
        
        np_info["效果"] = []
        for char in ['A', 'B', 'C', 'D']:
            effect_m = re.search(r"\|效果" + char + r"\s*=\s*(.*?)(?:\n|\|)", block)
            if effect_m:
                effect_data = {"描述": effect_m.group(1).strip(), "数值": []}
                for num in range(1, 6):
                    val_m = re.search(r"\|数值" + char + str(num) + r"\s*=\s*(.*?)(?:\n|\|)", block)
                    if val_m: effect_data["数值"].append(val_m.group(1).strip())
                np_info["效果"].append(effect_data)
        result["宝具列表"].append(np_info)

    return result

def start_collect(servant_name):
    # 1. 建立目录结构
    safe_name = servant_name.replace("/", "／").replace(":", "：").replace("*", "＊").replace("?", "？")
    servant_dir = os.path.join(BASE_DIR, safe_name)
    img_dir = os.path.join(servant_dir, "images")
    
    for d in [servant_dir, img_dir]:
        if not os.path.exists(d): os.makedirs(d)

    # 2. 获取源码
    params = {"action": "query", "prop": "revisions", "titles": servant_name, "rvprop": "content", "rvslots": "main", "format": "json"}
    try:
        print(f">>> 正在抓取: {servant_name}")
        res = requests.get(API_URL, params=params, headers=HEADERS, timeout=15).json()
        pages = res.get("query", {}).get("pages", {})
        page_id = list(pages.keys())[0]
        if page_id == "-1": return

        wikitext = pages[page_id]["revisions"][0]["slots"]["main"]["*"]
        
        # 保存源码
        with open(os.path.join(servant_dir, "raw_source.txt"), "w", encoding="utf-8") as f:
            f.write(wikitext)

        # 3. 解析 JSON
        data_json = parse_wikitext(wikitext)
        with open(os.path.join(servant_dir, "data.json"), "w", encoding="utf-8") as f:
            json.dump(data_json, f, ensure_ascii=False, indent=4)

        # 4. 下载图片
        print(f"    正在下载 {servant_name} 的图片资源...")
        for pic in data_json.get("卡面立绘", []):
            filename = pic["文件名"]
            img_url = get_image_url(filename)
            if img_url:
                # 保持原文件名并添加后缀
                ext = img_url.split('.')[-1]
                save_path = os.path.join(img_dir, f"{filename}.{ext}")
                if not os.path.exists(save_path):
                    if download_file(img_url, save_path):
                        print(f"    [成功] {filename}")
                    else:
                        print(f"    [失败] {filename}")
            time.sleep(0.5) # 稍微停顿，保护服务器

    except Exception as e:
        print(f"❌ 错误 ({servant_name}): {e}")

if __name__ == "__main__":
    # 检查名单文件
    if not os.path.exists(LIST_FILE):
        print(f"错误：找不到 {LIST_FILE}，请先运行名单抓取脚本。")
    else:
        # 读取全量名单
        with open(LIST_FILE, "r", encoding="utf-8-sig") as f:
            all_servants = [line.strip() for line in f if line.strip()]
        
        print(f"开始采集，共计 {len(all_servants)} 个从者...")
        
        # 逐个开始任务
        for name in all_servants:
            start_collect(name)
            time.sleep(1) # 每个从者间隔1秒
        
        print("\n✨ 所有任务已完成！")
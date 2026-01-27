import requests
import re
import os
import json
import time

# --- 配置 ---
BASE_DIR = "chara"
LIST_FILE = "servants_list.txt"
API_URL = "https://fgo.wiki/api.php"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def get_audio_url(filename):
    """通过文件名获取 mp3 下载链接 (文件名可能自带 .mp3)"""
    if not filename: return None
    # 如果文件名没有后缀，补上 .mp3
    full_title = filename if "." in filename else f"{filename}.mp3"
    
    params = {
        "action": "query",
        "prop": "imageinfo",
        "titles": f"File:{full_title}",
        "iiprop": "url",
        "format": "json"
    }
    try:
        res = requests.get(API_URL, params=params, headers=HEADERS, timeout=10).json()
        pages = res.get("query", {}).get("pages", {})
        for v in pages.values():
            if "imageinfo" in v:
                return v["imageinfo"][0]["url"]
    except: return None
    return None

def download_audio(url, save_path):
    try:
        r = requests.get(url, headers=HEADERS, stream=True, timeout=30)
        if r.status_code == 200:
            with open(save_path, 'wb') as f:
                for chunk in r.iter_content(1024):
                    f.write(chunk)
            return True
    except: pass
    return False

def parse_voice_table_invoke(wikitext):
    """
    专门解析 #invoke:VoiceTable 结构的 Wikitext
    """
    all_entries = []
    
    # 1. 找到所有的表格块
    blocks = re.findall(r"\{\{#invoke:VoiceTable\|table\|(.*?)\}\}", wikitext, re.DOTALL)
    
    for block in blocks:
        # 2. 在每个块里循环寻找数字编号的字段 (标题1, 标题2...)
        i = 1
        while True:
            # 匹配标题
            title_p = r"\|标题" + str(i) + r"\s*=\s*(.*?)(?=\s*\||\s*\}\})"
            title_m = re.search(title_p, block, re.DOTALL)
            
            if not title_m:
                break # 这个块抓完了
            
            entry = {"标题": title_m.group(1).strip()}
            
            # 匹配对应的日文、中文、语音文件名
            for key, field_prefix in [("日文", "日文"), ("中文", "中文"), ("文件名", "语音")]:
                p = r"\|" + field_prefix + str(i) + r"\s*=\s*(.*?)(?=\s*\||\s*\}\})"
                m = re.search(p, block, re.DOTALL)
                entry[key] = m.group(1).strip() if m else ""
            
            # 简单清洗台词里的 {{黑幕|...}} 标签
            for k in ["日文", "中文"]:
                entry[k] = re.sub(r"\{\{黑幕\|(.*?)\}\}", r"\1", entry[k])
            
            all_entries.append(entry)
            i += 1
            
    return all_entries

def scrape_servant_voices(servant_name):
    safe_name = servant_name.replace("/", "／").replace(":", "：").replace("*", "＊").replace("?", "？")
    servant_dir = os.path.join(BASE_DIR, safe_name)
    
    if not os.path.exists(servant_dir):
        return

    voice_page = f"{servant_name}/语音"
    params = {
        "action": "query", "prop": "revisions", "titles": voice_page,
        "rvprop": "content", "rvslots": "main", "format": "json"
    }

    try:
        print(f"正在抓取台词: {servant_name}")
        res = requests.get(API_URL, params=params, headers=HEADERS, timeout=15).json()
        pages = res.get("query", {}).get("pages", {})
        page_id = list(pages.keys())[0]
        
        if page_id == "-1":
            print(f"  [跳过] 无语音页")
            return

        wikitext = pages[page_id]["revisions"][0]["slots"]["main"]["*"]
        
        # 解析数据
        voice_data = parse_voice_table_invoke(wikitext)
        
        # 保存 JSON (包含所有台词文本)
        json_path = os.path.join(servant_dir, "voices.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(voice_data, f, ensure_ascii=False, indent=4)
        
        # 只下载召唤语音
        for v in voice_data:
            if v["标题"] == "召唤" and v["文件名"]:
                print(f"  发现召唤语音，正在下载: {v['文件名']}")
                audio_url = get_audio_url(v["文件名"])
                if audio_url:
                    # 统一保存为 召唤语音.mp3
                    save_path = os.path.join(servant_dir, "召唤语音.mp3")
                    download_audio(audio_url, save_path)
                    print(f"  [成功] 已保存召唤音频")
                break

    except Exception as e:
        print(f"  ❌ 出错: {e}")

if __name__ == "__main__":
    if os.path.exists(LIST_FILE):
        with open(LIST_FILE, "r", encoding="utf-8-sig") as f:
            names = [line.strip() for line in f if line.strip()]
        
        for name in names:
            scrape_servant_voices(name)
            time.sleep(0.5)
    print("✨ 任务完成！")
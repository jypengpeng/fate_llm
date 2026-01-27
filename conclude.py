import os
import json
import asyncio
import aiofiles
from openai import AsyncOpenAI

# ================= 配置区域 =================
API_KEY = "moeblack"
BASE_URL = "https://gravity.kuronet.top/v1"
MODEL_NAME = "gemini-3-flash"  # 或 gpt-4o 等
CONCURRENCY_LIMIT = 5  # 并发数
ROOT_DIR = r"chara" # 你的数据根目录
# ===========================================

client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)
semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

async def process_servant(servant_name, servant_path):
    data_file = os.path.join(servant_path, "data.json")
    
    if not os.path.exists(data_file):
        print(f"[跳过] {servant_name}: 找不到 data.json")
        return

    async with semaphore:
        try:
            # 1. 读取原始数据
            async with aiofiles.open(data_file, 'r', encoding='utf-8') as f:
                content = await f.read()
                raw_data = json.loads(content)

            # 2. 准备发送给 LLM 的精简上下文（减少 token 浪费）
            # 只提取对生成关键词有用的部分
            context = {
                "名字": raw_data.get("中文名"),
                "职阶": raw_data.get("职阶"),
                "昵称": raw_data.get("昵称"),
                "属性": f"{raw_data.get('属性1')}{raw_data.get('属性2')}",
                "详情描述": raw_data.get("详情描述"),
                "资料列表": raw_data.get("资料列表", [])[:3], # 取前三段核心资料
                "宝具": [b.get("中文名") for b in raw_data.get("宝具列表", [])]
            }

            # 3. 构造 Prompt
            prompt = f"""
你是一个Fate/Grand Order专家。请阅读以下英灵数据，并提取出两个字段：
1. 「召唤关联词」：包含圣遗物、历史典故物品、核心外貌特征、相关地名等（5-10个词）。
2. 「性格相性简述」：简述其性格，并说明什么样的御主（Master）最容易召唤他或与他相性最好。

英灵数据：
{json.dumps(context, ensure_ascii=False)}

请严格按以下JSON格式输出，不要包含其他文字：
{{
  "召唤关联词": ["词1", "词2", ...],
  "性格相性简述": "..."
}}
"""

            # 4. 请求 LLM
            response = await client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            
            res_content = json.loads(response.choices[0].message.content)

            # 5. 写回数据
            raw_data["召唤关联词"] = res_content.get("召唤关联词", [])
            raw_data["性格相性简述"] = res_content.get("性格相性简述", "")

            async with aiofiles.open(data_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(raw_data, ensure_ascii=False, indent=4))
            
            print(f"[成功] {servant_name} 处理完毕")

        except Exception as e:
            print(f"[错误] {servant_name} 处理失败: {str(e)}")

async def main():
    tasks = []
    # 遍历文件夹
    if not os.path.exists(ROOT_DIR):
        print(f"目录不存在: {ROOT_DIR}")
        return

    for servant_name in os.listdir(ROOT_DIR):
        servant_path = os.path.join(ROOT_DIR, servant_name)
        if os.path.isdir(servant_path):
            tasks.append(process_servant(servant_name, servant_path))

    print(f"开始处理，总计 {len(tasks)} 个英灵...")
    await asyncio.gather(*tasks)
    print("所有任务已完成。")

if __name__ == "__main__":
    asyncio.run(main())
"""
英灵召唤系统后端 API
Fate Servant Summoning System Backend API

包含:
- 召唤系统 API (/api/summon, /api/generate_story)
- 游戏初始化 API (/api/init_game)
- 旧版游戏行动 API (/api/game_action) - LLM直接生成
- 新版游戏回合 API (/api/game_turn) - 三阶段流水线
"""

import os
import json
import re
import requests
import concurrent.futures
import asyncio
from urllib.parse import quote
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

# 导入游戏引擎模块
from game_engine import (
    GodView,
    CharacterState,
    ServantClass,
    ServantParameters,
    LocationNode,
    AIContext,
    HealthStatus,
    RelationshipStatus,
    GameResponse,
    process_game_turn_sync,
)

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend access

# LLM Configuration
LLM_API_URL = os.getenv('LLM_API_URL', 'https://api.openai.com/v1/chat/completions')
LLM_API_KEY = os.getenv('LLM_API_KEY', '')
LLM_MODEL_ID = os.getenv('LLM_MODEL_ID', 'gpt-4')

# Class name mappings (English to Chinese and variations)
CLASS_MAPPINGS = {
    'saber': ['Saber', 'saber'],
    'archer': ['Archer', 'archer'],
    'lancer': ['Lancer', 'lancer'],
    'rider': ['Rider', 'rider'],
    'caster': ['Caster', 'caster'],
    'assassin': ['Assassin', 'assassin'],
    'berserker': ['Berserker', 'berserker'],
    'ruler': ['Ruler', 'ruler'],
    'avenger': ['Avenger', 'avenger'],
    'mooncancer': ['MoonCancer', 'mooncancer', 'Moon Cancer'],
    'alterego': ['Alterego', 'alterego', 'Alter Ego'],
    'foreigner': ['Foreigner', 'foreigner'],
    'pretender': ['Pretender', 'pretender'],
    'shielder': ['Shielder', 'shielder'],
    'beast': ['Beast', 'beast'],
    'unbeast': ['UnBeast', 'unbeast']
}

# Class-specific incantation patterns (used to detect if user selected a class)
CLASS_INCANTATIONS = {
    'saber': '此地即为王庭。吾之命系于汝剑，汝之剑系于吾命。——回应吧，斩断宿命之钢！',
    'archer': '星辰虽远，其光必至。跨越千之山丘，万之河川……哪怕是这天理的尽头，汝亦能看清吧？',
    'lancer': '以吾血为路，以吾气为风！不需要盾，亦无需铠，只求那贯穿万象的刹那之光——突进！',
    'rider': '通往尽头的门已开。无需回头，前方即是吾等的疆域。带上那暴风的缰绳，与我一同蹂躏这大地！',
    'caster': '第一术式展开，基盘定础。汲取深渊之水，烧却愚者之土。以睿智之理为钥，在此编织虚幻的神殿。',
    'assassin': '夜幕已至，万物沉寂。吾在此献上一盏残烛……请收下这无名的影子，赐予他们平等的终结。',
    'berserker': '……听得见吗？那就发狂吧。自蒙双眼，囚于槛中！此乃剥夺理智之锁，化作吞噬敌我的野兽咆哮吧！'
}


def load_characters():
    """Load character data from characters_info.json"""
    try:
        with open('characters_info.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading characters_info.json: {e}")
        return []


def detect_class_from_incantation(extra_text):
    """
    Detect if the user selected a class-specific incantation.
    Returns the class name if detected, None otherwise.
    """
    if not extra_text:
        return None
    
    for class_name, incantation in CLASS_INCANTATIONS.items():
        # Check if the extra text starts with or contains the class incantation
        if incantation in extra_text:
            return class_name
    
    return None


def filter_by_class(characters, class_name):
    """
    Filter characters by class.
    Returns only characters of the specified class.
    """
    if not class_name:
        return characters
    
    class_variations = CLASS_MAPPINGS.get(class_name.lower(), [class_name])
    
    filtered = []
    for char in characters:
        char_class = char.get('职阶', '')
        if char_class in class_variations:
            filtered.append(char)
    
    return filtered if filtered else characters  # Return all if no match found


def build_summoning_pool_text(characters):
    """
    Build a text representation of the summoning pool for the LLM.
    """
    pool_lines = []
    for char in characters:
        name = char.get('中文名', '')
        char_class = char.get('职阶', '')
        keywords = char.get('召唤关联词', [])
        personality = char.get('性格相性简述', '')
        
        if name:
            line = f"- {name} ({char_class})"
            if keywords:
                line += f"，召唤关联词：{', '.join(keywords[:5])}"
            if personality:
                # Truncate personality description to save tokens
                short_personality = personality[:100] + "..." if len(personality) > 100 else personality
                line += f"，相性：{short_personality}"
            pool_lines.append(line)
    
    return "\n".join(pool_lines)


def build_prompt(master_intro, relic, vow, extra_text, summoning_pool_text):
    """
    Build the prompt for the LLM to select a servant.
    """
    prompt = f"""你是一个Fate系列的英灵召唤系统。根据御主提供的召唤条件，从给定的英灵池中选择一个最合适的从者。

## 召唤条件

### 魔术师背景
{master_intro if master_intro else "（未提供）"}

### 圣遗物
{relic if relic else "（无圣遗物，以御主自身为触媒）"}

### 咒文誓言
{vow if vow else "（未宣告誓言）"}

### 追加咒文
{extra_text if extra_text else "（无追加咒文）"}

## 可召唤的英灵池

{summoning_pool_text}

## 要求

1. 根据上述召唤条件（魔术师背景、圣遗物、咒文誓言、追加咒文）综合分析
2. 从英灵池中选择一个最契合的从者
3. 考虑因素包括：
   - 圣遗物是否与某位英灵有直接关联
   - 召唤关联词是否匹配
   - 御主的性格与英灵的相性
   - 誓言的内涵与英灵的精神契合度
4. 只输出被召唤英灵的中文名，不要输出任何其他内容

被召唤的英灵是："""
    
    return prompt


class LLMError(Exception):
    """Custom exception for LLM-related errors with detailed information"""
    def __init__(self, message, error_type="api_error", raw_response=None, api_error=None):
        super().__init__(message)
        self.error_type = error_type  # "api_error", "parse_error", "config_error"
        self.raw_response = raw_response  # Raw LLM response if available
        self.api_error = api_error  # API error details if available


def call_llm(prompt):
    """
    Call the LLM API and return the response.
    """
    if not LLM_API_KEY:
        raise LLMError(
            "LLM_API_KEY not configured in .env file",
            error_type="config_error"
        )
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LLM_API_KEY}'
    }
    
    payload = {
        'model': LLM_MODEL_ID,
        'messages': [
            {
                'role': 'system',
                'content': '你是一个Fate系列的英灵召唤系统。你的任务是根据召唤条件从英灵池中选择最合适的从者，并只输出该从者的中文名。'
            },
            {
                'role': 'user',
                'content': prompt
            }
        ],
        'temperature': 0.7,
        'max_tokens': 50  # We only need the servant name
    }
    
    try:
        response = requests.post(LLM_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        
        result = response.json()
        
        # Extract the content from the response
        if 'choices' in result and len(result['choices']) > 0:
            content = result['choices'][0].get('message', {}).get('content', '')
            if not content or not content.strip():
                raise LLMError(
                    "LLM returned empty content",
                    error_type="parse_error",
                    raw_response=json.dumps(result, ensure_ascii=False, indent=2)
                )
            # Clean up the response - extract just the name
            servant_name = content.strip()
            # Remove any extra text or punctuation
            servant_name = re.sub(r'^[「『【\[]?', '', servant_name)
            servant_name = re.sub(r'[」』】\]]?$', '', servant_name)
            servant_name = servant_name.strip()
            return servant_name
        else:
            raise LLMError(
                "Unexpected LLM response format",
                error_type="parse_error",
                raw_response=json.dumps(result, ensure_ascii=False, indent=2)
            )
            
    except requests.exceptions.RequestException as e:
        # Try to get error details from response if available
        api_error_detail = None
        try:
            if hasattr(e, 'response') and e.response is not None:
                api_error_detail = e.response.text
        except:
            pass
        
        raise LLMError(
            f"LLM API request failed: {str(e)}",
            error_type="api_error",
            api_error=api_error_detail
        )


def validate_servant_name(name, characters):
    """
    Validate that the returned servant name exists in our character pool.
    Returns the exact name from the pool if found, or the original name if not.
    
    Handles both data formats:
    - Original character data: uses key '中文名'
    - get_servants_by_class output: uses key 'name'
    """
    # Helper to get character name from either format
    def get_char_name(char):
        return char.get('中文名', '') or char.get('name', '')
    
    # Try exact match first
    for char in characters:
        char_name = get_char_name(char)
        if char_name == name:
            return name
    
    # Try partial matching (but skip empty strings to avoid false matches)
    for char in characters:
        char_name = get_char_name(char)
        if char_name and name:  # Both must be non-empty
            if name in char_name or char_name in name:
                return char_name
    
    # If no match found, return original (the LLM might have hallucinated)
    return name


@app.route('/api/summon', methods=['POST'])
def summon():
    """
    Handle the summon request.
    
    Expected JSON body:
    {
        "masterIntro": "魔术师背景",
        "relic": "圣遗物",
        "vow": "咒文誓言",
        "extraText": "追加咒文"
    }
    
    Returns:
    {
        "success": true,
        "servantName": "从者中文名"
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400
        
        master_intro = data.get('masterIntro', '')
        relic = data.get('relic', '')
        vow = data.get('vow', '')
        extra_text = data.get('extraText', '')
        
        # Load all characters
        all_characters = load_characters()
        
        if not all_characters:
            return jsonify({
                'success': False,
                'error': 'Failed to load character data'
            }), 500
        
        # Check if a class-specific incantation was used
        detected_class = detect_class_from_incantation(extra_text)
        
        # Filter characters by class if applicable
        summoning_pool = filter_by_class(all_characters, detected_class)
        
        print(f"Detected class: {detected_class}")
        print(f"Summoning pool size: {len(summoning_pool)} (from {len(all_characters)} total)")
        
        # Build the summoning pool text
        pool_text = build_summoning_pool_text(summoning_pool)
        
        # Build the prompt
        prompt = build_prompt(master_intro, relic, vow, extra_text, pool_text)
        
        # Call the LLM
        servant_name = call_llm(prompt)
        
        # Validate the servant name
        validated_name = validate_servant_name(servant_name, summoning_pool)
        
        print(f"LLM returned: {servant_name}, Validated: {validated_name}")
        
        return jsonify({
            'success': True,
            'servantName': validated_name,
            'detectedClass': detected_class
        })
        
    except LLMError as e:
        error_response = {
            'success': False,
            'error': str(e),
            'errorType': e.error_type
        }
        if e.raw_response:
            error_response['rawResponse'] = e.raw_response
        if e.api_error:
            error_response['apiError'] = e.api_error
        return jsonify(error_response), 400
    except ValueError as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'errorType': 'validation_error'
        }), 400
    except Exception as e:
        print(f"Error in summon endpoint: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'errorType': 'unknown_error'
        }), 500


def load_name_to_path():
    """Load the name to path mapping"""
    try:
        with open('name_to_path.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading name_to_path.json: {e}")
        return {}


def normalize_servant_name(name):
    """
    Normalize servant name by removing quotes and extra whitespace.
    Handles both Chinese quotes ("") and English quotes ("").
    """
    if not name:
        return name
    # Remove Chinese quotes
    name = name.replace('"', '').replace('"', '')
    # Remove English quotes
    name = name.replace('"', '').replace("'", '')
    # Remove brackets that might be added
    name = name.replace('「', '').replace('」', '')
    name = name.replace('『', '').replace('』', '')
    name = name.replace('【', '').replace('】', '')
    name = name.replace('[', '').replace(']', '')
    # Strip whitespace
    return name.strip()


def get_servant_data(servant_name):
    """
    Get servant data from data.json using name_to_path.json mapping.
    Returns the servant data and the base path for other files.
    """
    name_to_path = load_name_to_path()
    
    # Normalize the input name
    normalized_input = normalize_servant_name(servant_name)
    
    # Find the data.json path for this servant
    data_path = name_to_path.get(servant_name)
    
    if not data_path:
        # Try exact match with normalized names
        for name, path in name_to_path.items():
            if normalize_servant_name(name) == normalized_input:
                data_path = path
                break
    
    if not data_path:
        # Try partial matching with normalized names
        for name, path in name_to_path.items():
            normalized_key = normalize_servant_name(name)
            if normalized_input in normalized_key or normalized_key in normalized_input:
                data_path = path
                break
    
    if not data_path:
        return None, None
    
    # Extract the base directory path
    base_path = '/'.join(data_path.split('/')[:-1])
    
    try:
        with open(data_path, 'r', encoding='utf-8') as f:
            return json.load(f), base_path
    except Exception as e:
        print(f"Error loading servant data from {data_path}: {e}")
        return None, None


def get_servant_images(base_path):
    """
    Get list of available images for a servant, sorted in descending order.
    Returns a list of image filenames.
    """
    images_path = f"{base_path}/images"
    
    try:
        # Normalize path for Windows (handle special characters)
        images_path_normalized = os.path.normpath(images_path)
        
        if os.path.exists(images_path_normalized) and os.path.isdir(images_path_normalized):
            # Get all image files (png, jpg, jpeg, webp)
            image_extensions = ('.png', '.jpg', '.jpeg', '.webp')
            images = [f for f in os.listdir(images_path_normalized)
                     if f.lower().endswith(image_extensions)]
            # Sort in descending alphabetical order
            images.sort(reverse=True)
            print(f"Found {len(images)} images in {images_path_normalized}: {images[:3]}...")
            return images
        else:
            print(f"Images path does not exist: {images_path_normalized}")
        return []
    except Exception as e:
        print(f"Error listing images from {images_path}: {e}")
        return []


def get_servant_voice(base_path, voice_title="召唤"):
    """
    Get a specific voice line from voices.json.
    """
    voices_path = f"{base_path}/voices.json"
    
    try:
        with open(voices_path, 'r', encoding='utf-8') as f:
            voices = json.load(f)
            
        # Find the voice with the matching title
        for voice in voices:
            if voice.get('标题') == voice_title:
                return voice.get('中文', '')
        
        return None
    except Exception as e:
        print(f"Error loading voices from {voices_path}: {e}")
        return None


def build_story_prompt(master_info, servant_data, summon_voice, location_info=None):
    """
    Build the prompt for generating the summoning story.
    Now includes location selection based on master background.
    """
    # Extract relevant servant data
    name = servant_data.get('中文名', '')
    attribute1 = servant_data.get('属性1', '')
    attribute2 = servant_data.get('属性2', '')
    gender = servant_data.get('性别', '')
    height = servant_data.get('身高', '')
    weight = servant_data.get('体重', '')
    servant_class = servant_data.get('职阶', '')
    strength = servant_data.get('筋力', '')
    endurance = servant_data.get('耐久', '')
    agility = servant_data.get('敏捷', '')
    mana = servant_data.get('魔力', '')
    luck = servant_data.get('幸运', '')
    traits = servant_data.get('特性', [])
    description = servant_data.get('详情描述', '')
    profiles = servant_data.get('资料列表', [])
    
    # Build location choices text
    location_choices = """
## 可选的召唤地点（请根据御主背景选择最合适的一个）

以下是冬木市的可用地点，请根据御主的背景和召唤条件选择最合适的召唤地点：

1. **tohsaka_manor（远坂邸）** - 远坂家的宅邸，强大的魔术工房，适合正统魔术师家族
2. **emiya_residence（卫宫宅）** - 有小型工房的日式住宅，适合普通人或自学魔术师
3. **church（言峰教会）** - 圣杯战争的中立地带，适合与教会有关联的人
4. **ryuudou_temple（柳洞寺）** - 灵脉中心的佛教寺院，魔力浓度极高，适合需要强大魔力的召唤
5. **harbor（港口仓库区）** - 废弃区域，无人打扰，适合秘密召唤
6. **fuyuki_bridge（冬木大桥）** - 开阔地形，适合戏剧性的召唤
7. **einzbern_forest（爱因兹贝伦森林）** - 神秘森林，适合与自然相关的召唤
8. **park（冬木公园）** - 十年前大火遗址，适合有宿命感的召唤

选择原则：
- 如果御主是名门魔术师 → 可能在自己的工房（如远坂邸）
- 如果御主是普通人/初学者 → 可能在偏僻处（港口、森林、公园）
- 如果御主与教会有关 → 言峰教会
- 如果御主需要强大魔力支持 → 柳洞寺
- 如果御主想要秘密行事 → 港口仓库区或森林
"""
    
    # Build servant description
    servant_desc = f"""
## 英灵资料

- 真名：{name}
- 职阶：{servant_class}
- 性别：{gender}
- 身高/体重：{height} / {weight}
- 属性：{attribute1}·{attribute2}
- 能力值：筋力 {strength} / 耐久 {endurance} / 敏捷 {agility} / 魔力 {mana} / 幸运 {luck}
- 特性：{', '.join(traits) if traits else '无'}

### 详情描述
{description}

### 背景资料
"""
    
    for i, profile in enumerate(profiles[:3]):  # Limit to first 3 profiles to save tokens
        servant_desc += f"\n{profile}\n"
    
    # Build the complete prompt
    prompt = f"""你是一位擅长Type-Moon世界观写作的小说家。请根据以下信息，撰写一段800字以上的召唤场景描写。

## 魔术师（御主）信息

### 魔术师背景
{master_info.get('masterIntro', '（未提供）')}

### 圣遗物
{master_info.get('relic', '（无圣遗物）')}

### 咒文誓言
{master_info.get('vow', '（未宣告誓言）')}

### 追加咒文
{master_info.get('extraText', '（无追加咒文）')}

{location_choices}

{servant_desc}

### 召唤台词（此为英灵唯一的台词）
「{summon_voice}」

## 写作要求

1. **【首先】根据御主背景选择召唤地点**：在故事开头，根据御主的背景、性格、处境选择最合适的召唤地点，并在故事中描写这个地点的环境。
2. 以第二人称视角（"你"）描写召唤场景，让读者沉浸其中
3. 描写必须契合Type-Moon世界观，使用魔术、英灵、从者等专有名词
4. 场景描写要细腻生动，包括：
   - **召唤地点的环境描写**（根据你选择的地点）
   - 召唤阵的光芒变化
   - 魔力流动的感受
   - 空间/时间的扭曲
   - 英灵现身的方式（要符合该英灵的特点和职阶）
   - 英灵的外貌、气势描写
5. 全文800字以上，营造史诗感和仪式感
6. **极其重要**：英灵在整个场景中只会说一句话，就是上面给出的"召唤台词"。故事中不能出现英灵说的任何其他台词或对话。
7. 你的叙事需要自然地铺垫，让读者感受到英灵现身的过程，最终在文章结尾处，当英灵终于要开口说出那唯一的台词时，用 [[VOICE]] 作为占位符代替实际台词内容。
8. 结尾示例：他/她凝视着你，嘴唇轻启，用那独属于英灵的声音宣告——[[VOICE]]
9. 不要在 [[VOICE]] 之后添加任何内容，[[VOICE]] 必须是文章的最后一个词。

## 输出格式要求

**重要：你的输出必须按以下格式：**

第一行必须是：
LOCATION: <地点ID>

例如：
LOCATION: ryuudou_temple

然后空一行，接着是召唤故事正文。

## 【最高优先级·禁止违反】关于英灵真名的保密要求

**绝对禁止在故事中透露英灵的真名！** 这是最重要的规则，必须严格遵守。

- 禁止直接写出英灵的真名（如"迦尔纳"、"阿尔托莉雅"、"伊斯坎达尔"等）
- 禁止通过称号直接点明身份（如"太阳神之子"、"征服王"、"骑士王"等明确指向特定英灵的称号）
- 禁止提及英灵来自哪部史诗、传说或历史（如"《摩诃婆罗多》的英雄"、"不列颠的王"等）
- 禁止写出"这便是XXX"这样的揭示身份的句子

**正确的做法：** 通过侧面描写来暗示英灵的特征，让读者产生期待和猜测：
- 描写外貌特征：发色、眼眸颜色、肤色、身形、表情等
- 描写服饰装备：铠甲样式、武器轮廓（但不要说出武器的真名）、饰品等
- 描写气质氛围：威严、温柔、疯狂、高贵、冷酷等气场
- 描写抽象感受：如"王者的威压"、"战士的气息"、"魔力的颜色"等
- 可以用模糊的暗示：如"那仿佛能照亮世界的光芒"、"带着异国风情的装束"等

**例子：**
- ❌ 错误："这便是迦尔纳。印度两大史诗之一《摩诃婆罗多》中最为悲壮的大英雄。"
- ✅ 正确："一道仿佛太阳般耀眼的光芒中，一位身披黄金铠甲的男子现身。他的眼眸平静如深潭，白皙的肌肤上隐约可见奇异的纹路，仿佛与生俱来的印记。"

请开始创作（记住第一行必须是 LOCATION: <地点ID>）："""

    return prompt


def call_llm_for_story(prompt):
    """
    Call the LLM API to generate the summoning story.
    """
    if not LLM_API_KEY:
        raise LLMError(
            "LLM_API_KEY not configured in .env file",
            error_type="config_error"
        )
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LLM_API_KEY}'
    }
    
    payload = {
        'model': LLM_MODEL_ID,
        'messages': [
            {
                'role': 'system',
                'content': '你是一位精通Type-Moon世界观的小说家，擅长撰写Fate系列风格的召唤场景描写。你的文笔华丽而富有感染力，善于营造史诗般的仪式感。'
            },
            {
                'role': 'user',
                'content': prompt
            }
        ],
        'temperature': 0.8,
        'max_tokens': 4000  # Increased for longer story generation
    }
    
    try:
        response = requests.post(LLM_API_URL, headers=headers, json=payload, timeout=120)
        response.raise_for_status()
        
        result = response.json()
        
        if 'choices' in result and len(result['choices']) > 0:
            content = result['choices'][0].get('message', {}).get('content', '')
            if not content or not content.strip():
                raise LLMError(
                    "LLM returned empty story content",
                    error_type="parse_error",
                    raw_response=json.dumps(result, ensure_ascii=False, indent=2)
                )
            return content.strip()
        else:
            raise LLMError(
                "Unexpected LLM response format for story",
                error_type="parse_error",
                raw_response=json.dumps(result, ensure_ascii=False, indent=2)
            )
            
    except requests.exceptions.RequestException as e:
        # Try to get error details from response if available
        api_error_detail = None
        try:
            if hasattr(e, 'response') and e.response is not None:
                api_error_detail = e.response.text
        except:
            pass
        
        raise LLMError(
            f"LLM API request failed: {str(e)}",
            error_type="api_error",
            api_error=api_error_detail
        )


@app.route('/api/generate_story', methods=['POST'])
def generate_story():
    """
    Generate the summoning story for a servant.
    
    Expected JSON body:
    {
        "servantName": "从者中文名",
        "masterIntro": "魔术师背景",
        "relic": "圣遗物",
        "vow": "咒文誓言",
        "extraText": "追加咒文"
    }
    
    Returns:
    {
        "success": true,
        "story": "召唤故事文本（包含[[VOICE]]占位符）",
        "servantData": { ... },
        "summonVoice": "召唤台词"
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400
        
        servant_name = data.get('servantName', '')
        
        if not servant_name:
            return jsonify({
                'success': False,
                'error': 'Servant name is required'
            }), 400
        
        # Get servant data
        servant_data, base_path = get_servant_data(servant_name)
        
        if not servant_data:
            return jsonify({
                'success': False,
                'error': f'Servant data not found for: {servant_name}'
            }), 404
        
        # Get summon voice
        summon_voice = get_servant_voice(base_path, "召唤")
        
        if not summon_voice:
            summon_voice = "吾应汝之召唤而来。"  # Fallback generic voice line
        
        # Build master info
        master_info = {
            'masterIntro': data.get('masterIntro', ''),
            'relic': data.get('relic', ''),
            'vow': data.get('vow', ''),
            'extraText': data.get('extraText', '')
        }
        
        # Build story prompt
        prompt = build_story_prompt(master_info, servant_data, summon_voice)
        
        print(f"Generating story for: {servant_name}")
        print(f"Summon voice: {summon_voice}")
        
        # Generate story
        story_raw = call_llm_for_story(prompt)
        
        # Parse location from story response
        # Format expected: "LOCATION: <location_id>\n\n<story>"
        selected_location = 'tohsaka_manor'  # 默认值
        story = story_raw
        
        if story_raw.startswith('LOCATION:'):
            lines = story_raw.split('\n', 2)
            if len(lines) >= 1:
                location_line = lines[0].strip()
                location_id = location_line.replace('LOCATION:', '').strip()
                
                # 验证地点ID是否有效
                valid_locations = [
                    'tohsaka_manor', 'emiya_residence', 'church', 'ryuudou_temple',
                    'harbor', 'fuyuki_bridge', 'einzbern_forest', 'park',
                    'miyama_residential', 'shinto', 'school', 'shopping_district'
                ]
                if location_id in valid_locations:
                    selected_location = location_id
                    print(f"LLM selected summoning location: {selected_location}")
                
                # 移除LOCATION行，保留故事正文
                story = '\n'.join(lines[1:]).strip()
        
        # Ensure the story ends with [[VOICE]] placeholder
        if '[[VOICE]]' not in story:
            story += '\n\n[[VOICE]]'
        
        # Get available images (URL-encoded for browser compatibility)
        available_images_raw = get_servant_images(base_path)
        available_images = [quote(img, safe='') for img in available_images_raw]
        
        # Prepare servant data response (subset for frontend)
        servant_response = {
            '中文名': servant_data.get('中文名', ''),
            '英文名': servant_data.get('英文名', ''),
            '属性1': servant_data.get('属性1', ''),
            '属性2': servant_data.get('属性2', ''),
            '职阶': servant_data.get('职阶', ''),
            '筋力': servant_data.get('筋力', ''),
            '耐久': servant_data.get('耐久', ''),
            '敏捷': servant_data.get('敏捷', ''),
            '魔力': servant_data.get('魔力', ''),
            '幸运': servant_data.get('幸运', ''),
            '宝具': servant_data.get('宝具', ''),
            '宝具描述': servant_data.get('宝具描述', ''),
            '资料列表': servant_data.get('资料列表', []),
            '宝具列表': servant_data.get('宝具列表', [])
        }
        
        # URL-encode the base path for browser compatibility
        # Keep the path structure but encode special characters
        base_path_encoded = '/'.join(quote(part, safe='') for part in base_path.split('/')) if base_path else ''
        
        return jsonify({
            'success': True,
            'story': story,
            'servantData': servant_response,
            'summonVoice': summon_voice,
            'basePath': base_path_encoded,
            'availableImages': available_images,
            'selectedLocation': selected_location
        })
        
    except LLMError as e:
        error_response = {
            'success': False,
            'error': str(e),
            'errorType': e.error_type
        }
        if e.raw_response:
            error_response['rawResponse'] = e.raw_response
        if e.api_error:
            error_response['apiError'] = e.api_error
        return jsonify(error_response), 400
    except ValueError as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'errorType': 'validation_error'
        }), 400
    except Exception as e:
        print(f"Error in generate_story endpoint: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'errorType': 'unknown_error'
        }), 500


@app.route('/api/game_action', methods=['POST'])
def game_action():
    """
    Handle player actions during the game.
    
    Expected JSON body:
    {
        "action": "玩家的行动描述",
        "gameState": {
            "day": 1,
            "time": "night",
            "location": "远坂邸",
            "master": { ... },
            "servant": { ... },
            ...
        },
        "godView": {
            "all_combatants": { ... }
        },
        "useCommandSpell": false
    }
    
    Returns:
    {
        "success": true,
        "response": "LLM生成的故事回应",
        "stateUpdates": { ... },
        "newIntel": "新情报",
        "activateNp": false,
        "enemyIntelUpdate": { ... }
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400
        
        action = data.get('action', '')
        game_state = data.get('gameState', {})
        god_view = data.get('godView', {})  # Receive god_view from frontend
        use_command_spell = data.get('useCommandSpell', False)
        
        if not action:
            return jsonify({
                'success': False,
                'error': 'Action is required'
            }), 400
        
        # Build the game action prompt with enemy information
        prompt = build_game_action_prompt(action, game_state, use_command_spell, god_view)
        
        # Call LLM for response
        response_data = call_llm_for_game_action(prompt)
        
        return jsonify({
            'success': True,
            'response': response_data.get('response', ''),
            'stateUpdates': response_data.get('stateUpdates', {}),
            'newIntel': response_data.get('newIntel'),
            'isImportantIntel': response_data.get('isImportantIntel', False),
            'activateNp': response_data.get('activateNp', False),
            'npName': response_data.get('npName'),
            'npRuby': response_data.get('npRuby'),
            'npImage': response_data.get('npImage'),
            'enemyIntelUpdate': response_data.get('enemyIntelUpdate')
        })
        
    except LLMError as e:
        error_response = {
            'success': False,
            'error': str(e),
            'errorType': e.error_type
        }
        if e.raw_response:
            error_response['rawResponse'] = e.raw_response
        if e.api_error:
            error_response['apiError'] = e.api_error
        return jsonify(error_response), 400
    except Exception as e:
        print(f"Error in game_action endpoint: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'errorType': 'unknown_error'
        }), 500


def build_game_action_prompt(action, game_state, use_command_spell, god_view=None):
    """
    Build the prompt for game action processing.
    Now includes enemy information from god_view for realistic encounters.
    """
    master = game_state.get('master', {})
    servant = game_state.get('servant', {})
    current_location = game_state.get('location', '不明')
    
    # Build basic context
    context = f"""## 当前状态

### 时间与地点
- 第{game_state.get('day', 1)}天
- 时间：{game_state.get('time', 'night')}
- 地点：{current_location}

### 御主状态
- 名字：{master.get('name', '御主')}
- 魔力：{master.get('mana', 100)}/{master.get('maxMana', 100)}
- 身体状态：{master.get('physicalStatus', 'healthy')}
- 剩余令咒：{master.get('commandSpells', 3)}画

### 从者状态
- 职阶：{servant.get('class', 'Saber')}
- 真名：{servant.get('trueName', '???')}
- HP：{servant.get('hp', 15000)}/{servant.get('maxHp', 15000)}
- NP：{servant.get('np', 0)}%
- 羁绊等级：{servant.get('bondLevel', 1)}/5

### 当前目标
{game_state.get('objective', '参与圣杯战争')}
"""

    # Build enemy context from god_view
    enemy_context = build_enemy_context(god_view, current_location, servant.get('class', 'Saber'))

    command_spell_note = ""
    if use_command_spell:
        command_spell_note = """
**【令咒发动】** 御主消耗了一画令咒！这是绝对命令，从者必须服从。请在回应中体现令咒的强制效果。
"""

    prompt = f"""你是一个Fate世界观的圣杯战争游戏叙事AI。根据玩家的行动，生成相应的故事回应。

{context}

{enemy_context}

{command_spell_note}

## 玩家行动
{action}

## 写作要求

1. 以第二人称视角（"你"）描写
2. 语言风格要符合Type-Moon世界观
3. 回应长度适中（800-1000字）
4. 用「」表示对话
5. 用*号包裹*表示动作描写
6. 如果涉及战斗或危险，要营造紧张感
7. 如果涉及从者互动，要体现从者的性格
8. 如果玩家在敌人可能出现的地点行动，根据情况决定是否遭遇敌人
9. 遭遇敌人时，不要直接透露敌人的真名，除非是剧情需要的揭示时刻
10. 如果揭示了敌人的信息（职阶、外貌、能力暗示），在enemyIntelUpdate中记录

## 输出格式

请以JSON格式输出，包含以下字段：
```json
{{
    "response": "故事回应文本",
    "stateUpdates": {{
        "mana": 数值变化后的魔力值（可选）,
        "hp": 数值变化后的HP（可选）,
        "np": 数值变化后的NP（可选）,
        "time": "时间变化（可选，day/dusk/night/dawn）",
        "location": "地点变化（可选）",
        "objective": "新目标（可选）"
    }},
    "newIntel": "新获得的情报（可选，如果没有则为null）",
    "isImportantIntel": false,
    "activateNp": false,
    "enemyIntelUpdate": {{
        "servantClass": "发现的敌人职阶（可选，如Archer）",
        "revealedTrueName": "揭示的真名（可选，重大剧情时刻）",
        "info": "获得的关于该敌人的情报（可选）",
        "lastSeenLocation": "最后目击地点（可选）"
    }}
}}
```

注意：
- 只有当状态真正发生变化时才在stateUpdates中包含对应字段
- 如果行动涉及释放宝具，设置activateNp为true
- 魔力消耗：普通行动不消耗，使用魔术消耗5-20点
- NP增长：战斗中每次攻击/被攻击增加10-20%
- 遭遇敌人概率：危险地点30%，普通地点10%，安全地点5%
- enemyIntelUpdate只在发现敌人信息时填写

请生成回应："""

    return prompt


def build_enemy_context(god_view, current_location, player_class):
    """
    Build enemy context for the LLM prompt based on god_view data.
    This gives the LLM information about enemies for realistic encounters.
    """
    if not god_view or 'all_combatants' not in god_view:
        return ""
    
    all_combatants = god_view.get('all_combatants', {})
    
    # Location name mapping for matching
    location_mapping = {
        '远坂邸': 'tohsaka_manor',
        '冬木大桥': 'fuyuki_bridge',
        '新都': 'shinto',
        '柳洞寺': 'ryuudou_temple',
        '言峰教会': 'church',
        '港口': 'harbor',
        '卫宫宅': 'emiya_residence',
        '爱因兹贝伦森林': 'einzbern_forest'
    }
    
    # Reverse mapping
    location_id = location_mapping.get(current_location, current_location)
    
    # Build enemy summary
    enemy_lines = []
    enemies_at_location = []
    enemies_nearby = []
    
    for servant_class, combatant in all_combatants.items():
        if combatant.get('is_player'):
            continue  # Skip player
        
        servant_data = combatant.get('servant', {})
        master_data = combatant.get('master', {})
        combatant_location = combatant.get('current_location', 'unknown')
        is_alive = servant_data.get('is_alive', True)
        
        status = '存活' if is_alive else '已退场'
        true_name = servant_data.get('true_name', '???')
        master_name = master_data.get('name', '???')
        master_personality = master_data.get('personality', '')[:50]
        
        # Check location match
        if combatant_location == location_id:
            enemies_at_location.append({
                'class': servant_class,
                'true_name': true_name,
                'master_name': master_name,
                'master_personality': master_personality,
                'threat_level': combatant.get('threat_level', 3)
            })
        else:
            enemies_nearby.append({
                'class': servant_class,
                'status': status,
                'location': combatant_location,
                'threat_level': combatant.get('threat_level', 3)
            })
    
    context_parts = ["## 圣杯战争敌人信息（GM视角，玩家不可见）"]
    
    # Enemies at current location - high encounter chance
    if enemies_at_location:
        context_parts.append("\n### ⚠️ 当前位置的敌人（遭遇概率：高）")
        for enemy in enemies_at_location:
            context_parts.append(f"""
- **{enemy['class']}阵营**
  - 从者真名：{enemy['true_name']}
  - 御主：{enemy['master_name']}（{enemy['master_personality']}）
  - 威胁等级：{enemy['threat_level']}/5
  - 如果玩家在此地侦查、巡逻或战斗，很可能会遭遇此敌人""")
    else:
        context_parts.append("\n### 当前位置暂无已知敌人")
    
    # Other enemies - for general war status
    if enemies_nearby:
        context_parts.append("\n### 其他敌人位置分布")
        for enemy in enemies_nearby:
            loc_name = {v: k for k, v in location_mapping.items()}.get(enemy['location'], enemy['location'])
            context_parts.append(f"- {enemy['class']}：{enemy['status']}，位于{loc_name}")
    
    context_parts.append("""
### 遭遇生成规则
- 如果玩家行动涉及侦查、巡逻、搜索敌人，应根据敌人位置决定是否遭遇
- 遭遇时，先描写战斗氛围和敌人的外貌特征，不要直接说出真名
- 只有在剧情关键时刻（如敌人主动揭示、战斗到关键时刻）才揭示真名
- 遭遇不一定意味着立即战斗，可能是远距离侦查、擦肩而过等""")
    
    return "\n".join(context_parts)


def call_llm_for_game_action(prompt):
    """
    Call the LLM API for game action response.
    """
    if not LLM_API_KEY:
        raise LLMError(
            "LLM_API_KEY not configured in .env file",
            error_type="config_error"
        )
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LLM_API_KEY}'
    }
    
    payload = {
        'model': LLM_MODEL_ID,
        'messages': [
            {
                'role': 'system',
                'content': '你是一个Fate系列圣杯战争游戏的叙事AI。你负责根据玩家的行动生成相应的故事回应，营造沉浸式的游戏体验。请始终以JSON格式输出。'
            },
            {
                'role': 'user',
                'content': prompt
            }
        ],
        'temperature': 0.8,
        'max_tokens': 1000
    }
    
    try:
        response = requests.post(LLM_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        
        result = response.json()
        
        if 'choices' in result and len(result['choices']) > 0:
            content = result['choices'][0].get('message', {}).get('content', '')
            if not content or not content.strip():
                raise LLMError(
                    "LLM returned empty content",
                    error_type="parse_error",
                    raw_response=json.dumps(result, ensure_ascii=False, indent=2)
                )
            
            # Try to parse JSON from the response
            try:
                # Extract JSON from possible markdown code blocks
                json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    json_str = content
                
                response_data = json.loads(json_str)
                return response_data
            except json.JSONDecodeError:
                # If JSON parsing fails, return the raw text as the response
                return {
                    'response': content,
                    'stateUpdates': {},
                    'newIntel': None,
                    'activateNp': False
                }
        else:
            raise LLMError(
                "Unexpected LLM response format",
                error_type="parse_error",
                raw_response=json.dumps(result, ensure_ascii=False, indent=2)
            )
            
    except requests.exceptions.RequestException as e:
        api_error_detail = None
        try:
            if hasattr(e, 'response') and e.response is not None:
                api_error_detail = e.response.text
        except:
            pass
        
        raise LLMError(
            f"LLM API request failed: {str(e)}",
            error_type="api_error",
            api_error=api_error_detail
        )


# ============ GAME INITIALIZATION SYSTEM ============

# All 7 standard servant classes for Holy Grail War
STANDARD_CLASSES = ['Saber', 'Archer', 'Lancer', 'Rider', 'Caster', 'Assassin', 'Berserker']


def get_servants_by_class(target_class):
    """
    Get all servants of a specific class from the character pool.
    Returns a list of servant names with their basic info.
    """
    characters = load_characters()
    class_variations = CLASS_MAPPINGS.get(target_class.lower(), [target_class])
    
    servants = []
    for char in characters:
        char_class = char.get('职阶', '')
        if char_class in class_variations or char_class.lower() == target_class.lower():
            servants.append({
                'name': char.get('中文名', ''),
                'class': char_class,
                'keywords': char.get('召唤关联词', []),
                'personality': char.get('性格相性简述', '')[:200] if char.get('性格相性简述') else ''
            })
    
    return servants


def get_enemy_classes(player_servant_class):
    """
    Determine which classes should be enemies based on player's class.
    If player has a standard class, enemies are the other 6 standard classes.
    If player has a non-standard class (Ruler, Avenger, etc.), all 7 standard classes are enemies.
    """
    player_class_lower = player_servant_class.lower()
    is_standard_class = any(
        player_class_lower == sc.lower() for sc in STANDARD_CLASSES
    )
    
    if is_standard_class:
        # Standard case: 6 enemies (excluding player's class)
        return [c for c in STANDARD_CLASSES if c.lower() != player_class_lower]
    else:
        # Non-standard class (Ruler, Avenger, MoonCancer, Foreigner, etc.): all 7 standard classes are enemies
        return STANDARD_CLASSES.copy()


def build_masters_generation_prompt_simple(enemy_classes, player_master_intro):
    """
    Build a SIMPLIFIED prompt for generating enemy Masters.
    Only generates basic info (name + title + wish) for speed.
    Detailed info will be generated in parallel during servant selection.
    """
    num_enemies = len(enemy_classes)
    
    prompt = f"""你是一个Fate系列圣杯战争的游戏设计师。请快速生成{num_enemies}位敌方御主的基本信息。

## 背景
玩家御主背景：{player_master_intro if player_master_intro else "一位魔术师"}

## 需要生成的御主（每个职阶一位）
{', '.join(enemy_classes)}

## 【重要】只需要生成最基本的信息

每位御主只需要：
1. 名字（日本名/西方名/中文名均可）
2. 一个简短的身份标签（如：时计塔讲师、圣堂教会代行者、暗杀者、隐士魔术师等）
3. 性格类型关键词（如：冷酷、热血、疯狂、理性、善良等）
4. 对圣杯的愿望（简短描述，如：复活挚爱、获得永生、抹消自身存在、世界和平等）

## 输出格式

请以JSON格式输出：
```json
{{
    "masters": [
        {{
            "servant_class": "Saber",
            "name": "远坂雅人",
            "title": "时计塔讲师",
            "personality_type": "冷酷理性",
            "wish": "抵达根源"
        }},
        {{
            "servant_class": "Archer",
            "name": "艾琳娜·索科洛娃",
            "title": "封印指定执行者",
            "personality_type": "执着复仇",
            "wish": "复活被杀害的家人"
        }}
    ]
}}
```

请生成{num_enemies}位御主的基本信息："""
    
    return prompt


def build_master_detail_prompt(master_basic, player_master_intro, all_masters_basic):
    """
    Build prompt for generating detailed master info.
    This runs in parallel with servant selection.
    """
    other_masters = [m for m in all_masters_basic if m['servant_class'] != master_basic['servant_class']]
    other_masters_text = ", ".join([f"{m['servant_class']}御主{m['name']}({m['title']})" for m in other_masters])
    
    prompt = f"""你是Fate系列圣杯战争的角色设计师。请为以下御主生成详细背景信息。

## 御主基本信息
- 职阶：{master_basic['servant_class']}
- 名字：{master_basic['name']}
- 身份：{master_basic['title']}
- 性格类型：{master_basic.get('personality_type', '不明')}

## 玩家御主背景
{player_master_intro if player_master_intro else "一位神秘的魔术师"}

## 其他参战御主
{other_masters_text}

## 需要生成的详细信息

请为这位御主设计完整背景，要求：
1. 与玩家御主之间有戏剧性联系（可以是旧识、对手、仰慕者、仇人等）
2. 与其他御主之间也有关系网络（宿敌、同盟可能、暗中博弈等）
3. 符合Type-Moon魔术师世界观

## 输出格式

请以JSON格式输出：
```json
{{
    "age": 28,
    "gender": "男/女",
    "personality_description": "100字以内的性格描述",
    "motivation": "参战动机（50字以内）",
    "magic_specialty": "魔术专长",
    "background_brief": "80字以内的背景简介",
    "threat_level": 3,
    "preferred_servant_traits": ["特质1", "特质2", "特质3"],
    "relation_to_player": "与玩家御主的关系",
    "relation_to_others": "与其他御主的关系"
}}
```

请生成详细信息："""
    
    return prompt


def build_servant_selection_prompt(master_info, available_servants, target_class):
    """
    Build prompt for AI to select a suitable servant for a Master.
    Now includes master's wish for better matching.
    """
    servants_text = "\n".join([
        f"- {s['name']}：{s.get('personality', '无描述')[:100]}"
        for s in available_servants[:30]  # Limit to 30 to save tokens
    ])
    
    # Get wish from master info
    wish = master_info.get('wish', '不明')
    
    prompt = f"""你是一个Fate系列圣杯战争的匹配系统。请为御主选择最契合的从者。

## 御主信息

- 名字：{master_info.get('name', '不明')}
- 称号：{master_info.get('title', '魔术师')}
- 性格类型：{master_info.get('personality_type', '不明')}
- 性格描述：{master_info.get('personality_description', '不明')}
- 魔术专长：{master_info.get('magic_specialty', '不明')}
- 参战动机：{master_info.get('motivation', '不明')}
- 对圣杯的愿望：{wish}
- 背景：{master_info.get('background_brief', '不明')}
- 希望的从者特质：{', '.join(master_info.get('preferred_servant_traits', []))}

## 职阶限定

必须从 {target_class} 职阶中选择。

## 可选从者列表（{target_class}职阶）

{servants_text}

## 要求

1. 根据御主的性格、动机、愿望、背景选择最契合的从者
2. 考虑从者的性格是否能与御主配合
3. 考虑从者的能力是否符合御主的战斗风格
4. 优先考虑从者与御主愿望的契合度（例如：想复活挚爱的御主可能更适合有类似经历的从者）
5. 只输出一个从者的中文名，不要输出任何其他内容

被选中的从者是："""
    
    return prompt


def call_llm_for_masters(prompt):
    """
    Call the LLM API to generate enemy Masters (simplified version).
    Returns parsed JSON with masters array containing only basic info.
    """
    if not LLM_API_KEY:
        raise LLMError("LLM_API_KEY not configured", error_type="config_error")
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LLM_API_KEY}'
    }
    
    payload = {
        'model': LLM_MODEL_ID,
        'messages': [
            {
                'role': 'system',
                'content': '你是一个Fate系列圣杯战争的游戏设计师。只输出JSON格式。'
            },
            {
                'role': 'user',
                'content': prompt
            }
        ],
        'temperature': 0.8,
        'max_tokens': 1000  # Reduced since we only need basic info
    }
    
    try:
        response = requests.post(LLM_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        
        result = response.json()
        
        if 'choices' in result and len(result['choices']) > 0:
            content = result['choices'][0].get('message', {}).get('content', '')
            if not content:
                raise LLMError("LLM returned empty content", error_type="parse_error")
            
            # Extract JSON from possible markdown code blocks
            json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find JSON object directly
                json_start = content.find('{')
                json_end = content.rfind('}') + 1
                if json_start != -1 and json_end > json_start:
                    json_str = content[json_start:json_end]
                else:
                    json_str = content
            
            return json.loads(json_str)
        else:
            raise LLMError("Unexpected response format", error_type="parse_error")
            
    except requests.exceptions.RequestException as e:
        raise LLMError(f"API request failed: {str(e)}", error_type="api_error")
    except json.JSONDecodeError as e:
        raise LLMError(f"JSON parse error: {str(e)}", error_type="parse_error", raw_response=content)


def call_llm_for_master_detail(prompt):
    """
    Call the LLM API to generate detailed master info.
    Returns parsed JSON with master details.
    """
    if not LLM_API_KEY:
        return None
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LLM_API_KEY}'
    }
    
    payload = {
        'model': LLM_MODEL_ID,
        'messages': [
            {
                'role': 'system',
                'content': '你是Fate系列角色设计师。只输出JSON格式。'
            },
            {
                'role': 'user',
                'content': prompt
            }
        ],
        'temperature': 0.85,
        'max_tokens': 800
    }
    
    try:
        response = requests.post(LLM_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        
        result = response.json()
        
        if 'choices' in result and len(result['choices']) > 0:
            content = result['choices'][0].get('message', {}).get('content', '')
            if content:
                json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    json_start = content.find('{')
                    json_end = content.rfind('}') + 1
                    if json_start != -1 and json_end > json_start:
                        json_str = content[json_start:json_end]
                    else:
                        json_str = content
                return json.loads(json_str)
        return None
    except Exception as e:
        print(f"Error generating master detail: {e}")
        return None


def call_llm_for_servant_selection(prompt):
    """
    Call the LLM API to select a servant for a Master.
    """
    if not LLM_API_KEY:
        raise LLMError("LLM_API_KEY not configured", error_type="config_error")
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LLM_API_KEY}'
    }
    
    payload = {
        'model': LLM_MODEL_ID,
        'messages': [
            {
                'role': 'system',
                'content': '你是一个Fate系列的匹配系统。只输出从者的中文名，不要输出任何其他内容。'
            },
            {
                'role': 'user',
                'content': prompt
            }
        ],
        'temperature': 0.7,
        'max_tokens': 50
    }
    
    try:
        response = requests.post(LLM_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        
        result = response.json()
        
        if 'choices' in result and len(result['choices']) > 0:
            content = result['choices'][0].get('message', {}).get('content', '')
            if content:
                # Clean up the response
                servant_name = content.strip()
                servant_name = re.sub(r'^[「『【\[]?', '', servant_name)
                servant_name = re.sub(r'[」』】\]]?$', '', servant_name)
                return servant_name.strip()
        
        return None
            
    except Exception as e:
        print(f"Error selecting servant: {e}")
        return None


def load_full_servant_data(servant_name):
    """
    Load complete servant data from data.json for game use.
    Returns structured data suitable for the game state.
    """
    servant_data, base_path = get_servant_data(servant_name)
    
    if not servant_data:
        return None
    
    # Get available images
    available_images = get_servant_images(base_path) if base_path else []
    
    # Get summon voice
    summon_voice = get_servant_voice(base_path, "召唤") if base_path else None
    
    # Structure the data for game use
    game_servant_data = {
        'true_name': servant_data.get('中文名', servant_name),
        'english_name': servant_data.get('英文名', ''),
        'japanese_name': servant_data.get('日文名', ''),
        'class': servant_data.get('职阶', 'Saber'),
        'gender': servant_data.get('性别', '不明'),
        'attribute1': servant_data.get('属性1', '中立'),
        'attribute2': servant_data.get('属性2', '中庸'),
        'height': servant_data.get('身高', '不明'),
        'weight': servant_data.get('体重', '不明'),
        'parameters': {
            'strength': servant_data.get('筋力', 'C'),
            'endurance': servant_data.get('耐久', 'C'),
            'agility': servant_data.get('敏捷', 'C'),
            'mana': servant_data.get('魔力', 'C'),
            'luck': servant_data.get('幸运', 'C'),
            'np': servant_data.get('宝具', 'C')
        },
        'traits': servant_data.get('特性', []),
        'noble_phantasms': servant_data.get('宝具列表', []),
        'profile': servant_data.get('资料列表', []),
        'personality': servant_data.get('性格相性简述', ''),
        'np_description': servant_data.get('宝具描述', ''),
        'image_base_path': base_path,
        'available_images': available_images,
        'summon_voice': summon_voice
    }
    
    return game_servant_data


def generate_initial_game_state(player_servant_data, enemy_combatants, player_master_intro):
    """
    Generate the complete initial game state with god_view and player_view separation.
    """
    import uuid
    from datetime import datetime
    
    game_id = f"hgw_{uuid.uuid4().hex[:8]}"
    
    # Build god_view (complete truth known only to backend)
    god_view = {
        'all_combatants': {},
        'event_schedule': [],
        'hidden_relationships': [],
        'world_state': {
            'grail_corruption_level': 0,
            'leyline_activity': 'normal'
        }
    }
    
    # Add player to combatants
    god_view['all_combatants'][player_servant_data['class']] = {
        'is_player': True,
        'master': {
            'name': '御主',
            'title': '魔术师',
            'is_alive': True,
            'command_spells': 3,
            'personality': player_master_intro[:200] if player_master_intro else '神秘的魔术师'
        },
        'servant': {
            'class': player_servant_data['class'],
            'true_name': player_servant_data.get('true_name', '???'),
            'is_alive': True,
            'hp': 15000,
            'max_hp': 15000,
            'np_gauge': 0,
            'parameters': player_servant_data.get('parameters', {}),
            'noble_phantasms': player_servant_data.get('noble_phantasms', []),
            'skills': player_servant_data.get('skills', []),
            'traits': player_servant_data.get('traits', [])
        },
        'current_location': 'tohsaka_manor',
        'threat_level': 3
    }
    
    # Add enemy combatants
    for enemy in enemy_combatants:
        servant_class = enemy['servant_class']
        god_view['all_combatants'][servant_class] = {
            'is_player': False,
            'master': {
                'name': enemy['master']['name'],
                'title': enemy['master'].get('title', '魔术师'),
                'is_alive': True,
                'command_spells': 3,
                'personality': enemy['master'].get('personality_description', ''),
                'magic_specialty': enemy['master'].get('magic_specialty', ''),
                'motivation': enemy['master'].get('motivation', ''),
                'background': enemy['master'].get('background_brief', '')
            },
            'servant': {
                'class': servant_class,
                'true_name': enemy['servant']['true_name'],
                'is_alive': True,
                'hp': 12000 + (enemy['master'].get('threat_level', 3) * 1000),
                'max_hp': 12000 + (enemy['master'].get('threat_level', 3) * 1000),
                'np_gauge': 0,
                'parameters': enemy['servant'].get('parameters', {}),
                'noble_phantasms': enemy['servant'].get('noble_phantasms', []),
                'traits': enemy['servant'].get('traits', [])
            },
            'current_location': get_random_starting_location(servant_class),
            'threat_level': enemy['master'].get('threat_level', 3)
        }
    
    # Build player_view (fog of war - what player knows)
    player_view = {
        'global_state': {
            'game_id': game_id,
            'turn_count': 1,
            'day': 1,
            'time_phase': 'night',
            'weather': 'clear',
            'current_location_id': 'tohsaka_manor'
        },
        'enemy_intel': {}
    }
    
    # Initialize enemy intel with fog of war
    for servant_class in STANDARD_CLASSES:
        is_player = servant_class.lower() == player_servant_data['class'].lower()
        player_view['enemy_intel'][servant_class] = {
            'status': 'alive',
            'is_player': is_player,
            'true_name_revealed': is_player,
            'known_true_name': player_servant_data.get('true_name') if is_player else None,
            'known_info': [],
            'last_seen_location': None,
            'last_seen_time': None,
            'threat_assessment': 'unknown'
        }
    
    return {
        'game_id': game_id,
        'god_view': god_view,
        'player_view': player_view,
        'timestamp': datetime.now().isoformat()
    }


def get_random_starting_location(servant_class):
    """
    Get a thematically appropriate starting location for a servant class.
    """
    import random
    
    location_preferences = {
        'Saber': ['emiya_residence', 'fuyuki_bridge', 'shinto'],
        'Archer': ['church', 'shinto', 'fuyuki_bridge'],
        'Lancer': ['fuyuki_bridge', 'harbor', 'shinto'],
        'Rider': ['harbor', 'shinto', 'fuyuki_bridge'],
        'Caster': ['ryuudou_temple', 'church', 'tohsaka_manor'],
        'Assassin': ['ryuudou_temple', 'shinto', 'harbor'],
        'Berserker': ['einzbern_forest', 'harbor', 'fuyuki_bridge']
    }
    
    preferred = location_preferences.get(servant_class, ['shinto', 'fuyuki_bridge'])
    return random.choice(preferred)


def select_servant_and_generate_master_detail_task(master_basic, target_class, player_master_intro, all_masters_basic):
    """
    Combined task function for parallel execution:
    1. Generate detailed master info (in parallel with other masters)
    2. Select servant for this master (in parallel with other servants)
    
    Returns (servant_class, full_master_data, servant_data) tuple or None on failure.
    """
    try:
        if not target_class:
            return None
        
        # ===== PART 1: Generate detailed master info =====
        detail_prompt = build_master_detail_prompt(master_basic, player_master_intro, all_masters_basic)
        master_detail = call_llm_for_master_detail(detail_prompt)
        
        # Merge basic and detailed info
        full_master = {**master_basic}
        if master_detail:
            full_master.update(master_detail)
        else:
            # Fallback defaults if detail generation fails
            full_master.update({
                'age': 25,
                'gender': '不明',
                'personality_description': f'{master_basic.get("personality_type", "神秘")}的魔术师',
                'motivation': '追求圣杯',
                'magic_specialty': '不明',
                'background_brief': f'{master_basic["title"]}，参与圣杯战争',
                'threat_level': 3,
                'preferred_servant_traits': [],
                'relation_to_player': '未知',
                'relation_to_others': '未知'
            })
        
        print(f"  {target_class}: Master detail generated for {master_basic['name']}")
        
        # ===== PART 2: Select servant =====
        # Get available servants filtered by class FIRST
        available_servants = get_servants_by_class(target_class)
        
        if not available_servants:
            print(f"  {target_class}: No servants found in pool")
            return None
        
        print(f"  {target_class}: Found {len(available_servants)} servants in pool")
        
        # Use AI to select the best matching servant
        selection_prompt = build_servant_selection_prompt(full_master, available_servants, target_class)
        selected_name = call_llm_for_servant_selection(selection_prompt)
        
        if not selected_name:
            # Fallback: pick randomly
            import random
            selected_name = random.choice(available_servants)['name']
            print(f"  {target_class}: LLM selection failed, randomly picked {selected_name}")
        
        # Validate and get full servant data
        validated_name = validate_servant_name(selected_name, available_servants)
        servant_data = load_full_servant_data(validated_name)
        
        if servant_data:
            print(f"  {target_class}: {full_master['name']} ← {validated_name}")
            return (target_class, full_master, servant_data)
        else:
            print(f"  {target_class}: Warning - Could not load data for {validated_name}")
            return None
            
    except Exception as e:
        print(f"  {target_class}: Error in combined task - {e}")
        import traceback
        traceback.print_exc()
        return None


def generate_initial_response_task(initial_action, player_servant_data):
    """
    Task function for parallel initial story response generation.
    Returns the response string or None on failure.
    """
    try:
        action_prompt = build_game_action_prompt(
            initial_action,
            {
                'day': 1,
                'time': 'night',
                'location': '远坂邸',
                'master': {'name': '御主', 'mana': 100, 'physicalStatus': 'healthy', 'commandSpells': 3},
                'servant': {
                    'class': player_servant_data.get('class', 'Saber'),
                    'trueName': player_servant_data.get('true_name', '???'),
                    'hp': 15000,
                    'np': 0,
                    'bondLevel': 1
                },
                'objective': '与召唤的从者建立契约，准备迎接圣杯战争'
            },
            False
        )
        response_data = call_llm_for_game_action(action_prompt)
        return response_data.get('response', '')
    except Exception as e:
        print(f"Error generating initial response: {e}")
        return None


@app.route('/api/init_game', methods=['POST'])
def init_game():
    """
    Initialize the Holy Grail War game.
    
    Optimized execution flow:
    1. Initial story response - runs in parallel with everything else
    2. Generate basic master info (name + title only) - fast, simple LLM call
    3. For each master in parallel:
       - Generate detailed master info
       - Select servant from class-filtered pool
    
    Non-standard classes (Ruler, Avenger, etc.) will face all 7 standard class enemies.
    
    Expected JSON body:
    {
        "playerServant": {
            "class": "Saber",
            "trueName": "高文",
            "englishName": "Gawain",
            "parameters": { "strength": "B+", ... },
            ...
        },
        "masterIntro": "玩家输入的魔术师背景",
        "summoningStory": "召唤故事摘要",
        "initialAction": "玩家的第一个行动"
    }
    
    Returns:
    {
        "success": true,
        "gameState": {
            "game_id": "hgw_xxx",
            "god_view": { ... },
            "player_view": { ... }
        },
        "enemyCombatants": [ ... ],
        "initialResponse": "AI生成的初始故事回应"
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        player_servant_info = data.get('playerServant', {})
        master_intro = data.get('masterIntro', '')
        summoning_story = data.get('summoningStory', '')
        initial_action = data.get('initialAction', '')
        
        player_servant_class = player_servant_info.get('class', 'Saber')
        player_servant_name = player_servant_info.get('trueName', '')
        
        # Determine enemy classes based on player's class
        enemy_classes = get_enemy_classes(player_servant_class)
        is_nonstandard = len(enemy_classes) == 7
        
        print(f"Initializing game with player class: {player_servant_class}")
        if is_nonstandard:
            print(f"  → Non-standard class detected! All 7 standard classes will be enemies")
        else:
            print(f"  → Standard class. 6 enemy classes: {', '.join(enemy_classes)}")
        print("Using optimized parallel execution...")
        
        # Load player servant data first (needed for initial response)
        print("Step 0: Loading player servant data...")
        player_servant_data = load_full_servant_data(player_servant_name)
        
        if not player_servant_data:
            # Use the provided data if we can't load from files
            player_servant_data = {
                'class': player_servant_class,
                'true_name': player_servant_name,
                'parameters': player_servant_info.get('parameters', {
                    'strength': 'C', 'endurance': 'C', 'agility': 'C',
                    'mana': 'C', 'luck': 'C', 'np': 'C'
                }),
                'noble_phantasms': player_servant_info.get('noblePhantasms', []),
                'traits': []
            }
        
        # Use ThreadPoolExecutor for parallel execution
        # max_workers: 1 for initial response + 7 for master detail + servant selection
        with concurrent.futures.ThreadPoolExecutor(max_workers=9) as executor:
            
            # ========== PARALLEL TASK 1: Initial story response ==========
            # Start this immediately - it runs in parallel with everything else
            initial_response_future = None
            if initial_action:
                print("Starting parallel task: Initial story response generation...")
                initial_response_future = executor.submit(
                    generate_initial_response_task,
                    initial_action,
                    player_servant_data
                )
            
            # ========== FAST SEQUENTIAL TASK: Generate basic master info ==========
            # Only generates name + title, very fast
            print(f"Step 1: Generating {len(enemy_classes)} enemy Masters (basic info only)...")
            masters_prompt = build_masters_generation_prompt_simple(enemy_classes, master_intro)
            
            masters_data = call_llm_for_masters(masters_prompt)
            enemy_masters_basic = masters_data.get('masters', [])
            
            if len(enemy_masters_basic) < len(enemy_classes):
                print(f"Warning: Only generated {len(enemy_masters_basic)} masters, expected {len(enemy_classes)}")
            
            print(f"Generated {len(enemy_masters_basic)} basic master profiles:")
            for m in enemy_masters_basic:
                print(f"  - {m.get('servant_class')}: {m.get('name')} ({m.get('title')})")
            
            # ========== PARALLEL TASK 2: Combined master detail + servant selection ==========
            # For each master, generate detailed info AND select servant in parallel
            print("Step 2: Parallel execution - master details + servant selection...")
            combined_futures = []
            
            for master_basic in enemy_masters_basic:
                target_class = master_basic.get('servant_class', '')
                if target_class:
                    future = executor.submit(
                        select_servant_and_generate_master_detail_task,
                        master_basic,
                        target_class,
                        master_intro,
                        enemy_masters_basic
                    )
                    combined_futures.append(future)
            
            # Collect results from parallel execution
            enemy_combatants = []
            for future in concurrent.futures.as_completed(combined_futures, timeout=180):
                try:
                    result = future.result()
                    if result:
                        servant_class, full_master, servant_data = result
                        enemy_combatants.append({
                            'servant_class': servant_class,
                            'master': full_master,
                            'servant': servant_data
                        })
                except Exception as e:
                    print(f"Error in combined task: {e}")
            
            print(f"Completed parallel execution: {len(enemy_combatants)} combatants")
            
            # ========== COLLECT PARALLEL TASK 1 RESULT ==========
            initial_response = None
            if initial_response_future:
                print("Collecting initial story response result...")
                try:
                    initial_response = initial_response_future.result(timeout=120)
                    if initial_response:
                        print("Initial story response generated successfully")
                    else:
                        print("Initial story response returned None")
                except concurrent.futures.TimeoutError:
                    print("Initial story response generation timed out")
                except Exception as e:
                    print(f"Error getting initial response: {e}")
        
        # Step 3: Generate complete initial game state
        print("Step 3: Generating initial game state...")
        game_state = generate_initial_game_state(
            player_servant_data,
            enemy_combatants,
            master_intro
        )
        
        # Prepare response - include god_view for frontend storage (方案B)
        # Note: This exposes enemy data to frontend, but simplifies architecture
        client_response = {
            'success': True,
            'gameId': game_state['game_id'],
            'playerView': game_state['player_view'],
            'godView': game_state['god_view'],  # Include full god_view for frontend storage
            'playerServant': {
                'class': player_servant_data.get('class'),
                'trueName': player_servant_data.get('true_name'),
                'englishName': player_servant_data.get('english_name', ''),
                'parameters': player_servant_data.get('parameters', {}),
                'noblePhantasms': player_servant_data.get('noble_phantasms', []),
                'npDescription': player_servant_data.get('np_description', ''),
                'imageBasePath': player_servant_data.get('image_base_path', ''),
                'availableImages': player_servant_data.get('available_images', [])
            },
            'enemyCombatants': enemy_combatants,  # Include detailed enemy data
            'enemyCount': len(enemy_combatants),
            'initialResponse': initial_response,
            'isNonStandardClass': is_nonstandard,
            'timestamp': game_state['timestamp']
        }
        
        print(f"Game initialized successfully: {game_state['game_id']}")
        print(f"  Player: {player_servant_data.get('class')} - {player_servant_data.get('true_name')}")
        print(f"  Enemies: {len(enemy_combatants)} combatants")
        for ec in enemy_combatants:
            print(f"    - {ec['servant_class']}: {ec['master']['name']} ← {ec['servant']['true_name']}")
        
        return jsonify(client_response)
        
    except LLMError as e:
        error_response = {
            'success': False,
            'error': str(e),
            'errorType': e.error_type
        }
        if e.raw_response:
            error_response['rawResponse'] = e.raw_response
        return jsonify(error_response), 400
    except Exception as e:
        print(f"Error in init_game endpoint: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e),
            'errorType': 'unknown_error'
        }), 500


@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'ok',
        'llm_configured': bool(LLM_API_KEY)
    })


@app.route('/api/characters', methods=['GET'])
def get_characters():
    """Get all available characters (for debugging)"""
    characters = load_characters()
    return jsonify({
        'count': len(characters),
        'characters': [c.get('中文名', '') for c in characters]
    })


@app.route('/api/servants_by_class/<class_name>', methods=['GET'])
def get_servants_by_class_endpoint(class_name):
    """Get all servants of a specific class (for debugging)"""
    servants = get_servants_by_class(class_name)
    return jsonify({
        'class': class_name,
        'count': len(servants),
        'servants': servants
    })


# ============ 新版游戏回合 API (三阶段流水线) ============

def json_to_god_view(data: dict) -> GodView:
    """
    将前端传入的JSON数据转换为GodView对象
    
    支持两种格式：
    1. 新格式：player_servant + npc_states（来自convert_init_to_godview）
    2. 旧格式：all_combatants（直接来自init_game）
    
    Args:
        data: 包含god_view信息的JSON字典
        
    Returns:
        GodView: 游戏引擎使用的GodView对象
    """
    god_view = GodView()
    
    # 解析时间和回合
    god_view.turn_count = data.get('turn_count', 1)
    god_view.time_phase = data.get('time_phase', 'night')
    god_view.player_character_id = data.get('player_character_id', '')
    
    # 检查是否使用 all_combatants 格式（来自init_game直接返回的godView）
    all_combatants = data.get('all_combatants')
    
    if all_combatants:
        # ===== 旧格式：从 all_combatants 解析 =====
        print("[json_to_god_view] Detected all_combatants format, converting...")
        
        for servant_class, combatant in all_combatants.items():
            is_player = combatant.get('is_player', False)
            servant_data = combatant.get('servant', {})
            master_data = combatant.get('master', {})
            current_location = combatant.get('current_location', 'unknown')
            
            # 构建角色数据
            char_id = f"{servant_class}_{servant_data.get('true_name', 'unknown')}"
            
            character_data = {
                'character_id': char_id,
                'true_name': servant_data.get('true_name', '???'),
                'display_name': servant_class,
                'servant_class': servant_class,
                'location_id': current_location,
                'hp_current': servant_data.get('hp', 15000),
                'hp_max': servant_data.get('max_hp', 15000),
                'mp_current': 10000,
                'mp_max': 10000,
                'np_gauge': servant_data.get('np_gauge', 0),
                'parameters': servant_data.get('parameters', {}),
                'noble_phantasms': servant_data.get('noble_phantasms', []),
                'skills': servant_data.get('skills', []),
                'traits': servant_data.get('traits', []),
                'status_effects': [],
                'health_status': 'healthy',
                'ai_personality': master_data.get('personality', '')[:50] if master_data.get('personality') else '',
                'ai_context': {
                    'goal': master_data.get('motivation', 'win the Holy Grail War'),
                    'memory': [],
                    'known_intel': {},
                    'current_stance_towards_others': {}
                }
            }
            
            if is_player:
                god_view.player_servant = _parse_character_state(character_data, is_player=True)
                god_view.player_character_id = char_id
                god_view.player_master = master_data
            else:
                god_view.npc_states[char_id] = _parse_character_state(character_data, is_player=False)
        
        print(f"[json_to_god_view] Converted: Player={god_view.player_servant.true_name if god_view.player_servant else 'None'}, NPCs={len(god_view.npc_states)}")
        
    else:
        # ===== 新格式：使用 player_servant + npc_states =====
        # 解析玩家从者
        player_data = data.get('player_servant')
        if player_data:
            god_view.player_servant = _parse_character_state(player_data, is_player=True)
            god_view.player_character_id = god_view.player_servant.character_id
        
        # 解析玩家御主
        god_view.player_master = data.get('player_master')
        
        # 解析NPC状态
        npc_states_data = data.get('npc_states', {})
        for char_id, npc_data in npc_states_data.items():
            god_view.npc_states[char_id] = _parse_character_state(npc_data, is_player=False)
    
    # 解析地图 - 如果没有提供则使用默认地图
    location_data = data.get('location_graph', {})
    if not location_data:
        location_data = _get_default_fuyuki_map()
    
    for loc_id, loc_info in location_data.items():
        god_view.location_graph[loc_id] = LocationNode(
            node_id=loc_id,
            name=loc_info.get('name', loc_id),
            english_name=loc_info.get('english_name', loc_id),
            description=loc_info.get('description', ''),
            region=loc_info.get('region', 'unknown'),
            connections=loc_info.get('connections', []),
            mana_density=loc_info.get('mana_density', 2),
            population=loc_info.get('population', 'Medium'),
            tactical_type=loc_info.get('tactical_type', 'Open'),
            is_unlocked=loc_info.get('is_unlocked', True),
            is_safe_zone=loc_info.get('is_safe_zone', False)
        )
    
    # 解析关系图谱
    relationship_data = data.get('relationship_graph', {})
    for key, value in relationship_data.items():
        if isinstance(value, str):
            try:
                god_view.relationship_graph[key] = RelationshipStatus(value)
            except ValueError:
                god_view.relationship_graph[key] = RelationshipStatus.NEUTRAL
        else:
            god_view.relationship_graph[key] = value
    
    return god_view


def _parse_character_state(data: dict, is_player: bool = False) -> CharacterState:
    """解析角色状态数据"""
    # 解析能力参数
    params_data = data.get('parameters', {})
    parameters = ServantParameters(
        strength=params_data.get('strength', 'C'),
        endurance=params_data.get('endurance', 'C'),
        agility=params_data.get('agility', 'C'),
        mana=params_data.get('mana', 'C'),
        luck=params_data.get('luck', 'C'),
        np=params_data.get('np', 'C')
    )
    
    # 解析职阶
    class_str = data.get('servant_class', data.get('class', 'Saber'))
    try:
        servant_class = ServantClass(class_str)
    except ValueError:
        servant_class = ServantClass.SABER
    
    # 解析健康状态
    health_str = data.get('health_status', 'healthy')
    try:
        health_status = HealthStatus(health_str)
    except ValueError:
        health_status = HealthStatus.HEALTHY
    
    # 解析AI上下文（仅NPC）
    ai_context = None
    if not is_player and 'ai_context' in data:
        ai_data = data['ai_context']
        if ai_data:
            ai_context = AIContext.from_dict(ai_data)
    
    # 处理HP数据（支持两种格式）
    hp_data = data.get('hp', {})
    if isinstance(hp_data, dict):
        hp_current = hp_data.get('current', 15000)
        hp_max = hp_data.get('max', 15000)
    else:
        hp_current = data.get('hp_current', 15000)
        hp_max = data.get('hp_max', 15000)
    
    # 处理MP数据
    mp_data = data.get('mp', {})
    if isinstance(mp_data, dict):
        mp_current = mp_data.get('current', 10000)
        mp_max = mp_data.get('max', 10000)
    else:
        mp_current = data.get('mp_current', 10000)
        mp_max = data.get('mp_max', 10000)
    
    return CharacterState(
        character_id=data.get('character_id', data.get('true_name', 'unknown')),
        true_name=data.get('true_name', '???'),
        display_name=data.get('display_name', data.get('true_name', '???')),
        servant_class=servant_class,
        is_player=is_player,
        location_id=data.get('location_id', 'unknown'),
        hp_current=hp_current,
        hp_max=hp_max,
        mp_current=mp_current,
        mp_max=mp_max,
        np_gauge=data.get('np_gauge', 0),
        parameters=parameters,
        status_effects=data.get('status_effects', []),
        health_status=health_status,
        ai_context=ai_context,
        ai_personality=data.get('ai_personality', ''),
        skills=data.get('skills', []),
        noble_phantasms=data.get('noble_phantasms', [])
    )


@app.route('/api/game_turn', methods=['POST'])
def game_turn():
    """
    新版游戏回合处理 API - 使用三阶段流水线
    
    三阶段流水线:
    1. Phase I: 并发NPC意图收集（每个NPC独立LLM调用，并发执行）
    2. Phase II: GM裁决（确定性Python逻辑，无LLM调用）
    3. Phase III: 分层叙事渲染（聚光灯叙事 + 侧边情报）
    
    Expected JSON body:
    {
        "godView": {
            "turn_count": 1,
            "time_phase": "night",
            "player_servant": { ... },
            "player_master": { ... },
            "npc_states": { ... },
            "location_graph": { ... },
            "relationship_graph": { ... }
        },
        "playerAction": {
            "type": "move|attack|talk|scout|defend|wait",
            "target_location": "地点ID（移动时）",
            "target_id": "目标角色ID（攻击/对话时）",
            "message": "对话内容（对话时）"
        }
    }
    
    Returns:
    {
        "success": true,
        "mainStory": "主要叙事文本",
        "sideIntel": [
            {"text": "情报内容", "level": "info|urgent|rumor|warning"}
        ],
        "stateUpdates": {
            "turn": 2,
            "time_phase": "night",
            "player": { "hp": 14500, "location": "ryuudou_temple", ... },
            "defeated": [],
            "relationship_changes": {}
        },
        "mapVisuals": {
            "ryuudou_temple": "combat",
            "fuyuki_bridge": "movement"
        }
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400
        
        god_view_data = data.get('godView', {})
        player_action_raw = data.get('playerAction', {})
        
        if not god_view_data:
            return jsonify({
                'success': False,
                'error': 'godView is required'
            }), 400
        
        # 处理 playerAction：支持字符串和字典两种格式
        # 前端可能发送：
        # 1. 字符串格式：用户直接输入的文本 (如 "去柳洞寺探索")
        # 2. 字典格式：结构化的行动数据 (如 {"type": "move", "target_location": "ryuudou_temple"})
        if isinstance(player_action_raw, str):
            # 将字符串转换为字典格式
            player_action = {
                'type': 'text',  # 自由文本输入
                'message': player_action_raw,
                'raw_input': player_action_raw
            }
        elif isinstance(player_action_raw, dict):
            player_action = player_action_raw
        else:
            player_action = {'type': 'wait'}
        
        # 转换为GodView对象
        god_view = json_to_god_view(god_view_data)
        
        print(f"[game_turn] Processing turn {god_view.turn_count}")
        print(f"[game_turn] Player: {god_view.player_servant.true_name if god_view.player_servant else 'None'}")
        print(f"[game_turn] NPCs: {len(god_view.npc_states)}")
        print(f"[game_turn] Player action: {player_action.get('type', 'wait')} - {player_action.get('message', '')[:50] if player_action.get('message') else ''}")
        
        # 调用三阶段流水线
        game_response = process_game_turn_sync(god_view, player_action)
        
        # 转换响应格式
        response_data = {
            'success': game_response.success,
            'mainStory': game_response.main_story,
            'sideIntel': [intel.to_dict() for intel in game_response.side_intel],
            'stateUpdates': game_response.state_updates,
            'mapVisuals': game_response.map_visuals
        }
        
        if game_response.error:
            response_data['error'] = game_response.error
        
        print(f"[game_turn] Response generated successfully")
        
        return jsonify(response_data)
        
    except Exception as e:
        print(f"Error in game_turn endpoint: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e),
            'errorType': 'unknown_error'
        }), 500


@app.route('/api/convert_init_to_godview', methods=['POST'])
def convert_init_to_godview():
    """
    辅助API：将init_game返回的数据转换为game_turn需要的GodView格式
    
    这个API帮助前端将初始化数据转换为可以直接传递给game_turn的格式。
    
    Expected JSON body:
    {
        "playerServant": { ... },  // 来自init_game
        "enemyCombatants": [ ... ], // 来自init_game
        "playerView": { ... }       // 来自init_game
    }
    
    Returns:
    {
        "success": true,
        "godView": { ... }  // 可直接传递给game_turn
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400
        
        player_servant = data.get('playerServant', {})
        enemy_combatants = data.get('enemyCombatants', [])
        player_view = data.get('playerView', {})
        
        # 构建GodView JSON
        god_view_json = {
            'turn_count': player_view.get('global_state', {}).get('turn_count', 1),
            'time_phase': player_view.get('global_state', {}).get('time_phase', 'night'),
            'player_character_id': player_servant.get('trueName', 'player'),
            
            # 玩家从者
            'player_servant': {
                'character_id': player_servant.get('trueName', 'player'),
                'true_name': player_servant.get('trueName', '???'),
                'display_name': player_servant.get('class', 'Saber'),
                'servant_class': player_servant.get('class', 'Saber'),
                'location_id': player_view.get('global_state', {}).get('current_location_id', 'tohsaka_manor'),
                'hp_current': 15000,
                'hp_max': 15000,
                'mp_current': 10000,
                'mp_max': 10000,
                'np_gauge': 0,
                'parameters': player_servant.get('parameters', {}),
                'noble_phantasms': player_servant.get('noblePhantasms', []),
                'skills': [],
                'status_effects': [],
                'health_status': 'healthy'
            },
            
            # 玩家御主
            'player_master': {
                'name': '御主',
                'mana': 100,
                'command_spells': 3
            },
            
            # NPC状态
            'npc_states': {},
            
            # 地图（使用默认冬木市地图）
            'location_graph': _get_default_fuyuki_map(),
            
            # 关系图谱
            'relationship_graph': {}
        }
        
        # 添加敌方NPC
        for enemy in enemy_combatants:
            servant_class = enemy.get('servant_class', 'Saber')
            servant_data = enemy.get('servant', {})
            master_data = enemy.get('master', {})
            
            char_id = f"{servant_class}_{servant_data.get('true_name', 'unknown')}"
            
            god_view_json['npc_states'][char_id] = {
                'character_id': char_id,
                'true_name': servant_data.get('true_name', '???'),
                'display_name': servant_class,
                'servant_class': servant_class,
                'location_id': _get_random_starting_location_for_class(servant_class),
                'hp_current': 12000 + (master_data.get('threat_level', 3) * 1000),
                'hp_max': 12000 + (master_data.get('threat_level', 3) * 1000),
                'mp_current': 10000,
                'mp_max': 10000,
                'np_gauge': 0,
                'parameters': servant_data.get('parameters', {}),
                'noble_phantasms': servant_data.get('noble_phantasms', []),
                'skills': [],
                'status_effects': [],
                'health_status': 'healthy',
                'ai_personality': master_data.get('personality_type', 'neutral'),
                'ai_context': {
                    'goal': master_data.get('motivation', 'win the Holy Grail War'),
                    'memory': [],
                    'known_intel': {},
                    'current_stance_towards_others': {}
                }
            }
            
            # 设置初始关系为未知/中立
            player_id = god_view_json['player_character_id']
            god_view_json['relationship_graph'][f"{player_id}_{char_id}"] = 'UNKNOWN'
        
        return jsonify({
            'success': True,
            'godView': god_view_json
        })
        
    except Exception as e:
        print(f"Error in convert_init_to_godview endpoint: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def _get_default_fuyuki_map():
    """获取默认冬木市地图配置"""
    return {
        'tohsaka_manor': {
            'name': '远坂邸',
            'english_name': 'Tohsaka Manor',
            'description': '远坂家的宅邸，位于深山町高地，是强大的魔术工房',
            'region': 'miyama',
            'connections': ['miyama_residential', 'shinto'],
            'mana_density': 4,
            'population': 'None',
            'tactical_type': 'Fortress',
            'is_safe_zone': True
        },
        'miyama_residential': {
            'name': '深山町住宅区',
            'english_name': 'Miyama Residential',
            'description': '冬木市的老城区，传统日式住宅林立',
            'region': 'miyama',
            'connections': ['tohsaka_manor', 'emiya_residence', 'shinto', 'church'],
            'mana_density': 2,
            'population': 'High',
            'tactical_type': 'Urban'
        },
        'emiya_residence': {
            'name': '卫宫宅',
            'english_name': 'Emiya Residence',
            'description': '卫宫士郎的家，有一个小型工房',
            'region': 'miyama',
            'connections': ['miyama_residential'],
            'mana_density': 2,
            'population': 'None',
            'tactical_type': 'Fortress'
        },
        'church': {
            'name': '言峰教会',
            'english_name': 'Kotomine Church',
            'description': '圣杯战争的中立地带，由监督者管理',
            'region': 'miyama',
            'connections': ['miyama_residential', 'ryuudou_temple'],
            'mana_density': 3,
            'population': 'Low',
            'tactical_type': 'Fortress',
            'is_safe_zone': True
        },
        'ryuudou_temple': {
            'name': '柳洞寺',
            'english_name': 'Ryuudou Temple',
            'description': '位于山顶的佛教寺院，拥有大型结界',
            'region': 'miyama',
            'connections': ['church', 'einzbern_forest'],
            'mana_density': 5,
            'population': 'Low',
            'tactical_type': 'Fortress'
        },
        'shinto': {
            'name': '新都商业区',
            'english_name': 'Shinto District',
            'description': '冬木市的现代商业中心',
            'region': 'shinto',
            'connections': ['tohsaka_manor', 'miyama_residential', 'fuyuki_bridge', 'harbor'],
            'mana_density': 1,
            'population': 'Very High',
            'tactical_type': 'Urban'
        },
        'fuyuki_bridge': {
            'name': '冬木大桥',
            'english_name': 'Fuyuki Bridge',
            'description': '连接新都和深山町的大桥，战略要地',
            'region': 'bridge',
            'connections': ['shinto', 'harbor'],
            'mana_density': 2,
            'population': 'Medium',
            'tactical_type': 'Chokepoint'
        },
        'harbor': {
            'name': '港口仓库区',
            'english_name': 'Harbor District',
            'description': '废弃的港口仓库，常有从者出没',
            'region': 'shinto',
            'connections': ['shinto', 'fuyuki_bridge'],
            'mana_density': 2,
            'population': 'None',
            'tactical_type': 'Open'
        },
        'einzbern_forest': {
            'name': '爱因兹贝伦森林',
            'english_name': 'Einzbern Forest',
            'description': '城郊的神秘森林，通往爱因兹贝伦城堡',
            'region': 'outskirts',
            'connections': ['ryuudou_temple'],
            'mana_density': 4,
            'population': 'None',
            'tactical_type': 'Fortress'
        }
    }


def _get_random_starting_location_for_class(servant_class):
    """根据职阶获取随机起始位置"""
    import random
    
    location_preferences = {
        'Saber': ['emiya_residence', 'fuyuki_bridge', 'shinto'],
        'Archer': ['church', 'shinto', 'fuyuki_bridge'],
        'Lancer': ['fuyuki_bridge', 'harbor', 'shinto'],
        'Rider': ['harbor', 'shinto', 'fuyuki_bridge'],
        'Caster': ['ryuudou_temple', 'church', 'tohsaka_manor'],
        'Assassin': ['ryuudou_temple', 'shinto', 'harbor'],
        'Berserker': ['einzbern_forest', 'harbor', 'fuyuki_bridge']
    }
    
    preferred = location_preferences.get(servant_class, ['shinto', 'fuyuki_bridge'])
    return random.choice(preferred)


# ============ 静态文件服务 ============

@app.route('/')
def serve_index():
    """Serve the main page - redirect to game.html"""
    return send_from_directory('.', 'game.html')


@app.route('/game.html')
def serve_game():
    """Serve game.html"""
    return send_from_directory('.', 'game.html')


@app.route('/summon.html')
def serve_summon():
    """Serve summon.html"""
    return send_from_directory('.', 'summon.html')


@app.route('/chara/<path:filepath>')
def serve_chara(filepath):
    """Serve character files (images, audio, etc.)"""
    return send_from_directory('chara', filepath)


@app.route('/class_image/<path:filepath>')
def serve_class_image(filepath):
    """Serve class images"""
    return send_from_directory('class_image', filepath)


if __name__ == '__main__':
    print("=" * 50)
    print("英灵召唤系统 API 启动中...")
    print("=" * 50)
    print(f"LLM API URL: {LLM_API_URL}")
    print(f"LLM Model: {LLM_MODEL_ID}")
    print(f"API Key configured: {'Yes' if LLM_API_KEY else 'No'}")
    print("=" * 50)
    print("可用端点:")
    print("  /api/summon          - 召唤从者")
    print("  /api/generate_story  - 生成召唤故事")
    print("  /api/init_game       - 初始化游戏")
    print("  /api/game_action     - 旧版游戏行动（LLM直接生成）")
    print("  /api/game_turn       - 新版游戏回合（三阶段流水线）")
    print("=" * 50)
    
    # Run the Flask app
    app.run(host='0.0.0.0', port=5000, debug=True)
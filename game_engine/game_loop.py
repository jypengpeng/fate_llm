"""
Holy Grail War Game Engine - Game Loop
圣杯战争游戏引擎 - 游戏循环

处理游戏回合的核心逻辑，包括并发地点叙事生成。
实现两步请求：
1. 第一步：根据角色意图生成地点叙事
2. 第二步：根据叙事更新角色意图和记忆
"""

import os
import json
import re
import uuid
import requests
import concurrent.futures
from urllib.parse import quote
from typing import Dict, List, Optional, Any, Tuple
from dotenv import load_dotenv

from .models import (
    GodView,
    CharacterState,
    LocationNode,
    GameResponse,
    SideIntelItem,
    Intent,
    IntentStatus,
    MemoryEntry,
    CharacterStateUpdate,
    LocationNarrativeResult,
    LocationHistoryEntry,
)

# Load environment variables
load_dotenv()

# LLM Configuration
LLM_API_URL = os.getenv('LLM_API_URL', 'https://api.openai.com/v1/chat/completions')
LLM_API_KEY = os.getenv('LLM_API_KEY', '')
LLM_MODEL_ID = os.getenv('LLM_MODEL_ID', 'gpt-4')
LLM_API_FORMAT = os.getenv('LLM_API_FORMAT', 'openai').strip().lower()


def _resolve_llm_config(llm_config: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """合并请求级配置与环境变量配置，返回生效的LLM配置。"""
    cfg = llm_config or {}
    api_url = (cfg.get('apiUrl') or LLM_API_URL or '').strip()
    api_key = (cfg.get('apiKey') or LLM_API_KEY or '').strip()
    model_id = (cfg.get('modelId') or LLM_MODEL_ID or '').strip()
    api_format = (cfg.get('apiFormat') or LLM_API_FORMAT or 'openai').strip().lower()
    api_format = 'gemini' if api_format == 'gemini' else 'openai'
    return {
        'api_url': api_url,
        'api_key': api_key,
        'model_id': model_id,
        'api_format': api_format,
    }


def _get_llm_api_format(llm_config: Optional[Dict[str, str]] = None) -> str:
    """返回规范化的LLM API格式。"""
    return _resolve_llm_config(llm_config)['api_format']


def _build_llm_headers(llm_config: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """构建当前LLM格式所需请求头。"""
    cfg = _resolve_llm_config(llm_config)

    if cfg['api_format'] == 'gemini':
        return {
            'Content-Type': 'application/json'
        }

    return {
        'Content-Type': 'application/json',
        'Authorization': f"Bearer {cfg['api_key']}"
    }


def _build_llm_url(llm_config: Optional[Dict[str, str]] = None) -> str:
    """构建当前LLM格式请求URL。"""
    cfg = _resolve_llm_config(llm_config)
    api_url = cfg['api_url']

    if cfg['api_format'] == 'gemini':
        # 如果只配置了网关根路径，自动补全 Gemini generateContent 路径
        if 'generateContent' not in api_url:
            trimmed_url = api_url.rstrip('/')
            api_url = f"{trimmed_url}/v1beta/models/{{model}}:generateContent"

        api_url = api_url.replace('{model}', quote(cfg['model_id'], safe=''))
        api_url = api_url.replace('{api_key}', quote(cfg['api_key'], safe=''))

        if 'key=' not in api_url and '{api_key}' not in cfg['api_url'] and cfg['api_key']:
            separator = '&' if '?' in api_url else '?'
            api_url = f"{api_url}{separator}key={quote(cfg['api_key'], safe='')}"

    return api_url


def _build_llm_payload(messages: List[Dict[str, str]], max_tokens: int, temperature: float, llm_config: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """构建当前LLM格式请求体。"""
    cfg = _resolve_llm_config(llm_config)

    if cfg['api_format'] == 'gemini':
        system_messages: List[str] = []
        contents: List[Dict[str, Any]] = []

        for msg in messages:
            role = (msg or {}).get('role', 'user')
            content = (msg or {}).get('content', '')
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)

            if role == 'system':
                if content.strip():
                    system_messages.append(content)
                continue

            gemini_role = 'model' if role == 'assistant' else 'user'
            contents.append({
                'role': gemini_role,
                'parts': [{'text': content}]
            })

        if not contents:
            contents = [{'role': 'user', 'parts': [{'text': ''}]}]

        payload: Dict[str, Any] = {
            'contents': contents,
            'generationConfig': {
                'temperature': temperature,
                'maxOutputTokens': max_tokens
            }
        }

        if system_messages:
            payload['systemInstruction'] = {
                'parts': [{'text': '\n'.join(system_messages)}]
            }

        return payload

    return {
        'model': cfg['model_id'],
        'messages': messages,
        'temperature': temperature,
        'max_tokens': max_tokens
    }


def _extract_text_from_llm_response(result: Dict[str, Any], llm_config: Optional[Dict[str, str]] = None) -> str:
    """从当前LLM格式响应中提取文本。"""
    if _get_llm_api_format(llm_config) == 'gemini':
        candidates = result.get('candidates', [])
        if candidates:
            content_obj = candidates[0].get('content', {})
            parts = content_obj.get('parts', [])
            text = ''.join(part.get('text', '') for part in parts if isinstance(part, dict)).strip()
            if text:
                return text
        raise ValueError("Unexpected Gemini response format")

    if 'choices' in result and len(result['choices']) > 0:
        content = result['choices'][0].get('message', {}).get('content', '')
        if isinstance(content, str):
            return content.strip()

    raise ValueError("Unexpected OpenAI-compatible response format")


# 地点名称到ID的映射
LOCATION_NAME_TO_ID = {
    '远坂宅邸': 'tohsaka_residence',
    '远坂邸': 'tohsaka_residence',
    '冬木大桥': 'fuyuki_bridge',
    '大桥': 'fuyuki_bridge',
    '新都中心': 'shinto_center',
    '新都': 'shinto_center',
    '柳洞寺': 'ryuudou_temple',
    '冬木教会': 'fuyuki_church',
    '教会': 'fuyuki_church',
    '冬木港': 'fuyuki_harbor',
    '港口': 'fuyuki_harbor',
    '卫宫宅邸': 'emiya_residence',
    '卫宫邸': 'emiya_residence',
    '爱因兹贝伦森林': 'einzbern_forest',
    '森林': 'einzbern_forest',
    '深山町十字路口': 'miyama_crossroads',
    '十字路口': 'miyama_crossroads',
    '穗群原学园': 'homurahara_academy',
    '学园': 'homurahara_academy',
    '学校': 'homurahara_academy',
    '商店街': 'shopping_district',
    '圆藏山脚': 'mountain_path',
    '山脚': 'mountain_path',
    '临海公园': 'riverside_park',
    '公园': 'riverside_park',
    '凯悦酒店': 'center_building',
    '酒店': 'center_building',
}


def parse_player_movement(action_text: str, current_location: str, location_graph: Dict[str, LocationNode]) -> Optional[str]:
    """
    解析玩家输入，判断是否是移动行动
    
    Args:
        action_text: 玩家输入的行动文本
        current_location: 当前位置ID
        location_graph: 地图数据
        
    Returns:
        目标地点ID，如果不是移动行动则返回None
    """
    # 移动关键词
    movement_keywords = ['前往', '去', '移动到', '走向', '赶往', '前去', '出发去', '到']
    
    action_lower = action_text.strip()
    
    # 检查是否包含移动关键词
    target_location = None
    for keyword in movement_keywords:
        if keyword in action_lower:
            # 提取目标地点名称
            parts = action_lower.split(keyword)
            if len(parts) > 1:
                location_name = parts[1].strip()
                # 去除末尾的标点符号
                location_name = location_name.rstrip('。，！？')
                
                # 在映射表中查找
                if location_name in LOCATION_NAME_TO_ID:
                    target_location = LOCATION_NAME_TO_ID[location_name]
                    break
                
                # 在地图数据中查找（按名称匹配）
                for loc_id, loc_node in location_graph.items():
                    if loc_node.name == location_name or loc_node.english_name.lower() == location_name.lower():
                        target_location = loc_id
                        break
                    # 部分匹配
                    if location_name in loc_node.name:
                        target_location = loc_id
                        break
                
                if target_location:
                    break
    
    # 验证目标地点是否可达（可选：检查连接）
    if target_location and target_location != current_location:
        return target_location
    
    return None


def call_llm(messages: List[Dict[str, str]], max_tokens: int = 2000, temperature: float = 0.8, llm_config: Optional[Dict[str, str]] = None) -> str:
    """
    调用LLM API
    
    Args:
        messages: 消息列表
        max_tokens: 最大token数
        temperature: 温度参数
        
    Returns:
        LLM响应文本
    """
    cfg = _resolve_llm_config(llm_config)

    if not cfg['api_key']:
        raise ValueError("LLM_API_KEY not configured")
    
    try:
        response = requests.post(
            _build_llm_url(cfg),
            headers=_build_llm_headers(cfg),
            json=_build_llm_payload(messages, max_tokens=max_tokens, temperature=temperature, llm_config=cfg),
            timeout=120
        )
        response.raise_for_status()

        result = response.json()
        return _extract_text_from_llm_response(result, cfg)
            
    except requests.exceptions.RequestException as e:
        raise ValueError(f"LLM API request failed: {str(e)}")


def format_intents_for_prompt(intents: List[Intent], indent: int = 0) -> str:
    """
    格式化意图列表为可读文本（递归处理子意图）
    
    Args:
        intents: 意图列表
        indent: 缩进级别
        
    Returns:
        格式化的意图文本
    """
    if not intents:
        return "（无明确意图）"
    
    lines = []
    prefix = "  " * indent
    for intent in intents:
        status_icon = {
            IntentStatus.PENDING: "○",
            IntentStatus.ACTIVE: "●",
            IntentStatus.COMPLETED: "✓",
            IntentStatus.ABANDONED: "✗",
            IntentStatus.BLOCKED: "⊘"
        }.get(intent.status, "○")
        
        priority_text = f"[P{intent.priority}]" if intent.priority != 3 else ""
        lines.append(f"{prefix}{status_icon} {priority_text}{intent.goal}")
        
        if intent.sub_intents:
            lines.append(format_intents_for_prompt(intent.sub_intents, indent + 1))
    
    return "\n".join(lines)


def format_memories_for_prompt(memories: List[MemoryEntry], count: int = 5) -> str:
    """
    格式化最近记忆为可读文本
    
    Args:
        memories: 记忆列表
        count: 返回的记忆数量
        
    Returns:
        格式化的记忆文本
    """
    if not memories:
        return "（无记忆）"
    
    # 按回合倒序排列
    sorted_memories = sorted(memories, key=lambda m: m.turn, reverse=True)[:count]
    
    lines = []
    for mem in sorted_memories:
        lines.append(f"- [回合{mem.turn}] {mem.content}")
    
    return "\n".join(lines)


def build_location_narrative_prompt(
    location: LocationNode,
    characters: List[CharacterState],
    player_action: Dict[str, Any],
    is_player_location: bool,
    god_view: GodView,
    time_phase: str
) -> List[Dict[str, str]]:
    """
    构建地点叙事的LLM提示（第一步：生成故事）
    
    Args:
        location: 地点节点
        characters: 该地点的角色列表
        player_action: 玩家行动
        is_player_location: 是否是玩家所在地点
        god_view: 上帝视角
        time_phase: 当前时间段
        
    Returns:
        消息列表
    """
    # 构建角色描述（包含意图和记忆）
    char_descriptions = []
    for char in characters:
        if char.is_player:
            char_descriptions.append(f"### 玩家从者 {char.display_name}（{char.true_name}）")
        else:
            # NPC角色包含意图和记忆
            char_desc = f"### NPC从者 {char.display_name}（{char.true_name}）\n"
            char_desc += f"性格：{char.ai_personality}\n"
            
            if char.ai_context:
                # 添加意图
                intents_text = format_intents_for_prompt(char.ai_context.intents)
                char_desc += f"当前意图：\n{intents_text}\n"
                
                # 添加最近记忆
                memories_text = format_memories_for_prompt(char.ai_context.memories)
                char_desc += f"最近记忆：\n{memories_text}"
            
            char_descriptions.append(char_desc)
    
    chars_text = "\n\n".join(char_descriptions) if char_descriptions else "（无角色在此）"
    
    # 时间描述
    time_descriptions = {
        'dawn': '黎明时分，天边刚刚泛起鱼肚白',
        'day': '白天，阳光明媚',
        'dusk': '黄昏时分，夕阳西下',
        'night': '深夜，月光洒落',
        'midnight': '午夜时分，万籁俱寂'
    }
    time_desc = time_descriptions.get(time_phase, '深夜')
    
    # 地点最近历史
    recent_history = ""
    if location.history:
        recent = location.get_recent_history(3)
        if recent:
            history_lines = []
            for entry in recent:
                summary = entry.narrative[:100] + "..." if len(entry.narrative) > 100 else entry.narrative
                history_lines.append(f"- [回合{entry.turn}] {summary}")
            recent_history = f"\n### 地点近况\n" + "\n".join(history_lines)
    
    if is_player_location:
        # 玩家所在地点 - 详细描写
        action_text = player_action.get('message', '') or player_action.get('raw_input', '观察周围')
        
        system_prompt = """你是一位精通Type-Moon世界观的小说家，正在为圣杯战争游戏撰写沉浸式叙事。
你需要根据玩家的行动和NPC的意图，生成800-1200字的详细场景描写。

写作要求：
1. 以第二人称视角（"你"）描写
2. 语言风格要符合Fate系列的史诗感和神秘感
3. 用「」表示对话
4. 用*号包裹*表示动作或心理描写
5. 详细描写环境、氛围、角色互动
6. NPC的行动应该符合他们的意图和性格
7. 如果有其他从者在场，描写他们的反应和可能的对峙
8. 营造紧张感或适当的日常氛围
9. 注意NPC的最近记忆会影响他们的反应"""

        user_prompt = f"""## 当前场景

### 地点
- 名称：{location.name}（{location.english_name}）
- 描述：{location.description}
- 魔力浓度：{location.mana_density}/5
- 战术类型：{location.tactical_type}
{recent_history}

### 时间
{time_desc}
第{god_view.turn_count}回合

### 在场角色
{chars_text}

### 玩家行动
{action_text}

请生成这个场景的详细叙事描写："""

    else:
        # 其他地点 - 简略描写
        system_prompt = """你是圣杯战争的情报系统。请用简短的50-100字描述这个地点发生的事情。
要求：
1. 第三人称视角
2. 简洁明了，突出关键信息
3. NPC的行动应该符合他们的意图
4. 如果有战斗或重要事件，突出描写
5. 如果平静无事，简单描述氛围"""

        user_prompt = f"""## 地点：{location.name}
## 时间：{time_desc}（第{god_view.turn_count}回合）
## 在场角色
{chars_text}
{recent_history}

请用50-100字描述此刻这个地点的情况："""

    return [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_prompt}
    ]


def build_character_update_prompt(
    narrative: str,
    characters: List[CharacterState],
    location: LocationNode,
    god_view: GodView
) -> Optional[List[Dict[str, str]]]:
    """
    构建角色状态更新的LLM提示（第二步：更新意图和记忆）
    
    Args:
        narrative: 第一步生成的叙事
        characters: 该地点的角色列表
        location: 地点节点
        god_view: 上帝视角
        
    Returns:
        消息列表
    """
    # 构建角色当前状态描述
    char_states = []
    for char in characters:
        if char.is_player:
            continue  # 跳过玩家角色
        
        char_info = {
            "character_id": char.character_id,
            "name": char.display_name,
            "current_location": char.location_id,
            "current_intents": []
        }
        
        if char.ai_context:
            char_info["current_intents"] = [i.to_dict() for i in char.ai_context.intents]
        
        char_states.append(char_info)
    
    if not char_states:
        return None  # 没有NPC角色需要更新
    
    # 可移动的地点
    available_locations = list(god_view.location_graph.keys())
    connected_locations = location.connections if location.connections else available_locations[:5]
    
    system_prompt = """你是圣杯战争游戏的AI引擎。根据刚才发生的故事，更新每个NPC角色的意图和记忆。

你需要返回一个JSON对象，格式如下：
```json
{
  "character_updates": [
    {
      "character_id": "角色ID",
      "new_memory": {
        "content": "1-2句话总结这个角色在本回合的关键经历或获得的信息",
        "importance": 3,
        "related_characters": ["相关角色名"]
      },
      "updated_intents": {
        "intent_id": "new_status"
      },
      "new_intents": [
        {
          "id": "新意图ID",
          "goal": "新意图描述",
          "priority": 3,
          "status": "active",
          "sub_intents": []
        }
      ],
      "location_change": null
    }
  ]
}
```

规则：
1. new_memory.content 必须是1-2句话，记住本回合故事的核心信息
2. importance 范围1-5，5最重要（战斗、重要发现等）
3. updated_intents 可以将意图状态改为: pending/active/completed/abandoned/blocked
4. new_intents 是新产生的意图，可以有子意图（递归结构）
5. location_change 如果角色决定移动，填写目标地点ID，否则为null
6. 意图应该是具体可执行的，不要太抽象

只返回JSON，不要其他文字。"""

    user_prompt = f"""## 刚才发生的故事

{narrative}

## 当前地点
{location.name}（{location.node_id}）

## 可移动到的地点
{', '.join(connected_locations)}

## 需要更新的角色

{json.dumps(char_states, ensure_ascii=False, indent=2)}

请根据故事更新这些角色的意图和记忆："""

    return [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_prompt}
    ]


def generate_location_narrative(
    location_id: str,
    location: LocationNode,
    characters: List[CharacterState],
    player_action: Dict[str, Any],
    is_player_location: bool,
    god_view: GodView,
    llm_config: Optional[Dict[str, str]] = None
) -> LocationNarrativeResult:
    """
    生成单个地点的叙事（第一步）
    
    Args:
        location_id: 地点ID
        location: 地点节点
        characters: 该地点的角色列表
        player_action: 玩家行动
        is_player_location: 是否是玩家所在地点
        god_view: 上帝视角
        
    Returns:
        LocationNarrativeResult 对象
    """
    try:
        messages = build_location_narrative_prompt(
            location=location,
            characters=characters,
            player_action=player_action,
            is_player_location=is_player_location,
            god_view=god_view,
            time_phase=god_view.time_phase
        )
        
        # 玩家地点需要更多token
        max_tokens = 2000 if is_player_location else 300
        
        narrative = call_llm(messages, max_tokens=max_tokens, llm_config=llm_config)
        
        # 判断是否有战斗（简单启发式）
        combat_keywords = ['战斗', '攻击', '宝具', '剑', '魔术', '冲突', '对峙', '杀', '伤']
        is_combat = any(kw in narrative for kw in combat_keywords) and len(characters) > 1
        
        return LocationNarrativeResult(
            location_id=location_id,
            narrative=narrative,
            is_player_location=is_player_location,
            characters_involved=[c.display_name for c in characters],
            is_combat=is_combat
        )
        
    except Exception as e:
        print(f"Error generating narrative for {location_id}: {e}")
        fallback = f"*你来到了{location.name}，环顾四周...*" if is_player_location else f"{location.name}一片寂静。"
        return LocationNarrativeResult(
            location_id=location_id,
            narrative=fallback,
            is_player_location=is_player_location,
            characters_involved=[c.display_name for c in characters]
        )


def update_characters_after_narrative(
    narrative_result: LocationNarrativeResult,
    characters: List[CharacterState],
    location: LocationNode,
    god_view: GodView,
    llm_config: Optional[Dict[str, str]] = None
) -> List[CharacterStateUpdate]:
    """
    根据叙事更新角色状态（第二步）
    
    Args:
        narrative_result: 第一步生成的叙事结果
        characters: 该地点的角色列表
        location: 地点节点
        god_view: 上帝视角
        
    Returns:
        角色状态更新列表
    """
    # 过滤出NPC角色
    npc_characters = [c for c in characters if not c.is_player]
    if not npc_characters:
        return []
    
    try:
        messages = build_character_update_prompt(
            narrative=narrative_result.narrative,
            characters=npc_characters,
            location=location,
            god_view=god_view
        )
        
        if not messages:
            return []
        
        # 调用LLM获取JSON更新
        response = call_llm(messages, max_tokens=1500, temperature=0.3, llm_config=llm_config)
        
        # 解析JSON响应
        # 尝试提取JSON部分
        json_match = re.search(r'\{[\s\S]*\}', response)
        if not json_match:
            print(f"No JSON found in response: {response[:200]}")
            return []
        
        json_str = json_match.group()
        data = json.loads(json_str)
        
        updates = []
        for update_data in data.get('character_updates', []):
            # 解析新记忆
            new_memory = None
            if update_data.get('new_memory'):
                mem_data = update_data['new_memory']
                new_memory = MemoryEntry(
                    turn=god_view.turn_count,
                    time_phase=god_view.time_phase,
                    location_id=location.node_id,
                    content=mem_data.get('content', ''),
                    importance=mem_data.get('importance', 3),
                    related_characters=mem_data.get('related_characters', [])
                )
            
            # 解析新意图
            new_intents = []
            for intent_data in update_data.get('new_intents', []):
                intent_data['id'] = intent_data.get('id', str(uuid.uuid4())[:8])
                intent_data['created_turn'] = god_view.turn_count
                new_intents.append(Intent.from_dict(intent_data))
            
            update = CharacterStateUpdate(
                character_id=update_data.get('character_id', ''),
                new_intents=new_intents,
                updated_intents=update_data.get('updated_intents', {}),
                new_memory=new_memory,
                location_change=update_data.get('location_change'),
                hp_change=update_data.get('hp_change', 0),
                mp_change=update_data.get('mp_change', 0)
            )
            updates.append(update)
        
        return updates
        
    except json.JSONDecodeError as e:
        print(f"JSON parse error in character update: {e}")
        return []
    except Exception as e:
        print(f"Error updating characters: {e}")
        import traceback
        traceback.print_exc()
        return []


def process_game_turn_sync(god_view: GodView, player_action: Dict[str, Any], llm_config: Optional[Dict[str, str]] = None) -> GameResponse:
    """
    同步处理游戏回合 - 两步请求模式
    
    第一步：并发请求所有有角色的地点生成叙事
    第二步：根据叙事并发更新角色意图和记忆
    
    Args:
        god_view: 上帝视角（完整游戏状态）
        player_action: 玩家行动
        
    Returns:
        GameResponse 游戏响应
    """
    try:
        # 获取所有有角色的地点
        locations_with_chars = god_view.get_locations_with_characters()
        player_location = god_view.get_player_location()
        
        print(f"[game_loop] Processing turn {god_view.turn_count}")
        print(f"[game_loop] Player location: {player_location}")
        print(f"[game_loop] Locations with characters: {locations_with_chars}")
        
        # ========== 解析玩家移动 ==========
        action_text = player_action.get('message', '') or player_action.get('raw_input', '')
        player_new_location = parse_player_movement(action_text, player_location, god_view.location_graph)
        
        if player_new_location:
            print(f"[game_loop] Player moving from {player_location} to {player_new_location}")
            # 更新玩家位置
            if god_view.player_servant:
                god_view.player_servant.location_id = player_new_location
            player_location = player_new_location
            # 确保新位置也在处理列表中
            if player_new_location not in locations_with_chars:
                locations_with_chars.append(player_new_location)
        
        # 准备并发任务
        narrative_tasks = []
        
        for loc_id in locations_with_chars:
            location = god_view.location_graph.get(loc_id)
            if not location:
                # 使用默认地点信息
                location = LocationNode(
                    node_id=loc_id,
                    name=loc_id,
                    description="未知地点"
                )
            
            characters = god_view.get_characters_at_location(loc_id)
            is_player_loc = (loc_id == player_location)
            
            narrative_tasks.append({
                'location_id': loc_id,
                'location': location,
                'characters': characters,
                'is_player_location': is_player_loc
            })
        
        # ========== 第一步：并发生成叙事 ==========
        print("[game_loop] Step 1: Generating narratives...")
        
        narrative_results: Dict[str, LocationNarrativeResult] = {}
        task_map: Dict[str, dict] = {}  # location_id -> task
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = {}
            
            for task in narrative_tasks:
                future = executor.submit(
                    generate_location_narrative,
                    task['location_id'],
                    task['location'],
                    task['characters'],
                    player_action,
                    task['is_player_location'],
                    god_view,
                    llm_config
                )
                futures[future] = task
                task_map[task['location_id']] = task
            
            # 收集叙事结果
            for future in concurrent.futures.as_completed(futures, timeout=120):
                try:
                    result = future.result()
                    narrative_results[result.location_id] = result
                except Exception as e:
                    print(f"Error in narrative generation: {e}")
        
        print(f"[game_loop] Step 1 complete: {len(narrative_results)} narratives generated")
        
        # ========== 第二步：并发更新角色状态 ==========
        print("[game_loop] Step 2: Updating character states...")
        
        all_character_updates: List[CharacterStateUpdate] = []
        location_histories: Dict[str, LocationHistoryEntry] = {}
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            update_futures = {}
            
            for loc_id, narrative_result in narrative_results.items():
                task = task_map.get(loc_id)
                if not task:
                    continue
                
                # 提交第二步任务
                future = executor.submit(
                    update_characters_after_narrative,
                    narrative_result,
                    task['characters'],
                    task['location'],
                    god_view,
                    llm_config
                )
                update_futures[future] = (loc_id, narrative_result, task)
            
            # 收集更新结果
            for future in concurrent.futures.as_completed(update_futures, timeout=120):
                try:
                    updates = future.result()
                    loc_id, narrative_result, task = update_futures[future]
                    
                    all_character_updates.extend(updates)
                    
                    # 创建地点历史记录
                    history_entry = LocationHistoryEntry(
                        turn=god_view.turn_count,
                        time_phase=god_view.time_phase,
                        narrative=narrative_result.narrative,
                        characters_present=narrative_result.characters_involved,
                        is_combat=narrative_result.is_combat
                    )
                    location_histories[loc_id] = history_entry
                    
                except Exception as e:
                    print(f"Error in character update: {e}")
        
        print(f"[game_loop] Step 2 complete: {len(all_character_updates)} character updates")
        
        # ========== 组装响应 ==========
        main_story = ""
        side_intel_items = []
        map_visuals = {}
        
        for loc_id, result in narrative_results.items():
            task = task_map.get(loc_id)
            if not task:
                continue
            
            location = task['location']
            
            if result.is_player_location:
                main_story = result.narrative
                map_visuals[loc_id] = "current"
            else:
                level = "urgent" if result.is_combat else "info"
                
                side_intel_items.append(SideIntelItem(
                    text=result.narrative,
                    level=level,
                    location_id=loc_id,
                    location_name=location.name,
                    characters_involved=result.characters_involved,
                    is_combat=result.is_combat
                ))
                
                map_visuals[loc_id] = "combat" if result.is_combat else "activity"
        
        # ========== 处理NPC移动 ==========
        npc_movements = {}
        for update in all_character_updates:
            if update.location_change:
                npc_movements[update.character_id] = update.location_change
                print(f"[game_loop] NPC {update.character_id} moving to {update.location_change}")
        
        # 构建状态更新
        state_updates = {
            'turn': god_view.turn_count + 1,
            'time_phase': god_view.time_phase,
            'player': {
                'location': player_location,
                'hp': god_view.player_servant.hp_current if god_view.player_servant else 15000,
                'moved': player_new_location is not None,
                'previous_location': god_view.get_player_location() if player_new_location else None
            },
            'npc_movements': npc_movements  # NPC移动信息
        }
        
        return GameResponse(
            success=True,
            main_story=main_story,
            side_intel=side_intel_items,
            state_updates=state_updates,
            map_visuals=map_visuals,
            character_updates=all_character_updates,
            location_histories=location_histories
        )
        
    except Exception as e:
        print(f"Error in process_game_turn_sync: {e}")
        import traceback
        traceback.print_exc()
        
        return GameResponse(
            success=False,
            error=str(e)
        )

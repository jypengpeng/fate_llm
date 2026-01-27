"""
Holy Grail War Game Engine - Data Models
圣杯战争游戏引擎 - 数据模型

定义游戏中使用的所有数据结构。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any
from datetime import datetime


class ServantClass(Enum):
    """从者职阶枚举"""
    SABER = "Saber"
    ARCHER = "Archer"
    LANCER = "Lancer"
    RIDER = "Rider"
    CASTER = "Caster"
    ASSASSIN = "Assassin"
    BERSERKER = "Berserker"
    RULER = "Ruler"
    AVENGER = "Avenger"
    MOONCANCER = "MoonCancer"
    ALTEREGO = "Alterego"
    FOREIGNER = "Foreigner"
    PRETENDER = "Pretender"
    SHIELDER = "Shielder"
    BEAST = "Beast"


class HealthStatus(Enum):
    """健康状态枚举"""
    HEALTHY = "healthy"
    FATIGUED = "fatigued"
    INJURED = "injured"
    CRITICAL = "critical"
    UNCONSCIOUS = "unconscious"
    DEAD = "dead"


class RelationshipStatus(Enum):
    """关系状态枚举"""
    ALLY = "ally"
    FRIENDLY = "friendly"
    NEUTRAL = "neutral"
    HOSTILE = "hostile"
    ENEMY = "enemy"
    UNKNOWN = "unknown"


@dataclass
class ServantParameters:
    """从者能力参数"""
    strength: str = "C"
    endurance: str = "C"
    agility: str = "C"
    mana: str = "C"
    luck: str = "C"
    np: str = "C"
    
    def to_dict(self) -> Dict[str, str]:
        return {
            'strength': self.strength,
            'endurance': self.endurance,
            'agility': self.agility,
            'mana': self.mana,
            'luck': self.luck,
            'np': self.np
        }


class IntentStatus(Enum):
    """意图状态枚举"""
    PENDING = "pending"      # 待执行
    ACTIVE = "active"        # 正在执行
    COMPLETED = "completed"  # 已完成
    ABANDONED = "abandoned"  # 已放弃
    BLOCKED = "blocked"      # 被阻塞


@dataclass
class Intent:
    """
    角色意图 - 递归todolist结构
    大意图可以包含多个子意图
    """
    id: str                                          # 唯一标识
    goal: str                                        # 意图描述
    priority: int = 3                                # 优先级 1-5，1最高
    status: IntentStatus = IntentStatus.PENDING     # 当前状态
    sub_intents: List['Intent'] = field(default_factory=list)  # 子意图列表
    created_turn: int = 0                           # 创建于第几回合
    completed_turn: Optional[int] = None            # 完成于第几回合
    notes: str = ""                                 # 额外备注
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Intent':
        sub_intents = [cls.from_dict(sub) for sub in data.get('sub_intents', [])]
        status_str = data.get('status', 'pending')
        try:
            status = IntentStatus(status_str)
        except ValueError:
            status = IntentStatus.PENDING
            
        return cls(
            id=data.get('id', ''),
            goal=data.get('goal', ''),
            priority=data.get('priority', 3),
            status=status,
            sub_intents=sub_intents,
            created_turn=data.get('created_turn', 0),
            completed_turn=data.get('completed_turn'),
            notes=data.get('notes', '')
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'goal': self.goal,
            'priority': self.priority,
            'status': self.status.value,
            'sub_intents': [sub.to_dict() for sub in self.sub_intents],
            'created_turn': self.created_turn,
            'completed_turn': self.completed_turn,
            'notes': self.notes
        }
    
    def get_active_intents(self) -> List['Intent']:
        """获取所有活跃的意图（包括子意图）"""
        active = []
        if self.status == IntentStatus.ACTIVE:
            active.append(self)
        for sub in self.sub_intents:
            active.extend(sub.get_active_intents())
        return active
    
    def get_pending_intents(self) -> List['Intent']:
        """获取所有待执行的意图"""
        pending = []
        if self.status == IntentStatus.PENDING:
            pending.append(self)
        for sub in self.sub_intents:
            pending.extend(sub.get_pending_intents())
        return pending


@dataclass
class MemoryEntry:
    """记忆条目 - 每回合产生的核心记忆"""
    turn: int                    # 产生于第几回合
    time_phase: str              # 时间段
    location_id: str             # 地点ID
    content: str                 # 记忆内容（1-2句话）
    importance: int = 3          # 重要性 1-5，5最重要
    related_characters: List[str] = field(default_factory=list)  # 相关角色
    
    @classmethod
    def from_dict(cls, data: dict) -> 'MemoryEntry':
        return cls(
            turn=data.get('turn', 0),
            time_phase=data.get('time_phase', 'night'),
            location_id=data.get('location_id', ''),
            content=data.get('content', ''),
            importance=data.get('importance', 3),
            related_characters=data.get('related_characters', [])
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'turn': self.turn,
            'time_phase': self.time_phase,
            'location_id': self.location_id,
            'content': self.content,
            'importance': self.importance,
            'related_characters': self.related_characters
        }


@dataclass
class AIContext:
    """NPC AI上下文信息"""
    goal: str = ""
    memory: List[str] = field(default_factory=list)  # 旧版简单记忆（保持兼容）
    memories: List[MemoryEntry] = field(default_factory=list)  # 新版结构化记忆
    intents: List[Intent] = field(default_factory=list)  # 意图列表
    known_intel: Dict[str, Any] = field(default_factory=dict)
    current_stance_towards_others: Dict[str, str] = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'AIContext':
        memories = [MemoryEntry.from_dict(m) for m in data.get('memories', [])]
        intents = [Intent.from_dict(i) for i in data.get('intents', [])]
        return cls(
            goal=data.get('goal', ''),
            memory=data.get('memory', []),
            memories=memories,
            intents=intents,
            known_intel=data.get('known_intel', {}),
            current_stance_towards_others=data.get('current_stance_towards_others', {})
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'goal': self.goal,
            'memory': self.memory,
            'memories': [m.to_dict() for m in self.memories],
            'intents': [i.to_dict() for i in self.intents],
            'known_intel': self.known_intel,
            'current_stance_towards_others': self.current_stance_towards_others
        }
    
    def get_active_intents(self) -> List[Intent]:
        """获取所有活跃意图"""
        active = []
        for intent in self.intents:
            active.extend(intent.get_active_intents())
        return active
    
    def get_recent_memories(self, count: int = 5) -> List[MemoryEntry]:
        """获取最近的记忆"""
        sorted_memories = sorted(self.memories, key=lambda m: m.turn, reverse=True)
        return sorted_memories[:count]
    
    def add_memory(self, memory: MemoryEntry):
        """添加新记忆"""
        self.memories.append(memory)
        # 保持最多50条记忆
        if len(self.memories) > 50:
            # 按重要性和时间排序，保留重要的和最近的
            self.memories.sort(key=lambda m: (m.importance, m.turn), reverse=True)
            self.memories = self.memories[:50]


@dataclass
class CharacterState:
    """角色状态"""
    character_id: str
    true_name: str
    display_name: str
    servant_class: ServantClass
    is_player: bool = False
    location_id: str = "unknown"
    hp_current: int = 15000
    hp_max: int = 15000
    mp_current: int = 10000
    mp_max: int = 10000
    np_gauge: int = 0
    parameters: ServantParameters = field(default_factory=ServantParameters)
    status_effects: List[str] = field(default_factory=list)
    health_status: HealthStatus = HealthStatus.HEALTHY
    ai_context: Optional[AIContext] = None
    ai_personality: str = ""
    skills: List[Dict[str, Any]] = field(default_factory=list)
    noble_phantasms: List[Dict[str, Any]] = field(default_factory=list)
    
    def is_alive(self) -> bool:
        return self.hp_current > 0 and self.health_status != HealthStatus.DEAD
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'character_id': self.character_id,
            'true_name': self.true_name,
            'display_name': self.display_name,
            'servant_class': self.servant_class.value,
            'is_player': self.is_player,
            'location_id': self.location_id,
            'hp_current': self.hp_current,
            'hp_max': self.hp_max,
            'mp_current': self.mp_current,
            'mp_max': self.mp_max,
            'np_gauge': self.np_gauge,
            'parameters': self.parameters.to_dict(),
            'status_effects': self.status_effects,
            'health_status': self.health_status.value,
            'ai_context': self.ai_context.to_dict() if self.ai_context else None,
            'ai_personality': self.ai_personality,
            'skills': self.skills,
            'noble_phantasms': self.noble_phantasms
        }


@dataclass
class LocationHistoryEntry:
    """地点历史记录条目"""
    turn: int                                # 回合数
    time_phase: str                          # 时间段
    narrative: str                           # 叙事内容
    characters_present: List[str] = field(default_factory=list)  # 在场角色
    events: List[str] = field(default_factory=list)  # 关键事件标签
    is_combat: bool = False                  # 是否有战斗
    timestamp: str = ""                      # 实际时间戳
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()
    
    @classmethod
    def from_dict(cls, data: dict) -> 'LocationHistoryEntry':
        return cls(
            turn=data.get('turn', 0),
            time_phase=data.get('time_phase', 'night'),
            narrative=data.get('narrative', ''),
            characters_present=data.get('characters_present', []),
            events=data.get('events', []),
            is_combat=data.get('is_combat', False),
            timestamp=data.get('timestamp', '')
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'turn': self.turn,
            'time_phase': self.time_phase,
            'narrative': self.narrative,
            'characters_present': self.characters_present,
            'events': self.events,
            'is_combat': self.is_combat,
            'timestamp': self.timestamp
        }


@dataclass
class LocationNode:
    """地图节点"""
    node_id: str
    name: str
    english_name: str = ""
    description: str = ""
    region: str = "unknown"
    connections: List[str] = field(default_factory=list)
    mana_density: int = 2
    population: str = "Medium"
    tactical_type: str = "Open"
    is_unlocked: bool = True
    is_safe_zone: bool = False
    history: List[LocationHistoryEntry] = field(default_factory=list)  # 地点历史
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'node_id': self.node_id,
            'name': self.name,
            'english_name': self.english_name,
            'description': self.description,
            'region': self.region,
            'connections': self.connections,
            'mana_density': self.mana_density,
            'population': self.population,
            'tactical_type': self.tactical_type,
            'is_unlocked': self.is_unlocked,
            'is_safe_zone': self.is_safe_zone,
            'history': [h.to_dict() for h in self.history]
        }
    
    def add_history(self, entry: LocationHistoryEntry):
        """添加历史记录"""
        self.history.append(entry)
        # 保持最多100条历史
        if len(self.history) > 100:
            self.history = self.history[-100:]
    
    def get_recent_history(self, count: int = 10) -> List[LocationHistoryEntry]:
        """获取最近的历史记录"""
        return self.history[-count:] if self.history else []


@dataclass
class GodView:
    """
    上帝视角 - 游戏的完整状态
    包含所有角色、地图、关系的真实信息
    """
    turn_count: int = 1
    time_phase: str = "night"
    player_character_id: str = ""
    player_servant: Optional[CharacterState] = None
    player_master: Optional[Dict[str, Any]] = None
    npc_states: Dict[str, CharacterState] = field(default_factory=dict)
    location_graph: Dict[str, LocationNode] = field(default_factory=dict)
    relationship_graph: Dict[str, RelationshipStatus] = field(default_factory=dict)
    
    def get_characters_at_location(self, location_id: str) -> List[CharacterState]:
        """获取指定地点的所有角色"""
        chars = []
        if self.player_servant and self.player_servant.location_id == location_id:
            chars.append(self.player_servant)
        for char in self.npc_states.values():
            if char.location_id == location_id and char.is_alive():
                chars.append(char)
        return chars
    
    def get_locations_with_characters(self) -> List[str]:
        """获取有角色存在的所有地点ID"""
        locations = set()
        if self.player_servant:
            locations.add(self.player_servant.location_id)
        for char in self.npc_states.values():
            if char.is_alive():
                locations.add(char.location_id)
        return list(locations)
    
    def get_player_location(self) -> str:
        """获取玩家当前位置"""
        if self.player_servant:
            return self.player_servant.location_id
        return "unknown"


@dataclass
class SideIntelItem:
    """侧边情报项"""
    text: str
    level: str = "info"  # info, urgent, rumor, warning
    location_id: str = ""
    location_name: str = ""
    characters_involved: List[str] = field(default_factory=list)
    is_combat: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'text': self.text,
            'level': self.level,
            'location_id': self.location_id,
            'location_name': self.location_name,
            'characters_involved': self.characters_involved,
            'is_combat': self.is_combat
        }


@dataclass
class CharacterStateUpdate:
    """角色状态更新 - 第二步LLM返回的结构"""
    character_id: str
    new_intents: List[Intent] = field(default_factory=list)      # 新增意图
    updated_intents: Dict[str, str] = field(default_factory=dict)  # 更新意图状态 {intent_id: new_status}
    new_memory: Optional[MemoryEntry] = None                      # 新增记忆
    location_change: Optional[str] = None                         # 移动到新地点
    hp_change: int = 0                                            # HP变化
    mp_change: int = 0                                            # MP变化
    
    @classmethod
    def from_dict(cls, data: dict) -> 'CharacterStateUpdate':
        new_intents = [Intent.from_dict(i) for i in data.get('new_intents', [])]
        new_memory = None
        if data.get('new_memory'):
            new_memory = MemoryEntry.from_dict(data['new_memory'])
        return cls(
            character_id=data.get('character_id', ''),
            new_intents=new_intents,
            updated_intents=data.get('updated_intents', {}),
            new_memory=new_memory,
            location_change=data.get('location_change'),
            hp_change=data.get('hp_change', 0),
            mp_change=data.get('mp_change', 0)
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'character_id': self.character_id,
            'new_intents': [i.to_dict() for i in self.new_intents],
            'updated_intents': self.updated_intents,
            'new_memory': self.new_memory.to_dict() if self.new_memory else None,
            'location_change': self.location_change,
            'hp_change': self.hp_change,
            'mp_change': self.mp_change
        }


@dataclass
class LocationNarrativeResult:
    """地点叙事结果 - 第一步请求返回"""
    location_id: str
    narrative: str
    is_player_location: bool
    characters_involved: List[str] = field(default_factory=list)
    is_combat: bool = False
    events: List[str] = field(default_factory=list)  # 关键事件标签
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'location_id': self.location_id,
            'narrative': self.narrative,
            'is_player_location': self.is_player_location,
            'characters_involved': self.characters_involved,
            'is_combat': self.is_combat,
            'events': self.events
        }


@dataclass
class GameResponse:
    """游戏回合响应"""
    success: bool = True
    main_story: str = ""
    side_intel: List[SideIntelItem] = field(default_factory=list)
    state_updates: Dict[str, Any] = field(default_factory=dict)
    map_visuals: Dict[str, str] = field(default_factory=dict)
    character_updates: List[CharacterStateUpdate] = field(default_factory=list)  # 角色状态更新
    location_histories: Dict[str, LocationHistoryEntry] = field(default_factory=dict)  # 新增的地点历史
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'success': self.success,
            'mainStory': self.main_story,
            'sideIntel': [item.to_dict() for item in self.side_intel],
            'stateUpdates': self.state_updates,
            'mapVisuals': self.map_visuals,
            'characterUpdates': [u.to_dict() for u in self.character_updates],
            'locationHistories': {k: v.to_dict() for k, v in self.location_histories.items()},
            'error': self.error
        }
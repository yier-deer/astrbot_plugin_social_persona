from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class BigFive:
    """大五人格维度"""
    openness: float = 0.5
    conscientiousness: float = 0.5
    extraversion: float = 0.5
    agreeableness: float = 0.5
    neuroticism: float = 0.5

    def to_dict(self) -> dict:
        """序列化为字典"""
        return dict(self.__dict__)


@dataclass
class TypingStyle:
    """打字风格"""
    fragmentation_level: float = 0.3
    emoji_frequency: float = 0.2
    punctuation_style: str = "casual"
    avg_message_length: int = 15

    def to_dict(self) -> dict:
        """序列化为字典"""
        return dict(self.__dict__)


@dataclass
class Persona:
    """Persona 完整配置，包含 25+ 维度"""
    persona_id: str = ""
    name: str = ""
    gender: str = ""
    age: int = 20
    language_hint: str = "zh-CN"

    big_five: BigFive = field(default_factory=BigFive)

    attachment_anxiety: float = 0.3
    attachment_avoidance: float = 0.3
    self_esteem_stability: float = 0.5

    social_rhythm: str = "regular"
    conflict_style: str = "avoidant"
    initiative_tendency: float = 0.5

    input_method: str = "pinyin"
    typing_style: TypingStyle = field(default_factory=TypingStyle)
    typing_speed: int = 3

    image_enabled: int = 0
    image_style_prompt: str = ""
    character_appearance: str = ""

    character_current_context: str = ""
    life_stage: str = ""
    life_stage_detail: str = ""
    current_location: str = ""

    relationship_phase: str = "stranger"
    character_initial_world_time: str = ""

    created_at: str = ""
    session_key: str = ""

    def to_dict(self) -> dict:
        """序列化为字典"""
        result = {}
        for k, v in self.__dict__.items():
            if hasattr(v, 'to_dict'):
                result[k] = v.to_dict()
            else:
                result[k] = v
        return result

    @classmethod
    def from_dict(cls, data: dict) -> 'Persona':
        """从字典反序列化"""
        if 'big_five' in data and isinstance(data['big_five'], dict):
            data['big_five'] = BigFive(**data['big_five'])
        if 'typing_style' in data and isinstance(data['typing_style'], dict):
            data['typing_style'] = TypingStyle(**data['typing_style'])
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class RelationshipState:
    """关系状态"""
    persona_id: str = ""
    trust: float = 30.0
    closeness: float = 10.0
    tension: float = 0.0
    emotional_energy: float = 70.0
    tension_pressure: float = 0.0
    contact_urge: float = 0.3
    last_heartbeat_at: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: dict) -> 'RelationshipState':
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

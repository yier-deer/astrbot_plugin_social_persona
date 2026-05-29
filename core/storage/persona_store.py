import json
from datetime import datetime
from typing import Optional, List
from astrbot.api import logger
from .models import Persona, RelationshipState


class PersonaStore:
    """基于 AstrBot KV 存储的 Persona 数据管理"""

    KEY_PERSONA_INDEX = "persona:index"
    KEY_PERSONA_PREFIX = "persona:"
    KEY_RELATIONSHIP_PREFIX = "relationship:"
    KEY_ACTIVE_PERSONA_PREFIX = "active_persona:"
    KEY_MATCHMAKER_SESSION_PREFIX = "matchmaker_session:"
    KEY_EVENTS_PREFIX = "events:"
    KEY_PERSONA_STATE_PREFIX = "state:"

    def __init__(self, star_instance):
        """初始化存储，接收 Star 实例以调用 KV 方法"""
        self._star = star_instance

    async def _put(self, key: str, value):
        """写入 KV 存储"""
        await self._star.put_kv_data(key, value)

    async def _get(self, key: str, default=None):
        """读取 KV 存储"""
        return await self._star.get_kv_data(key, default)

    async def _delete(self, key: str):
        """删除 KV 存储"""
        await self._star.delete_kv_data(key)

    # === Persona CRUD ===

    async def create_persona(self, persona: Persona) -> None:
        """创建 Persona 并加入索引"""
        if not persona.created_at:
            persona.created_at = datetime.now().isoformat()
        await self._put(f"{self.KEY_PERSONA_PREFIX}{persona.persona_id}", persona.to_dict())
        index = await self._get(self.KEY_PERSONA_INDEX, [])
        if persona.persona_id not in index:
            index.append(persona.persona_id)
            await self._put(self.KEY_PERSONA_INDEX, index)

    async def get_persona(self, persona_id: str) -> Optional[Persona]:
        """获取 Persona"""
        data = await self._get(f"{self.KEY_PERSONA_PREFIX}{persona_id}")
        if data is None:
            return None
        return Persona.from_dict(data)

    async def update_persona(self, persona: Persona) -> None:
        """更新 Persona"""
        await self._put(f"{self.KEY_PERSONA_PREFIX}{persona.persona_id}", persona.to_dict())

    async def delete_persona(self, persona_id: str) -> None:
        """删除 Persona 及关联数据

        注意：active_bindings 清理必须在 persona 数据删除之前执行，因为需要读取 persona.session_key。
        """
        await self.cleanup_persona_active_bindings(persona_id)
        await self.cleanup_persona_events(persona_id)
        await self._delete(f"{self.KEY_PERSONA_PREFIX}{persona_id}")
        await self._delete(f"{self.KEY_RELATIONSHIP_PREFIX}{persona_id}")
        await self._delete(f"{self.KEY_PERSONA_STATE_PREFIX}{persona_id}")
        index = await self._get(self.KEY_PERSONA_INDEX, [])
        if persona_id in index:
            index.remove(persona_id)
            await self._put(self.KEY_PERSONA_INDEX, index)

    async def cleanup_persona_events(self, persona_id: str) -> None:
        """清理 Persona 的所有事件 KV 数据

        遍历近 7 天日期删除 events:{persona_id}:{date} 键。
        """
        from datetime import datetime, timedelta
        today = datetime.now()
        for day_offset in range(7):
            date_str = (today + timedelta(days=day_offset)).strftime("%Y-%m-%d")
            key = f"{self.KEY_EVENTS_PREFIX}{persona_id}:{date_str}"
            await self._delete(key)

    async def cleanup_persona_active_bindings(self, persona_id: str) -> None:
        """清理该 Persona 的所有 active_persona 绑定

        通过 session_key 定位并删除对应的 active_persona:{umo} 键。
        """
        persona = await self.get_persona(persona_id)
        if persona and persona.session_key:
            await self._delete(f"{self.KEY_ACTIVE_PERSONA_PREFIX}{persona.session_key}")

    async def list_personas(self) -> List[Persona]:
        """列出所有 Persona"""
        index = await self._get(self.KEY_PERSONA_INDEX, [])
        result = []
        for pid in index:
            p = await self.get_persona(pid)
            if p:
                result.append(p)
        return result

    # === RelationshipState CRUD ===

    async def init_relationship(self, persona_id: str, phase: str = "stranger") -> RelationshipState:
        """初始化关系状态"""
        initial = {
            "stranger": (30.0, 10.0),
            "acquaintance": (45.0, 25.0),
            "friend": (60.0, 45.0),
            "close_friend": (75.0, 70.0),
        }
        trust, closeness = initial.get(phase, (30.0, 10.0))
        state = RelationshipState(
            persona_id=persona_id,
            trust=trust,
            closeness=closeness,
            last_heartbeat_at=datetime.now().isoformat()
        )
        await self._put(f"{self.KEY_RELATIONSHIP_PREFIX}{persona_id}", state.to_dict())
        return state

    async def get_relationship(self, persona_id: str) -> Optional[RelationshipState]:
        """获取关系状态"""
        data = await self._get(f"{self.KEY_RELATIONSHIP_PREFIX}{persona_id}")
        if data is None:
            return None
        return RelationshipState.from_dict(data)

    async def save_relationship(self, state: RelationshipState) -> None:
        """保存关系状态"""
        await self._put(f"{self.KEY_RELATIONSHIP_PREFIX}{state.persona_id}", state.to_dict())

    # === Session-Persona Binding ===

    async def activate_persona(self, umo: str, persona_id: str) -> None:
        """激活会话的 Persona"""
        await self._put(f"{self.KEY_ACTIVE_PERSONA_PREFIX}{umo}", persona_id)

    async def deactivate_persona(self, umo: str) -> None:
        """取消激活"""
        await self._delete(f"{self.KEY_ACTIVE_PERSONA_PREFIX}{umo}")

    async def get_active_persona_id(self, umo: str) -> Optional[str]:
        """获取当前会话激活的 Persona ID"""
        return await self._get(f"{self.KEY_ACTIVE_PERSONA_PREFIX}{umo}")

    async def get_active_persona(self, umo: str) -> Optional[Persona]:
        """获取当前会话激活的 Persona 对象"""
        pid = await self.get_active_persona_id(umo)
        if pid:
            return await self.get_persona(pid)
        return None

    # === Persona State ===

    async def get_persona_state(self, persona_id: str) -> str:
        """获取 Persona 状态（ACTIVE/SLEEPING）"""
        return await self._get(f"{self.KEY_PERSONA_STATE_PREFIX}{persona_id}", "ACTIVE")

    async def set_persona_state(self, persona_id: str, state: str) -> None:
        """设置 Persona 状态"""
        await self._put(f"{self.KEY_PERSONA_STATE_PREFIX}{persona_id}", state)

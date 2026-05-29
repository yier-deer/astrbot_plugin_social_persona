from datetime import datetime
from typing import Optional

from astrbot.api import logger

from .curves import apply_closeness_curve, apply_trust_curve, apply_exponential_decay, apply_tension_decay
from .coefficients import CoefficientDeriver, DerivedCoefficients


class RelationshipEngine:
    """关系状态引擎：LLM 输出线性 delta，业务代码转非线性"""

    def __init__(self, store, coefficient_deriver: Optional[CoefficientDeriver] = None):
        self._store = store
        self._deriver = coefficient_deriver or CoefficientDeriver()

    async def apply_deltas(
        self,
        persona_id: str,
        trust_delta: float = 0.0,
        closeness_delta: float = 0.0,
        tension_delta: float = 0.0,
        emotional_energy_delta: float = 0.0,
        contact_urge_delta: float = 0.0,
        is_qualitative_leap: bool = False,
    ) -> None:
        """应用线性 delta，内部转非线性后更新存储"""
        state = await self._store.get_relationship(persona_id)
        if state is None:
            return

        persona = await self._store.get_persona(persona_id)
        if persona is None:
            return

        coeffs = self._deriver.derive(persona_id, persona.attachment_anxiety, persona.attachment_avoidance)

        # 先执行惰性心跳衰减
        state = self._apply_heartbeat(state, coeffs)

        # 亲密感：S 形曲线
        state.closeness = apply_closeness_curve(state.closeness, closeness_delta, is_qualitative_leap)

        # 信任：易碎效应
        state.trust = apply_trust_curve(state.trust, trust_delta, coeffs.trust_fragility_multiplier)

        # 张力：直接加减 + 依恋策略倍率
        state.tension = max(0.0, state.tension + tension_delta * coeffs.tension_growth_multiplier)

        # 情绪能量：直接加减
        state.emotional_energy = max(0.0, min(100.0, state.emotional_energy + emotional_energy_delta))

        # 联系冲动：直接加减
        state.contact_urge = max(0.0, min(1.0, state.contact_urge + contact_urge_delta))

        # 更新心跳时间
        state.last_heartbeat_at = datetime.now().isoformat()

        await self._store.save_relationship(state)
        logger.debug(f"关系状态已更新: {persona_id} trust={state.trust:.1f} closeness={state.closeness:.1f}")

    def _apply_heartbeat(self, state, coeffs: DerivedCoefficients):
        """惰性心跳衰减：计算距上次心跳的小时数，应用衰减"""
        if not state.last_heartbeat_at:
            return state

        try:
            last = datetime.fromisoformat(state.last_heartbeat_at)
            now = datetime.now()
            hours = (now - last).total_seconds() / 3600
        except (ValueError, TypeError):
            return state

        if hours <= 0:
            return state

        # 张力自然衰减
        state.tension = apply_tension_decay(state.tension, hours)

        # 情绪能量指数衰减
        state.emotional_energy = apply_exponential_decay(state.emotional_energy, coeffs.energy_decay_rate, hours)
        state.emotional_energy = max(0.0, min(100.0, state.emotional_energy))

        # 张力压强每小时积攒
        state.tension_pressure = max(0.0, state.tension_pressure + coeffs.tension_pressure_base * hours)

        return state

    async def get_state(self, persona_id: str):
        """获取关系状态（含惰性心跳衰减）"""
        state = await self._store.get_relationship(persona_id)
        if state is None:
            return None

        persona = await self._store.get_persona(persona_id)
        if persona is None:
            return state

        coeffs = self._deriver.derive(persona_id, persona.attachment_anxiety, persona.attachment_avoidance)
        state = self._apply_heartbeat(state, coeffs)

        state.last_heartbeat_at = datetime.now().isoformat()
        await self._store.save_relationship(state)

        return state

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api import logger


class RelationshipTools:
    """关系状态更新和记忆保存的 LLM Tool 集合"""

    def __init__(self, relationship_engine, memory_service, store):
        self._engine = relationship_engine
        self._memory = memory_service
        self._store = store

    def register(self, plugin_instance):
        """将所有 Tool 方法绑定到插件实例上

        注意：@filter.llm_tool 装饰器必须在插件类中才能被 AstrBot 识别。
        因此这里返回待注册的 Tool 定义，由 main.py 中的插件类使用。
        """
        pass


def create_update_relationship_tool(engine, store):
    """创建 update_relationship Tool 的工厂函数

    返回一个可以被 @filter.llm_tool 使用的异步函数。
    LLM 只输出线性 delta，非线性转换由 RelationshipEngine 完成。
    """
    async def update_relationship(self, event: AstrMessageEvent,
                                   trust_delta: float = 0.0,
                                   closeness_delta: float = 0.0,
                                   tension_delta: float = 0.0,
                                   emotional_energy_delta: float = 0.0,
                                   contact_urge_delta: float = 0.0,
                                   is_qualitative_leap: bool = False) -> MessageEventResult:
        """更新与用户的关系状态。根据对话内容判断关系变化的方向和幅度。

        Args:
            trust_delta(number): 信任变化量（线性增量，正为增加，负为减少，范围建议 -10 到 +10）
            closeness_delta(number): 亲密感变化量（线性增量，正为增加，负为减少，范围建议 -10 到 +10）
            tension_delta(number): 张力变化量（线性增量，正为增加，负为减少）
            emotional_energy_delta(number): 情绪能量变化量（线性增量，正为增加，负为减少）
            contact_urge_delta(number): 联系冲动变化量（0-1之间的小数，正为增加）
            is_qualitative_leap(boolean): 是否为质变事件（如表白、重大承诺等突破性时刻）
        """
        umo = event.unified_msg_origin
        persona = await store.get_active_persona(umo)
        if not persona:
            return

        await engine.apply_deltas(
            persona_id=persona.persona_id,
            trust_delta=trust_delta,
            closeness_delta=closeness_delta,
            tension_delta=tension_delta,
            emotional_energy_delta=emotional_energy_delta,
            contact_urge_delta=contact_urge_delta,
            is_qualitative_leap=is_qualitative_leap,
        )

    return update_relationship


def create_save_memory_tool(memory_service, store):
    """创建 save_memory Tool 的工厂函数"""
    async def save_memory(self, event: AstrMessageEvent,
                          memorable_point: str = "") -> MessageEventResult:
        """保存一段值得长期记住的内容到记忆中。

        Args:
            memorable_point(string): 值得记住的内容（一句话总结，如"用户提到他养了一只叫小橘的猫"）
        """
        if not memorable_point:
            return

        umo = event.unified_msg_origin
        persona = await store.get_active_persona(umo)
        if not persona:
            return

        await memory_service.add(memorable_point, persona.persona_id)

    return save_memory


def create_get_persona_status_tool(store, engine):
    """创建 get_persona_status Tool 的工厂函数"""
    async def get_persona_status(self, event: AstrMessageEvent):
        """获取当前 Persona 的关系状态详情。"""
        umo = event.unified_msg_origin
        persona = await store.get_active_persona(umo)
        if not persona:
            yield event.plain_result("当前没有激活的 Persona。")
            return

        state = await engine.get_state(persona.persona_id)
        if not state:
            yield event.plain_result("关系状态未初始化。")
            return

        status_text = (
            f"📊 {persona.name} 的关系状态\n"
            f"信任: {state.trust:.1f}/100\n"
            f"亲密: {state.closeness:.1f}/100\n"
            f"张力: {state.tension:.1f}\n"
            f"情绪能量: {state.emotional_energy:.1f}/100\n"
            f"联系冲动: {state.contact_urge:.2f}\n"
            f"张力压强: {state.tension_pressure:.2f}"
        )
        yield event.plain_result(status_text)

    return get_persona_status

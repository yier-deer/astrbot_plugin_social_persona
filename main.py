from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api import AstrBotConfig
from astrbot.core.star.filter.command import GreedyStr

@register("astrbot_plugin_social_persona", "SocialPersona", "关系状态驱动的 AI 社交模拟插件", "0.1.0")
class SocialPersonaPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

    async def initialize(self):
        """插件异步初始化：初始化关系引擎、记忆服务、事件调度器、Matchmaker"""
        from pathlib import Path
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path

        from .core.storage.persona_store import PersonaStore
        from .core.relationship.engine import RelationshipEngine
        from .core.relationship.coefficients import CoefficientDeriver
        from .core.memory.memory_service import MemoryService
        from .core.matchmaker.matchmaker_engine import MatchmakerEngine

        plugin_data_path = str(Path(get_astrbot_data_path()) / "plugin_data" / "astrbot_plugin_social_persona")
        Path(plugin_data_path).mkdir(parents=True, exist_ok=True)

        self.store = PersonaStore(self)
        self._deriver = CoefficientDeriver()
        self.engine = RelationshipEngine(self.store, self._deriver)
        self.memory_service = MemoryService(plugin_data_path, self.config.get("memory_search_limit", 5))

        embedding_providers = self.context.get_all_embedding_providers()
        if embedding_providers:
            self.memory_service.set_embedding_provider(embedding_providers[0])
            logger.info(f"记忆服务：使用 Embedding Provider: {embedding_providers[0].get_model()}")
        else:
            logger.warning("记忆服务：未检测到 Embedding Provider，记忆功能将不可用。请在 WebUI 中配置 Embedding 模型。")

        from .core.prompts.prompt_builder import PromptBuilder
        self.prompt_builder = PromptBuilder()
        self.matchmaker = MatchmakerEngine(self.store, self.prompt_builder)

        from .core.event.event_engine import EventEngine
        self.event_engine = EventEngine(
            store=self.store,
            engine=self.engine,
            memory_service=self.memory_service,
            prompt_builder=self.prompt_builder,
            context=self.context,
            config=self.config,
        )
        await self.event_engine.start()
        await self.event_engine.recover_on_startup()

        from .core.tools import create_update_relationship_tool, create_save_memory_tool
        self._update_relationship = create_update_relationship_tool(self.engine, self.store)
        self._save_memory = create_save_memory_tool(self.memory_service, self.store)

        from typing import Any
        from pydantic import Field
        from pydantic.dataclasses import dataclass
        from astrbot.core.agent.tool import FunctionTool, ToolExecResult
        from astrbot.core.agent.run_context import ContextWrapper
        from astrbot.core.astr_agent_context import AstrAgentContext

        @dataclass
        class UpdateRelationshipTool(FunctionTool[AstrAgentContext]):
            """更新与用户关系状态的 LLM 工具"""
            __pydantic_config__ = {"arbitrary_types_allowed": True}
            name: str = "update_relationship"
            description: str = "更新与用户的关系状态。根据对话内容判断关系变化的方向和幅度。"
            parameters: dict = Field(default_factory=lambda: {
                "type": "object",
                "properties": {
                    "trust_delta": {"type": "number", "description": "信任变化量（-10到+10）"},
                    "closeness_delta": {"type": "number", "description": "亲密感变化量（-10到+10）"},
                    "tension_delta": {"type": "number", "description": "张力变化量"},
                    "emotional_energy_delta": {"type": "number", "description": "情绪能量变化量"},
                    "contact_urge_delta": {"type": "number", "description": "联系冲动变化量（0-1小数）"},
                    "is_qualitative_leap": {"type": "boolean", "description": "是否质变事件"},
                },
                "required": [],
            })
            _engine: Any = None
            _store: Any = None

            async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
                event = context.context.event
                umo = event.unified_msg_origin
                persona = await self._store.get_active_persona(umo)
                if not persona:
                    return "没有激活的Persona"
                await self._engine.apply_deltas(persona_id=persona.persona_id, **kwargs)
                return "关系状态已更新"

        @dataclass
        class SaveMemoryTool(FunctionTool[AstrAgentContext]):
            """保存值得长期记住的内容到记忆中的 LLM 工具"""
            __pydantic_config__ = {"arbitrary_types_allowed": True}
            name: str = "save_memory"
            description: str = "保存一段值得长期记住的内容到记忆中。"
            parameters: dict = Field(default_factory=lambda: {
                "type": "object",
                "properties": {
                    "memorable_point": {"type": "string", "description": "值得记住的内容（一句话总结）"},
                },
                "required": ["memorable_point"],
            })
            _memory_service: Any = None
            _store: Any = None

            async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
                event = context.context.event
                umo = event.unified_msg_origin
                persona = await self._store.get_active_persona(umo)
                if not persona:
                    return "没有激活的Persona"
                await self._memory_service.add(kwargs.get("memorable_point", ""), persona.persona_id)
                return "记忆已保存"

        urt = UpdateRelationshipTool()
        urt._engine = self.engine
        urt._store = self.store

        smt = SaveMemoryTool()
        smt._memory_service = self.memory_service
        smt._store = self.store

        @dataclass
        class UpdateEventsTool(FunctionTool[AstrAgentContext]):
            """当对话改变了AI的计划时，重新生成今日事件线"""
            __pydantic_config__ = {"arbitrary_types_allowed": True}
            name: str = "update_events"
            description: str = "当你和用户的对话改变了你今天的计划时调用。例如用户邀请你旅游、约你出去、对话让你心情大变需要调整安排。"
            parameters: dict = Field(default_factory=lambda: {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "计划改变的原因"},
                },
                "required": ["reason"],
            })
            _event_engine: Any = None
            _store: Any = None

            async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
                event = context.context.event
                umo = event.unified_msg_origin
                persona = await self._store.get_active_persona(umo)
                if not persona:
                    return "没有激活的Persona"
                reason = kwargs.get("reason", "")
                result = await self._event_engine.regenerate_events_from_now(persona.persona_id)
                if result:
                    return f"事件线已更新（原因：{reason}），共 {len(result)} 个事件。"
                return "事件线更新失败"

        uet = UpdateEventsTool()
        uet._event_engine = self.event_engine
        uet._store = self.store

        self.context.add_llm_tools(urt, smt, uet)

        logger.info("社交人格插件初始化完成")

        cron_mgr = self.context.cron_manager
        if cron_mgr is None:
            logger.warning("CronJobManager 不可用，事件调度功能将禁用。"
                           "请在 AstrBot 配置中启用「主动型能力」以使用事件触发和主动消息功能。")
        else:
            logger.info("CronJobManager 可用，事件调度功能已启用。")

    async def terminate(self):
        """插件销毁：停止事件引擎并清理所有本插件的 CronJob"""
        if hasattr(self, "event_engine"):
            await self.event_engine.stop()
        else:
            cron_mgr = self.context.cron_manager
            if cron_mgr:
                try:
                    jobs = await cron_mgr.list_jobs()
                    for job in jobs:
                        if job.name and job.name.startswith("sp_event"):
                            await cron_mgr.delete_job(job.job_id)
                except Exception:
                    pass
        logger.info("社交人格插件已停止")

    @filter.on_llm_request()
    async def inject_persona_context(self, event: AstrMessageEvent, req):
        """在 LLM 请求前注入 Persona 动态上下文

        支持两种场景：
        1. 正常聊天：注入 persona 上下文 + 关系状态 + 记忆
        2. CronJob 唤醒：注入事件上下文，让 Agent 自主决定行动
        """
        umo = event.unified_msg_origin

        cron_job = event._extras.get("cron_job")
        cron_payload = event._extras.get("cron_payload", {})

        if cron_job and cron_payload.get("origin") == "plugin":
            persona_id = cron_payload.get("persona_id")
            if persona_id:
                await self._inject_cron_wake_context(event, req, persona_id, cron_payload)
            return

        matchmaker_active = await self.store._get(f"matchmaker_session:{umo}")
        if matchmaker_active:
            return

        quick_create_active = await self.store._get(f"quick_create_session:{umo}")
        if quick_create_active:
            return

        persona = await self.store.get_active_persona(umo)
        if not persona:
            platform_id = event.get_platform_id()
            mounted_persona_id = await self._get_platform_mounted_persona(platform_id)
            if mounted_persona_id:
                persona = await self.store.get_persona(mounted_persona_id)
                if persona:
                    await self._auto_activate_for_umo(persona, umo)

        if not persona:
            return

        if hasattr(self, "event_engine"):
            await self.event_engine.defer_sleep(persona.persona_id)

        state = await self.store.get_persona_state(persona.persona_id)
        if state == "SLEEPING":
            mode = self.config.get("sleep_response_mode", "drowsy")
            if mode == "ignore":
                return
            if mode == "silent":
                return

        relationship = await self.engine.get_state(persona.persona_id)
        if not relationship:
            return

        memories = await self.memory_service.search(event.message_str, persona.persona_id)

        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        events = await self.store._get(f"events:{persona.persona_id}:{today}", [])

        persona.last_user_message_time = datetime.now().isoformat()
        await self.store.update_persona(persona)

        world_date, world_dow = self.prompt_builder.compute_world_date(
            persona.character_initial_world_time, persona.created_at
        )

        is_drowsy = (state == "SLEEPING" and self.config.get("sleep_response_mode", "drowsy") == "drowsy")
        context_text = self.prompt_builder.build_chat_context(
            persona=persona.to_dict(),
            relationship=relationship.to_dict(),
            memories=memories,
            today_events=events,
            current_world_date=world_date,
            current_world_day_of_week=world_dow,
            is_drowsy=is_drowsy,
        )

        from astrbot.core.agent.message import TextPart
        req.extra_user_content_parts.append(TextPart(text=context_text))

    async def _inject_cron_wake_context(self, event, req, persona_id: str, cron_payload: dict):
        """CronJob 唤醒时注入事件上下文

        当 AstrBot 主动型能力触发 CronJob 时，主 Agent 被唤醒。
        此方法将 persona 上下文 + 事件信息注入到 Agent 请求中。

        Args:
            event: AstrMessageEvent
            req: LLM 请求对象
            persona_id: Persona 唯一标识
            cron_payload: CronJob 的 payload 字典
        """
        persona = await self.store.get_persona(persona_id)
        if not persona:
            return

        event_type = cron_payload.get("event_type", "routine")
        if event_type == "sleep":
            await self.store.set_persona_state(persona_id, "SLEEPING")
        else:
            current_state = await self.store.get_persona_state(persona_id)
            if current_state == "SLEEPING":
                await self.store.set_persona_state(persona_id, "ACTIVE")

        event_index = cron_payload.get("event_index", 0)
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        events = await self.store._get(f"events:{persona_id}:{today}", [])
        trigger_event = None
        if events and 0 <= event_index < len(events):
            trigger_event = events[event_index]
            trigger_event["is_active"] = False
            await self.store._put(f"events:{persona_id}:{today}", events)

        if not trigger_event:
            trigger_event = {
                "time": cron_payload.get("event_time", ""),
                "type": event_type,
                "description": cron_payload.get("event_description", ""),
            }

        relationship = await self.engine.get_state(persona_id)
        if not relationship:
            return

        memories = await self.memory_service.search(
            cron_payload.get("event_description", ""), persona_id
        )

        context_text = self.prompt_builder.build_cron_wake_note(
            persona=persona.to_dict(),
            event=trigger_event,
            relationship=relationship.to_dict(),
            memories=memories,
        )

        from astrbot.core.agent.message import TextPart
        req.extra_user_content_parts.append(TextPart(text=context_text))

    @filter.command_group("sp")
    def sp_group(self):
        """社交人格指令组"""
        pass

    @sp_group.command("list")
    async def sp_list(self, event: AstrMessageEvent):
        """查看所有 Persona 列表及挂载状态"""
        personas = await self.store.list_personas()
        if not personas:
            yield event.plain_result("还没有创建任何 Persona。使用 /sp create 或 /sp quick 创建一个吧！")
            return
        lines = ["📋 Persona 列表："]
        for p in personas:
            state = await self.store.get_persona_state(p.persona_id)
            mounted_platform = await self.store._get(f"persona_mount:{p.persona_id}")
            if mounted_platform:
                platform_info = self._get_platform_display_name(mounted_platform)
                lines.append(f"  • {p.name} ({p.relationship_phase}) [{state}] → 🤖 {platform_info}")
            else:
                lines.append(f"  • {p.name} ({p.relationship_phase}) [{state}] ⬜ 未挂载")
        yield event.plain_result("\n".join(lines))

    @sp_group.command("mount")
    async def sp_mount(self, event: AstrMessageEvent, name: GreedyStr):
        """将 Persona 挂载到指定机器人

        Args:
            name(string): 要挂载的 Persona 名称（可附加机器人ID，如"林小雨 aiocqhttp_1"）
        """
        parts = name.strip().split(None, 1)
        persona_name = parts[0]
        platform_id = parts[1].strip() if len(parts) > 1 else None

        personas = await self.store.list_personas()
        target = None
        for p in personas:
            if p.name == persona_name:
                target = p
                break
        if not target:
            yield event.plain_result(f"未找到名为「{persona_name}」的 Persona。")
            return

        if not platform_id:
            platforms = self._get_available_platforms()
            if not platforms:
                yield event.plain_result("⚠️ 当前没有可用的机器人（平台适配器）。请先在 WebUI 中配置平台。")
                return
            lines = [f"🤖 可用的机器人列表：\n"]
            for pf in platforms:
                mounted_pid = await self.store._get(f"platform_persona:{pf['id']}")
                mount_status = ""
                if mounted_pid:
                    mp = await self.store.get_persona(mounted_pid)
                    if mp:
                        mount_status = f"（已挂载：{mp.name}）"
                lines.append(f"  • {pf['display_name']} (ID: {pf['id']}) {mount_status}")
            lines.append(f"\n请使用 /sp mount {persona_name} <机器人ID> 挂载。")
            yield event.plain_result("\n".join(lines))
            return

        existing_platform = self._get_platform_by_id(platform_id)
        if not existing_platform:
            platforms = self._get_available_platforms()
            valid_ids = [pf["id"] for pf in platforms]
            yield event.plain_result(
                f"⚠️ 未找到 ID 为「{platform_id}」的机器人。\n"
                f"当前可用的机器人 ID：{', '.join(valid_ids)}"
            )
            return

        old_platform = await self.store._get(f"persona_mount:{target.persona_id}")
        if old_platform:
            await self.store._delete(f"platform_persona:{old_platform}")

        old_persona_id = await self.store._get(f"platform_persona:{platform_id}")
        if old_persona_id:
            await self.store._delete(f"persona_mount:{old_persona_id}")

        await self.store._put(f"persona_mount:{target.persona_id}", platform_id)
        await self.store._put(f"platform_persona:{platform_id}", target.persona_id)

        umo = event.unified_msg_origin
        target.session_key = umo
        await self.store.update_persona(target)
        await self.store.activate_persona(umo, target.persona_id)

        await self._register_persona_to_astrbot(target)

        if hasattr(self, "event_engine"):
            await self.event_engine.ensure_today_events(target.persona_id)

        platform_display = existing_platform.get("display_name", platform_id)
        yield event.plain_result(
            f"✅ 已将 Persona「{target.name}」挂载到机器人「{platform_display}」(ID: {platform_id})。\n"
            f"该机器人上的所有对话将自动使用此人格。"
        )

    @sp_group.command("unmount")
    async def sp_unmount(self, event: AstrMessageEvent, name: GreedyStr):
        """取消 Persona 的机器人挂载

        Args:
            name(string): 要取消挂载的 Persona 名称
        """
        personas = await self.store.list_personas()
        target = None
        for p in personas:
            if p.name == name:
                target = p
                break
        if not target:
            yield event.plain_result(f"未找到名为「{name}」的 Persona。")
            return

        mounted_platform = await self.store._get(f"persona_mount:{target.persona_id}")
        if not mounted_platform:
            yield event.plain_result(f"Persona「{target.name}」当前未挂载到任何机器人。")
            return

        await self.store._delete(f"platform_persona:{mounted_platform}")
        await self.store._delete(f"persona_mount:{target.persona_id}")

        if hasattr(self, "event_engine"):
            await self.event_engine._cleanup_persona_cronjobs(target.persona_id)

        try:
            persona_mgr = self.context.persona_manager
            for ap in persona_mgr.personas:
                if ap.persona_id == f"social_persona_{target.persona_id}":
                    await persona_mgr.delete_persona(ap.persona_id)
                    break
        except Exception as e:
            logger.warning(f"PersonaManager 清理失败: {e}")

        platform_display = self._get_platform_display_name(mounted_platform)
        yield event.plain_result(f"✅ 已将 Persona「{target.name}」从机器人「{platform_display}」取消挂载。")

    @sp_group.command("deactivate")
    async def sp_deactivate(self, event: AstrMessageEvent):
        """取消当前会话的 Persona 激活，同时清理相关 CronJob"""
        umo = event.unified_msg_origin
        persona = await self.store.get_active_persona(umo)
        if persona and hasattr(self, "event_engine"):
            await self.event_engine._cleanup_persona_cronjobs(persona.persona_id)
        await self.store.deactivate_persona(umo)
        yield event.plain_result("已取消 Persona 激活。恢复正常聊天模式。")

    @sp_group.command("status")
    async def sp_status(self, event: AstrMessageEvent):
        """查看当前关系状态"""
        umo = event.unified_msg_origin
        persona = await self.store.get_active_persona(umo)
        if not persona:
            platform_id = event.get_platform_id()
            mounted_persona_id = await self._get_platform_mounted_persona(platform_id)
            if mounted_persona_id:
                persona = await self.store.get_persona(mounted_persona_id)
        if not persona:
            yield event.plain_result("当前没有激活的 Persona。")
            return
        state = await self.engine.get_state(persona.persona_id)
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

    @filter.permission_type(filter.PermissionType.ADMIN)
    @sp_group.command("delete")
    async def sp_delete(self, event: AstrMessageEvent, name: GreedyStr):
        """删除指定 Persona（管理员权限）

        Args:
            name(string): 要删除的 Persona 名称
        """
        personas = await self.store.list_personas()
        target = None
        for p in personas:
            if p.name == name:
                target = p
                break
        if not target:
            yield event.plain_result(f"未找到名为「{name}」的 Persona。")
            return

        mounted_platform = await self.store._get(f"persona_mount:{target.persona_id}")
        if mounted_platform:
            await self.store._delete(f"platform_persona:{mounted_platform}")
            await self.store._delete(f"persona_mount:{target.persona_id}")

        if hasattr(self, "event_engine"):
            await self.event_engine._cleanup_persona_cronjobs(target.persona_id)

        await self.store.delete_persona(target.persona_id)
        await self.memory_service.delete_all(target.persona_id)

        try:
            persona_mgr = self.context.persona_manager
            for ap in persona_mgr.personas:
                if ap.persona_id == f"social_persona_{target.persona_id}":
                    await persona_mgr.delete_persona(ap.persona_id)
                    break
        except Exception as e:
            logger.warning(f"PersonaManager 清理失败: {e}")

        yield event.plain_result(f"已删除 Persona「{target.name}」及其所有数据。")

    @sp_group.command("create")
    async def sp_create(self, event: AstrMessageEvent):
        """创建新的 Persona（通过 Matchmaker 访谈引导）"""
        umo = event.unified_msg_origin
        existing = await self.matchmaker.get_session(umo)
        if existing:
            yield event.plain_result('你已经在创建流程中了。说"取消"可以退出。')
            return
        greeting = await self.matchmaker.start_session(umo)
        yield event.plain_result(greeting)

    @sp_group.command("info")
    async def sp_info(self, event: AstrMessageEvent, name: GreedyStr):
        """查看角色简要状态（好感度、今日事件、当前心思）

        Args:
            name(string): 角色名称
        """
        personas = await self.store.list_personas()
        target = None
        for p in personas:
            if p.name == name:
                target = p
                break
        if not target:
            yield event.plain_result(f"未找到名为「{name}」的角色。")
            return

        relationship = await self.engine.get_state(target.persona_id)
        state = await self.store.get_persona_state(target.persona_id)

        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        events = await self.store._get(f"events:{target.persona_id}:{today}", [])

        lines = [f"📊 {target.name} 的当前状态"]
        lines.append(f"状态：{state}")

        mounted_platform = await self.store._get(f"persona_mount:{target.persona_id}")
        if mounted_platform:
            lines.append(f"挂载：{self._get_platform_display_name(mounted_platform)}")

        if relationship:
            lines.append(f"\n💕 关系：")
            lines.append(f"  信任 {relationship.trust:.0f}/100 | 亲密 {relationship.closeness:.0f}/100")
            lines.append(f"  张力 {relationship.tension:.1f} | 情绪能量 {relationship.emotional_energy:.0f}/100")
            lines.append(f"  联系冲动 {relationship.contact_urge:.2f}")

        if target.life_stage_detail or target.current_location:
            lines.append(f"\n📍 处境：")
            if target.life_stage_detail:
                lines.append(f"  {target.life_stage_detail}")
            if target.current_location:
                lines.append(f"  在 {target.current_location}")

        if events:
            now_time = datetime.now().strftime("%H:%M")
            active = [e for e in events if e.get("is_active", True)]
            future = [e for e in active if e.get("time", "") >= now_time]
            if future:
                lines.append(f"\n📅 接下来的安排：")
                for e in future[:3]:
                    lines.append(f"  {e.get('time', '?')} {e.get('description', '')}")
                if len(future) > 3:
                    lines.append(f"  ...还有 {len(future) - 3} 件事")

        yield event.plain_result("\n".join(lines))

    @sp_group.command("detail")
    async def sp_detail(self, event: AstrMessageEvent, name: GreedyStr):
        """查看角色完整信息（所有属性、关系、记忆、事件线）

        Args:
            name(string): 角色名称
        """
        personas = await self.store.list_personas()
        target = None
        for p in personas:
            if p.name == name:
                target = p
                break
        if not target:
            yield event.plain_result(f"未找到名为「{name}」的角色。")
            return

        relationship = await self.engine.get_state(target.persona_id)
        state = await self.store.get_persona_state(target.persona_id)

        lines = [f"📋 {target.name} 的完整信息"]
        lines.append(f"ID: {target.persona_id}")
        lines.append(f"状态: {state}")

        mounted_platform = await self.store._get(f"persona_mount:{target.persona_id}")
        if mounted_platform:
            lines.append(f"挂载平台: {self._get_platform_display_name(mounted_platform)} (ID: {mounted_platform})")
        else:
            lines.append(f"挂载平台: 未挂载")

        lines.append(f"\n👤 基本信息：")
        lines.append(f"  名字: {target.name}")
        lines.append(f"  性别: {target.gender}")
        lines.append(f"  年龄: {target.age}")
        lines.append(f"  生活阶段: {target.life_stage} - {target.life_stage_detail}")
        lines.append(f"  所在地: {target.current_location}")

        bf = target.big_five
        lines.append(f"\n🧠 大五人格：")
        lines.append(f"  开放性: {bf.openness:.2f} | 尽责性: {bf.conscientiousness:.2f}")
        lines.append(f"  外向性: {bf.extraversion:.2f} | 宜人性: {bf.agreeableness:.2f}")
        lines.append(f"  神经质: {bf.neuroticism:.2f}")

        lines.append(f"\n💞 依恋与冲突：")
        lines.append(f"  依恋焦虑: {target.attachment_anxiety:.2f}")
        lines.append(f"  依恋回避: {target.attachment_avoidance:.2f}")
        lines.append(f"  自尊稳定性: {target.self_esteem_stability:.2f}")
        lines.append(f"  冲突风格: {target.conflict_style}")
        lines.append(f"  关系阶段: {target.relationship_phase}")

        ts = target.typing_style
        lines.append(f"\n⌨️ 打字风格：")
        lines.append(f"  碎片化: {ts.fragmentation_level:.2f}")
        lines.append(f"  发图: {'是' if target.image_enabled else '否'}")

        if relationship:
            lines.append(f"\n💕 关系状态：")
            lines.append(f"  信任: {relationship.trust:.1f}/100")
            lines.append(f"  亲密: {relationship.closeness:.1f}/100")
            lines.append(f"  张力: {relationship.tension:.1f}")
            lines.append(f"  情绪能量: {relationship.emotional_energy:.1f}/100")
            lines.append(f"  联系冲动: {relationship.contact_urge:.3f}")
            lines.append(f"  张力压强: {relationship.tension_pressure:.3f}")

        if target.character_current_context:
            lines.append(f"\n📖 生活背景：")
            lines.append(f"  {target.character_current_context}")

        if target.character_appearance:
            lines.append(f"\n👤 外貌：")
            lines.append(f"  {target.character_appearance}")

        if target.birthday:
            lines.append(f"\n🎂 生日：{target.birthday}")

        if target.life_archives:
            lines.append(f"\n📜 人生经历（{len(target.life_archives)} 条）：")
            sorted_archives = sorted(target.life_archives, key=lambda x: x.get("time", ""))
            for a in sorted_archives:
                stage_name = {"childhood": "童年", "adolescence": "青少年", "young_adult": "青年", "": ""}.get(a.get("stage", ""), a.get("stage", ""))
                lines.append(f"  [{stage_name}] {a.get('time', '')}：{a.get('content', '')}")

        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        events = await self.store._get(f"events:{target.persona_id}:{today}", [])
        if events:
            lines.append(f"\n📅 今日事件线（{len(events)} 个）：")
            for e in events:
                status = "✅" if not e.get("is_active", True) else "⏳"
                lines.append(f"  {status} {e.get('time', '?')} [{e.get('type', '?')}] {e.get('description', '')}")

        memories = await self.memory_service.search("", target.persona_id)
        if memories:
            lines.append(f"\n🧠 记忆（最近 {len(memories)} 条）：")
            for i, mem in enumerate(memories, 1):
                lines.append(f"  {i}. {mem}")

        yield event.plain_result("\n".join(lines))

    @sp_group.command("quick")
    async def sp_quick(self, event: AstrMessageEvent, description: GreedyStr):
        """快速创建 Persona（一段话描述角色，立即生成）

        Args:
            description(string): 角色的完整描述（名字、年龄、性格、说话风格、依恋倾向等）
        """
        umo = event.unified_msg_origin

        provider_id = await self._get_chat_provider_id()
        if not provider_id:
            yield event.plain_result("未配置 LLM Provider，请在 WebUI 中配置后再试。")
            return

        async def llm_generate(prompt: str) -> str:
            try:
                resp = await self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                    system_prompt="你是一个数据提取助手。你必须严格按照用户要求的JSON格式回复，不要添加任何解释、markdown标记或额外文本。直接输出纯JSON。",
                )
                return resp.completion_text if resp else ""
            except Exception as e:
                logger.error(f"QuickCreate LLM 调用失败: {e}")
                return ""

        message, persona_id = await self.matchmaker.quick_create(umo, description, llm_generate)

        if persona_id:
            persona = await self.store.get_persona(persona_id)
            if persona:
                await self._register_persona_to_astrbot(persona)

        yield event.plain_result(message)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_all_message(self, event: AstrMessageEvent):
        """监听所有消息，路由到快速创建或 Matchmaker 会话"""
        umo = event.unified_msg_origin

        if event.message_str.strip().startswith("/"):
            return

        provider_id = await self._get_chat_provider_id()

        async def _quick_llm(prompt: str) -> str:
            if not provider_id:
                return ""
            try:
                resp = await self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                    system_prompt="你是一个数据提取助手。你必须严格按照用户要求的JSON格式回复，不要添加任何解释、markdown标记或额外文本。直接输出纯JSON。",
                )
                return resp.completion_text if resp else ""
            except Exception as e:
                logger.error(f"QuickCreate LLM 调用失败: {e}")
                return ""

        async def _matchmaker_llm(prompt: str) -> str:
            if not provider_id:
                return ""
            try:
                resp = await self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                    system_prompt=self.prompt_builder.build_matchmaker_system_prompt(),
                )
                return resp.completion_text if resp else ""
            except Exception as e:
                logger.error(f"Matchmaker LLM 调用失败: {e}")
                return ""

        quick_session = await self.matchmaker.get_quick_session(umo)
        if quick_session:
            message, persona_id = await self.matchmaker.quick_create(umo, event.message_str, _quick_llm)
            if persona_id:
                persona = await self.store.get_persona(persona_id)
                if persona:
                    await self._register_persona_to_astrbot(persona)
            yield event.plain_result(message)
            event.stop_event()
            return

        session = await self.matchmaker.get_session(umo)
        if not session:
            return

        message, persona_id = await self.matchmaker.process_message(umo, event.message_str, _matchmaker_llm)
        if persona_id:
            persona = await self.store.get_persona(persona_id)
            if persona:
                await self._register_persona_to_astrbot(persona)
        yield event.plain_result(message)
        event.stop_event()

    async def _get_chat_provider_id(self) -> str:
        """获取当前可用的 LLM Provider ID"""
        configured = self.config.get("chat_provider_id", "")
        if configured:
            return configured
        providers = self.context.get_all_providers()
        if providers:
            return providers[0].meta().id
        return ""

    def _get_available_platforms(self) -> list:
        """获取所有可用的平台适配器列表

        Returns:
            平台信息列表，每项包含 id, name, display_name
        """
        platforms = []
        try:
            for inst in self.context.platform_manager.platform_insts:
                meta = inst.meta()
                platforms.append({
                    "id": meta.id,
                    "name": meta.name,
                    "display_name": meta.adapter_display_name or meta.name,
                })
        except Exception as e:
            logger.warning(f"获取平台列表失败: {e}")
        return platforms

    def _get_platform_by_id(self, platform_id: str) -> dict | None:
        """根据平台 ID 查找平台信息

        Args:
            platform_id: 平台适配器的唯一标识符

        Returns:
            平台信息字典，未找到返回 None
        """
        for pf in self._get_available_platforms():
            if pf["id"] == platform_id:
                return pf
        return None

    def _get_platform_display_name(self, platform_id: str) -> str:
        """获取平台的显示名称

        Args:
            platform_id: 平台适配器的唯一标识符

        Returns:
            平台显示名称，未找到则返回 platform_id 本身
        """
        pf = self._get_platform_by_id(platform_id)
        if pf:
            return pf["display_name"]
        return platform_id

    async def _get_platform_mounted_persona(self, platform_id: str) -> str | None:
        """获取挂载到指定平台的 Persona ID

        Args:
            platform_id: 平台适配器的唯一标识符

        Returns:
            挂载的 Persona ID，未挂载返回 None
        """
        return await self.store._get(f"platform_persona:{platform_id}")

    async def _auto_activate_for_umo(self, persona, umo: str) -> bool:
        """自动为 UMO 激活 Persona（仅当该 UMO 没有已激活的 Persona 时）

        Args:
            persona: 插件内部的 Persona 对象
            umo: 用户会话标识

        Returns:
            是否激活成功
        """
        try:
            persona_mgr = self.context.persona_manager
            astr_persona_id = f"social_persona_{persona.persona_id}"

            registered = False
            for ap in persona_mgr.personas:
                if ap.persona_id == astr_persona_id:
                    registered = True
                    break
            if not registered:
                await self._register_persona_to_astrbot(persona)

            conv_mgr = self.context.conversation_manager
            curr_cid = await conv_mgr.get_curr_conversation_id(umo)
            if curr_cid:
                await conv_mgr.update_conversation(umo, curr_cid, persona_id=astr_persona_id)

            is_mounted = await self.store._get(f"persona_mount:{persona.persona_id}")
            if not is_mounted:
                persona.session_key = umo
                await self.store.update_persona(persona)
            await self.store.activate_persona(umo, persona.persona_id)

            if hasattr(self, "event_engine"):
                await self.event_engine.ensure_today_events(persona.persona_id)

            return True
        except Exception as e:
            logger.warning(f"Persona 自动激活失败: {e}")
            return False

    def _build_stable_system_prompt(self, persona) -> str:
        """构建只含稳定特质的 system_prompt（不含会变化的处境）

        只使用 Persona 模型中实际存在的字段，避免 AttributeError。
        大五人格维度从 persona.big_five 推导出性格描述。
        """
        traits = []
        if persona.name:
            traits.append(f"你的名字是{persona.name}")
        if persona.gender:
            traits.append(f"你是{persona.gender}性")
        if persona.age:
            traits.append(f"你{persona.age}岁")
        if persona.life_stage_detail:
            traits.append(f"你的身份是{persona.life_stage_detail}")
        if persona.current_location:
            traits.append(f"你在{persona.current_location}")

        bf = persona.big_five
        personality_parts = []
        if bf.agreeableness < 0.4:
            personality_parts.append("直言不讳")
        elif bf.agreeableness > 0.6:
            personality_parts.append("温和友善")
        if bf.extraversion > 0.6:
            personality_parts.append("外向活泼")
        elif bf.extraversion < 0.4:
            personality_parts.append("内向安静")
        if bf.neuroticism > 0.6:
            personality_parts.append("情绪敏感")
        if bf.openness > 0.6:
            personality_parts.append("好奇开放")
        if personality_parts:
            traits.append(f"你的性格：{'、'.join(personality_parts)}")

        if persona.conflict_style:
            conflict_map = {"avoidant": "回避冲突", "confrontational": "直接对抗", "compromising": "妥协但嘴硬"}
            traits.append(f"你处理冲突的方式是{conflict_map.get(persona.conflict_style, persona.conflict_style)}")
        if persona.attachment_anxiety is not None:
            if persona.attachment_anxiety >= 0.7:
                traits.append("你很容易焦虑对方是否还在乎你")
            elif persona.attachment_anxiety >= 0.4:
                traits.append("你偶尔会担心对方的态度")
        if persona.attachment_avoidance is not None:
            if persona.attachment_avoidance <= 0.3:
                traits.append("你很依赖亲密关系，喜欢黏着对方")
            elif persona.attachment_avoidance >= 0.7:
                traits.append("你倾向于保持距离")

        if persona.character_appearance:
            traits.append(f"你的外貌：{persona.character_appearance}")

        if not traits:
            return f"你是{persona.name}，一个有独立情感和生活的AI角色。"
        return "。".join(traits) + "。"

    async def _register_persona_to_astrbot(self, persona) -> bool:
        """将 Persona 注册到 AstrBot PersonaManager（使用稳定特质作为 system_prompt）

        Args:
            persona: 插件内部的 Persona 对象

        Returns:
            是否注册成功
        """
        try:
            persona_mgr = self.context.persona_manager
            astr_persona_id = f"social_persona_{persona.persona_id}"
            system_prompt = self._build_stable_system_prompt(persona)

            existing = None
            for ap in persona_mgr.personas:
                if ap.persona_id == astr_persona_id:
                    existing = ap
                    break

            if existing:
                await persona_mgr.update_persona(astr_persona_id, system_prompt=system_prompt)
                logger.info(f"已更新 AstrBot 人格设定: {astr_persona_id}")
            else:
                await persona_mgr.create_persona(
                    persona_id=astr_persona_id,
                    system_prompt=system_prompt,
                )
                logger.info(f"已注册 AstrBot 人格设定: {astr_persona_id}")
            return True
        except Exception as e:
            logger.warning(f"PersonaManager 注册失败（不影响核心功能）: {e}")
            return False

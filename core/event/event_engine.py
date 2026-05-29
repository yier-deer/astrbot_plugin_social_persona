import json
import re
from datetime import datetime, timedelta
from typing import Optional, List

from astrbot.api import logger


class EventEngine:
    """事件调度引擎：每日事件生成 + CronJob 调度 + 主动消息

    职责边界：
      EventEngine → 事件生成 + CronJob 创建/清理
      AstrBot CronJobManager → 定时触发
      AstrBot 主 Agent → 事件触发时的思考和行动
      PersonaStore → KV 数据读写
    """

    SLEEP_POSTPONE_MINUTES = 30
    SLEEP_HARD_CAP = "02:00"
    CRON_JOB_PREFIX = "sp_event"

    def __init__(self, store, engine, memory_service, prompt_builder, context, config):
        """
        Args:
            store: PersonaStore 实例，负责 KV 读写
            engine: RelationshipEngine 实例，负责关系增量
            memory_service: MemoryService 实例，负责记忆写入
            prompt_builder: PromptBuilder 实例，负责 Prompt 构建
            context: AstrBot Context 实例，提供 cron_manager / llm_generate
            config: 插件配置字典
        """
        self._store = store
        self._engine = engine
        self._memory = memory_service
        self._prompt_builder = prompt_builder
        self._context = context
        self._config = config

    async def start(self):
        """启动事件调度引擎（CronJob 模式，无需后台轮询）"""
        cron_mgr = self._context.cron_manager
        if cron_mgr is None:
            logger.warning("CronJobManager 不可用，事件生成功能将禁用。请在配置中启用主动型能力。")
        else:
            logger.info("事件调度引擎已启动（CronJob 模式）")

    async def stop(self):
        """停止事件调度引擎并清理所有本插件的 CronJob"""
        await self.cleanup_all_plugin_cronjobs()
        logger.info("事件调度引擎已停止")

    async def _get_chat_provider_id(self) -> Optional[str]:
        """获取当前可用的 LLM Provider ID"""
        configured = self._config.get("chat_provider_id", "")
        if configured:
            return configured
        providers = self._context.get_all_providers()
        if providers:
            return providers[0].meta().id
        return None

    async def _call_llm(self, prompt: str) -> Optional[str]:
        """调用 LLM 并返回 completion_text（仅用于事件生成）"""
        provider_id = await self._get_chat_provider_id()
        if not provider_id:
            logger.warning("无可用的 LLM Provider，事件生成跳过")
            return None
        try:
            resp = await self._context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )
            if resp and resp.completion_text:
                return resp.completion_text
            return None
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            return None

    @staticmethod
    def _parse_json_from_text(text: str) -> Optional[dict]:
        """从 LLM 输出中提取第一个 JSON 对象"""
        if not text:
            return None
        json_match = re.search(r'\{[\s\S]*\}', text)
        if not json_match:
            return None
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            return None

    async def generate_daily_events(self, persona_id: str) -> Optional[List[dict]]:
        """为指定 Persona 生成每日事件并创建 CronJob

        流程：
          1. 计算 world_date / world_dow
          2. 构建 Prompt → 调 LLM
          3. 解析 JSON → 存储事件
          4. 处理今日反思（关键记忆 + 生命阶段切换）
          5. 为每个事件创建 CronJob

        Args:
            persona_id: Persona 唯一标识

        Returns:
            生成的事件列表，失败返回 None
        """
        persona = await self._store.get_persona(persona_id)
        if not persona:
            return None

        world_date, world_dow = self._prompt_builder.compute_world_date(
            persona.character_initial_world_time, persona.created_at
        )

        prompt = self._prompt_builder.build_event_generate_prompt(
            persona=persona.to_dict(),
            current_world_date=world_date,
            current_world_day_of_week=world_dow,
        )

        raw_text = await self._call_llm(prompt)
        if not raw_text:
            return None

        parsed = self._parse_json_from_text(raw_text)
        if not parsed:
            logger.warning(f"事件生成 JSON 解析失败 ({persona_id})")
            return None

        events = parsed.get("events", [])

        events = self._ensure_event_order(events)

        today = datetime.now().strftime("%Y-%m-%d")
        await self._store._put(f"events:{persona_id}:{today}", events)

        reflection = parsed.get("today_reflection", {})

        key_memories = reflection.get("key_memories", [])
        for mem in key_memories:
            if isinstance(mem, dict) and mem.get("importance", 0) >= 7:
                await self._memory.add(mem.get("content", ""), persona_id)

        transition = reflection.get("life_stage_transition", {})
        if transition.get("should_transition"):
            new_stage = transition.get("new_life_stage", persona.life_stage)
            new_detail = transition.get("new_life_stage_detail", persona.life_stage_detail)
            new_location = transition.get("new_location", persona.current_location)
            reason = transition.get("transition_reason", "")

            persona.life_stage = new_stage
            persona.life_stage_detail = new_detail
            persona.current_location = new_location

            context_parts = []
            base = persona.character_current_context or ""
            if base:
                context_parts.append(base)
            if new_detail:
                context_parts.append(f"【当前身份】{new_detail}")
            if new_location:
                context_parts.append(f"【当前地点】{new_location}")
            if reason:
                context_parts.append(f"【切换原因】{reason}")
            persona.character_current_context = "\n".join(context_parts)

            await self._store.update_persona(persona)
            logger.info(f"Persona {persona.name} 生命阶段切换: {new_stage} (原因: {reason})")

        life_archive_entry = reflection.get("life_archive_entry")
        if isinstance(life_archive_entry, dict) and life_archive_entry.get("content"):
            entry = {
                "stage": persona.life_stage or "young_adult",
                "time": world_date,
                "type": "created_event",
                "content": life_archive_entry.get("content", ""),
                "importance": life_archive_entry.get("importance", 7),
            }
            persona.life_archives = list(persona.life_archives or [])
            persona.life_archives.append(entry)
            await self._store.update_persona(persona)
            logger.info(f"Persona {persona.name} 人生经历新增: {entry['content'][:50]}")

        await self._schedule_event_cronjobs(persona_id, events)

        return events

    async def _schedule_event_cronjobs(self, persona_id: str, events: List[dict]):
        """为当日事件创建 CronJob

        每个 active 事件创建一个 run_once CronJob，触发时唤醒主 Agent。

        Args:
            persona_id: Persona 唯一标识
            events: 当日事件列表
        """
        cron_mgr = self._context.cron_manager
        if cron_mgr is None:
            logger.warning("CronJobManager 不可用，跳过 CronJob 创建")
            return

        persona = await self._store.get_persona(persona_id)
        if not persona or not persona.session_key:
            logger.debug(f"Persona {persona_id} 无 session_key，跳过 CronJob 创建")
            return

        if persona.session_key.count(":") < 2:
            logger.warning(f"Persona {persona_id} 的 session_key 格式无效（期望 platform_id:message_type:session_id），跳过 CronJob 创建")
            return

        await self._cleanup_persona_cronjobs(persona_id)

        today = datetime.now().strftime("%Y-%m-%d")
        now = datetime.now()

        for idx, event in enumerate(events):
            if not event.get("is_active", True):
                continue

            event_type = event.get("type", "routine")
            event_time_str = event.get("time", "")
            if not event_time_str:
                continue

            try:
                hour, minute = map(int, event_time_str.split(":"))
                run_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if run_at <= now:
                    logger.debug(f"事件 {event_time_str} 已过，跳过 CronJob 创建")
                    continue
            except (ValueError, AttributeError):
                continue

            job_name = f"{self.CRON_JOB_PREFIX}_{persona_id}_{today}_{idx}"
            description = event.get("description", "")

            relationship = await self._engine.get_state(persona_id)
            note = self._build_event_note(persona, event, relationship)

            payload = {
                "session": persona.session_key,
                "sender_id": persona.session_key.split(":", 2)[-1] if ":" in persona.session_key else "",
                "note": note,
                "persona_id": persona_id,
                "event_index": idx,
                "event_time": event_time_str,
                "event_type": event_type,
                "event_description": description,
                "origin": "plugin",
            }

            try:
                await cron_mgr.add_active_job(
                    name=job_name,
                    cron_expression=None,
                    payload=payload,
                    description=description,
                    timezone="Asia/Shanghai",
                    enabled=True,
                    persistent=False,
                    run_once=True,
                    run_at=run_at,
                )
                logger.debug(f"CronJob 已创建: {job_name} @ {event_time_str}")
            except Exception as e:
                logger.warning(f"CronJob 创建失败 ({job_name}): {e}")

        logger.info(f"Persona {persona.name} 事件 CronJob 创建完成")

    async def _cleanup_persona_cronjobs(self, persona_id: str):
        """清理 Persona 的所有事件 CronJob

        Args:
            persona_id: Persona 唯一标识
        """
        cron_mgr = self._context.cron_manager
        if cron_mgr is None:
            return

        try:
            jobs = await cron_mgr.list_jobs()
            for job in jobs:
                if job.name and job.name.startswith(f"{self.CRON_JOB_PREFIX}_{persona_id}_"):
                    try:
                        await cron_mgr.delete_job(job.job_id)
                    except Exception as e:
                        logger.debug(f"CronJob 删除失败 ({job.job_id}): {e}")
        except Exception as e:
            logger.warning(f"CronJob 清理失败 ({persona_id}): {e}")

    def _build_event_note(self, persona, event: dict, relationship) -> str:
        """构建 CronJob 唤醒时的 note 文本

        主 Agent 被唤醒后会看到这段 note，作为行动指引。

        Args:
            persona: Persona 对象
            event: 事件字典
            relationship: 关系状态对象（可为 None）

        Returns:
            note 文本
        """
        name = persona.name if persona else "未知"
        event_desc = event.get("description", "")
        event_type = event.get("type", "routine")

        parts = [f"你是{name}。"]

        if persona.life_stage_detail:
            parts.append(f"你的身份：{persona.life_stage_detail}")
        if persona.current_location:
            parts.append(f"你在：{persona.current_location}")

        parts.append(f"\n你生活中刚刚发生了一件事：{event_desc}（类型：{event_type}）")

        if relationship:
            parts.append(f"\n你和用户的关系：信任 {relationship.trust:.0f}/100，亲密 {relationship.closeness:.0f}/100，"
                         f"张力 {relationship.tension:.1f}，情绪能量 {relationship.emotional_energy:.0f}/100")

        if event_type == "sleep":
            parts.append("\n你要去睡觉了。不需要联系用户，安静入睡即可。")
        elif event_type == "wake":
            parts.append("\n你刚醒来，新的一天开始了。可以给用户发个早安消息，也可以不发。"
                         "如果想联系，请用 SendMessageToUser 工具发送消息。")
        else:
            parts.append("\n请根据你的性格和当前关系状态，自主决定是否要联系用户分享这件事。"
                         "如果想联系，请用 SendMessageToUser 工具发送消息。"
                         "如果不想联系，也请简要说明你的内心想法。")

        return "\n".join(parts)

    async def defer_sleep(self, persona_id: str):
        """sleep 延后：用户发消息时自动推迟 sleep 事件 +30 分钟

        同时更新对应的 CronJob 时间。

        Args:
            persona_id: Persona 唯一标识
        """
        today = datetime.now().strftime("%Y-%m-%d")
        events = await self._store._get(f"events:{persona_id}:{today}", [])
        if not events:
            return

        for event in events:
            if event.get("type") == "sleep" and event.get("is_active", True):
                try:
                    current_time = datetime.strptime(event["time"], "%H:%M")
                    new_time = current_time + timedelta(minutes=self.SLEEP_POSTPONE_MINUTES)
                    hard_limit = datetime.strptime(self.SLEEP_HARD_CAP, "%H:%M")
                    if 0 <= new_time.hour < 6 and new_time.time() > hard_limit.time():
                        return

                    old_time_str = event["time"]
                    event["time"] = new_time.strftime("%H:%M")
                    await self._store._put(f"events:{persona_id}:{today}", events)

                    await self._reschedule_sleep_cronjob(persona_id, today, old_time_str, new_time)

                    logger.debug(f"Sleep 延后至 {event['time']}")
                except (ValueError, KeyError):
                    pass
                return

    @staticmethod
    def _ensure_event_order(events: List[dict]) -> List[dict]:
        """确保事件顺序：第一个是起床，最后一个是睡觉

        如果没有起床事件，在 07:00 添加一个。
        如果没有睡觉事件，在 23:00 添加一个。
        中间事件按时间排序。
        """
        wake_events = [e for e in events if e.get("type") == "wake"]
        sleep_events = [e for e in events if e.get("type") == "sleep"]
        middle = [e for e in events if e.get("type") not in ("wake", "sleep")]

        middle.sort(key=lambda e: e.get("time", ""))

        if not wake_events:
            wake_events = [{"time": "07:00", "type": "wake", "description": "起床，开始新的一天", "is_active": True}]
        if not sleep_events:
            sleep_events = [{"time": "23:00", "type": "sleep", "description": "睡觉", "is_active": True}]

        return wake_events + middle + sleep_events

    async def regenerate_events_from_now(self, persona_id: str) -> Optional[List[dict]]:
        """从当前时间重新生成事件线（由 LLM 工具调用）

        删除当前时间之后的所有事件和 CronJob，重新生成全天事件。
        过去的事件保留，新事件只从当前时间开始创建 CronJob。

        Args:
            persona_id: Persona 唯一标识

        Returns:
            重新生成的事件列表，失败返回 None
        """
        await self._cleanup_persona_cronjobs(persona_id)
        return await self.generate_daily_events(persona_id)

    async def _reschedule_sleep_cronjob(self, persona_id: str, today: str, old_time_str: str, new_time: datetime):
        """重新调度 sleep 事件的 CronJob

        Args:
            persona_id: Persona 唯一标识
            today: 日期字符串
            old_time_str: 原始时间字符串
            new_time: 新时间
        """
        cron_mgr = self._context.cron_manager
        if cron_mgr is None:
            return

        try:
            jobs = await cron_mgr.list_jobs()
            for job in jobs:
                if (job.name and
                    job.name.startswith(f"{self.CRON_JOB_PREFIX}_{persona_id}_{today}_") and
                    isinstance(job.payload, dict) and
                    job.payload.get("event_type") == "sleep"):
                    try:
                        await cron_mgr.update_job(
                            job.job_id,
                            run_once=True,
                            run_at=new_time,
                            cron_expression=None,
                        )
                    except Exception as e:
                        logger.debug(f"Sleep CronJob 更新失败: {e}")
                    return
        except Exception as e:
            logger.debug(f"Sleep CronJob 重调度失败: {e}")

    async def fill_events_from_now(self, persona_id: str):
        """事件线断裂自救：从当前时间补生成到凌晨

        Args:
            persona_id: Persona 唯一标识
        """
        today = datetime.now().strftime("%Y-%m-%d")
        events = await self._store._get(f"events:{persona_id}:{today}", [])

        if not events:
            await self.generate_daily_events(persona_id)
            return

        now_time = datetime.now().strftime("%H:%M")
        future_events = [
            e for e in events
            if e.get("time", "") > now_time and e.get("is_active", True)
        ]

        if not future_events:
            await self.generate_daily_events(persona_id)

    async def ensure_today_events(self, persona_id: str):
        """确保 Persona 有当日事件（懒加载）

        幂等：已有事件则跳过

        Args:
            persona_id: Persona 唯一标识
        """
        today = datetime.now().strftime("%Y-%m-%d")
        events = await self._store._get(f"events:{persona_id}:{today}", [])
        if not events:
            await self.generate_daily_events(persona_id)

    async def recover_on_startup(self):
        """启动时恢复：清理所有旧 CronJob，为已挂载角色重新生成事件

        流程：
          1. 清理所有本插件的旧 CronJob（确保无残留）
          2. 遍历所有已挂载的 Persona
          3. 为每个已挂载角色生成事件并创建 CronJob
        """
        await self.cleanup_all_plugin_cronjobs()

        personas = await self._store.list_personas()
        for persona in personas:
            if not persona.session_key or persona.session_key.count(":") < 2:
                continue

            logger.info(f"Persona {persona.name} 已挂载，触发事件生成")
            await self.generate_daily_events(persona.persona_id)

        logger.info("启动事件恢复完成")

    async def cleanup_all_plugin_cronjobs(self):
        """清理所有属于本插件的 CronJob（卸载/停止时调用）

        遍历 CronJobManager 中所有以 CRON_JOB_PREFIX 开头的任务并删除。
        确保插件卸载后不残留任何 CronJob。
        """
        cron_mgr = self._context.cron_manager
        if cron_mgr is None:
            return

        try:
            jobs = await cron_mgr.list_jobs()
            cleaned = 0
            for job in jobs:
                if job.name and job.name.startswith(self.CRON_JOB_PREFIX):
                    try:
                        await cron_mgr.delete_job(job.job_id)
                        cleaned += 1
                    except Exception:
                        pass
            if cleaned > 0:
                logger.info(f"已清理 {cleaned} 个本插件的 CronJob")
        except Exception as e:
            logger.warning(f"CronJob 全量清理失败: {e}")

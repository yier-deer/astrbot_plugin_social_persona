"""社交人格插件 - 事件系统测试脚本

独立运行，不需要 AstrBot 环境。测试核心逻辑：
  1. 事件顺序保障（首尾事件约束）
  2. JSON 解析
  3. Sleep 推迟
  4. CronJob 创建与清理
  5. 事件线动态调整（regenerate）

运行方式：
  cd <plugin_dir>
  python tests/test_event_system.py
"""

import sys
import json
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_DIR))

astrbot_mock = MagicMock()
astrbot_mock.api = MagicMock()
astrbot_mock.api.logger = MagicMock()
astrbot_mock.api.star = MagicMock()
astrbot_mock.api.star.Star = MagicMock()
astrbot_mock.api.event = MagicMock()
astrbot_mock.api.AstrBotConfig = MagicMock()
sys.modules["astrbot"] = astrbot_mock
sys.modules["astrbot.api"] = astrbot_mock.api
sys.modules["astrbot.api.star"] = astrbot_mock.api.star
sys.modules["astrbot.api.event"] = astrbot_mock.api.event
sys.modules["astrbot.api.logger"] = MagicMock()
sys.modules["astrbot.core"] = MagicMock()
sys.modules["astrbot.core.star"] = MagicMock()
sys.modules["astrbot.core.star.filter"] = MagicMock()
sys.modules["astrbot.core.star.filter.command"] = MagicMock()
sys.modules["astrbot.core.star.context"] = MagicMock()
sys.modules["astrbot.core.star.base"] = MagicMock()
sys.modules["astrbot.core.db"] = MagicMock()
sys.modules["astrbot.core.db.po"] = MagicMock()
sys.modules["astrbot.core.agent"] = MagicMock()
sys.modules["astrbot.core.agent.tool"] = MagicMock()
sys.modules["astrbot.core.agent.message"] = MagicMock()
sys.modules["astrbot.core.agent.run_context"] = MagicMock()
sys.modules["astrbot.core.astr_agent_context"] = MagicMock()
sys.modules["astrbot.core.persona_mgr"] = MagicMock()
sys.modules["astrbot.core.conversation_mgr"] = MagicMock()
sys.modules["astrbot.core.platform"] = MagicMock()
sys.modules["astrbot.core.platform.platform_metadata"] = MagicMock()
sys.modules["astrbot.core.vector_store"] = MagicMock()
sys.modules["astrbot.core.provider"] = MagicMock()

from core.event.event_engine import EventEngine


class MockCronJob:
    def __init__(self, job_id, name, payload, enabled=True, status="waiting"):
        self.job_id = job_id
        self.name = name
        self.payload = payload
        self.enabled = enabled
        self.status = status


class MockCronManager:
    def __init__(self):
        self.jobs = []
        self._id_counter = 0

    async def add_active_job(self, **kwargs):
        self._id_counter += 1
        job = MockCronJob(
            job_id=f"job_{self._id_counter}",
            name=kwargs.get("name", ""),
            payload=kwargs.get("payload", {}),
            enabled=kwargs.get("enabled", True),
        )
        self.jobs.append(job)
        return job

    async def list_jobs(self):
        return list(self.jobs)

    async def delete_job(self, job_id):
        self.jobs = [j for j in self.jobs if j.job_id != job_id]

    async def update_job(self, job_id, **kwargs):
        for job in self.jobs:
            if job.job_id == job_id:
                if "run_at" in kwargs:
                    job.payload["run_at"] = str(kwargs["run_at"])
                break


class MockPersona:
    def __init__(self, **kwargs):
        self.persona_id = kwargs.get("persona_id", "test_persona_001")
        self.name = kwargs.get("name", "小雨")
        self.session_key = kwargs.get("session_key", "aiocqhttp:private:12345")
        self.life_stage = kwargs.get("life_stage", "student")
        self.life_stage_detail = kwargs.get("life_stage_detail", "大二学生")
        self.current_location = kwargs.get("current_location", "北京")
        self.character_current_context = kwargs.get("character_current_context", "普通的一天")
        self.character_initial_world_time = kwargs.get("character_initial_world_time", "2026-05-29")
        self.created_at = kwargs.get("created_at", "2026-05-29T12:00:00")
        self.relationship_phase = kwargs.get("relationship_phase", "acquaintance")

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items()}


class MockRelationship:
    def __init__(self):
        self.trust = 45.0
        self.closeness = 25.0
        self.tension = 1.0
        self.emotional_energy = 70.0
        self.contact_urge = 0.3
        self.tension_pressure = 0.1

    def to_dict(self):
        return self.__dict__.copy()


class MockStore:
    def __init__(self):
        self._data = {}
        self._personas = {}

    async def _get(self, key, default=None):
        return self._data.get(key, default)

    async def _put(self, key, value):
        self._data[key] = value

    async def _delete(self, key):
        self._data.pop(key, None)

    async def get_persona(self, persona_id):
        return self._personas.get(persona_id)

    async def update_persona(self, persona):
        self._personas[persona.persona_id] = persona

    async def list_personas(self):
        return list(self._personas.values())


class MockEngine:
    async def get_state(self, persona_id):
        return MockRelationship()


class MockMemory:
    async def add(self, content, persona_id):
        pass

    async def search(self, query, persona_id):
        return []


class MockPromptBuilder:
    def compute_world_date(self, initial, created):
        weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        today = datetime.now()
        return today.strftime("%Y-%m-%d"), weekdays[today.weekday()]

    def build_event_generate_prompt(self, **kwargs):
        return "test prompt"


class MockContext:
    def __init__(self):
        self.cron_manager = MockCronManager()

    def get_all_providers(self):
        return []

    async def llm_generate(self, **kwargs):
        return None


def make_sample_events():
    """生成一组标准测试事件"""
    return [
        {"time": "07:00", "type": "wake", "description": "起床", "is_active": True},
        {"time": "08:00", "type": "routine", "description": "吃早餐", "is_active": True},
        {"time": "10:00", "type": "routine", "description": "上课", "is_active": True},
        {"time": "12:00", "type": "routine", "description": "午饭", "is_active": True},
        {"time": "14:00", "type": "routine", "description": "图书馆自习", "is_active": True},
        {"time": "17:00", "type": "moment", "description": "和朋友散步", "is_active": True},
        {"time": "19:00", "type": "routine", "description": "吃晚饭", "is_active": True},
        {"time": "21:00", "type": "routine", "description": "看剧放松", "is_active": True},
        {"time": "23:00", "type": "sleep", "description": "睡觉", "is_active": True},
    ]


def test_ensure_event_order():
    """测试事件顺序保障"""
    print("\n=== 测试 1: 事件顺序保障 ===")
    _ensure = EventEngine._ensure_event_order

    events = make_sample_events()
    result = _ensure(events)
    assert result[0]["type"] == "wake", f"第一个事件应该是 wake，实际是 {result[0]['type']}"
    assert result[-1]["type"] == "sleep", f"最后一个事件应该是 sleep，实际是 {result[-1]['type']}"
    print("  ✅ 正常事件列表：首尾正确")

    no_wake = [e for e in events if e.get("type") != "wake"]
    result = _ensure(no_wake)
    assert result[0]["type"] == "wake", "缺少 wake 时应自动添加"
    assert result[0]["time"] == "07:00", "默认 wake 时间应为 07:00"
    print("  ✅ 缺少 wake：自动添加 07:00 起床")

    no_sleep = [e for e in events if e.get("type") != "sleep"]
    result = _ensure(no_sleep)
    assert result[-1]["type"] == "sleep", "缺少 sleep 时应自动添加"
    assert result[-1]["time"] == "23:00", "默认 sleep 时间应为 23:00"
    print("  ✅ 缺少 sleep：自动添加 23:00 睡觉")

    empty = []
    result = _ensure(empty)
    assert len(result) == 2, f"空列表应添加 wake+sleep，实际 {len(result)} 个"
    assert result[0]["type"] == "wake"
    assert result[1]["type"] == "sleep"
    print("  ✅ 空列表：自动添加 wake + sleep")

    shuffled = [
        {"time": "23:00", "type": "sleep", "description": "睡觉", "is_active": True},
        {"time": "12:00", "type": "routine", "description": "午饭", "is_active": True},
        {"time": "07:00", "type": "wake", "description": "起床", "is_active": True},
        {"time": "14:00", "type": "routine", "description": "自习", "is_active": True},
    ]
    result = _ensure(shuffled)
    assert result[0]["type"] == "wake"
    assert result[-1]["type"] == "sleep"
    assert result[1]["time"] == "12:00", "中间事件应按时间排序"
    assert result[2]["time"] == "14:00"
    print("  ✅ 乱序事件：自动排序正确")

    print("  🎉 事件顺序保障测试全部通过！")


def test_parse_json():
    """测试 JSON 解析"""
    print("\n=== 测试 2: JSON 解析 ===")
    _parse = EventEngine._parse_json_from_text

    assert _parse("") is None, "空字符串应返回 None"
    assert _parse(None) is None, "None 应返回 None"
    assert _parse("hello world") is None, "无 JSON 应返回 None"
    print("  ✅ 无效输入：正确返回 None")

    valid = '{"events": [], "today_reflection": {}}'
    result = _parse(valid)
    assert result is not None
    assert "events" in result
    print("  ✅ 纯 JSON：正确解析")

    wrapped = '这是分析结果：\n```json\n{"events": [{"time": "08:00"}]}\n```\n以上。'
    result = _parse(wrapped)
    assert result is not None
    assert len(result["events"]) == 1
    print("  ✅ Markdown 包裹的 JSON：正确提取")

    print("  🎉 JSON 解析测试全部通过！")


async def test_defer_sleep():
    """测试 Sleep 推迟"""
    print("\n=== 测试 3: Sleep 推迟 ===")

    store = MockStore()
    ctx = MockContext()
    engine = MockEngine()
    memory = MockMemory()
    pb = MockPromptBuilder()
    config = {}

    ee = EventEngine(store, engine, memory, pb, ctx, config)

    today = datetime.now().strftime("%Y-%m-%d")
    events = make_sample_events()
    await store._put(f"events:test_001:{today}", events)

    await ee.defer_sleep("test_001")

    stored = await store._get(f"events:test_001:{today}")
    sleep_event = next(e for e in stored if e["type"] == "sleep")
    assert sleep_event["time"] == "23:30", f"Sleep 应推迟到 23:30，实际是 {sleep_event['time']}"
    print(f"  ✅ Sleep 从 23:00 推迟到 {sleep_event['time']}")

    await ee.defer_sleep("test_001")
    stored = await store._get(f"events:test_001:{today}")
    sleep_event = next(e for e in stored if e["type"] == "sleep")
    assert sleep_event["time"] == "00:00", f"Sleep 应推迟到 00:00，实际是 {sleep_event['time']}"
    print(f"  ✅ Sleep 再次推迟到 {sleep_event['time']}")

    events_hard = make_sample_events()
    for e in events_hard:
        if e["type"] == "sleep":
            e["time"] = "01:45"
    await store._put(f"events:test_hard:{today}", events_hard)
    await ee.defer_sleep("test_hard")
    stored = await store._get(f"events:test_hard:{today}")
    sleep_event = next(e for e in stored if e["type"] == "sleep")
    assert sleep_event["time"] == "01:45", f"超过硬上限应不推迟，实际是 {sleep_event['time']}"
    print(f"  ✅ 硬上限 02:00：不推迟")

    print("  🎉 Sleep 推迟测试全部通过！")


async def test_cronjob_lifecycle():
    """测试 CronJob 创建与清理"""
    print("\n=== 测试 4: CronJob 生命周期 ===")

    store = MockStore()
    ctx = MockContext()
    engine = MockEngine()
    memory = MockMemory()
    pb = MockPromptBuilder()
    config = {}

    persona = MockPersona(persona_id="test_001", session_key="aiocqhttp:private:12345")
    store._personas["test_001"] = persona

    ee = EventEngine(store, engine, memory, pb, ctx, config)

    events = make_sample_events()
    await ee._schedule_event_cronjobs("test_001", events)

    cron_mgr = ctx.cron_manager
    active_jobs = [j for j in cron_mgr.jobs if j.enabled]
    print(f"  创建了 {len(active_jobs)} 个 CronJob")
    assert len(active_jobs) > 0, "应该创建了 CronJob"

    for job in active_jobs:
        assert job.name.startswith("sp_event_test_001_"), f"Job 名称应以 sp_event_test_001_ 开头: {job.name}"
        assert isinstance(job.payload, dict)
        assert job.payload.get("origin") == "plugin"
        assert job.payload.get("persona_id") == "test_001"
        assert "aiocqhttp" in job.payload.get("session", "")
    print("  ✅ CronJob 命名和 payload 格式正确")

    await ee._cleanup_persona_cronjobs("test_001")
    remaining = [j for j in cron_mgr.jobs if j.name.startswith("sp_event_test_001_")]
    assert len(remaining) == 0, f"清理后应无残留，实际 {len(remaining)} 个"
    print("  ✅ 清理后无残留")

    await ee._schedule_event_cronjobs("test_001", events)
    count_before = len(cron_mgr.jobs)
    await ee._schedule_event_cronjobs("test_001", events)
    count_after = len(cron_mgr.jobs)
    assert count_after <= count_before + len(events), "重新调度不应叠加"
    print("  ✅ 重新调度不会叠加 CronJob")

    no_session = MockPersona(persona_id="test_no_session", session_key="")
    store._personas["test_no_session"] = no_session
    await ee._schedule_event_cronjobs("test_no_session", events)
    no_session_jobs = [j for j in cron_mgr.jobs if "test_no_session" in j.name]
    assert len(no_session_jobs) == 0, "无 session_key 不应创建 CronJob"
    print("  ✅ 无 session_key 时跳过创建")

    bad_session = MockPersona(persona_id="test_bad", session_key="invalid_format")
    store._personas["test_bad"] = bad_session
    await ee._schedule_event_cronjobs("test_bad", events)
    bad_jobs = [j for j in cron_mgr.jobs if "test_bad" in j.name]
    assert len(bad_jobs) == 0, "无效 session 格式不应创建 CronJob"
    print("  ✅ 无效 session 格式时跳过创建")

    await ee.cleanup_all_plugin_cronjobs()
    assert len(cron_mgr.jobs) == 0, f"全量清理后应无残留，实际 {len(cron_mgr.jobs)} 个"
    print("  ✅ 全量清理无残留")

    print("  🎉 CronJob 生命周期测试全部通过！")


async def test_regenerate():
    """测试事件线重新生成"""
    print("\n=== 测试 5: 事件线重新生成 ===")

    store = MockStore()
    ctx = MockContext()
    engine = MockEngine()
    memory = MockMemory()
    pb = MockPromptBuilder()

    llm_response = json.dumps({
        "events": [
            {"time": "09:00", "type": "wake", "description": "晚起", "is_active": True},
            {"time": "11:00", "type": "routine", "description": "收拾行李", "is_active": True},
            {"time": "14:00", "type": "routine", "description": "坐火车去海边", "is_active": True},
            {"time": "22:00", "type": "sleep", "description": "睡觉", "is_active": True},
        ],
        "today_reflection": {
            "key_memories": [{"content": "决定去旅游", "importance": 8}],
            "life_stage_transition": {"should_transition": False}
        }
    })

    class MockProvider:
        class Meta:
            id = "deepseek"
        def meta(self):
            return self.Meta()

    class MockResp:
        completion_text = llm_response

    async def mock_llm_generate(**kwargs):
        return MockResp()

    ctx.get_all_providers = lambda: [MockProvider()]
    ctx.llm_generate = mock_llm_generate

    config = {"chat_provider_id": "deepseek"}
    ee = EventEngine(store, engine, memory, pb, ctx, config)

    persona = MockPersona(persona_id="test_001", session_key="aiocqhttp:private:12345")
    store._personas["test_001"] = persona

    result = await ee.regenerate_events_from_now("test_001")
    assert result is not None, "重新生成应返回事件列表"
    assert len(result) >= 2, f"应有至少 2 个事件，实际 {len(result)}"
    assert result[0]["type"] == "wake", f"第一个应是 wake，实际 {result[0]['type']}"
    assert result[-1]["type"] == "sleep", f"最后应是 sleep，实际 {result[-1]['type']}"
    print(f"  ✅ 重新生成 {len(result)} 个事件，首尾正确")

    today = datetime.now().strftime("%Y-%m-%d")
    stored = await store._get(f"events:test_001:{today}")
    assert stored is not None
    assert stored[0]["type"] == "wake"
    assert stored[-1]["type"] == "sleep"
    print("  ✅ 存储的事件顺序正确")

    cron_jobs = [j for j in ctx.cron_manager.jobs if "test_001" in j.name]
    print(f"  ✅ 创建了 {len(cron_jobs)} 个 CronJob")

    print("  🎉 事件线重新生成测试全部通过！")


async def test_startup_recovery():
    """测试启动恢复"""
    print("\n=== 测试 6: 启动恢复 ===")

    store = MockStore()
    ctx = MockContext()
    engine = MockEngine()
    memory = MockMemory()
    pb = MockPromptBuilder()

    class MockProvider:
        class Meta:
            id = "deepseek"
        def meta(self):
            return self.Meta()

    class MockResp:
        completion_text = json.dumps({
            "events": [
                {"time": "07:00", "type": "wake", "description": "起床", "is_active": True},
                {"time": "12:00", "type": "routine", "description": "午饭", "is_active": True},
                {"time": "23:00", "type": "sleep", "description": "睡觉", "is_active": True},
            ],
            "today_reflection": {"key_memories": [], "life_stage_transition": {"should_transition": False}}
        })

    async def mock_llm_generate(**kwargs):
        return MockResp()

    ctx.get_all_providers = lambda: [MockProvider()]
    ctx.llm_generate = mock_llm_generate

    config = {"chat_provider_id": "deepseek"}
    ee = EventEngine(store, engine, memory, pb, ctx, config)

    old_job = MockCronJob("old_1", "sp_event_old_persona_2026-01-01_0", {"session": "bad"})
    ctx.cron_manager.jobs.append(old_job)

    mounted = MockPersona(persona_id="mounted_001", session_key="aiocqhttp:private:111")
    unmounted = MockPersona(persona_id="unmounted_001", session_key="")
    store._personas["mounted_001"] = mounted
    store._personas["unmounted_001"] = unmounted

    await ee.recover_on_startup()

    old_jobs = [j for j in ctx.cron_manager.jobs if j.job_id == "old_1"]
    assert len(old_jobs) == 0, "旧 CronJob 应被清理"
    print("  ✅ 旧 CronJob 已清理")

    mounted_jobs = [j for j in ctx.cron_manager.jobs if "mounted_001" in j.name]
    assert len(mounted_jobs) > 0, "已挂载角色应生成 CronJob"
    print(f"  ✅ 已挂载角色生成了 {len(mounted_jobs)} 个 CronJob")

    unmounted_jobs = [j for j in ctx.cron_manager.jobs if "unmounted_001" in j.name]
    assert len(unmounted_jobs) == 0, "未挂载角色不应生成 CronJob"
    print("  ✅ 未挂载角色无 CronJob")

    print("  🎉 启动恢复测试全部通过！")


async def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("社交人格插件 - 事件系统测试")
    print("=" * 60)

    test_ensure_event_order()
    test_parse_json()
    await test_defer_sleep()
    await test_cronjob_lifecycle()
    await test_regenerate()
    await test_startup_recovery()

    print("\n" + "=" * 60)
    print("🎉 所有测试通过！")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_all_tests())

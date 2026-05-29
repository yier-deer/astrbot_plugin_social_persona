"""Persona 新字段单元测试 — life_archives, birthday, last_user_message_time

TDD RED 阶段：测试先行，预期全部 FAIL。
"""

import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_DIR))

import json
from unittest.mock import MagicMock

astrbot_mock = MagicMock()
astrbot_mock.api = MagicMock()
astrbot_mock.api.event = MagicMock()
astrbot_mock.api.logger = MagicMock()
astrbot_mock.api.star = MagicMock()
astrbot_mock.api.AstrBotConfig = MagicMock()
astrbot_mock.core = MagicMock()
astrbot_mock.core.star = MagicMock()
astrbot_mock.core.star.filter = MagicMock()
astrbot_mock.core.star.filter.command = MagicMock()
astrbot_mock.core.star.context = MagicMock()
astrbot_mock.core.star.base = MagicMock()
astrbot_mock.core.db = MagicMock()
astrbot_mock.core.db.po = MagicMock()
astrbot_mock.core.agent = MagicMock()
astrbot_mock.core.agent.tool = MagicMock()
astrbot_mock.core.agent.message = MagicMock()
astrbot_mock.core.agent.run_context = MagicMock()
astrbot_mock.core.astr_agent_context = MagicMock()
astrbot_mock.core.persona_mgr = MagicMock()
astrbot_mock.core.conversation_mgr = MagicMock()
astrbot_mock.core.platform = MagicMock()
astrbot_mock.core.platform.platform_metadata = MagicMock()
astrbot_mock.core.vector_store = MagicMock()
astrbot_mock.core.provider = MagicMock()
astrbot_mock.core.utils = MagicMock()
astrbot_mock.core.utils.astrbot_path = MagicMock()
astrbot_mock.core.utils.astrbot_path.get_astrbot_data_path = MagicMock(return_value="/tmp/test")
sys.modules["astrbot"] = astrbot_mock
sys.modules["astrbot.api"] = astrbot_mock.api
sys.modules["astrbot.api.event"] = astrbot_mock.api.event
sys.modules["astrbot.api.logger"] = astrbot_mock.api.logger
sys.modules["astrbot.api.star"] = astrbot_mock.api.star
sys.modules["astrbot.core"] = astrbot_mock.core
sys.modules["astrbot.core.utils"] = astrbot_mock.core.utils
sys.modules["astrbot.core.utils.astrbot_path"] = astrbot_mock.core.utils.astrbot_path
sys.modules["astrbot.core.star"] = astrbot_mock.core.star
sys.modules["astrbot.core.star.filter"] = astrbot_mock.core.star.filter
sys.modules["astrbot.core.star.filter.command"] = astrbot_mock.core.star.filter.command
sys.modules["astrbot.core.star.context"] = astrbot_mock.core.star.context
sys.modules["astrbot.core.star.base"] = astrbot_mock.core.star.base
sys.modules["astrbot.core.db"] = astrbot_mock.core.db
sys.modules["astrbot.core.db.po"] = astrbot_mock.core.db.po
sys.modules["astrbot.core.agent"] = astrbot_mock.core.agent
sys.modules["astrbot.core.agent.tool"] = astrbot_mock.core.agent.tool
sys.modules["astrbot.core.agent.message"] = astrbot_mock.core.agent.message
sys.modules["astrbot.core.agent.run_context"] = astrbot_mock.core.agent.run_context
sys.modules["astrbot.core.astr_agent_context"] = astrbot_mock.core.astr_agent_context
sys.modules["astrbot.core.persona_mgr"] = astrbot_mock.core.persona_mgr
sys.modules["astrbot.core.conversation_mgr"] = astrbot_mock.core.conversation_mgr
sys.modules["astrbot.core.platform"] = astrbot_mock.core.platform
sys.modules["astrbot.core.platform.platform_metadata"] = astrbot_mock.core.platform.platform_metadata
sys.modules["astrbot.core.vector_store"] = astrbot_mock.core.vector_store
sys.modules["astrbot.core.provider"] = astrbot_mock.core.provider

from core.storage.models import Persona, BigFive, TypingStyle


def test_persona_new_fields_default():
    """Persona 新字段有正确的默认值"""
    p = Persona()
    assert p.birthday == "", f"birthday 默认应为空字符串，实际 {p.birthday!r}"
    assert p.life_archives == [], f"life_archives 默认应为空列表，实际 {p.life_archives!r}"
    assert p.last_user_message_time == "", f"last_user_message_time 默认应为空字符串"


def test_persona_to_dict_with_new_fields():
    """to_dict 序列化包含新字段"""
    p = Persona(
        name="小雨",
        birthday="2005-07-15",
        life_archives=[
            {
                "stage": "adolescence",
                "time": "2019-09-01",
                "type": "personality_origin",
                "content": "高中被闺蜜背叛",
                "importance": 8,
            }
        ],
        last_user_message_time="2026-05-29T20:00:00",
    )
    d = p.to_dict()
    assert d["birthday"] == "2005-07-15"
    assert len(d["life_archives"]) == 1
    assert d["life_archives"][0]["content"] == "高中被闺蜜背叛"
    assert d["last_user_message_time"] == "2026-05-29T20:00:00"


def test_persona_from_dict_old_data_compat():
    """from_dict 加载缺失新字段的旧数据时不报错"""
    old_data = {
        "persona_id": "abc123",
        "name": "小雨",
        "age": 20,
        "gender": "女",
        "big_five": {
            "openness": 0.5,
            "conscientiousness": 0.5,
            "extraversion": 0.5,
            "agreeableness": 0.5,
            "neuroticism": 0.5,
        },
        "typing_style": {
            "fragmentation_level": 0.3,
            "emoji_frequency": 0.2,
            "punctuation_style": "casual",
            "avg_message_length": 15,
        },
    }
    p = Persona.from_dict(old_data)
    assert p.birthday == "", "旧数据应默认 birthday 为空"
    assert p.life_archives == [], "旧数据应默认 life_archives 为空列表"
    assert p.last_user_message_time == "", "旧数据应默认 last_user_message_time 为空"


def test_persona_life_archives_append():
    """life_archives 支持运行时追加条目"""
    p = Persona(name="小雨", birthday="2005-07-15")
    p.life_archives.append({
        "stage": "young_adult",
        "time": "2026-06-01",
        "type": "life_turning_point",
        "content": "大学毕业，搬到深圳开始实习",
        "importance": 9,
    })
    assert len(p.life_archives) == 1
    assert p.life_archives[0]["type"] == "life_turning_point"

    d = p.to_dict()
    assert len(d["life_archives"]) == 1


def test_coerce_birthday_valid():
    """_coerce_quick_create_data 处理合法的 birthday 字符串"""
    from core.matchmaker.matchmaker_engine import MatchmakerEngine

    class FakeStore:
        pass

    class FakePrompt:
        pass

    engine = MatchmakerEngine(FakeStore(), FakePrompt())

    data = {"birthday": "2005-07-15"}
    result = engine._coerce_quick_create_data(data)
    assert result["birthday"] == "2005-07-15"


def test_coerce_birthday_invalid():
    """_coerce_quick_create_data 将非法 birthday 修正为空字符串"""
    from core.matchmaker.matchmaker_engine import MatchmakerEngine

    class FakeStore:
        pass

    class FakePrompt:
        pass

    engine = MatchmakerEngine(FakeStore(), FakePrompt())

    for bad_val in ("七月十五日", "2005/07/15", 20050715):
        data = {"birthday": bad_val}
        result = engine._coerce_quick_create_data(data)
        assert result.get("birthday") == "", f"birthday={bad_val!r} 应修正为空，实际 {result.get('birthday')!r}"


def test_coerce_life_archives_type():
    """_coerce_quick_create_data 将非 list 的 life_archives 修正为空列表"""
    from core.matchmaker.matchmaker_engine import MatchmakerEngine

    class FakeStore:
        pass

    class FakePrompt:
        pass

    engine = MatchmakerEngine(FakeStore(), FakePrompt())

    data = {
        "name": "测试",
        "life_archives": "不是列表的字符串",
    }
    result = engine._coerce_quick_create_data(data)
    assert isinstance(result.get("life_archives"), list)
    assert result["life_archives"] == []


def test_build_chat_context_injects_life_archives():
    """build_chat_context 注入 importance >= 7 的人生经历"""
    from core.prompts.prompt_builder import PromptBuilder

    pb = PromptBuilder()
    persona = {
        "name": "小雨",
        "life_archives": [
            {
                "stage": "adolescence",
                "time": "2019-09-01",
                "type": "personality_origin",
                "content": "高中被闺蜜背叛，从此很难信任别人",
                "importance": 8,
            },
            {
                "stage": "childhood",
                "time": "2012-03-15",
                "type": "key_event",
                "content": "小学时养过一只仓鼠，叫团子，后来死了哭了一周",
                "importance": 6,
            },
        ],
        "big_five": {},
        "typing_style": {},
    }
    relationship = {"trust": 30, "closeness": 10, "tension": 0, "emotional_energy": 70}
    ctx = pb.build_chat_context(
        persona=persona,
        relationship=relationship,
        memories=[],
        today_events=[],
    )
    assert "高中被闺蜜背叛" in ctx, "importance >= 7 的条目应出现在上下文中"
    assert "仓鼠" not in ctx, "importance < 7 的条目不应出现在上下文中"


def test_build_cron_wake_note_injects_life_archives():
    """build_cron_wake_note 同样注入重要性高的人生经历"""
    from core.prompts.prompt_builder import PromptBuilder

    pb = PromptBuilder()
    persona = {
        "name": "小雨",
        "life_archives": [
            {
                "stage": "adolescence",
                "time": "2019-09-01",
                "type": "personality_origin",
                "content": "高中被闺蜜背叛",
                "importance": 8,
            },
        ],
        "big_five": {},
    }
    relationship = {"trust": 30, "closeness": 10, "tension": 0, "emotional_energy": 70}
    event = {"time": "12:00", "type": "routine", "description": "午休"}
    note = pb.build_cron_wake_note(
        persona=persona,
        event=event,
        relationship=relationship,
    )
    assert "高中被闺蜜背叛" in note, "CronJob 唤醒时也应注入人生经历"


def run_all():
    tests = [
        test_persona_new_fields_default,
        test_persona_to_dict_with_new_fields,
        test_persona_from_dict_old_data_compat,
        test_persona_life_archives_append,
        test_coerce_birthday_valid,
        test_coerce_birthday_invalid,
        test_coerce_life_archives_type,
        test_build_chat_context_injects_life_archives,
        test_build_cron_wake_note_injects_life_archives,
    ]
    passed = 0
    for fn in tests:
        try:
            fn()
            print(f"  ✅ {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ❌ {fn.__name__}: {e}")
    print(f"\n{'='*60}")
    if passed == len(tests):
        print(f"🎉 全部 {passed} 个测试通过！")
    else:
        print(f"⚠️ {passed}/{len(tests)} 通过，{len(tests)-passed} 失败")
    print(f"{'='*60}")


if __name__ == "__main__":
    run_all()

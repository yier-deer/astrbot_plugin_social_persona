import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime

from astrbot.api import logger

from ..storage.models import Persona, BigFive, TypingStyle


MATCHMAKER_STAGES = {
    "basic_profile": {
        "goal": "收集角色的基本信息",
        "questions": [
            "你想让她/他叫什么名字？",
            "她/他多大了？",
            "她/他的性别是什么？",
        ],
        "extract_schema": {
            "name": "角色名字",
            "age": "年龄（整数）",
            "gender": "性别",
        },
        "next_stage": "style_anchor",
    },
    "style_anchor": {
        "goal": "确定角色的说话风格和性格锚点",
        "questions": [
            "她/他说话是什么风格？温柔？毒舌？冷淡？",
            "有没有一个你觉得像她/他的角色可以参考？",
            "她/他平时怎么表达情绪？",
        ],
        "extract_schema": {
            "communication_style": "说话风格描述",
            "style_reference": "参考角色名（可选）",
            "emotional_expression": "情绪表达方式",
        },
        "next_stage": "boundary_probe",
    },
    "boundary_probe": {
        "goal": "探索角色在关系中的边界反应",
        "questions": [
            "如果三天不找她/他，她/他会有什么反应？",
            "如果她/他发现你对别人也很好，会怎样？",
            "吵架的时候她/他通常怎么处理？",
        ],
        "extract_schema": {
            "reaction_to_silence": "被冷落的反应",
            "reaction_to_rivalry": "发现竞争对手的反应",
            "conflict_style": "冲突处理方式（avoidant/confrontational/compromising）",
        },
        "next_stage": "attachment_explore",
    },
    "attachment_explore": {
        "goal": "探索角色的依恋倾向",
        "questions": [
            "她/他会不会反复确认你是不是还在乎她/他？",
            "被拉黑后她/他会怎样？",
            "她/他会不会突然疏远你？",
        ],
        "extract_schema": {
            "attachment_anxiety": "依恋焦虑程度（0-1，0=完全不焦虑，1=极度焦虑）",
            "attachment_avoidance": "依恋回避程度（0-1，0=完全不回避，1=极度回避）",
            "self_esteem_stability": "自尊稳定性（0-1）",
        },
        "next_stage": "system_detail",
    },
    "system_detail": {
        "goal": "收集系统级配置",
        "questions": [
            "她/他打字快还是慢？喜欢发长消息还是短消息？",
            "她/他会不会发图片？什么风格的？",
            "她/他现在在做什么？学生？工作？",
        ],
        "extract_schema": {
            "typing_speed": "打字速度（1-5）",
            "fragmentation_level": "碎片化程度（0-1）",
            "image_enabled": "是否发图片（0/1）",
            "life_stage": "生活阶段（student/working/etc）",
            "life_stage_detail": "生活阶段详情",
            "current_location": "所在地",
        },
        "next_stage": "sample_confirm",
    },
    "sample_confirm": {
        "goal": "展示角色设定摘要并确认",
        "questions": [
            '这是你想要的角色吗？如果需要调整请告诉我，确认请说"确认"。',
        ],
        "extract_schema": {
            "confirmed": "是否确认（true/false）",
        },
        "next_stage": "complete",
    },
    "complete": {
        "goal": "创建完成",
        "questions": [],
        "extract_schema": {},
        "next_stage": None,
    },
}


@dataclass
class MatchmakerSession:
    """Matchmaker 会话状态"""
    umo: str = ""
    current_stage: str = "basic_profile"
    collected_data: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict:
        """安全序列化为字典（确保所有值 JSON 可序列化）"""
        import json
        result = {}
        for k, v in self.__dict__.items():
            try:
                json.dumps(v, ensure_ascii=False)
                result[k] = v
            except (TypeError, ValueError):
                if hasattr(v, 'to_dict'):
                    result[k] = v.to_dict()
                else:
                    result[k] = str(v)
        return result

    @classmethod
    def from_dict(cls, data: dict) -> 'MatchmakerSession':
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class QuickCreateSession:
    """快速创建会话状态"""
    umo: str = ""
    collected_data: Dict[str, Any] = field(default_factory=dict)
    status: str = "collecting"
    created_at: str = ""

    def to_dict(self) -> dict:
        """安全序列化为字典（确保所有值 JSON 可序列化）"""
        import json
        result = {}
        for k, v in self.__dict__.items():
            try:
                json.dumps(v, ensure_ascii=False)
                result[k] = v
            except (TypeError, ValueError):
                if hasattr(v, 'to_dict'):
                    result[k] = v.to_dict()
                else:
                    result[k] = str(v)
        return result

    @classmethod
    def from_dict(cls, data: dict) -> 'QuickCreateSession':
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


REQUIRED_FIELDS = {
    "name": "角色名字",
    "age": "年龄",
    "gender": "性别",
    "communication_style": "说话风格（如：毒舌傲娇、温柔体贴）",
    "attachment_anxiety": "依恋焦虑程度（0-1）",
    "attachment_avoidance": "依恋回避程度（0-1）",
}

OPTIONAL_FIELDS = {
    "style_reference": "参考角色名",
    "emotional_expression": "情绪表达方式",
    "reaction_to_silence": "被冷落的反应",
    "reaction_to_rivalry": "发现竞争对手的反应",
    "conflict_style": "冲突处理方式",
    "self_esteem_stability": "自尊稳定性（0-1）",
    "typing_speed": "打字速度（1-5）",
    "fragmentation_level": "碎片化程度（0-1）",
    "image_enabled": "是否发图片（0/1）",
    "image_style_prompt": "图片风格描述",
    "life_stage": "生活阶段",
    "life_stage_detail": "生活阶段详情",
    "current_location": "所在地",
    "character_current_context": "角色生活背景",
    "character_appearance": "外貌描述",
    "relationship_phase": "初始关系阶段",
    "character_initial_world_time": "世界初始日期（YYYY-MM-DD）",
    "initiative_tendency": "主动联系倾向（0-1）",
    "big_five": "大五人格（openness/conscientiousness/extraversion/agreeableness/neuroticism）",
}


class MatchmakerEngine:
    """Matchmaker 7 阶段访谈引擎

    通过多轮对话引导用户创建 AI 角色，状态通过 KV 存储持久化。
    会话期间屏蔽正常聊天流程，由消息监听器路由到本引擎处理。
    """

    def __init__(self, store, prompt_builder):
        self._store = store
        self._prompt_builder = prompt_builder

    async def start_session(self, umo: str) -> str:
        """启动 Matchmaker 会话，返回开场白"""
        session = MatchmakerSession(
            umo=umo,
            created_at=datetime.now().isoformat(),
        )
        await self._store._put(f"matchmaker_session:{umo}", session.to_dict())

        return (
            "🎭 欢迎来到牵线人！我会帮你创建一个AI角色。\n\n"
            "我会问你一些问题，根据你的回答来塑造这个角色。\n"
            '随时可以说"取消"来退出创建流程。\n\n'
            f"让我们开始吧——{MATCHMAKER_STAGES['basic_profile']['questions'][0]}"
        )

    async def cancel_session(self, umo: str) -> None:
        """取消 Matchmaker 会话"""
        await self._store._delete(f"matchmaker_session:{umo}")

    async def get_session(self, umo: str) -> Optional[MatchmakerSession]:
        """获取当前 Matchmaker 会话"""
        data = await self._store._get(f"matchmaker_session:{umo}")
        if data is None:
            return None
        return MatchmakerSession.from_dict(data)

    async def get_quick_session(self, umo: str) -> Optional[QuickCreateSession]:
        """获取当前快速创建会话"""
        return await self._get_quick_session(umo)

    async def process_message(self, umo: str, user_message: str, llm_generate_func) -> tuple:
        """处理用户在 Matchmaker 会话中的消息

        Args:
            umo: 会话标识
            user_message: 用户消息
            llm_generate_func: LLM 调用函数（async def(prompt) -> str）

        Returns:
            (message: str, persona_id: str | None) 元组
        """
        if user_message.strip() in ("取消", "cancel", "退出"):
            await self.cancel_session(umo)
            return ("已取消创建流程。", None)

        session = await self.get_session(umo)
        if session is None:
            return ("没有进行中的创建流程。使用 /sp create 开始。", None)

        if session.current_stage == "complete":
            await self.cancel_session(umo)
            return ("角色已创建完成。", None)

        stage_config = MATCHMAKER_STAGES.get(session.current_stage)
        if not stage_config:
            await self.cancel_session(umo)
            return ("会话状态异常，已取消。", None)

        prompt = self._prompt_builder.build_matchmaker_prompt(
            stage=session.current_stage,
            stage_config=stage_config,
            collected_data=session.collected_data,
            user_message=user_message,
        )

        try:
            llm_response = await llm_generate_func(prompt)

            if not llm_response or not llm_response.strip():
                logger.warning("Matchmaker: LLM 返回为空")
                return ("抱歉，我暂时无法处理。请再试一次。", None)

            cleaned = llm_response.strip()
            if cleaned.startswith("```"):
                first_newline = cleaned.find("\n")
                if first_newline != -1:
                    cleaned = cleaned[first_newline + 1:]
                last_fence = cleaned.rfind("```")
                if last_fence != -1:
                    cleaned = cleaned[:last_fence]
                cleaned = cleaned.strip()

            json_match = re.search(r'\{[\s\S]*\}', cleaned)
            if not json_match:
                logger.warning(f"Matchmaker: LLM 回复中未找到 JSON: {llm_response[:200]}")
                return ("抱歉，我没理解你的回答。能再说一次吗？", None)

            parsed = json.loads(json_match.group())

            extracted = parsed.get("extracted_data", {})
            session.collected_data.update(extracted)

            is_complete = parsed.get("is_complete", False)
            if is_complete and stage_config.get("next_stage"):
                session.current_stage = stage_config["next_stage"]

            if session.current_stage == "complete":
                persona = await self._create_persona_from_session(session)
                await self.cancel_session(umo)
                return (
                    f"✅ 角色「{persona.name}」创建成功！\n\n"
                    f"已自动注册到人格设定列表，可在 WebUI 查看。\n"
                    f"使用 /sp mount {persona.name} 挂载到机器人开始聊天。",
                    persona.persona_id,
                )

            await self._store._put(f"matchmaker_session:{umo}", session.to_dict())

            return (parsed.get("response", "请继续描述。"), None)

        except json.JSONDecodeError:
            return ("抱歉，我没理解你的回答。能再说一次吗？", None)
        except Exception as e:
            logger.error(f"Matchmaker 处理失败: {e}")
            return ("处理出了点问题，请再试一次。", None)

    async def quick_create(self, umo: str, user_input: str, llm_generate_func) -> tuple:
        """快速创建模式：多轮会话，提取→校验→展示→补充→确认→创建

        Args:
            umo: 用户会话标识
            user_input: 用户输入（首次为角色描述，后续为补充信息或确认）
            llm_generate_func: LLM 调用函数

        Returns:
            (message: str, persona_id: str | None) 元组
        """
        if user_input.strip() in ("取消", "cancel", "退出"):
            await self._delete_quick_session(umo)
            return ("已取消快速创建。", None)

        session = await self._get_quick_session(umo)

        if session is None:
            return await self._quick_create_start(umo, user_input, llm_generate_func)

        if session.status == "confirming":
            if user_input.strip() in ("确认", "确认创建", "ok", "OK", "好", "好的", "可以"):
                return await self._quick_create_confirm(umo)
            return await self._quick_create_handle_supplement(umo, user_input, llm_generate_func, session)

        return await self._quick_create_handle_supplement(umo, user_input, llm_generate_func, session)

    async def _quick_create_start(self, umo: str, user_description: str, llm_generate_func) -> tuple:
        """首次快速创建：提取数据→校验→展示模板

        Returns:
            (message: str, persona_id: str | None) 元组
        """
        prompt = self._prompt_builder.build_quick_create_prompt(user_description)

        try:
            llm_response = await llm_generate_func(prompt)

            if not llm_response or not llm_response.strip():
                return ("抱歉，AI 无法理解你的描述。请再试一次或使用 /sp create 逐步创建。", None)

            cleaned = self._clean_llm_json(llm_response)
            json_match = re.search(r'\{[\s\S]*\}', cleaned)
            if not json_match:
                return ("抱歉，无法解析角色数据。请再试一次或使用 /sp create 逐步创建。", None)

            parsed = json.loads(json_match.group())

            self._coerce_quick_create_data(parsed)
            logger.debug(f"QuickCreate 提取数据: {json.dumps(parsed, ensure_ascii=False)[:500]}")

            session = QuickCreateSession(
                umo=umo,
                collected_data=parsed,
                status="collecting",
                created_at=datetime.now().isoformat(),
            )
            await self._save_quick_session(umo, session)

            return (self._build_fill_template(session), None)

        except json.JSONDecodeError:
            return ("抱歉，数据解析出错。请再试一次或使用 /sp create 逐步创建。", None)
        except Exception as e:
            logger.error(f"QuickCreate 启动失败: {e}", exc_info=True)
            return (f"创建失败（{type(e).__name__}: {str(e)[:100]}），请再试一次或使用 /sp create 逐步创建。", None)

    async def _quick_create_handle_supplement(self, umo: str, user_input: str, llm_generate_func, session: QuickCreateSession) -> tuple:
        """处理用户补充信息或确认

        Returns:
            (message: str, persona_id: str | None) 元组
        """
        if user_input.strip() in ("让AI填写", "AI填写", "自动填写", "LLM填写"):
            return await self._quick_auto_fill(umo, session, llm_generate_func)

        return await self._quick_create_update(umo, user_input, llm_generate_func, session)

    async def _quick_create_update(self, umo: str, user_input: str, llm_generate_func, session: QuickCreateSession) -> tuple:
        """用用户补充的信息更新会话数据

        Returns:
            (message: str, persona_id: str | None) 元组
        """
        supplement_prompt = f"""用户正在创建一个AI角色，以下是已有的数据：
{json.dumps(session.collected_data, ensure_ascii=False, indent=2)}

用户补充了以下信息：
{user_input}

请将补充信息合并到已有数据中，返回完整的合并后JSON。只输出纯JSON。"""

        try:
            llm_response = await llm_generate_func(supplement_prompt)
            cleaned = self._clean_llm_json(llm_response)
            json_match = re.search(r'\{[\s\S]*\}', cleaned)
            if not json_match:
                return ("无法解析补充信息，请换个说法再试。", None)

            parsed = json.loads(json_match.group())
            session.collected_data.update(parsed)
            session.status = "collecting"
            await self._save_quick_session(umo, session)

            missing = self._get_missing_required(session)
            if missing:
                return (self._build_fill_template(session), None)
            else:
                session.status = "confirming"
                await self._save_quick_session(umo, session)
                return (self._build_confirm_template(session), None)

        except Exception as e:
            logger.error(f"QuickCreate 补充失败: {e}")
            return ("处理补充信息时出错，请再试一次。", None)

    async def _quick_auto_fill(self, umo: str, session: QuickCreateSession, llm_generate_func) -> tuple:
        """让 LLM 自动填写缺失字段

        Returns:
            (message: str, persona_id: str | None) 元组
        """
        missing = self._get_missing_required(session)
        if not missing:
            session.status = "confirming"
            await self._save_quick_session(umo, session)
            return (self._build_confirm_template(session), None)

        auto_fill_prompt = f"""用户正在创建一个AI角色，已有数据：
{json.dumps(session.collected_data, ensure_ascii=False, indent=2)}

以下字段缺失，请根据已有信息推断合理的值：
{json.dumps(missing, ensure_ascii=False)}

返回包含所有缺失字段的JSON（只返回缺失字段即可）。只输出纯JSON。"""

        try:
            llm_response = await llm_generate_func(auto_fill_prompt)
            cleaned = self._clean_llm_json(llm_response)
            json_match = re.search(r'\{[\s\S]*\}', cleaned)
            if not json_match:
                return ("AI 自动填写失败，请手动补充。", None)

            parsed = json.loads(json_match.group())
            session.collected_data.update(parsed)
            session.status = "confirming"
            await self._save_quick_session(umo, session)
            return (self._build_confirm_template(session), None)

        except Exception as e:
            logger.error(f"QuickCreate 自动填写失败: {e}")
            return ("AI 自动填写失败，请手动补充。", None)

    async def _quick_create_confirm(self, umo: str) -> tuple:
        """确认创建角色（校验必填字段后再创建）

        Returns:
            (message: str, persona_id: str | None) 元组
        """
        session = await self._get_quick_session(umo)
        if session is None:
            return ("没有进行中的快速创建会话。", None)

        missing = self._get_missing_required(session)
        if missing:
            missing_desc = [REQUIRED_FIELDS[k] for k in missing if k in REQUIRED_FIELDS]
            return (f"⚠️ 还有必填项未填写：{'、'.join(missing_desc)}\n请补充或说'让AI填写'。", None)

        try:
            persona = await self._create_persona_from_quick_data(session.collected_data)
            await self._delete_quick_session(umo)

            summary = self._build_persona_summary(persona)

            return (
                f"✅ 角色「{persona.name}」创建成功！\n\n"
                f"{summary}\n\n"
                f"已自动注册到人格设定列表，可在 WebUI 查看。\n"
                f"使用 /sp mount {persona.name} 挂载到当前会话开始聊天。",
                persona.persona_id,
            )
        except Exception as e:
            logger.error(f"QuickCreate 创建失败: {e}", exc_info=True)
            return (f"角色创建失败（{type(e).__name__}: {str(e)[:100]}），请再试一次或使用 /sp create 逐步创建。", None)

    def _build_fill_template(self, session: QuickCreateSession) -> str:
        """构建填写模板，展示已填和待填字段"""
        lines = ['📝 角色信息填写（直接发送补充内容，或说"让AI填写"自动补全）：\n']

        lines.append("【必填项】")
        for key, desc in REQUIRED_FIELDS.items():
            value = session.collected_data.get(key)
            if value is not None and value != "" and value != 0:
                value_str = self._format_template_value(value)
                lines.append(f"  ✅ {desc}（{key}）：{value_str}")
            else:
                lines.append(f"  ⬜ {desc}（{key}）：___")

        lines.append("\n【可选项（已有值或默认值）】")
        for key, desc in OPTIONAL_FIELDS.items():
            value = session.collected_data.get(key)
            if value is not None and value != "" and value != 0:
                value_str = self._format_template_value(value)
                lines.append(f"  ✅ {desc}（{key}）：{value_str}")
            else:
                lines.append(f"  ⬜ {desc}（{key}）：默认")

        missing = self._get_missing_required(session)
        if missing:
            lines.append(f'\n⚠️ 还缺 {len(missing)} 个必填项，请补充或说"让AI填写"。')
        else:
            lines.append('\n✅ 必填项已齐全！说"确认"创建角色，或继续补充可选项。')
            session.status = "confirming"

        return "\n".join(lines)

    def _build_confirm_template(self, session: QuickCreateSession) -> str:
        """构建确认模板，展示完整设定"""
        lines = ["📋 角色总设定，请确认：\n"]

        all_fields = {**REQUIRED_FIELDS, **OPTIONAL_FIELDS}
        for key, desc in all_fields.items():
            value = session.collected_data.get(key)
            if value is not None and value != "" and value != 0:
                value_str = self._format_template_value(value)
                lines.append(f"  {desc}：{value_str}")

        lines.append('\n说"确认"创建角色，或发送修改内容。')
        return "\n".join(lines)

    def _format_template_value(self, value) -> str:
        """安全格式化模板中的值（dict/list 用 json.dumps，None 显示为未填写）"""
        if value is None:
            return "未填写"
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def _build_astrbot_persona_config(self, persona: Persona) -> str:
        """构建 AstrBot 人格设定配置（只含稳定特质，不含会变化的处境）"""
        stable_traits = []

        if persona.name:
            stable_traits.append(f"你的名字是{persona.name}")
        if persona.gender:
            stable_traits.append(f"你是{persona.gender}性")
        if persona.age:
            stable_traits.append(f"你{persona.age}岁")

        bf = persona.big_five
        personality_parts = []
        if bf.agreeableness < 0.4:
            personality_parts.append("直言不讳、毒舌")
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
            stable_traits.append(f"你的性格：{'、'.join(personality_parts)}")

        if persona.attachment_anxiety > 0.5:
            stable_traits.append("你在关系中容易焦虑，害怕被忽视")
        if persona.attachment_avoidance > 0.5:
            stable_traits.append("你在关系中倾向保持距离")

        if persona.conflict_style == "compromising":
            stable_traits.append("遇到矛盾你会妥协但嘴上不认输")
        elif persona.conflict_style == "avoidant":
            stable_traits.append("遇到矛盾你会回避")
        elif persona.conflict_style == "confrontational":
            stable_traits.append("遇到矛盾你会直接表达不满")

        if persona.image_style_prompt:
            stable_traits.append(f"你的外貌：{persona.image_style_prompt}")

        system_prompt = "。".join(stable_traits) + "。"

        config = {
            "persona_id": f"social_persona_{persona.persona_id}",
            "name": persona.name,
            "system_prompt": system_prompt,
        }

        return json.dumps(config, ensure_ascii=False, indent=2)

    def _coerce_quick_create_data(self, data: dict) -> dict:
        """校验并自动修正 LLM 返回的数据类型

        LLM 可能返回字符串类型的数值或非法枚举值，此方法确保数据类型正确。
        """
        INT_FIELDS = {
            "age": 20,
            "typing_speed": 3,
            "image_enabled": 0,
        }
        FLOAT_FIELDS = {
            "attachment_anxiety": 0.3,
            "attachment_avoidance": 0.3,
            "self_esteem_stability": 0.5,
            "fragmentation_level": 0.3,
            "initiative_tendency": 0.5,
        }
        ENUM_FIELDS = {
            "conflict_style": {"avoidant", "confrontational", "compromising"},
            "relationship_phase": {"stranger", "acquaintance", "friend", "close_friend"},
            "life_stage": {"student", "working", "at_home", "traveling"},
            "gender": {"男", "女", "非二元", "其他"},
        }
        ENUM_DEFAULTS = {
            "conflict_style": "avoidant",
            "relationship_phase": "stranger",
            "life_stage": "student",
            "gender": "",
        }

        for field_name, default in INT_FIELDS.items():
            val = data.get(field_name)
            if val is not None and not isinstance(val, int):
                try:
                    data[field_name] = int(float(val))
                except (ValueError, TypeError):
                    data[field_name] = default
                    logger.debug(f"QuickCreate 数据修正: {field_name}={val!r} → {default}")

        for field_name, default in FLOAT_FIELDS.items():
            val = data.get(field_name)
            if val is not None and not isinstance(val, (int, float)):
                try:
                    data[field_name] = float(val)
                except (ValueError, TypeError):
                    data[field_name] = default
                    logger.debug(f"QuickCreate 数据修正: {field_name}={val!r} → {default}")

        for field_name, valid_set in ENUM_FIELDS.items():
            val = data.get(field_name)
            if val is not None and val not in valid_set:
                default = ENUM_DEFAULTS[field_name]
                logger.debug(f"QuickCreate 数据修正: {field_name}={val!r} → {default}")
                data[field_name] = default

        big_five = data.get("big_five")
        if not isinstance(big_five, dict):
            inferred = self._infer_big_five(data)
            data["big_five"] = {
                "openness": inferred.openness,
                "conscientiousness": inferred.conscientiousness,
                "extraversion": inferred.extraversion,
                "agreeableness": inferred.agreeableness,
                "neuroticism": inferred.neuroticism,
            }
            logger.debug(f"QuickCreate 数据修正: big_five 缺失，从 communication_style 推断")

        return data

    def _get_missing_required(self, session: QuickCreateSession) -> list:
        """获取缺失的必填字段"""
        missing = []
        for key in REQUIRED_FIELDS:
            value = session.collected_data.get(key)
            if value is None or value == "":
                missing.append(key)
        return missing

    def _clean_llm_json(self, text: str) -> str:
        """清理 LLM 返回的 JSON 文本（剥离 markdown 代码块、BOM 头、尾部多余逗号）"""
        cleaned = text.strip()

        if cleaned.startswith("\ufeff"):
            cleaned = cleaned.lstrip("\ufeff")

        if cleaned.startswith("```"):
            first_newline = cleaned.find("\n")
            if first_newline != -1:
                cleaned = cleaned[first_newline + 1:]
            last_fence = cleaned.rfind("```")
            if last_fence != -1:
                cleaned = cleaned[:last_fence]

        cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)

        return cleaned.strip()

    async def _save_quick_session(self, umo: str, session: QuickCreateSession) -> None:
        """保存快速创建会话（按用户维度存储）"""
        await self._store._put(f"quick_create_session:{umo}", session.to_dict())

    async def _get_quick_session(self, umo: str) -> Optional[QuickCreateSession]:
        """获取快速创建会话"""
        data = await self._store._get(f"quick_create_session:{umo}")
        if data is None:
            return None
        return QuickCreateSession.from_dict(data)

    async def _delete_quick_session(self, umo: str) -> None:
        """删除快速创建会话"""
        await self._store._delete(f"quick_create_session:{umo}")

    async def _create_persona_from_quick_data(self, data: dict) -> Persona:
        """从快速创建的 LLM 提取数据创建 Persona"""
        big_five_data = data.get("big_five", {})
        big_five = BigFive(
            openness=float(big_five_data.get("openness", 0.5)),
            conscientiousness=float(big_five_data.get("conscientiousness", 0.5)),
            extraversion=float(big_five_data.get("extraversion", 0.5)),
            agreeableness=float(big_five_data.get("agreeableness", 0.5)),
            neuroticism=float(big_five_data.get("neuroticism", 0.5)),
        )

        typing_style = TypingStyle(
            fragmentation_level=float(data.get("fragmentation_level", 0.3)),
        )

        anxiety = float(data.get("attachment_anxiety", 0.3))
        avoidance = float(data.get("attachment_avoidance", 0.3))

        phase = data.get("relationship_phase", "")
        if phase not in ("stranger", "acquaintance", "friend", "close_friend"):
            phase = self._infer_relationship_phase(anxiety, avoidance)

        world_time = data.get("character_initial_world_time", "")
        if world_time:
            try:
                datetime.strptime(world_time, "%Y-%m-%d")
            except ValueError:
                world_time = ""

        persona = Persona(
            persona_id=str(uuid.uuid4())[:8],
            name=data.get("name", "未命名"),
            gender=data.get("gender", ""),
            age=int(data.get("age", 20)),
            big_five=big_five,
            attachment_anxiety=anxiety,
            attachment_avoidance=avoidance,
            self_esteem_stability=float(data.get("self_esteem_stability", 0.5)),
            conflict_style=data.get("conflict_style", "avoidant"),
            initiative_tendency=float(data.get("initiative_tendency", 0.5)),
            typing_style=typing_style,
            typing_speed=int(data.get("typing_speed", 3)),
            image_enabled=int(data.get("image_enabled", 0)),
            image_style_prompt=data.get("image_style_prompt", ""),
            character_appearance=data.get("character_appearance", ""),
            life_stage=data.get("life_stage", ""),
            life_stage_detail=data.get("life_stage_detail", ""),
            current_location=data.get("current_location", ""),
            character_current_context=data.get("character_current_context", ""),
            relationship_phase=phase,
            character_initial_world_time=world_time or datetime.now().strftime("%Y-%m-%d"),
        )

        await self._store.create_persona(persona)
        await self._store.init_relationship(persona.persona_id, phase)

        return persona

    def _build_persona_summary(self, persona: Persona) -> str:
        """构建角色摘要用于创建成功后展示"""
        lines = [
            f"📋 角色设定：",
            f"  名字：{persona.name}",
            f"  年龄：{persona.age}岁",
            f"  性别：{persona.gender}",
        ]
        if persona.life_stage_detail:
            lines.append(f"  身份：{persona.life_stage_detail}")
        if persona.current_location:
            lines.append(f"  所在地：{persona.current_location}")
        if persona.character_current_context:
            lines.append(f"  背景：{persona.character_current_context}")
        lines.append(f"  依恋焦虑：{persona.attachment_anxiety:.1f}")
        lines.append(f"  依恋回避：{persona.attachment_avoidance:.1f}")
        lines.append(f"  主动联系：{persona.initiative_tendency:.1f}")
        lines.append(f"  打字速度：{persona.typing_speed}/5")
        lines.append(f"  碎片化：{persona.typing_style.fragmentation_level:.1f}")
        lines.append(f"  初始关系：{persona.relationship_phase}")
        if persona.image_enabled:
            lines.append(f"  发图片：是（{persona.image_style_prompt}）")
        if persona.character_initial_world_time:
            lines.append(f"  世界时间：{persona.character_initial_world_time}")
        return "\n".join(lines)

    async def _create_persona_from_session(self, session: MatchmakerSession) -> Persona:
        """从 Matchmaker 会话数据创建 Persona"""
        data = session.collected_data

        big_five = self._infer_big_five(data)

        typing_style = TypingStyle(
            fragmentation_level=float(data.get("fragmentation_level", 0.3)),
        )

        anxiety = float(data.get("attachment_anxiety", 0.3))
        avoidance = float(data.get("attachment_avoidance", 0.3))

        phase = self._infer_relationship_phase(anxiety, avoidance)

        persona = Persona(
            persona_id=str(uuid.uuid4())[:8],
            name=data.get("name", "未命名"),
            gender=data.get("gender", ""),
            age=int(data.get("age", 20)),
            big_five=big_five,
            attachment_anxiety=anxiety,
            attachment_avoidance=avoidance,
            self_esteem_stability=float(data.get("self_esteem_stability", 0.5)),
            conflict_style=data.get("conflict_style", "avoidant"),
            typing_style=typing_style,
            typing_speed=int(data.get("typing_speed", 3)),
            image_enabled=int(data.get("image_enabled", 0)),
            life_stage=data.get("life_stage", ""),
            life_stage_detail=data.get("life_stage_detail", ""),
            current_location=data.get("current_location", ""),
            relationship_phase=phase,
            character_current_context=data.get("life_stage_detail", ""),
            character_initial_world_time=datetime.now().strftime("%Y-%m-%d"),
        )

        await self._store.create_persona(persona)
        await self._store.init_relationship(persona.persona_id, phase)

        return persona

    def _infer_big_five(self, data: dict) -> BigFive:
        """从风格描述推断大五人格"""
        style = data.get("communication_style", "") + data.get("emotional_expression", "")
        style_lower = style.lower()

        openness = 0.5
        conscientiousness = 0.5
        extraversion = 0.5
        agreeableness = 0.5
        neuroticism = 0.5

        if any(w in style_lower for w in ["温柔", "温和", "友善", "体贴"]):
            agreeableness = 0.7
        if any(w in style_lower for w in ["毒舌", "刻薄", "尖锐", "直言"]):
            agreeableness = 0.3
        if any(w in style_lower for w in ["外向", "活泼", "开朗", "热情"]):
            extraversion = 0.7
        if any(w in style_lower for w in ["冷淡", "沉默", "内敛", "安静"]):
            extraversion = 0.3
        if any(w in style_lower for w in ["敏感", "多疑", "脆弱", "情绪化"]):
            neuroticism = 0.7
        if any(w in style_lower for w in ["好奇", "开放", "创意"]):
            openness = 0.7

        return BigFive(
            openness=openness,
            conscientiousness=conscientiousness,
            extraversion=extraversion,
            agreeableness=agreeableness,
            neuroticism=neuroticism,
        )

    def _infer_relationship_phase(self, anxiety: float, avoidance: float) -> str:
        """从依恋维度推断初始关系阶段"""
        return "stranger"

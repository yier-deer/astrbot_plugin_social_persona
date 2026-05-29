from datetime import datetime, timedelta
from typing import Optional, List


class PromptBuilder:
    """Prompt 模板构建器，适配 AstrBot extra_user_content_parts 模式"""

    def build_chat_context(
        self,
        persona: dict,
        relationship: dict,
        memories: List[str],
        today_events: List[dict],
        current_world_date: str = "",
        current_world_day_of_week: str = "",
        is_drowsy: bool = False,
    ) -> str:
        """构建日常聊天动态上下文（注入到 extra_user_content_parts）

        不包含 [SPLIT] 指令和 JSON 格式要求，LLM 正常输出自然语言。
        """
        parts = []

        name = persona.get("name", "未知")
        parts.append(f"你的名字是{name}。")
        if persona.get("character_current_context"):
            parts.append(f"你的生活背景：{persona['character_current_context']}")
        if persona.get("life_stage_detail"):
            parts.append(f"你目前处于：{persona['life_stage_detail']}")

        age = persona.get("age")
        if age is not None:
            parts.append(f"你{age}岁。")

        bf = persona.get("big_five", {})
        if bf:
            traits = []
            if bf.get("extraversion", 0.5) > 0.6:
                traits.append("外向活泼")
            elif bf.get("extraversion", 0.5) < 0.4:
                traits.append("内向安静")
            if bf.get("neuroticism", 0.5) > 0.6:
                traits.append("情绪敏感")
            if bf.get("agreeableness", 0.5) > 0.6:
                traits.append("温和友善")
            elif bf.get("agreeableness", 0.5) < 0.4:
                traits.append("直言不讳")
            if bf.get("openness", 0.5) > 0.6:
                traits.append("好奇开放")
            if traits:
                parts.append(f"你的性格特点：{'、'.join(traits)}。")

        anxiety = persona.get("attachment_anxiety", 0.3)
        avoidance = persona.get("attachment_avoidance", 0.3)
        if anxiety >= 0.5:
            parts.append("你在关系中容易焦虑不安，害怕被忽视，被冷落时会反复确认对方是否还在乎你。")
        elif avoidance >= 0.5:
            parts.append("你在关系中倾向保持距离，过于亲密会让你不适，冲突时你会选择回避。")

        conflict = persona.get("conflict_style", "")
        if conflict:
            conflict_map = {
                "direct_confront": "遇到矛盾你会直接表达不满",
                "cold_shoulder": "遇到矛盾你会冷处理、沉默",
                "avoidant": "遇到矛盾你会回避、转移话题",
                "emotional": "遇到矛盾你会情绪化地表达",
            }
            if conflict in conflict_map:
                parts.append(conflict_map[conflict])

        rhythm = persona.get("social_rhythm", "")
        if rhythm:
            rhythm_map = {
                "slow_warm": "你慢热，需要时间才能打开话匣子",
                "irregular": "你的社交节奏不规律，有时热情有时冷淡",
                "steady": "你的社交节奏稳定，回复比较规律",
            }
            if rhythm in rhythm_map:
                parts.append(rhythm_map[rhythm])

        life_archives = persona.get("life_archives", [])
        if isinstance(life_archives, list):
            high_importance = [a for a in life_archives if isinstance(a, dict) and a.get("importance", 0) >= 7]
            if high_importance:
                parts.append(f"\n你的人生经历：")
                for a in sorted(high_importance, key=lambda x: x.get("time", "")):
                    parts.append(f"  - {a.get('time', '')}：{a.get('content', '')}")

        trust = relationship.get("trust", 30)
        closeness = relationship.get("closeness", 10)
        tension = relationship.get("tension", 0)
        emotional_energy = relationship.get("emotional_energy", 70)

        parts.append(f"\n当前关系状态：")
        parts.append(f"- 信任度：{trust:.0f}/100")
        parts.append(f"- 亲密感：{closeness:.0f}/100")
        parts.append(f"- 张力：{tension:.1f}")
        parts.append(f"- 情绪能量：{emotional_energy:.0f}/100")

        phase = relationship.get("phase", persona.get("relationship_phase", ""))
        phase_desc = self._phase_description(phase, name, trust, closeness)
        if phase_desc:
            parts.append(phase_desc)
        else:
            if closeness < 20:
                parts.append("你们刚认识不久，还不熟悉。")
            elif closeness < 40:
                parts.append("你们有些了解，但还不够亲密。")
            elif closeness < 60:
                parts.append("你们关系不错，有些默契。")
            elif closeness < 80:
                parts.append("你们关系亲密，彼此信任。")
            else:
                parts.append("你们关系非常亲密，无话不谈。")

        if tension > 5:
            parts.append("你们之间有些紧张气氛。")

        if memories:
            parts.append(f"\n你记得关于用户的这些事：")
            for i, mem in enumerate(memories, 1):
                parts.append(f"  {i}. {mem}")

        if today_events:
            active_events = [e for e in today_events if e.get("is_active", True)]
            if active_events:
                parts.append(f"\n你今天的事：")
                for e in active_events:
                    time_str = e.get("time", e.get("event_time", ""))
                    desc = e.get("description", "")
                    parts.append(f"  - {time_str} {desc}")

        if current_world_date:
            parts.append(f"\n今天是{current_world_date}，{current_world_day_of_week}。")

        if is_drowsy:
            parts.append("\n你正在睡觉，被用户的消息吵醒了。你很困，说话含糊简短。")

        ts = persona.get("typing_style", persona.get("typing_style_json", {}))
        if isinstance(ts, str):
            import json as _json
            try:
                ts = _json.loads(ts)
            except Exception:
                ts = {}
        frag = ts.get("fragmentation_level", 0.3) if isinstance(ts, dict) else 0.3
        if frag > 0.6:
            parts.append("\n你说话喜欢一句一句蹦，很少一次说完。")
        elif frag > 0.3:
            parts.append("\n你说话有时会分几条发。")

        return "\n".join(parts)

    def build_cron_wake_note(
        self,
        persona: dict,
        event: dict,
        relationship: dict,
        memories: Optional[List[str]] = None,
    ) -> str:
        """构建 CronJob 唤醒时注入到主 Agent 的上下文

        当 CronJob 触发时，主 Agent 被唤醒。此方法构建的文本会通过
        inject_persona_context 注入到 Agent 的请求中，让 Agent 知道
        自己是谁、发生了什么事、和用户的关系如何。

        Args:
            persona: Persona 字典
            event: 触发的事件字典
            relationship: 关系状态字典
            memories: 相关记忆列表

        Returns:
            注入到 extra_user_content_parts 的上下文文本
        """
        name = persona.get("name", "未知")
        event_desc = event.get("description", "")
        event_type = event.get("type", "routine")
        event_time = event.get("time", "")

        parts = [f"你是{name}。这是一个定时唤醒——你生活中刚刚发生了一件事。"]

        if persona.get("life_stage_detail"):
            parts.append(f"你的身份：{persona['life_stage_detail']}")
        if persona.get("current_location"):
            parts.append(f"你在：{persona['current_location']}")
        if persona.get("character_current_context"):
            parts.append(f"生活背景：{persona['character_current_context']}")

        bf = persona.get("big_five", {})
        if bf:
            traits = []
            if bf.get("extraversion", 0.5) > 0.6:
                traits.append("外向活泼")
            elif bf.get("extraversion", 0.5) < 0.4:
                traits.append("内向安静")
            if bf.get("neuroticism", 0.5) > 0.6:
                traits.append("情绪敏感")
            if bf.get("agreeableness", 0.5) > 0.6:
                traits.append("温和友善")
            elif bf.get("agreeableness", 0.5) < 0.4:
                traits.append("直言不讳")
            if traits:
                parts.append(f"你的性格：{'、'.join(traits)}")

        anxiety = persona.get("attachment_anxiety", 0.3)
        avoidance = persona.get("attachment_avoidance", 0.3)
        if anxiety >= 0.5:
            parts.append("你在关系中容易焦虑不安，害怕被忽视。")
        elif avoidance >= 0.5:
            parts.append("你在关系中倾向保持距离，过于亲密会让你不适。")

        life_archives = persona.get("life_archives", [])
        if isinstance(life_archives, list):
            high_importance = [a for a in life_archives if isinstance(a, dict) and a.get("importance", 0) >= 7]
            if high_importance:
                parts.append(f"\n你的人生经历：")
                for a in sorted(high_importance, key=lambda x: x.get("time", "")):
                    parts.append(f"  - {a.get('time', '')}：{a.get('content', '')}")

        parts.append(f"\n⏰ {event_time} 发生了一件事：{event_desc}（类型：{event_type}）")

        trust = relationship.get("trust", 30)
        closeness = relationship.get("closeness", 10)
        tension = relationship.get("tension", 0)
        emotional_energy = relationship.get("emotional_energy", 70)

        parts.append(f"\n你和用户的关系：")
        parts.append(f"- 信任度：{trust:.0f}/100")
        parts.append(f"- 亲密感：{closeness:.0f}/100")
        parts.append(f"- 张力：{tension:.1f}")
        parts.append(f"- 情绪能量：{emotional_energy:.0f}/100")

        if closeness < 20:
            parts.append("你们刚认识不久，还不熟悉。")
        elif closeness < 40:
            parts.append("你们有些了解，但还不够亲密。")
        elif closeness < 60:
            parts.append("你们关系不错，有些默契。")
        elif closeness < 80:
            parts.append("你们关系亲密，彼此信任。")
        else:
            parts.append("你们关系非常亲密，无话不谈。")

        if tension > 5:
            parts.append("你们之间有些紧张气氛。")

        if memories:
            parts.append(f"\n你记得关于用户的这些事：")
            for i, mem in enumerate(memories, 1):
                parts.append(f"  {i}. {mem}")

        if event_type == "sleep":
            parts.append("\n你要去睡觉了。不需要联系用户，安静入睡即可。"
                         "请简要说明你的内心想法后结束。")
        else:
            parts.append("\n请根据你的性格和当前关系状态，自主决定是否要联系用户分享这件事。"
                         "如果想联系，请用 SendMessageToUser 工具发送消息。"
                         "如果不想联系，也请简要说明你的内心想法。")

        return "\n".join(parts)

    def build_event_generate_prompt(
        self,
        persona: dict,
        current_world_date: str,
        current_world_day_of_week: str,
        yesterday_events: Optional[List[dict]] = None,
        inner_thoughts: Optional[List[dict]] = None,
    ) -> str:
        """构建每日事件生成的 Prompt（内部 LLM 调用，保留 JSON 输出格式）"""
        name = persona.get("name", "未知")
        context = persona.get("character_current_context", "暂无")
        trust = persona.get("trust", 50)
        closeness = persona.get("closeness", 20)
        life_stage_detail = persona.get("life_stage_detail", persona.get("life_stage", ""))
        current_location = persona.get("current_location", "")
        age = persona.get("age", 20)

        identity_block = ""
        if life_stage_detail:
            identity_block += f"你的身份：{life_stage_detail}\n"
        if current_location:
            identity_block += f"当前地点：{current_location}\n"

        thoughts_text = ""
        if inner_thoughts:
            lines = []
            for t in inner_thoughts:
                raw = t.get("raw_thought", t.get("description", ""))
                att = t.get("attitude", "")
                lines.append(f"  [{att}] {raw}")
            thoughts_text = "\n".join(lines)

        yesterday_text = ""
        if yesterday_events:
            lines = []
            for e in yesterday_events:
                t = e.get("time", e.get("event_time", "?"))
                d = e.get("description", "")
                etype = e.get("type", "")
                lines.append(f"  [{t}] ({etype}) {d}")
            yesterday_text = "\n".join(lines)

        return f"""你是{name}。

{identity_block}当前处境：{context}
年龄：{age}
今天日期：{current_world_date}（{current_world_day_of_week}）
关系状态：信任 {trust}，亲密 {closeness}

今天的内心独白：
{thoughts_text if thoughts_text else "今天还没有内心独白"}

昨天事件参考：
{yesterday_text if yesterday_text else "暂无"}

请以第一人称视角，生成你今天从早到晚的事件线，并写一份今日反思。
生成至少 6 个事件（建议 8~12 个），时间从起床排列到睡觉。
第一个事件的 type 必须是 "wake"（起床），最后一个事件的 type 必须是 "sleep"（睡觉），这是硬性要求，不可违反。

事件生成规则：
  - time：24 小时制（如 08:00、12:00、23:00），从早到晚，各不相同
  - type：wake（起床）/ routine（日常）/ moment（特别时刻）/ sleep（睡觉）
  - 你当前是"{life_stage_detail}"，住在{current_location}——
    请想象你今天在这个身份和地点下真实的一天会做什么
  - 转折性活动（毕业典礼、收拾行李、坐火车去新城市、入职报到等）可以正常作为事件出现
  - 不要在事件描述里写 meta 声明——身份变化统一在 life_stage_transition 中判断

生命阶段 / 地点切换判断（必须执行以下两步）：

  第一步：根据当前处境、你生成的事件线内容和今天日期，
    判断今天你的身份和日常活动地点是否发生了变化。
    判断标准——今天的主要场景是否和你上述的"当前身份/地点"一致？
    · 如果今天有毕业/入职/搬家去新城市等活动，而你当前身份仍是 student →
      身份应变化，should_transition 必须为 true
    · 如果今天去了一个新的城市长期停留 → 地点应变化
    · 如果今天只是普通的一天，没有人生转折 → 无变化

  第二步：根据判断结果填写 life_stage_transition：
    · 有变化 → should_transition 设为 true，并填写：
      - new_life_stage：新身份阶段（student / working / at_home / traveling 等）
      - new_life_stage_detail：对新身份的简短描述
      - new_location：新的日常活动城市
      - transition_reason：一句话说明变化原因
    · 无变化 → should_transition 设为 false，其余字段留空字符串

人生档案追加判断（重要——不是每天都写！）：
  判断今天是否发生了值得写入你人生档案的里程碑事件。以下情况可以写：
  · 人生重大转折：毕业、入学、入职、创业、结婚、搬家去新城市
  · 与用户关系突破：从陌生人变成熟人、从朋友变成密友
  · 重要的情感经历：第一次对某人敞开心扉、经历重大冲突与和解
  以下情况不要写：
  · 普通的日常（上课、吃饭、自习、运动）
  · 没有实质改变的常规社交
  
  如果有里程碑事件，在 today_reflection 中填写 life_archive_entry 字段；
  如果只是普通的一天，将 life_archive_entry 设为 null。

JSON格式：
{{
  "today_reflection": {{
    "raw_text": "今天的感受和思考...",
    "key_memories": [{{"content":"今天最值得记住的一件事","importance":7}}],
    "relationship_summary": "与用户的关系变化",
    "life_archive_entry": null,
    "life_stage_transition": {{
      "should_transition": false,
      "new_life_stage": "",
      "new_life_stage_detail": "",
      "new_location": "",
      "transition_reason": ""
    }}
  }},
  "events": [
    {{"time":"08:00","type":"routine","description":"起床，开始新的一天","is_active":true}},
    {{"time":"12:00","type":"routine","description":"中间的事件...","is_active":true}},
    {{"time":"23:00","type":"sleep","description":"睡觉","is_active":true}}
  ]
}}"""

    def build_matchmaker_prompt(
        self,
        stage: str,
        stage_config: dict,
        collected_data: dict,
        user_message: str = "",
    ) -> str:
        """构建 Matchmaker 访谈 Prompt（7 阶段，保留完整格式）"""
        goal = stage_config.get("goal", "")
        questions = stage_config.get("questions", [])
        extract_schema = stage_config.get("extract_schema", {})
        next_stage = stage_config.get("next_stage", "")

        prompt = f"""你是"牵线人"，一个帮助用户创建AI角色的引导者。你正在第{stage}阶段。

目标：{goal}

需要收集的信息：
{self._format_extract_schema(extract_schema)}

已收集的数据：
{self._format_collected_data(collected_data)}

用户说：{user_message}

请根据用户的回答提取数据，并决定是否可以进入下一阶段。

请以JSON格式回复：
{{
    "extracted_data": {{
        "field_name": "提取的值"
    }},
    "is_complete": true/false,
    "response": "你的回复（引导性、自然的对话）"
}}"""
        return prompt

    def build_quick_create_prompt(self, user_description: str) -> str:
        """构建快速创建角色的 Prompt，从用户的一段完整描述中提取所有字段

        Args:
            user_description: 用户提供的角色完整描述文本

        Returns:
            要求 LLM 返回 JSON 的 Prompt
        """
        return f"""你是"牵线人"的数据提取助手。用户会提供一段关于AI角色的完整描述，你需要从中提取所有字段。

用户描述：
{user_description}

请从描述中提取以下信息，返回JSON。如果用户没有提到某个字段，使用合理的默认值。

必须提取的字段：
{{
  "name": "角色名字",
  "age": 年龄整数,
  "gender": "性别",
  "communication_style": "说话风格描述（如：毒舌傲娇，嘴硬心软）",
  "style_reference": "参考角色名（如：友利奈绪，没有则为空字符串）",
  "emotional_expression": "情绪表达方式（如：毒舌掩饰真心，亲密后像小猫）",
  "reaction_to_silence": "被冷落的反应描述",
  "reaction_to_rivalry": "发现竞争对手的反应描述",
  "conflict_style": "冲突处理方式（avoidant/confrontational/compromising）",
  "attachment_anxiety": 依恋焦虑程度0到1的浮点数,
  "attachment_avoidance": 依恋回避程度0到1的浮点数,
  "self_esteem_stability": 自尊稳定性0到1的浮点数,
  "typing_speed": 打字速度1到5整数,
  "fragmentation_level": 碎片化程度0到1浮点数,
  "image_enabled": 是否发图片0或1整数,
  "image_style_prompt": "图片风格描述（如：动漫风，外貌像友利奈绪），不发图片则为空",
  "life_stage": "生活阶段（student/working/at_home/traveling等）",
  "life_stage_detail": "生活阶段详情（如：大二学生）",
  "current_location": "所在地（如：中国大学校园）",
  "character_current_context": "角色当前生活背景和处境描述",
  "character_appearance": "外貌描述",
  "relationship_phase": "初始关系阶段（stranger/acquaintance/friend/close_friend）",
  "character_initial_world_time": "角色世界初始日期YYYY-MM-DD格式，没有则为空",
  "initiative_tendency": 主动联系倾向0到1浮点数,
  "birthday": "角色出生日期YYYY-MM-DD格式，没有则为空",
  "life_archives": [
    {{
      "stage": "childhood/adolescence/young_adult",
      "time": "YYYY-MM-DD格式的日期",
      "type": "key_event/personality_origin/life_turning_point/created_event",
      "content": "描述文本，写清楚这件事对角色性格或人生的影响",
      "importance": 1到10的整数，越高越影响性格
    }}
  ],
  "big_five": {{
    "openness": 开放性0到1,
    "conscientiousness": 尽责性0到1,
    "extraversion": 外向性0到1,
    "agreeableness": 宜人性0到1,
    "neuroticism": 神经质0到1
  }}
}}

推断规则：
- attachment_anxiety：经常想找对方、反复确认→高(0.7-0.9)；不在意→低(0.1-0.3)
- attachment_avoidance：突然疏远、回避亲密→高(0.7-0.9)；粘人→低(0.1-0.3)
- conflict_style：主动道歉→compromising；冷处理→avoidant；直接怼→confrontational
- initiative_tendency：秒回+主动找→高(0.7-0.9)；被动→低(0.1-0.3)
- fragmentation_level：一句一句发→高(0.5-0.8)；整段发→低(0.1-0.2)
- big_five：毒舌→agreeableness低；情绪敏感→neuroticism高；粘人→extraversion高

只输出纯JSON，不要添加任何解释或markdown标记。"""

    def _phase_description(self, phase: str, name: str, trust: float, closeness: float) -> str:
        """根据关系阶段生成行为指导描述"""
        descriptions = {
            "stranger": (
                "你和对方完全是陌生人——你们今天才第一次接触，你对他一无所知。"
                "你应该带着警惕和困惑与他交流，用对待完全陌生人的方式。"
                "如果对话持续且他表现得友好，你才会逐渐放下戒备。"
            ),
            "acquaintance": (
                "你们算是认识了，但还不太熟——大概聊过几次，知道对方是谁。"
                "你对他有基本的好感，但还不会主动分享太私密的事情。"
            ),
            "friend": (
                "你们是朋友了——互相信任，会主动分享生活中的事情。"
                "你可以在聊天中自然地开玩笑、抱怨、分享心情。"
            ),
            "close_friend": (
                "你们是密友——你对他非常信任，几乎无所不谈。"
                "你会在他面前展现真实的情绪，不需要伪装或保留。"
                "你可以主动找他、依赖他，也愿意在他需要时提供支持。"
            ),
        }
        return descriptions.get(phase, "")

    def _format_extract_schema(self, schema: dict) -> str:
        """格式化 extract_schema 为可读文本"""
        if not schema:
            return "无"
        lines = []
        for key, desc in schema.items():
            lines.append(f"  - {key}: {desc}")
        return "\n".join(lines)

    def _format_collected_data(self, data: dict) -> str:
        """格式化已收集数据为可读文本"""
        if not data:
            return "暂无"
        lines = []
        for key, value in data.items():
            lines.append(f"  - {key}: {value}")
        return "\n".join(lines)

    def compute_world_date(self, initial_world_time: str, created_at: str) -> tuple:
        """计算当前世界日期

        Args:
            initial_world_time: 角色世界的初始日期（YYYY-MM-DD）
            created_at: 角色创建的真实日期

        Returns:
            (current_world_date, current_world_day_of_week)
        """
        weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

        if not initial_world_time or not created_at:
            today = datetime.now()
            return today.strftime("%Y-%m-%d"), weekdays[today.weekday()]

        try:
            initial = datetime.strptime(initial_world_time, "%Y-%m-%d")
            created = datetime.strptime(created_at[:10], "%Y-%m-%d")
            now = datetime.now()
            delta_days = (now - created).days
            world_now = initial + timedelta(days=delta_days)
            return world_now.strftime("%Y-%m-%d"), weekdays[world_now.weekday()]
        except (ValueError, TypeError):
            today = datetime.now()
            return today.strftime("%Y-%m-%d"), weekdays[today.weekday()]

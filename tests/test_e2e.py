"""
社交人格插件 - 端到端测试（仿真人使用）

通过 AstrBot Web 聊天 API 发送真实消息，模拟用户完整使用流程。

运行前提：
  1. AstrBot 已启动
  2. 插件已安装
  3. LLM Provider 已配置
  4. 主动型能力已启用

运行方式：
  python tests/test_e2e.py
  python tests/test_e2e.py --base-url http://localhost:6185 --password your_pwd
"""

import requests
import json
import sys
import time
import argparse

DEFAULT_BASE = "http://localhost:6185"
SEP = "=" * 70
SUBSEP = "-" * 50


def print_step(num, title):
    print(f"\n{SEP}")
    print(f"  [步骤 {num}] {title}")
    print(f"{SEP}")


def print_ok(msg):
    print(f"  [OK] {msg}")


def print_fail(msg):
    print(f"  [FAIL] {msg}")


def print_info(msg):
    print(f"  -> {msg}")


def print_warn(msg):
    print(f"  [!] {msg}")


def print_data(key, value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, indent=4)
    print(f"  {key}: {value}")


class AstrBotClient:
    """AstrBot Web 聊天客户端（使用 JWT Bearer 认证）"""

    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session_id = None
        self.token = None

    def login(self, username="astrbot", password=""):
        """登录 AstrBot dashboard，提取 JWT token 用于后续请求"""
        r = self.session.post(f"{self.base_url}/api/auth/login",
                              json={"username": username, "password": password})
        resp = r.json()
        if resp.get("status") == "ok":
            token = resp.get("data", {}).get("token")
            if token:
                self.token = token
                self.session.headers["Authorization"] = f"Bearer {token}"
            return True
        print_fail(f"登录失败: {resp.get('message', resp)}")
        return False

    def new_session(self):
        """创建新的聊天会话"""
        r = self.session.get(f"{self.base_url}/api/chat/new_session")
        resp = r.json()
        if resp.get("status") == "ok":
            self.session_id = resp["data"]["session_id"]
            return self.session_id
        raise Exception(f"创建会话失败: {resp}")

    def send_message(self, message, timeout=120):
        """发送消息并等待完整回复（处理 SSE 流）"""
        if not self.session_id:
            self.new_session()

        payload = {
            "message": message,
            "session_id": self.session_id,
            "enable_streaming": False,
        }

        r = self.session.post(f"{self.base_url}/api/chat/send",
                              json=payload, stream=True, timeout=timeout)

        full_text = ""
        for line in r.iter_lines():
            if not line:
                continue
            decoded = line.decode("utf-8")
            if not decoded.startswith("data: "):
                continue
            try:
                data = json.loads(decoded[6:])
            except json.JSONDecodeError:
                continue
            msg_type = data.get("type", "")
            if msg_type == "plain":
                full_text += data.get("data", "")
            elif msg_type == "end":
                break
        return full_text.strip()


def main():
    parser = argparse.ArgumentParser(description="社交人格插件端到端测试")
    parser.add_argument("--base-url", default=DEFAULT_BASE, help="AstrBot 地址")
    parser.add_argument("--username", default="astrbot", help="登录用户名")
    parser.add_argument("--password", default="", help="登录密码")
    args = parser.parse_args()

    print(f"\n{'#' * 70}")
    print(f"  社交人格插件 - 端到端测试")
    print(f"{'#' * 70}")
    print(f"  AstrBot: {args.base_url}")
    print(f"  开始: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    client = AstrBotClient(args.base_url)
    persona_name = None

    try:
        if not client.login(args.username, args.password):
            print_warn("无法登录，后续请求可能因未授权而失败")

        # =====================================================
        # 步骤 1：快速创建角色
        # =====================================================
        print_step(1, "快速创建角色（/sp quick）")

        sid = client.new_session()
        print_ok(f"会话已创建: {sid}")

        quick_desc = (
            "名字叫测试小雨，20岁女大学生，性格毒舌傲娇但内心温柔，"
            "说话喜欢用颜文字和省略号，有点社恐但对熟人很话多，"
            "焦虑型依恋，容易吃醋，在北京上学"
        )
        print_info("发送 /sp quick ...")

        start = time.time()
        reply = client.send_message(f"/sp quick {quick_desc}", timeout=180)
        elapsed = time.time() - start

        print_ok(f"收到回复（{elapsed:.1f}s）：")
        print(f"  {reply[:500]}")

        if "确认" in reply:
            print_info("需要确认，发送 '确认'...")
            reply2 = client.send_message("确认", timeout=120)
            print_ok(f"确认回复: {reply2[:200]}")

        # =====================================================
        # 步骤 2：查看角色列表
        # =====================================================
        print_step(2, "查看角色列表（/sp list）")

        reply = client.send_message("/sp list", timeout=30)
        print_ok(f"角色列表：\n  {reply[:500]}")

        if "测试小雨" in reply:
            persona_name = "测试小雨"
            print_ok(f"检测到角色: {persona_name}")

        # =====================================================
        # 步骤 3：查看可用机器人
        # =====================================================
        print_step(3, "查看可用机器人（/sp mount 测试小雨）")

        reply = client.send_message("/sp mount 测试小雨", timeout=30)
        print_ok(f"机器人列表：\n  {reply[:500]}")

        # =====================================================
        # 步骤 4：挂载到 webchat
        # =====================================================
        print_step(4, "挂载角色到 webchat 机器人")

        reply = client.send_message("/sp mount 测试小雨 webchat", timeout=60)
        print_ok(f"挂载结果：\n  {reply[:300]}")

        if "已将" in reply or "挂载" in reply:
            print_ok("挂载成功！事件生成应已触发")
        else:
            print_warn("请检查挂载是否成功")

        time.sleep(2)

        # =====================================================
        # 步骤 5：查看简要信息
        # =====================================================
        print_step(5, "查看角色简要信息（/sp info）")

        reply = client.send_message("/sp info 测试小雨", timeout=30)
        print_ok(f"简要信息：\n  {reply[:500]}")

        # =====================================================
        # 步骤 6：查看详细信息
        # =====================================================
        print_step(6, "查看角色详细信息（/sp detail）")

        reply = client.send_message("/sp detail 测试小雨", timeout=30)
        print_ok(f"详细信息：\n  {reply[:800]}")

        if "今日事件线" in reply:
            print_ok("事件线已生成！")
            if "wake" in reply.lower() or "起床" in reply:
                print_ok("包含起床事件")
            if "sleep" in reply.lower() or "睡觉" in reply:
                print_ok("包含睡觉事件")
        else:
            print_warn("未检测到事件线，请检查主动型能力是否启用")

        # =====================================================
        # 步骤 7：正常聊天
        # =====================================================
        print_step(7, "正常聊天（测试 persona 上下文注入）")

        for msg in ["你好呀~", "今天在干嘛呢？", "最近有什么有趣的事吗？"]:
            print_info(f"用户: {msg}")
            start = time.time()
            reply = client.send_message(msg, timeout=60)
            elapsed = time.time() - start
            print_ok(f"AI（{elapsed:.1f}s）: {reply[:200]}")
            time.sleep(1)

        # =====================================================
        # 步骤 8：测试事件线修改
        # =====================================================
        print_step(8, "测试事件线修改（邀请角色出去玩）")

        invite_msg = "下午别自习了，跟我一起去逛街吧！我知道一个很好玩的地方！"
        print_info(f"用户: {invite_msg}")

        start = time.time()
        reply = client.send_message(invite_msg, timeout=120)
        elapsed = time.time() - start
        print_ok(f"AI（{elapsed:.1f}s）: {reply[:300]}")

        time.sleep(2)

        print_info("检查事件线是否已更新...")
        reply = client.send_message("/sp detail 测试小雨", timeout=30)
        if "逛街" in reply or "出门" in reply or "收拾" in reply:
            print_ok("事件线已动态调整！")
        else:
            print_info("事件线可能未变化")

        # =====================================================
        # 步骤 9：查看关系状态
        # =====================================================
        print_step(9, "查看关系状态（/sp status）")

        reply = client.send_message("/sp status", timeout=30)
        print_ok(f"关系状态：\n  {reply[:300]}")

        # =====================================================
        # 步骤 10：记忆测试
        # =====================================================
        print_step(10, "记忆测试（提及之前的话题）")

        reply = client.send_message("刚才聊到哪了？你还记得吗？", timeout=60)
        print_ok(f"AI: {reply[:300]}")

        # =====================================================
        # 步骤 11：清理
        # =====================================================
        print_step(11, "清理测试数据")

        user_input = input("\n  >>> 按 Enter 删除测试角色，输入其他跳过: ").strip()
        if user_input == "" and persona_name:
            reply = client.send_message(f"/sp delete {persona_name}", timeout=30)
            print_ok(f"删除结果: {reply[:200]}")
        else:
            print_info("数据已保留")

    except requests.exceptions.ConnectionError:
        print_fail(f"无法连接到 AstrBot ({args.base_url})")
        print_info("请确认 AstrBot 已启动，地址正确")
        sys.exit(1)
    except Exception as e:
        print_fail(f"测试异常: {e}")
        import traceback
        traceback.print_exc()

    print(f"\n{'#' * 70}")
    print(f"  测试完成")
    print(f"{'#' * 70}")


if __name__ == "__main__":
    main()

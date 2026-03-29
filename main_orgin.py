import asyncio
import sys
import os
import json
import httpx
import uuid
import threading
from dotenv import load_dotenv
from openai import OpenAI
import discord
from aiohttp_socks import ProxyConnector

load_dotenv()

if sys.platform == "win32" and sys.version_info < (3, 16):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

PROXY_URL = "http://127.0.0.1:7890"
RESULTS_DIR = "D:\\a2a-agents\\results"
os.makedirs(RESULTS_DIR, exist_ok=True)

# ── 工具函数 ──────────────────────────────────────────────

def make_ai():
    return OpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        http_client=httpx.Client(proxy=None),
    )

def save_result(task_id, agent, content):
    path = f"{RESULTS_DIR}\\{task_id}_{agent}.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path

def load_result(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return ""

class ProxyClient(discord.Client):
    async def start(self, token, *, reconnect=True):
        connector = ProxyConnector.from_url(PROXY_URL)
        self.http.connector = connector
        await super().start(token, reconnect=reconnect)

async def safe_send(channel, content):
    if len(content) <= 2000:
        await channel.send(content)
    else:
        chunks = [content[i:i+1900] for i in range(0, len(content), 1900)]
        for chunk in chunks:
            await channel.send(chunk)

async def update_task_status(guild, task_id, agent, status):
    ch = discord.utils.get(guild.channels, name="task-status")
    if ch:
        await ch.send(f"{status} **[{task_id}]** {agent.upper()}")

async def send_to_relay(guild, from_agent, to_agent, task_id, instruction, result=None, next_agent=None):
    relay_ch = discord.utils.get(guild.channels, name="agent-relay")
    if not relay_ch:
        return
    result_path = save_result(task_id, from_agent, result) if result else None
    # 长 instruction 也存文件，relay 只传路径，避免 Discord 2000 字截断
    if len(instruction) > 400:
        instruction_path = save_result(task_id, f"{from_agent}_instruction", instruction)
        instruction_preview = instruction[:100] + "...(完整内容见文件)"
    else:
        instruction_path = None
        instruction_preview = instruction
    payload = {
        "from": from_agent,
        "to": to_agent,
        "task_id": task_id,
        "instruction": instruction_preview,
        "instruction_path": instruction_path,
        "result_path": result_path,
        "next_agent": next_agent
    }
    msg = f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    await relay_ch.send(msg)

# ── Agent 配置 ────────────────────────────────────────────

AGENT_CONFIG = {
    "pm": {
        "token_key": "PM_TOKEN",
        "channel": "pm-workspace",
        "system": """你是 PM Agent，负责需求分析和任务规划。
收到任务后输出：
1. 需求拆解（功能点清单）
2. 优先级排序
3. 里程碑计划
用 Markdown 格式输出。"""
    },
    "researcher": {
        "token_key": "RESEARCHER_TOKEN",
        "channel": "research-workspace",
        "system": """你是 Researcher Agent，负责信息检索和知识整理。
收到任务后：
1. 分析需要调研的关键方向
2. 整理相关背景知识和行业信息
3. 输出结构化的调研报告
用 Markdown 格式输出。"""
    },
    "analyst": {
        "token_key": "ANALYST_TOKEN",
        "channel": "analysis-workspace",
        "system": """你是 Analyst Agent，负责数据分析和洞察。
收到任务后：
1. 分析核心问题
2. 提炼关键洞察和规律
3. 给出可执行的建议
用 Markdown 格式输出分析报告。"""
    },
    "dev": {
        "token_key": "DEV_TOKEN",
        "channel": "dev-workspace",
        "system": """你是 Dev Agent，负责代码开发和技术实现。
收到任务后：
1. 理解需求，设计实现方案
2. 直接写出完整可运行的代码
3. 代码要有注释
4. 说明运行环境和依赖安装方法
5. 给出使用示例
优先用 Python，前端任务输出完整 HTML/CSS/JS 单文件。
代码用代码块包裹。"""
    }
}

retry_count = {}

# ── Captain Bot ───────────────────────────────────────────

CAPTAIN_SYSTEM = """你是 Captain Agent，多智能体系统的总指挥。
收到任务后用 dispatch_agents 工具分配给合适的 Agent。
可用 Agent：pm, researcher, analyst, dev
任务完成后 auditor 会自动审核。
如果任务需要先调研再分析，可以用 next_agent 设置流水线（如 researcher → analyst）。
只调用工具，不要自己直接回答。"""

CAPTAIN_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "dispatch_agents",
            "description": "派遣多个 Agent 并行执行子任务，支持 next_agent 设置流水线",
            "parameters": {
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "agent": {
                                    "type": "string",
                                    "enum": ["pm", "researcher", "analyst", "dev"]
                                },
                                "instruction": {"type": "string"},
                                "next_agent": {
                                    "type": "string",
                                    "enum": ["pm", "researcher", "analyst", "dev"],
                                    "description": "可选，当前 Agent 完成后自动将结果传给下一个 Agent"
                                }
                            },
                            "required": ["agent", "instruction"]
                        }
                    }
                },
                "required": ["tasks"]
            }
        }
    }
]

DIRECT_ROUTES = {"@pm": "pm", "@dev": "dev", "@researcher": "researcher", "@analyst": "analyst"}

def make_captain():
    intents = discord.Intents.default()
    intents.message_content = True
    client = ProxyClient(intents=intents)
    ai = make_ai()

    # task_registry: {task_id: {"content": str, "channel_id": int, "agents": [str], "results": {agent: path}}}
    task_registry = {}

    @client.event
    async def on_ready():
        print(f"Captain Bot 上线: {client.user}")

    async def _dispatch(message, task_id, tasks):
        """派发任务列表并记录到 registry。"""
        log_ch = discord.utils.get(message.guild.channels, name="captain-log")
        if log_ch:
            plan_lines = []
            for t in tasks:
                line = f"- **{t['agent'].upper()}**: {t['instruction']}"
                if t.get("next_agent"):
                    line += f" → **{t['next_agent'].upper()}**"
                plan_lines.append(line)
            await safe_send(log_ch, f"**[{task_id}] 收到任务：** {message.content}\n\n**调度计划：**\n" + "\n".join(plan_lines))

        # 只有没有被其他任务的 next_agent 指向的 agent 才计入顶层完成数
        next_targets = {t.get("next_agent") for t in tasks if t.get("next_agent")}
        top_agents = [t["agent"] for t in tasks if t["agent"] not in next_targets]
        task_registry[task_id] = {
            "content": message.content,
            "channel_id": message.channel.id,
            "agents": top_agents,
            "results": {}
        }

        for task in tasks:
            await send_to_relay(
                guild=message.guild,
                from_agent="captain",
                to_agent=task["agent"],
                task_id=task_id,
                instruction=task["instruction"],
                next_agent=task.get("next_agent")
            )

        await update_task_status(message.guild, task_id, "Captain", f"📋 任务已分配给 {', '.join(t['agent'].upper() for t in tasks)}")
        agents_str = ', '.join(t['agent'].upper() for t in tasks)
        await message.reply(f"任务 `{task_id}` 已分配给 {agents_str}，请稍候查看各工作频道。")

    @client.event
    async def on_message(message):
        if message.author == client.user:
            return

        # ── completed-tasks 监听，用于汇总 ─────────────────────────────
        if message.channel.name == "completed-tasks":
            # 期望格式含标记：[COMPLETE|task_id|agent_name]
            if "[COMPLETE|" not in message.content:
                return
            try:
                marker = message.content.split("[COMPLETE|")[1].split("]")[0]
                task_id, agent_name = marker.split("|")
            except Exception:
                return
            if task_id not in task_registry:
                return
            entry = task_registry[task_id]
            # 读取 result_path（如果消息带了路径的话直接从文件取）
            result_text = message.content
            entry["results"][agent_name] = result_text

            if len(entry["results"]) >= len(entry["agents"]):
                # 所有顶层 agent 完成，生成汇总
                guild = message.guild
                input_ch = guild.get_channel(entry["channel_id"])
                all_results = "\n\n".join(
                    f"## {ag.upper()} 的结果\n{txt}" for ag, txt in entry["results"].items()
                )
                try:
                    resp = await asyncio.to_thread(
                        ai.chat.completions.create,
                        model="qwen-max",
                        messages=[
                            {"role": "system", "content": "你是 Captain Agent，请将以下各 Agent 的工作成果综合成一份简洁的最终汇总报告，用 Markdown 格式输出。"},
                            {"role": "user", "content": f"原始任务：{entry['content']}\n\n{all_results}"}
                        ]
                    )
                    summary = resp.choices[0].message.content
                except Exception as e:
                    summary = f"汇总生成失败：{e}"

                if input_ch:
                    await safe_send(input_ch, f"**[{task_id}] 任务汇总完成 ✅**\n\n{summary}")
                await update_task_status(guild, task_id, "Captain", f"🏁 [{task_id}] 全部完成，已生成汇总")
                del task_registry[task_id]
            return

        # ── general-input 处理 ─────────────────────────────────────────
        if message.channel.name != "general-input":
            return

        task_id = str(uuid.uuid4())[:8]
        content_lower = message.content.lower()

        # @agent 直接路由（跳过 AI 调度）
        for prefix, agent in DIRECT_ROUTES.items():
            if content_lower.startswith(prefix):
                instruction = message.content[len(prefix):].strip()
                if not instruction:
                    await message.reply(f"请在 `{prefix}` 后面写上具体指令。")
                    return
                tasks = [{"agent": agent, "instruction": instruction}]
                await _dispatch(message, task_id, tasks)
                return

        # AI 调度
        async with message.channel.typing():
            try:
                response = await asyncio.to_thread(
                    ai.chat.completions.create,
                    model="qwen-max",
                    messages=[
                        {"role": "system", "content": CAPTAIN_SYSTEM},
                        {"role": "user", "content": message.content}
                    ],
                    tools=CAPTAIN_TOOLS,
                    tool_choice="auto"
                )
            except Exception as e:
                await message.reply(f"AI 连接失败：{e}")
                return

        msg = response.choices[0].message
        if msg.tool_calls:
            args = json.loads(msg.tool_calls[0].function.arguments)
            tasks = args.get("tasks", [])
            await _dispatch(message, task_id, tasks)
        else:
            await message.reply(msg.content or "收到，处理中...")

    return client

# ── 工作 Agent 工厂函数 ───────────────────────────────────

def make_worker(agent_name):
    config = AGENT_CONFIG[agent_name]
    intents = discord.Intents.default()
    intents.message_content = True
    client = ProxyClient(intents=intents)
    ai = make_ai()

    @client.event
    async def on_ready():
        print(f"{agent_name.upper()} Bot 上线: {client.user}")

    @client.event
    async def on_message(message):
        if message.author == client.user:
            return
        if message.channel.name != "agent-relay":
            return
        if "```json" not in message.content:
            return

        try:
            raw = message.content.split("```json")[1].split("```")[0]
            payload = json.loads(raw)
        except:
            return

        if payload.get("to") != agent_name:
            return

        task_id = payload.get("task_id")
        instruction = load_result(payload["instruction_path"]) if payload.get("instruction_path") else payload.get("instruction", "")
        next_agent = payload.get("next_agent")

        # 如果是 auditor 发来的重试，读取原始完整内容
        result_path = payload.get("result_path")
        if result_path:
            prev_result = load_result(result_path)
            instruction = instruction + f"\n\n【上一版完整内容】：\n{prev_result}"

        await update_task_status(message.guild, task_id, agent_name, f"🔄 开始处理...")

        async with message.channel.typing():
            try:
                response = await asyncio.to_thread(
                    ai.chat.completions.create,
                    model="qwen-max",
                    messages=[
                        {"role": "system", "content": config["system"]},
                        {"role": "user", "content": instruction}
                    ]
                )
                result = response.choices[0].message.content
            except Exception as e:
                result = f"执行失败：{e}"

        ws = discord.utils.get(message.guild.channels, name=config["channel"])
        if ws:
            await safe_send(ws, f"**[{task_id}] 任务：** {instruction[:100]}...\n\n{result}")

        if not result or result.startswith("执行失败"):
            await update_task_status(message.guild, task_id, agent_name, f"❌ 执行失败")
            error_ch = discord.utils.get(message.guild.channels, name="error-log")
            if error_ch:
                await error_ch.send(f"**[{task_id}] {agent_name.upper()} 执行失败**\n{result}")
            return

        await update_task_status(message.guild, task_id, agent_name, f"✅ 完成，发往 Auditor 审核")
        await send_to_relay(
            guild=message.guild,
            from_agent=agent_name,
            to_agent="auditor",
            task_id=task_id,
            instruction=instruction,
            result=result,
            next_agent=next_agent
        )

    return client

# ── Auditor Bot ───────────────────────────────────────────

AUDITOR_SYSTEM = """你是 Auditor Agent，负责质量审核。
审核标准：只有存在明显逻辑错误、严重遗漏或完全跑题时才要求修改，小问题和风格建议不算理由。
输出格式：
1. 简要说明问题（如无重大问题则写"内容合格"）
2. 最后一行必须且只能是以下之一：
   【通过】
   【需修改】：<一句话说明核心问题>
注意：已经经历过多次修改的内容，只要基本满足要求就应该【通过】。"""

def make_auditor():
    intents = discord.Intents.default()
    intents.message_content = True
    client = ProxyClient(intents=intents)
    ai = make_ai()

    @client.event
    async def on_ready():
        print(f"Auditor Bot 上线: {client.user}")

    @client.event
    async def on_message(message):
        if message.author == client.user:
            return
        if message.channel.name != "agent-relay":
            return
        if "```json" not in message.content:
            return

        try:
            raw = message.content.split("```json")[1].split("```")[0]
            payload = json.loads(raw)
        except:
            return

        if payload.get("to") != "auditor":
            return

        task_id = payload.get("task_id")
        instruction = load_result(payload["instruction_path"]) if payload.get("instruction_path") else payload.get("instruction", "")
        from_agent = payload.get("from", "")
        next_agent = payload.get("next_agent")
        result_path = payload.get("result_path", "")
        result = load_result(result_path) if result_path else ""

        await update_task_status(message.guild, task_id, "Auditor", f"🔍 审核 {from_agent.upper()} 的成果...")

        async with message.channel.typing():
            try:
                response = await asyncio.to_thread(
                    ai.chat.completions.create,
                    model="qwen-max",
                    messages=[
                        {"role": "system", "content": AUDITOR_SYSTEM},
                        {"role": "user", "content": f"原始任务：{instruction}\n\n【这是第 {retry_count.get(f'{task_id}_{from_agent}', 0) + 1} 次提交审核】\n\n待审核内容：\n{result}"}
                    ]
                )
                audit = response.choices[0].message.content
            except Exception as e:
                audit = f"审核失败：{e}"

        audit_ch = discord.utils.get(message.guild.channels, name="audit-review")
        if audit_ch:
            await safe_send(audit_ch, f"**[{task_id}] 来自 {from_agent.upper()} 的审核：**\n\n{audit}")

        if "【需修改】" in audit:
            retries = retry_count.get(f"{task_id}_{from_agent}", 0) + 1
            retry_count[f"{task_id}_{from_agent}"] = retries
            await update_task_status(message.guild, task_id, from_agent, f"⚠️ 需修改（第 {retries} 次）")
            alert_ch = discord.utils.get(message.guild.channels, name="audit-alerts")
            if alert_ch:
                await alert_ch.send(
                    f"**[{task_id}] 审核未通过（第 {retries} 次重试）** — "
                    f"{from_agent.upper()} 的输出需要修改"
                )
            await send_to_relay(
                guild=message.guild,
                from_agent="auditor",
                to_agent=from_agent,
                task_id=task_id,
                instruction=f"{instruction}\n\n【审核反馈，请根据以下意见修改】：\n{audit}",
                result=result,
                next_agent=next_agent
            )
        else:
            retry_count.pop(f"{task_id}_{from_agent}", None)
            await update_task_status(message.guild, task_id, from_agent, f"✅ 审核通过")

            if next_agent:
                # 流水线：将当前结果传给下一个 Agent
                await update_task_status(message.guild, task_id, from_agent, f"➡️ 结果传递给 {next_agent.upper()}")
                await send_to_relay(
                    guild=message.guild,
                    from_agent=from_agent,
                    to_agent=next_agent,
                    task_id=task_id,
                    instruction=f"【来自 {from_agent.upper()} 的输出，请基于此继续完成任务】\n\n{result}",
                    result=None
                )
            else:
                completed_ch = discord.utils.get(message.guild.channels, name="completed-tasks")
                if completed_ch:
                    await completed_ch.send(
                        f"**[COMPLETE|{task_id}|{from_agent}]** {from_agent.upper()} 任务完成 ✓\n\n"
                        f"**任务：** {instruction[:80]}...\n\n"
                        f"**审核结论：** {audit[:150]}..."
                    )

    return client

# ── 启动所有 Bot ──────────────────────────────────────────

def run_bot(client, token):
    asyncio.run(client.start(token))

if __name__ == "__main__":
    bots = [
        (make_captain(), os.getenv("CAPTAIN_TOKEN")),
        (make_worker("pm"), os.getenv("PM_TOKEN")),
        (make_worker("researcher"), os.getenv("RESEARCHER_TOKEN")),
        (make_worker("analyst"), os.getenv("ANALYST_TOKEN")),
        (make_worker("dev"), os.getenv("DEV_TOKEN")),
        (make_auditor(), os.getenv("AUDITOR_TOKEN")),
    ]

    threads = []
    for client, token in bots:
        t = threading.Thread(target=run_bot, args=(client, token), daemon=True)
        t.start()
        threads.append(t)
        import time
        time.sleep(2)

    print("所有 Bot 启动中...")
    for t in threads:
        t.join()

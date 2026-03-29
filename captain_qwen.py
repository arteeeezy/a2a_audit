import asyncio
import sys
import discord
import os
import json
import uuid
from dotenv import load_dotenv
from utils import make_ai_client, make_proxy_client, send_to_relay, safe_send

if sys.platform == "win32" and sys.version_info < (3, 16):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
client = make_proxy_client(intents)
ai = make_ai_client()

SYSTEM = """你是 Captain Agent，多智能体系统的总指挥。
收到任务后用 dispatch_agents 工具分配给合适的 Agent。
可用 Agent：pm, researcher, analyst, dev
任务完成后 auditor 会自动审核。
只调用工具，不要自己直接回答。"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "dispatch_agents",
            "description": "派遣多个 Agent 并行执行子任务",
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
                                "instruction": {"type": "string"}
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

@client.event
async def on_ready():
    print(f"Captain Bot 上线: {client.user}")

@client.event
async def on_message(message):
    if message.author == client.user:
        return
    if message.channel.name != "general-input":
        return

    task_id = str(uuid.uuid4())[:8]

    async with message.channel.typing():
        try:
            response = await asyncio.to_thread(
                ai.chat.completions.create,
                model="qwen-max",
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": message.content}
                ],
                tools=TOOLS,
                tool_choice="auto"
            )
        except Exception as e:
            await message.reply(f"AI 连接失败：{e}")
            return

        msg = response.choices[0].message
        log_ch = discord.utils.get(message.guild.channels, name="captain-log")

        if msg.tool_calls:
            args = json.loads(msg.tool_calls[0].function.arguments)
            tasks = args.get("tasks", [])

            if log_ch:
                plan = "\n".join([f"- **{t['agent'].upper()}**: {t['instruction']}" for t in tasks])
                await safe_send(log_ch, f"**[{task_id}] 收到任务：** {message.content}\n\n**调度计划：**\n{plan}")

            for task in tasks:
                await send_to_relay(
                    guild=message.guild,
                    from_agent="captain",
                    to_agent=task["agent"],
                    task_id=task_id,
                    instruction=task["instruction"]
                )

            status_ch = discord.utils.get(message.guild.channels, name="task-status")
            if status_ch:
                await status_ch.send(f"**[{task_id}] 进行中** — {message.content[:60]}...")

            agents = ', '.join([t['agent'].upper() for t in tasks])
            await message.reply(f"任务 `{task_id}` 已分配给 {agents}，请稍候查看各工作频道。")
        else:
            await message.reply(msg.content or "收到，处理中...")

client.run(os.getenv("CAPTAIN_TOKEN"))
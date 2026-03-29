import asyncio
import sys
import discord
import os
import json
from dotenv import load_dotenv
from utils import make_ai_client, make_proxy_client, send_to_relay, safe_send

if sys.platform == "win32" and sys.version_info < (3, 16):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
client = make_proxy_client(intents)
ai = make_ai_client()

SYSTEM = """你是 PM Agent，负责需求分析和任务规划。
收到任务后输出：
1. 需求拆解（功能点清单）
2. 优先级排序
3. 里程碑计划
用 Markdown 格式输出。"""

@client.event
async def on_ready():
    print(f"PM Bot 上线: {client.user}")

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

    if payload.get("to") != "pm":
        return

    task_id = payload.get("task_id")
    instruction = payload.get("instruction")

    async with message.channel.typing():
        try:
            response = await asyncio.to_thread(
                ai.chat.completions.create,
                model="qwen-max",
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": instruction}
                ]
            )
            result = response.choices[0].message.content
        except Exception as e:
            result = f"执行失败：{e}"

    ws = discord.utils.get(message.guild.channels, name="pm-workspace")
    if ws:
        await safe_send(ws, f"**[{task_id}] 任务：** {instruction}\n\n{result}")

    if not result or result.startswith("执行失败"):
        error_ch = discord.utils.get(message.guild.channels, name="error-log")
        if error_ch:
            await error_ch.send(f"**[{task_id}] PM 执行失败**\n{result}")
        return

    await send_to_relay(
        guild=message.guild,
        from_agent="pm",
        to_agent="auditor",
        task_id=task_id,
        instruction=instruction,
        result=result
    )

client.run(os.getenv("PM_TOKEN"))
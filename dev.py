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

SYSTEM = """你是 Dev Agent，负责代码开发和技术实现。
收到任务后：
1. 理解需求，设计实现方案
2. 直接写出完整可运行的代码
3. 代码要有注释，说明每个关键部分的作用
4. 说明运行环境和依赖安装方法
5. 给出使用示例

要求：
- 代码必须完整，不能只写框架或伪代码
- 优先用 Python，除非任务明确要求其他语言
- 前端任务输出完整的 HTML/CSS/JS 单文件
- 数据库任务输出完整的 SQL 脚本
代码用代码块包裹。"""

@client.event
async def on_ready():
    print(f"Dev Bot 上线: {client.user}")

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

    if payload.get("to") != "dev":
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

    ws = discord.utils.get(message.guild.channels, name="dev-workspace")
    if ws:
        await safe_send(ws, f"**[{task_id}] 任务：** {instruction}\n\n{result}")

    if not result or result.startswith("执行失败"):
        error_ch = discord.utils.get(message.guild.channels, name="error-log")
        if error_ch:
            await error_ch.send(f"**[{task_id}] Dev 执行失败**\n{result}")
        return

    await send_to_relay(
        guild=message.guild,
        from_agent="dev",
        to_agent="auditor",
        task_id=task_id,
        instruction=instruction,
        result=result
    )

client.run(os.getenv("DEV_TOKEN"))
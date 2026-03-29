import asyncio
import sys
import os
import json
import httpx
from openai import OpenAI

if sys.platform == "win32" and sys.version_info < (3, 16):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

def make_ai_client():
    return OpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        http_client=httpx.Client(proxy=None),
    )

def make_proxy_client(intents):
    import discord
    from aiohttp_socks import ProxyConnector

    class ProxyClient(discord.Client):
        async def start(self, token, *, reconnect=True):
            connector = ProxyConnector.from_url("http://127.0.0.1:7890")
            self.http.connector = connector
            await super().start(token, reconnect=reconnect)

    return ProxyClient(intents=intents)

def save_result(task_id, agent, content):
    """把完整结果存到本地文件，返回文件路径"""
    folder = "D:\\a2a-agents\\results"
    os.makedirs(folder, exist_ok=True)
    path = f"{folder}\\{task_id}_{agent}.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path

def load_result(path):
    """从文件读取完整结果"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return ""

async def send_to_relay(guild, from_agent, to_agent, task_id, instruction, result=None):
    import discord
    relay_ch = discord.utils.get(guild.channels, name="agent-relay")
    if not relay_ch:
        return

    # 把完整 result 存到文件，relay 只传路径
    result_path = None
    if result:
        result_path = save_result(task_id, from_agent, result)

    payload = {
        "from": from_agent,
        "to": to_agent,
        "task_id": task_id,
        "instruction": instruction[:500] + ("...(截断)" if len(instruction) > 500 else ""),
        "result_path": result_path
    }
    msg = f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    await relay_ch.send(msg)

async def safe_send(channel, content):
    if len(content) <= 2000:
        await channel.send(content)
    else:
        chunks = [content[i:i+1900] for i in range(0, len(content), 1900)]
        for chunk in chunks:
            await channel.send(chunk)
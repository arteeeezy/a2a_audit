import discord
import aiohttp
import os
from dotenv import load_dotenv
import anthropic
from aiohttp_socks import ProxyConnector

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True

ai = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """你是 Captain Agent，一个多智能体系统的总指挥。
当用户给你任务时，你需要：
1. 分析任务需要哪些 Agent 参与（PM/Researcher/Analyst/Dev/Auditor）
2. 把任务拆解成子任务，说明每个 Agent 要做什么
3. 用清晰的格式输出你的调度计划
现在系统刚启动，你先以单 Agent 模式运行，直接回答用户问题。"""

class ProxyClient(discord.Client):
    async def setup_hook(self):
        connector = ProxyConnector.from_url("http://127.0.0.1:7890")
        session = self.http._HTTPClient__session
        await session.close()
        self.http._HTTPClient__session = aiohttp.ClientSession(
            connector=connector,
            headers={"User-Agent": self.http.user_agent},
        )

client = ProxyClient(intents=intents)

@client.event
async def on_ready():
    print(f"Captain Bot 上线: {client.user}")

@client.event
async def on_message(message):
    if message.author == client.user:
        return
    if message.channel.name != "general-input":
        return

    async with message.channel.typing():
        response = ai.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": message.content}]
        )
        reply = response.content[0].text

    log_ch = discord.utils.get(message.guild.channels, name="captain-log")
    if log_ch:
        await log_ch.send(f"**收到任务：** {message.content}\n**Captain 决策：**\n{reply}")

    await message.reply(reply)

client.run(os.getenv("CAPTAIN_TOKEN"))

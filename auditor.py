import asyncio
import sys
import discord
import os
import json
from dotenv import load_dotenv
from utils import make_ai_client, make_proxy_client, send_to_relay, safe_send, load_result

if sys.platform == "win32" and sys.version_info < (3, 16):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
client = make_proxy_client(intents)
ai = make_ai_client()

SYSTEM = """你是 Auditor Agent，负责质量审核和风险识别。
收到内容后：
1. 检查逻辑是否严谨
2. 标注潜在风险点
3. 给出改进建议
4. 最终给出 【通过】或【需修改】的结论
用 Markdown 格式输出审核报告。"""

retry_count = {}

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
    instruction = payload.get("instruction")
    from_agent = payload.get("from", "")
    result_path = payload.get("result_path", "")
    result = load_result(result_path) if result_path else ""

    async with message.channel.typing():
        try:
            response = await asyncio.to_thread(
                ai.chat.completions.create,
                model="qwen-max",
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": f"原始任务：{instruction}\n\n待审核内容：\n{result}"}
                ]
            )
            audit = response.choices[0].message.content
        except Exception as e:
            audit = f"审核失败：{e}"

    audit_ch = discord.utils.get(message.guild.channels, name="audit-review")
    if audit_ch:
        await safe_send(audit_ch, f"**[{task_id}] 来自 {from_agent.upper()} 的审核：**\n\n{audit}")

    if "需修改" in audit:
        retries = retry_count.get(f"{task_id}_{from_agent}", 0)
        if retries < 2:
            retry_count[f"{task_id}_{from_agent}"] = retries + 1

            alert_ch = discord.utils.get(message.guild.channels, name="audit-alerts")
            if alert_ch:
                await alert_ch.send(
                    f"**[{task_id}] 审核未通过（第 {retries + 1} 次重试）** — "
                    f"{from_agent.upper()} 的输出需要修改"
                )

            new_instruction = (
                f"{instruction}\n\n"
                f"【上一版内容】：\n{result}\n\n"
                f"【审核反馈，请根据以下意见修改后重新输出完整内容】：\n{audit}"
            )
            await send_to_relay(
                guild=message.guild,
                from_agent="auditor",
                to_agent=from_agent,
                task_id=task_id,
                instruction=new_instruction
            )
        else:
            error_ch = discord.utils.get(message.guild.channels, name="error-log")
            if error_ch:
                await safe_send(error_ch,
                    f"**[{task_id}] {from_agent.upper()} 多次审核未通过，已放弃重试。**\n\n"
                    f"最终审核意见：\n{audit}"
                )
    else:
        completed_ch = discord.utils.get(message.guild.channels, name="completed-tasks")
        if completed_ch:
            await completed_ch.send(
                f"**[{task_id}] {from_agent.upper()} 任务完成 ✓**\n\n"
                f"**任务：** {instruction[:80]}...\n\n"
                f"**审核结论：** {audit[:150]}..."
            )
        retry_count.pop(f"{task_id}_{from_agent}", None)

client.run(os.getenv("AUDITOR_TOKEN"))
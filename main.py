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

from meta_loop import (
    load_agent_prompt, log_eval, save_memory,
    should_trigger_meta, run_meta_loop,
)

if sys.platform == "win32" and sys.version_info < (3, 16):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

PROXY_URL = "http://127.0.0.1:7890"
RESULTS_DIR = "D:\\a2a-agents\\results"
SKILLS_DIR = "D:\\a2a-agents\\skills"
os.makedirs(RESULTS_DIR, exist_ok=True)
os.makedirs(SKILLS_DIR, exist_ok=True)

# ── 工具函数 ──────────────────────────────────────────────

def make_ai():
    if os.getenv("OPENROUTER_API_KEY"):
        return OpenAI(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api/v1",
            default_headers={"HTTP-Referer": "https://a2a-agents", "X-Title": "A2A Agents"},
        )
    return OpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        http_client=httpx.Client(proxy=None),
    )

def save_result(task_id, agent, content):
    path = f"{RESULTS_DIR}\\{task_id}_{agent}.md"
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

async def send_to_relay(guild, from_agent, to_agent, task_id, instruction, result=None, next_agent=None, skills=None):
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
        "next_agent": next_agent,
        "skills": skills or []
    }
    msg = f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    await relay_ch.send(msg)

# ── Skill 系统 ───────────────────────────────────────────
# 设计原则：节省 token
#   · Registry 只存名字+描述（几十字），给 Captain 决策用
#   · Body 按需加载，只注入本次任务用到的 skill
#   · 内存缓存避免重复读文件
#   · Skill 以独立 system message 注入，不污染 base system prompt

_skill_cache: dict[str, str] = {}  # key: "{agent}/{skill_name}" → body text

def _skill_dir(agent_name: str) -> str:
    return os.path.join(SKILLS_DIR, agent_name)

def _parse_skill_md(content: str) -> tuple[dict, str]:
    """解析 SKILL.md，返回 (frontmatter_dict, body)。"""
    frontmatter, body = {}, content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            import re
            for line in parts[1].splitlines():
                m = re.match(r"^(\w[\w-]*):\s*(.+)$", line.strip())
                if m:
                    frontmatter[m.group(1)] = m.group(2).strip()
            body = parts[2].strip()
    return frontmatter, body

def load_skills_registry(agent_name: str) -> list[dict]:
    """只读 frontmatter（name + description），极少 token，给 Captain 用。"""
    agent_dir = _skill_dir(agent_name)
    if not os.path.isdir(agent_dir):
        return []
    registry = []
    for skill_name in os.listdir(agent_dir):
        skill_file = os.path.join(agent_dir, skill_name, "SKILL.md")
        if not os.path.isfile(skill_file):
            continue
        try:
            with open(skill_file, encoding="utf-8") as f:
                fm, _ = _parse_skill_md(f.read())
            registry.append({
                "name": fm.get("name", skill_name),
                "description": fm.get("description", ""),
                "agent": agent_name,
                "key": skill_name,
            })
        except Exception:
            pass
    return registry

def load_skill_body(agent_name: str, skill_key: str) -> str:
    """按需加载 skill 目录下所有 .md 文件，合并为一份 context。

    加载顺序（节省 token 的分层逻辑）：
      SKILL.md  → 核心指令，始终加载（最小）
      REFERENCE.md / FORMS.md / 其他 .md → 补充文档，追加在后
      scripts/  → 仅列出脚本名称，不注入内容（避免大量 token）
    """
    cache_key = f"{agent_name}/{skill_key}"
    if cache_key in _skill_cache:
        return _skill_cache[cache_key]

    skill_dir_path = os.path.join(_skill_dir(agent_name), skill_key)
    if not os.path.isdir(skill_dir_path):
        return ""

    parts = []

    # 1. 优先加载 SKILL.md（核心）
    skill_md = os.path.join(skill_dir_path, "SKILL.md")
    if os.path.isfile(skill_md):
        with open(skill_md, encoding="utf-8") as f:
            _, body = _parse_skill_md(f.read())
        if body:
            parts.append(body)

    # 2. 加载其余 .md 文件（REFERENCE.md、FORMS.md 等），按文件名排序
    for fname in sorted(os.listdir(skill_dir_path)):
        if fname.upper() in ("SKILL.MD", "LICENSE.TXT") or not fname.lower().endswith(".md"):
            continue
        fpath = os.path.join(skill_dir_path, fname)
        if os.path.isfile(fpath):
            with open(fpath, encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                parts.append(f"### {fname}\n{content}")

    # 3. scripts/ 只列名，不注入代码（节省 token；Dev bot 知道它们存在即可）
    scripts_dir = os.path.join(skill_dir_path, "scripts")
    if os.path.isdir(scripts_dir):
        scripts = [f for f in os.listdir(scripts_dir) if os.path.isfile(os.path.join(scripts_dir, f))]
        if scripts:
            parts.append(f"### 可用脚本（scripts/）\n" + "\n".join(f"- {s}" for s in sorted(scripts)))

    result = "\n\n".join(parts)
    _skill_cache[cache_key] = result
    return result

def build_skills_context(agent_name: str, skill_keys: list[str]) -> str:
    """拼接本次任务需要的 skill context，作为独立 system message 注入。"""
    parts = []
    for key in skill_keys:
        body = load_skill_body(agent_name, key)
        if body:
            parts.append(f"## Skill: {key}\n{body}")
    return "\n\n".join(parts)

def build_captain_skill_summary() -> str:
    """给 Captain 看的极简技能目录（所有 agent 含 auditor/captain），只有 name+描述。"""
    lines = []
    for agent in ["captain", "pm", "researcher", "analyst", "dev", "auditor"]:
        skills = load_skills_registry(agent)
        if skills:
            lines.append(f"[{agent.upper()}] " + " | ".join(
                f"{s['key']}({s['description'][:30]})" for s in skills
            ))
    return "\n".join(lines) if lines else "（暂无已安装的 skill）"

async def search_skill_url(skill_name: str) -> str | None:
    """按 skill 名称查找 GitHub URL，优先 anthropics/skills，再搜 openclawskills.net。"""
    import httpx as _httpx
    async with _httpx.AsyncClient(timeout=10, headers={"User-Agent": "a2a-skill-installer"}) as client:
        # 1. 直接尝试 anthropics/skills 官方 repo
        api = f"https://api.github.com/repos/anthropics/skills/contents/skills/{skill_name}"
        try:
            r = await client.get(api)
            if r.status_code == 200:
                return f"https://github.com/anthropics/skills/tree/main/skills/{skill_name}"
        except Exception:
            pass

        # 2. 搜索 openclawskills.net（解析页面找匹配 skill）
        try:
            r = await client.get("https://openclawskills.net/skills", timeout=8)
            if r.status_code == 200:
                import re
                # 找页面中含 skill_name 的 GitHub tree URL
                pattern = rf"https://github\.com/[^\"'\s]+/tree/[^\"'\s]+/{re.escape(skill_name)}[\"'\s]"
                m = re.search(pattern, r.text, re.IGNORECASE)
                if m:
                    return m.group(0).strip("\"' ")
        except Exception:
            pass

    return None

async def install_skill(agent_name: str, url: str) -> str:
    """从 GitHub 目录或单个文件 URL 下载 skill，保存到对应 agent 目录。

    支持两种 URL 格式：
      · GitHub 目录页：https://github.com/{owner}/{repo}/tree/{branch}/{path}
        → 调用 GitHub Contents API 列出所有文件逐个下载
      · 直接文件 URL（raw 或普通）：以 .md / .py 结尾
        → 直接下载单个文件，推断 skill_key 为上级目录名
    """
    import httpx as _httpx
    import re

    async def _download(client, raw_url: str) -> str:
        r = await client.get(raw_url, follow_redirects=True)
        r.raise_for_status()
        return r.text

    async with _httpx.AsyncClient(timeout=20, headers={"User-Agent": "a2a-skill-installer"}) as client:

        # ── 判断是否为 GitHub 目录 URL ────────────────────────────
        gh_tree = re.match(
            r"https://github\.com/([^/]+)/([^/]+)/tree/([^/]+)/(.+)", url
        )
        if gh_tree:
            owner, repo, branch, path = gh_tree.groups()
            api = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
            try:
                resp = await client.get(api)
                resp.raise_for_status()
                entries = resp.json()
            except Exception as e:
                return f"GitHub API 请求失败：{e}"

            # 从 SKILL.md 读取 skill_key
            skill_key = path.rstrip("/").split("/")[-1]
            for entry in entries:
                if entry.get("name", "").upper() == "SKILL.MD":
                    try:
                        raw = await _download(client, entry["download_url"])
                        fm, _ = _parse_skill_md(raw)
                        skill_key = fm.get("name", skill_key).replace(" ", "-").lower()
                    except Exception:
                        pass
                    break

            save_dir = os.path.join(_skill_dir(agent_name), skill_key)
            os.makedirs(save_dir, exist_ok=True)
            downloaded, skipped = [], []

            for entry in entries:
                name = entry.get("name", "")
                etype = entry.get("type", "")
                if etype == "file":
                    try:
                        content = await _download(client, entry["download_url"])
                        fpath = os.path.join(save_dir, name)
                        with open(fpath, "w", encoding="utf-8") as f:
                            f.write(content)
                        downloaded.append(name)
                    except Exception as e:
                        skipped.append(f"{name}({e})")
                elif etype == "dir" and name == "scripts":
                    # 递归下载 scripts/ 子目录
                    sub_api = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}/{name}?ref={branch}"
                    try:
                        sub_resp = await client.get(sub_api)
                        sub_resp.raise_for_status()
                        sub_dir = os.path.join(save_dir, "scripts")
                        os.makedirs(sub_dir, exist_ok=True)
                        for sub_entry in sub_resp.json():
                            if sub_entry.get("type") == "file":
                                sub_content = await _download(client, sub_entry["download_url"])
                                with open(os.path.join(sub_dir, sub_entry["name"]), "w", encoding="utf-8") as f:
                                    f.write(sub_content)
                                downloaded.append(f"scripts/{sub_entry['name']}")
                    except Exception as e:
                        skipped.append(f"scripts/({e})")

            _skill_cache.pop(f"{agent_name}/{skill_key}", None)
            msg = f"✅ skill `{skill_key}` 已安装到 {agent_name}，共下载 {len(downloaded)} 个文件：{', '.join(downloaded)}"
            if skipped:
                msg += f"\n⚠️ 跳过：{', '.join(skipped)}"
            return msg

        # ── 单文件 URL ────────────────────────────────────────────
        try:
            # 将 github.com/blob/ 转为 raw URL
            raw_url = re.sub(r"github\.com/([^/]+/[^/]+)/blob/", r"raw.githubusercontent.com/\1/", url)
            content = await _download(client, raw_url)
        except Exception as e:
            return f"下载失败：{e}"

        fm, _ = _parse_skill_md(content)
        skill_key = fm.get("name", url.rstrip("/").split("/")[-2]).replace(" ", "-").lower()
        fname = url.rstrip("/").split("/")[-1]

        save_dir = os.path.join(_skill_dir(agent_name), skill_key)
        os.makedirs(save_dir, exist_ok=True)
        with open(os.path.join(save_dir, fname), "w", encoding="utf-8") as f:
            f.write(content)

        _skill_cache.pop(f"{agent_name}/{skill_key}", None)
        return f"✅ 文件 `{fname}` 已安装到 {agent_name}/skills/{skill_key}/"

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

def build_captain_system() -> str:
    skill_summary = build_captain_skill_summary()
    captain_skills = load_skills_registry("captain")
    captain_ctx = build_skills_context("captain", [s["key"] for s in captain_skills]) if captain_skills else ""
    extra = f"\n\n# Captain 自身 Skills\n{captain_ctx}" if captain_ctx else ""
    return f"""你是 Captain Agent，多智能体系统的总指挥。

## 执行任务
用 dispatch_agents 工具分配给合适的 Agent。
可用 Agent：pm, researcher, analyst, dev（完成后 auditor 自动审核）
可以用 next_agent 设置流水线（如 researcher → analyst）。
如果 Agent 有合适的 skill，在 tasks 里带上 skills 字段激活它。

## 安装 Skill
用户提到"安装/install skill"时，使用 install_skill 工具。
- 未指定 agent → 根据 skill 的用途判断最合适的 agent（可同时安装给多个）
- 指定了 agent → 直接安装给该 agent
- 可用 agent：pm, researcher, analyst, dev, auditor, captain

## 已安装 Skill 目录
{skill_summary}
{extra}
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
                                },
                                "skills": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "可选，为该 Agent 激活的 skill key 列表"
                                }
                            },
                            "required": ["agent", "instruction"]
                        }
                    }
                },
                "required": ["tasks"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "install_skill",
            "description": "为一个或多个 Agent 安装 skill。用户说'安装xxx skill'时调用。未指定 agent 则根据 skill 用途自行判断。",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill": {
                        "type": "string",
                        "description": "skill 名称（如 'pdf'、'web-search'）或完整 GitHub URL"
                    },
                    "agents": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["pm", "researcher", "analyst", "dev", "auditor", "captain"]
                        },
                        "description": "要安装的目标 agent 列表。用户未指定时由 Captain 根据 skill 用途决定。"
                    },
                    "reason": {
                        "type": "string",
                        "description": "选择这些 agent 的理由（用户未指定 agent 时必填）"
                    }
                },
                "required": ["skill", "agents"]
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
                next_agent=task.get("next_agent"),
                skills=task.get("skills", [])
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
                        model=os.getenv("AI_MODEL", "qwen-max"),
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

        # AI 调度（dispatch_agents 或 install_skill）
        async with message.channel.typing():
            try:
                response = await asyncio.to_thread(
                    ai.chat.completions.create,
                    model=os.getenv("AI_MODEL", "qwen-max"),
                    messages=[
                        {"role": "system", "content": build_captain_system()},
                        {"role": "user", "content": message.content}
                    ],
                    tools=CAPTAIN_TOOLS,
                    tool_choice="auto"
                )
            except Exception as e:
                await message.reply(f"AI 连接失败：{e}")
                return

        msg = response.choices[0].message
        if not msg.tool_calls:
            # AI 没有调用工具，直接回复内容作为最终结果
            final_content = msg.content or "收到，处理中..."
            await safe_send(message.channel, f"**[{task_id}] Captain 直接回复：**\n\n{final_content}")
            await update_task_status(message.guild, task_id, "Captain", f"✅ 已完成（直接回复）")
            return

        tool_name = msg.tool_calls[0].function.name
        args = json.loads(msg.tool_calls[0].function.arguments)

        if tool_name == "dispatch_agents":
            await _dispatch(message, task_id, args.get("tasks", []))

        elif tool_name == "install_skill":
            skill_input = args.get("skill", "")
            agents = args.get("agents", [])
            reason = args.get("reason", "")

            # 判断是名称还是 URL
            if skill_input.startswith("http"):
                url = skill_input
            else:
                await message.reply(f"🔍 正在查找 skill `{skill_input}`...")
                url = await search_skill_url(skill_input)
                if not url:
                    await message.reply(f"❌ 找不到 skill `{skill_input}`，请提供完整 GitHub URL。")
                    return

            if reason:
                await message.reply(f"🤖 Captain 判断：{reason}")

            results = []
            for agent in agents:
                await message.reply(f"⏳ 正在为 **{agent.upper()}** 安装 `{skill_input}`...")
                result_msg = await install_skill(agent, url)
                results.append(result_msg)

            await message.reply("\n".join(results))

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
        skill_keys = payload.get("skills", [])

        # 如果是 auditor 发来的重试，读取原始完整内容
        result_path = payload.get("result_path")
        if result_path:
            prev_result = load_result(result_path)
            instruction = instruction + f"\n\n【上一版完整内容】：\n{prev_result}"

        await update_task_status(message.guild, task_id, agent_name, f"🔄 开始处理...")

        # 按需加载 skill，作为独立 system message 注入（不污染 base system prompt）
        # 节省 token：只加载本次任务指定的 skill，其余 skill body 不消耗任何 token
        messages = [{"role": "system", "content": load_agent_prompt(agent_name, config["system"])}]
        if skill_keys:
            skills_ctx = build_skills_context(agent_name, skill_keys)
            if skills_ctx:
                messages.append({"role": "system", "content": f"# 本次任务可用的 Skills\n\n{skills_ctx}"})
        messages.append({"role": "user", "content": instruction})

        async with message.channel.typing():
            try:
                response = await asyncio.to_thread(
                    ai.chat.completions.create,
                    model=os.getenv("AI_MODEL", "qwen-max"),
                    messages=messages
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
        skill_keys = payload.get("skills", [])
        result_path = payload.get("result_path", "")
        result = load_result(result_path) if result_path else ""

        await update_task_status(message.guild, task_id, "Auditor", f"🔍 审核 {from_agent.upper()} 的成果...")

        # Auditor 也支持 skill：加载 auditor 自己目录的 skill + worker 使用的相同 skill
        # 这样 auditor 能用与 worker 相同的知识背景来评判输出质量
        messages_audit = [{"role": "system", "content": AUDITOR_SYSTEM}]
        auditor_skills_ctx = build_skills_context("auditor", load_skills_registry("auditor") and
                                                  [s["key"] for s in load_skills_registry("auditor")] or [])
        worker_skills_ctx = build_skills_context(from_agent, skill_keys) if skill_keys else ""
        combined_ctx = "\n\n".join(filter(None, [auditor_skills_ctx, worker_skills_ctx]))
        if combined_ctx:
            messages_audit.append({"role": "system", "content": f"# 审核参考 Skills\n\n{combined_ctx}"})
        messages_audit.append({"role": "user", "content": f"原始任务：{instruction}\n\n【这是第 {retry_count.get(f'{task_id}_{from_agent}', 0) + 1} 次提交审核】\n\n待审核内容：\n{result}"})

        async with message.channel.typing():
            try:
                response = await asyncio.to_thread(
                    ai.chat.completions.create,
                    model=os.getenv("AI_MODEL", "qwen-max"),
                    messages=messages_audit
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
            final_retries = retry_count.pop(f"{task_id}_{from_agent}", 0)
            await update_task_status(message.guild, task_id, from_agent, f"✅ 审核通过")

            # ── HyperAgent：记录 eval + 持久记忆 ─────────────────
            log_eval(task_id, from_agent, success=True, retries=final_retries,
                     instruction_preview=instruction[:120])
            save_memory(task_id, from_agent, instruction, retries=final_retries, success=True)

            # 每 META_TRIGGER_N 次通过后触发元循环
            if should_trigger_meta():
                meta_ch = discord.utils.get(message.guild.channels, name="meta-log")
                async def _notify(msg):
                    if meta_ch:
                        await safe_send(meta_ch, msg)
                default_prompts = {k: v["system"] for k, v in AGENT_CONFIG.items()}
                asyncio.create_task(run_meta_loop(
                    agents=list(AGENT_CONFIG.keys()),
                    default_prompts=default_prompts,
                    ai_client=ai,
                    notify_fn=_notify,
                ))

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

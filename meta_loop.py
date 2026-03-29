"""
meta_loop.py — HyperAgent 元循环
对应论文映射：
  - Editable program    → prompt_store.json（版本化 prompt）
  - Meta agent          → run_meta_loop()（读 eval → AI 优化 → 写回）
  - Archive             → prompt_store.json 的 history 列表
  - Eval results        → eval_log.jsonl
  - Persistent memory   → memory.json（成功/失败案例）
  - Skills library      → skills/（可复用的成功经验）
"""
import json
import os
import asyncio
import uuid
from datetime import datetime

PROMPT_STORE_PATH = "D:/a2a-agents/prompt_store.json"
EVAL_LOG_PATH     = "D:/a2a-agents/eval_log.jsonl"
MEMORY_PATH       = "D:/a2a-agents/memory.json"
SKILLS_DIR        = "D:/a2a-agents/skills"
META_TRIGGER_N      = 5    # 每累计 N 次审核通过后触发一次元循环
SCORE_THRESHOLD     = 0.75 # 低于此分才触发 prompt 优化
META_META_TRIGGER_N = 3    # 每触发 N 次元循环后，执行一次元认知自我修改
META_PROMPT_STORE   = "D:/a2a-agents/meta_prompt_store.json"

_meta_loop_count = 0  # 当前进程内元循环触发次数

# 确保技能库目录存在
os.makedirs(SKILLS_DIR, exist_ok=True)
for agent_dir in ["captain", "pm", "researcher", "analyst", "developer", "auditor"]:
    os.makedirs(os.path.join(SKILLS_DIR, agent_dir), exist_ok=True)

# ── Prompt Store ──────────────────────────────────────────

def load_prompt_store() -> dict:
    if os.path.exists(PROMPT_STORE_PATH):
        with open(PROMPT_STORE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}

def _save_prompt_store(store: dict):
    with open(PROMPT_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)

def load_agent_prompt(agent_name: str, default: str) -> str:
    """从 prompt_store 读当前 prompt；若无记录则返回默认值（不写入）。"""
    return load_prompt_store().get(agent_name, {}).get("current", default)

def _archive_and_write_prompt(agent_name: str, new_prompt: str, old_score: float) -> int:
    """将旧 prompt 归档，写入新 prompt，返回新版本号。"""
    store = load_prompt_store()
    entry = store.get(agent_name, {"current": new_prompt, "version": 0, "history": []})
    entry["history"].append({
        "version": entry["version"],
        "prompt": entry["current"],
        "score": old_score,
        "archived_at": datetime.now().isoformat(),
    })
    entry["version"] += 1
    entry["current"] = new_prompt
    store[agent_name] = entry
    _save_prompt_store(store)
    return entry["version"]

def rollback_prompt(agent_name: str, version: int) -> str:
    """回滚到指定版本，返回回滚后的 prompt。"""
    store = load_prompt_store()
    entry = store.get(agent_name)
    if not entry:
        return "未找到该 agent 的 prompt 记录"
    history = entry.get("history", [])
    match = next((h for h in history if h["version"] == version), None)
    if not match:
        return f"未找到版本 v{version}，可用版本：{[h['version'] for h in history]}"
    # 把当前归档，写入目标版本
    new_version = _archive_and_write_prompt(agent_name, match["prompt"], old_score=0.0)
    return f"✅ {agent_name.upper()} 已回滚到 v{version}（当前为 v{new_version}）"

# ── Eval Log ──────────────────────────────────────────────

def log_eval(task_id: str, agent: str, success: bool, retries: int, instruction_preview: str = ""):
    """审核完成时追加一条记录到 eval_log.jsonl。"""
    record = {
        "task_id": task_id,
        "agent": agent,
        "timestamp": datetime.now().isoformat(),
        "success": success,
        "audit_retries": retries,
        "instruction_preview": instruction_preview[:120],
    }
    with open(EVAL_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

def _read_recent_evals(agent_name: str, last_n: int = 20) -> list:
    if not os.path.exists(EVAL_LOG_PATH):
        return []
    records = []
    with open(EVAL_LOG_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                if r.get("agent") == agent_name:
                    records.append(r)
            except Exception:
                pass
    return records[-last_n:]

def _count_total_evals() -> int:
    if not os.path.exists(EVAL_LOG_PATH):
        return 0
    count = 0
    with open(EVAL_LOG_PATH, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count

def should_trigger_meta() -> bool:
    """每累计 META_TRIGGER_N 条 eval 记录触发一次。"""
    total = _count_total_evals()
    return total > 0 and total % META_TRIGGER_N == 0

def _compute_score(evals: list) -> float:
    """综合评分：成功=1分，每次重试扣 0.25 分，失败基础 0.3 分。"""
    if not evals:
        return 0.0
    total = sum(
        (1.0 if e["success"] else 0.3) - 0.25 * e.get("audit_retries", 0)
        for e in evals
    )
    return round(max(0.0, total / len(evals)), 3)

# ── Persistent Memory ─────────────────────────────────────

def save_memory(task_id: str, agent: str, instruction: str, retries: int, success: bool):
    """保存任务案例到 memory.json（成功/失败各保留最近 50 条）。"""
    memory: dict = {}
    if os.path.exists(MEMORY_PATH):
        try:
            with open(MEMORY_PATH, encoding="utf-8") as f:
                memory = json.load(f)
        except Exception:
            memory = {}

    key = "success_cases" if success else "failure_cases"
    memory.setdefault(key, []).append({
        "task_id": task_id,
        "agent": agent,
        "instruction_preview": instruction[:150],
        "audit_retries": retries,
        "timestamp": datetime.now().isoformat(),
    })
    memory[key] = memory[key][-50:]

    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)

# ── Meta Loop ─────────────────────────────────────────────

_DEFAULT_META_PROMPT = """你是 Meta-Captain，负责通过分析任务数据来优化各 Agent 的 system prompt。

当前 {agent} Agent 的 system prompt：
---
{current_prompt}
---

近 {n} 次任务表现：
- 成功率：{success_rate:.0%}
- 平均审核重试次数：{avg_retries:.1f}
- 综合评分：{score}（满分约 1.0，低于 {threshold} 触发优化）

最近任务样本（含失败案例）：
{samples}

请分析该 agent 表现不佳的可能原因，输出一个改进后的 system prompt。
要求：
1. 保持原有角色定位（{agent}）不变
2. 针对高重试率/低成功率做出具体改进，例如：更清晰的输出格式要求、更严格的质量标准、更好的任务分解指引
3. 直接输出新 prompt 文本，不要任何解释、标题或引号"""

# ── 元认知层：meta_prompt 的持久化存储与自修改 ─────────────

def _load_meta_prompt() -> str:
    """从 meta_prompt_store.json 读当前 meta prompt；不存在则用默认值。"""
    if os.path.exists(META_PROMPT_STORE):
        try:
            with open(META_PROMPT_STORE, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("current", _DEFAULT_META_PROMPT)
        except Exception:
            pass
    return _DEFAULT_META_PROMPT

def _archive_meta_prompt(new_meta_prompt: str, effectiveness: float):
    """将旧 meta prompt 归档，写入新版本。"""
    data: dict = {"current": _DEFAULT_META_PROMPT, "version": 0, "history": []}
    if os.path.exists(META_PROMPT_STORE):
        try:
            with open(META_PROMPT_STORE, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    data["history"].append({
        "version": data["version"],
        "prompt": data["current"],
        "effectiveness": effectiveness,
        "archived_at": datetime.now().isoformat(),
    })
    data["version"] += 1
    data["current"] = new_meta_prompt
    with open(META_PROMPT_STORE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data["version"]

# 二阶元提示：用于让 AI 评估并重写 _META_PROMPT 自身
_META_META_PROMPT = """你是 HyperAgent 的元认知层，负责评估并改进 Meta-Captain 的"优化策略"本身。

当前 Meta-Captain 使用的优化提示模板（即它如何分析和改进 agent prompt）：
---
{current_meta_prompt}
---

过去 {n} 次元循环的优化效果数据（score_before → score_after）：
{effectiveness_records}

综合有效率：{avg_effectiveness:.0%}（优化后分数提升的比例）

请判断当前优化模板的不足之处，并输出一个更好的模板。
模板必须保留以下占位符（原样保留，不要修改）：
  {{agent}}, {{current_prompt}}, {{n}}, {{success_rate}}, {{avg_retries}}, {{score}}, {{threshold}}, {{samples}}
改进方向示例：
- 让 Meta-Captain 关注失败案例的模式而非单纯重写
- 要求它给出改动理由，形成可追溯的优化链
- 增加"不要改动已经有效的部分"的约束
直接输出新模板文本，不要任何解释或引号。"""


async def run_meta_loop(
    agents: list,
    default_prompts: dict,
    ai_client,
    notify_fn=None,
):
    """
    一阶元循环：分析 eval_log → 用当前 meta_prompt 优化 agent prompt → 归档。
    每触发 META_META_TRIGGER_N 次后，额外执行二阶元循环（自我修改 meta_prompt）。
    """
    global _meta_loop_count
    _meta_loop_count += 1

    if notify_fn:
        await notify_fn(f"🔄 **Meta Loop #{_meta_loop_count} 触发** — 开始分析各 Agent 表现...")

    current_meta_prompt = _load_meta_prompt()
    effectiveness_records = []  # 记录本轮优化前后的分数变化

    for agent in agents:
        evals = _read_recent_evals(agent, last_n=20)
        if len(evals) < 3:
            continue

        score_before = _compute_score(evals)
        if score_before >= SCORE_THRESHOLD:
            if notify_fn:
                await notify_fn(f"✅ [{agent.upper()}] 评分 {score_before} 达标，无需优化")
            continue

        current_prompt = load_agent_prompt(agent, default_prompts.get(agent, ""))
        success_rate   = sum(1 for e in evals if e["success"]) / len(evals)
        avg_retries    = sum(e.get("audit_retries", 0) for e in evals) / len(evals)
        samples        = json.dumps(evals[-5:], ensure_ascii=False, indent=2)

        prompt = current_meta_prompt.format(
            agent=agent.upper(),
            current_prompt=current_prompt,
            n=len(evals),
            success_rate=success_rate,
            avg_retries=avg_retries,
            score=score_before,
            threshold=SCORE_THRESHOLD,
            samples=samples,
        )

        try:
            resp = await asyncio.to_thread(
                ai_client.chat.completions.create,
                model=os.getenv("AI_MODEL", "qwen-max"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )
            new_prompt = resp.choices[0].message.content.strip()
            version = _archive_and_write_prompt(agent, new_prompt, old_score=score_before)
            effectiveness_records.append({
                "agent": agent,
                "score_before": score_before,
                "score_after": None,  # 下轮 meta loop 才能知道
                "version": version,
                "timestamp": datetime.now().isoformat(),
            })
            if notify_fn:
                await notify_fn(
                    f"🧬 **[{agent.upper()}]** prompt 优化至 v{version} "
                    f"（旧评分 {score_before} < {SCORE_THRESHOLD}）"
                )
        except Exception as e:
            if notify_fn:
                await notify_fn(f"⚠️ Meta Loop [{agent.upper()}] 优化失败：{e}")

    # ── 二阶元循环：评估 meta_prompt 自身的有效性并自我修改 ───────
    if _meta_loop_count % META_META_TRIGGER_N == 0:
        await _run_meta_meta_loop(ai_client, notify_fn)


async def _run_meta_meta_loop(ai_client, notify_fn=None):
    """
    二阶元循环（元认知自我修改）：
    分析历史优化记录 → 评估 _META_PROMPT 是否有效 → 重写自身。
    对应论文："Meta agent 修改自身"。
    """
    if notify_fn:
        await notify_fn("🧠 **Meta-Meta Loop 触发** — 评估优化策略自身的有效性...")

    # 从 prompt_store 读各 agent 的历史版本，计算 meta_prompt 的有效率
    store = load_prompt_store()
    effectiveness_records = []
    for agent, entry in store.items():
        history = entry.get("history", [])
        for i in range(len(history) - 1):
            before = history[i].get("score", 0)
            after  = history[i + 1].get("score", 0)
            effectiveness_records.append(
                f"{agent.upper()} v{history[i]['version']}: {before:.2f} → {after:.2f} "
                f"({'↑' if after > before else '↓ 未改善'})"
            )

    if len(effectiveness_records) < 2:
        if notify_fn:
            await notify_fn("⏭️ Meta-Meta Loop：历史优化记录不足，跳过")
        return

    improved = sum(1 for r in effectiveness_records if "↑" in r)
    avg_effectiveness = improved / len(effectiveness_records)
    current_meta_prompt = _load_meta_prompt()

    meta_meta_prompt = _META_META_PROMPT.format(
        current_meta_prompt=current_meta_prompt,
        n=len(effectiveness_records),
        effectiveness_records="\n".join(effectiveness_records[-10:]),
        avg_effectiveness=avg_effectiveness,
    )

    try:
        resp = await asyncio.to_thread(
            ai_client.chat.completions.create,
            model=os.getenv("AI_MODEL", "qwen-max"),
            messages=[{"role": "user", "content": meta_meta_prompt}],
            temperature=0.8,
        )
        new_meta_prompt = resp.choices[0].message.content.strip()

        # 验证占位符完整性，防止 AI 漏掉关键变量
        required = ["{agent}", "{current_prompt}", "{n}", "{score}", "{samples}"]
        missing = [p for p in required if p not in new_meta_prompt]
        if missing:
            if notify_fn:
                await notify_fn(f"⚠️ Meta-Meta Loop：新模板缺少占位符 {missing}，已放弃本次修改")
            return

        version = _archive_meta_prompt(new_meta_prompt, effectiveness=avg_effectiveness)
        if notify_fn:
            await notify_fn(
                f"🔬 **Meta-Meta Loop 完成** — meta_prompt 自我改写至 v{version}\n"
                f"历史有效率 {avg_effectiveness:.0%}（{improved}/{len(effectiveness_records)} 次优化后分数提升）"
            )
    except Exception as e:
        if notify_fn:
            await notify_fn(f"⚠️ Meta-Meta Loop 失败：{e}")


# ── Skills Library ────────────────────────────────────────

async def extract_skill(
    task_id: str,
    agent: str,
    instruction: str,
    result: str,
    ai_client,
    notify_fn=None
) -> str:
    """
    从成功案例中提取可复用的技能
    
    Args:
        task_id: 任务ID
        agent: Agent名称
        instruction: 任务描述
        result: 解决方案
        ai_client: AI客户端
        notify_fn: 通知函数
    
    Returns:
        技能文件路径
    """
    extraction_prompt = f"""分析以下成功完成的任务，提取可复用的解决模式。

任务类型：{agent.upper()}
任务描述：{instruction[:500]}
解决方案：{result[:1000]}

请提取：
1. task_type: 任务类型（如"API集成"、"数据分析"、"代码审查"等，简短精确）
2. steps: 关键步骤（3-5个要点，每个要点一句话）
3. template: 可复用的代码片段或解决方案模板（如果适用）
4. notes: 注意事项和最佳实践

输出严格的 JSON 格式，不要任何其他文字：
{{
  "task_type": "任务类型",
  "steps": ["步骤1", "步骤2", "步骤3"],
  "template": "模板内容（如无则为空字符串）",
  "notes": "注意事项"
}}"""

    try:
        resp = await asyncio.to_thread(
            ai_client.chat.completions.create,
            model=os.getenv("AI_MODEL", "qwen-max"),
            messages=[{"role": "user", "content": extraction_prompt}],
            temperature=0.3,
        )
        content = resp.choices[0].message.content.strip()
        
        # 尝试解析 JSON（可能包含 markdown 代码块）
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        
        skill_data = json.loads(content)
        
        # 生成技能名称（符合 Claude Code 标准：小写、连字符、最多64字符）
        task_type = skill_data.get("task_type", "未分类")
        skill_name = task_type.lower().replace(' ', '-').replace('_', '-')
        skill_name = ''.join(c for c in skill_name if c.isalnum() or c == '-')
        skill_name = skill_name[:64]  # 最多64字符
        
        # 创建技能目录（Claude Code 标准格式）
        skill_dir = os.path.join(SKILLS_DIR, agent, skill_name)
        
        # 如果目录已存在，添加后缀
        if os.path.exists(skill_dir):
            counter = 1
            while os.path.exists(f"{skill_dir}-{counter}"):
                counter += 1
            skill_dir = f"{skill_dir}-{counter}"
            skill_name = f"{skill_name}-{counter}"
        
        os.makedirs(skill_dir, exist_ok=True)
        os.makedirs(os.path.join(skill_dir, "examples"), exist_ok=True)
        
        # 创建 SKILL.md（Claude Code 标准格式）
        steps_text = ""
        if skill_data.get("steps"):
            steps_text = "\n\n## Steps\n\n"
            steps_text += "\n".join(f"{i+1}. {step}" for i, step in enumerate(skill_data["steps"]))
        
        template_section = ""
        if skill_data.get("template"):
            template_section = f"\n\n## Template\n\n```\n{skill_data['template']}\n```"
        
        notes_section = ""
        if skill_data.get("notes"):
            notes_section = f"\n\n## Notes\n\n{skill_data['notes']}"
        
        skill_md_content = f"""---
name: {skill_name}
description: {task_type[:250]}
---

# {task_type}

从任务 {task_id} 中提取的成功经验。
{steps_text}
{template_section}
{notes_section}
"""
        
        skill_md_path = os.path.join(skill_dir, "SKILL.md")
        with open(skill_md_path, "w", encoding="utf-8") as f:
            f.write(skill_md_content)
        
        # 创建 template.md（如果有独立模板）
        if skill_data.get("template"):
            template_path = os.path.join(skill_dir, "template.md")
            with open(template_path, "w", encoding="utf-8") as f:
                f.write(skill_data["template"])
        
        # 创建 metadata.json
        metadata = {
            "id": skill_name,
            "name": skill_name,
            "agent": agent,
            "source_task_id": task_id,
            "created_at": datetime.now().isoformat(),
            "usage_count": 0,
            "success_count": 0,
            "last_used": None
        }
        
        metadata_path = os.path.join(skill_dir, "metadata.json")
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        if notify_fn:
            await notify_fn(
                f"📚 **[{agent.upper()}]** 提取新技能：{task_type} ({skill_name})"
            )
        
        return skill_dir
        
    except Exception as e:
        if notify_fn:
            await notify_fn(f"⚠️ 技能提取失败 [{agent.upper()}]：{e}")
        return ""


def retrieve_relevant_skills(agent: str, instruction: str, top_k: int = 3) -> list:
    """
    检索与当前任务相关的技能
    
    Args:
        agent: Agent名称
        instruction: 任务描述
        top_k: 返回前k个最相关的技能
    
    Returns:
        技能列表
    """
    agent_skills_dir = os.path.join(SKILLS_DIR, agent)
    if not os.path.exists(agent_skills_dir):
        return []
    
    all_skills = []
    
    # 加载该 agent 的所有技能（新格式：目录结构）
    for skill_name in os.listdir(agent_skills_dir):
        skill_dir = os.path.join(agent_skills_dir, skill_name)
        if not os.path.isdir(skill_dir):
            continue
        
        try:
            # 读取 SKILL.md
            skill_md_path = os.path.join(skill_dir, "SKILL.md")
            if not os.path.exists(skill_md_path):
                continue
            
            with open(skill_md_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            # 解析 frontmatter
            frontmatter = {}
            skill_content = content
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    import re
                    for line in parts[1].splitlines():
                        m = re.match(r"^(\w[\w-]*):\s*(.+)$", line.strip())
                        if m:
                            frontmatter[m.group(1)] = m.group(2).strip()
                    skill_content = parts[2].strip()
            
            # 读取 metadata.json
            metadata_path = os.path.join(skill_dir, "metadata.json")
            metadata = {}
            if os.path.exists(metadata_path):
                with open(metadata_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
            
            # 构建技能对象
            skill = {
                "id": skill_name,
                "name": frontmatter.get("name", skill_name),
                "description": frontmatter.get("description", ""),
                "content": skill_content,
                "usage_count": metadata.get("usage_count", 0),
                "success_count": metadata.get("success_count", 0),
            }
            
            all_skills.append(skill)
        except Exception:
            continue
    
    if not all_skills:
        return []
    
    # 简单的关键词匹配评分（TODO: 未来可以使用 embedding 向量相似度）
    instruction_lower = instruction.lower()
    scored_skills = []
    
    for skill in all_skills:
        score = 0.0
        description_lower = skill.get("description", "").lower()
        content_lower = skill.get("content", "").lower()
        
        # 描述匹配（权重最高）
        if description_lower in instruction_lower:
            score += 10.0
        
        # 关键词匹配
        for word in description_lower.split():
            if len(word) > 2 and word in instruction_lower:
                score += 2.0
        
        # 内容关键词匹配
        for word in content_lower.split():
            if len(word) > 4 and word in instruction_lower:
                score += 0.3
        
        # 使用频率加权（使用越多，越可能有用）
        usage_count = skill.get("usage_count", 0)
        if usage_count > 0:
            success_rate = skill.get("success_count", 0) / usage_count
            score += success_rate * 3.0
        
        scored_skills.append((score, skill))
    
    # 排序并返回 top-k
    scored_skills.sort(reverse=True, key=lambda x: x[0])
    return [skill for score, skill in scored_skills[:top_k] if score > 0]


def inject_skills_to_prompt(base_prompt: str, skills: list) -> str:
    """
    将技能注入到 agent 的系统提示词中
    
    Args:
        base_prompt: 基础系统提示词
        skills: 技能列表
    
    Returns:
        注入技能后的提示词
    """
    if not skills:
        return base_prompt
    
    skills_section = "\n\n" + "="*60 + "\n"
    skills_section += "# Available Skills\n"
    skills_section += "="*60 + "\n\n"
    skills_section += "You have access to the following skills from past successful cases:\n\n"
    
    for i, skill in enumerate(skills, 1):
        skill_name = skill.get('name', skill.get('id', '未知'))
        description = skill.get('description', '')
        content = skill.get('content', '')
        
        skills_section += f"## Skill {i}: {skill_name}\n\n"
        
        if description:
            skills_section += f"**Description**: {description}\n\n"
        
        if content:
            skills_section += content + "\n\n"
        
        usage_count = skill.get("usage_count", 0)
        if usage_count > 0:
            success_rate = skill.get("success_count", 0) / usage_count
            skills_section += f"*（Used {usage_count} times, success rate {success_rate:.0%}）*\n\n"
        
        skills_section += "---\n\n"
    
    return base_prompt + skills_section


def update_skill_usage(skill_id: str, agent: str, success: bool):
    """
    更新技能的使用统计（新格式：目录结构）
    
    Args:
        skill_id: 技能ID（即技能目录名）
        agent: Agent名称
        success: 是否成功
    """
    # 新格式：skill_id 是目录名
    skill_dir = os.path.join(SKILLS_DIR, agent, skill_id)
    metadata_path = os.path.join(skill_dir, "metadata.json")
    
    if not os.path.exists(metadata_path):
        return
    
    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        
        metadata["usage_count"] = metadata.get("usage_count", 0) + 1
        if success:
            metadata["success_count"] = metadata.get("success_count", 0) + 1
        
        metadata["last_used"] = datetime.now().isoformat()
        
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def cleanup_low_quality_skills(min_uses: int = 5, min_success_rate: float = 0.3):
    """
    清理低质量的技能（新格式：目录结构）
    
    Args:
        min_uses: 最少使用次数阈值
        min_success_rate: 最低成功率阈值
    """
    removed_count = 0
    
    for agent_dir in os.listdir(SKILLS_DIR):
        agent_path = os.path.join(SKILLS_DIR, agent_dir)
        if not os.path.isdir(agent_path):
            continue
        
        for skill_name in os.listdir(agent_path):
            skill_dir = os.path.join(agent_path, skill_name)
            if not os.path.isdir(skill_dir):
                continue
            
            metadata_path = os.path.join(skill_dir, "metadata.json")
            if not os.path.exists(metadata_path):
                continue
            
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                
                usage_count = metadata.get("usage_count", 0)
                if usage_count >= min_uses:
                    success_rate = metadata.get("success_count", 0) / usage_count
                    if success_rate < min_success_rate:
                        import shutil
                        shutil.rmtree(skill_dir)
                        removed_count += 1
            except Exception:
                continue
    
    return removed_count

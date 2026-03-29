"""
skill_web_learning.py - 从网站学习技能的功能模块

实现从网站抓取内容、解析技能文档、Captain 分配和导入技能的完整流程
"""
import asyncio
import json
import os
import uuid
import httpx
from datetime import datetime
from bs4 import BeautifulSoup

from meta_loop import (
    retrieve_relevant_skills,
    SKILLS_DIR
)


def safe_notify_text(text: str) -> str:
    """移除 emoji 以避免编码问题"""
    # 移除常见 emoji
    emoji_map = {
        "🔍": "[FETCH]",
        "📄": "[PARSE]",
        "✅": "[OK]",
        "⚠️": "[WARN]",
        "📋": "[ASSIGN]",
        "🔄": "[UPDATE]",
        "✨": "[NEW]",
        "🎉": "[DONE]",
        "❌": "[ERROR]",
    }
    for emoji, replacement in emoji_map.items():
        text = text.replace(emoji, replacement)
    return text


async def fetch_website_content(url: str, timeout: int = 30) -> str:
    """
    抓取网站内容
    
    Args:
        url: 网站URL
        timeout: 超时时间（秒）
    
    Returns:
        网站的文本内容
    """
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        
        # 使用 BeautifulSoup 解析 HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 移除 script 和 style 标签
        for script in soup(["script", "style"]):
            script.decompose()
        
        # 获取文本内容
        text = soup.get_text()
        
        # 清理空白
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)
        
        return text


async def parse_skill_documents(content: str, ai_client) -> list[dict]:
    """
    从网站内容中提取技能文档
    
    Args:
        content: 网站内容
        ai_client: AI 客户端
    
    Returns:
        技能文档列表
    """
    # 限制内容长度
    max_length = 8000
    if len(content) > max_length:
        content = content[:max_length] + "\n\n... (内容已截断)"
    
    prompt = f"""分析以下网站内容，提取所有技能相关的文档。

网站内容：
{content}

请提取：
1. 每个技能的标题
2. 技能描述（简短，1-2句话）
3. 技能详细内容（步骤、示例、注意事项）
4. 技能类别（从以下选择：developer, researcher, analyst, pm, auditor, captain）

输出严格的 JSON 格式（不要任何其他文字）：
[
  {{
    "title": "技能标题",
    "description": "简短描述",
    "content": "详细内容",
    "category": "developer"
  }}
]

如果没有找到技能相关内容，返回空数组 []
"""
    
    response = await asyncio.to_thread(
        ai_client.chat.completions.create,
        model=os.getenv("AI_MODEL", "qwen-max"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    
    content = response.choices[0].message.content.strip()
    
    # 解析 JSON
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()
    
    try:
        skill_docs = json.loads(content)
        return skill_docs if isinstance(skill_docs, list) else []
    except json.JSONDecodeError:
        return []


async def captain_assign_skills(skill_docs: list[dict], ai_client) -> dict:
    """
    Captain 分析技能文档并分配给合适的 Agent
    
    Args:
        skill_docs: 技能文档列表
        ai_client: AI 客户端
    
    Returns:
        分配结果
    """
    if not skill_docs:
        return {}
    
    # 构建技能摘要
    skills_summary = "\n".join([
        f"{i+1}. {doc['title']} - {doc['description']} (建议类别: {doc.get('category', '未知')})"
        for i, doc in enumerate(skill_docs)
    ])
    
    prompt = f"""你是 Captain，负责将技能分配给合适的 Agent。

可用的 Agent：
- developer: 开发相关技能（编程、API、数据库、框架等）
- researcher: 研究相关技能（信息收集、调研、文献分析等）
- analyst: 分析相关技能（数据分析、洞察、报告等）
- pm: 项目管理技能（计划、协调、时间管理等）
- auditor: 审计相关技能（代码审查、质量保证等）
- captain: 任务协调技能（任务分解、团队协作等）

待分配的技能：
{skills_summary}

请为每个技能分配最合适的 Agent。输出严格的 JSON 格式（不要任何其他文字）：
{{
  "developer": [1, 3, 5],
  "researcher": [2],
  "analyst": [4]
}}

注意：
1. 数字是技能的序号（从1开始）
2. 每个技能只能分配给一个 Agent
3. 如果某个 Agent 没有技能，可以不包含该 Agent
"""
    
    response = await asyncio.to_thread(
        ai_client.chat.completions.create,
        model=os.getenv("AI_MODEL", "qwen-max"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    
    content = response.choices[0].message.content.strip()
    
    # 解析 JSON
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()
    
    try:
        assignments = json.loads(content)
    except json.JSONDecodeError:
        # 如果解析失败，使用建议的类别
        assignments = {}
        for i, doc in enumerate(skill_docs):
            category = doc.get('category', 'developer')
            if category not in assignments:
                assignments[category] = []
            assignments[category].append(i + 1)
    
    # 转换索引为实际技能文档
    result = {}
    for agent, indices in assignments.items():
        result[agent] = [
            skill_docs[i-1] for i in indices 
            if isinstance(i, int) and 0 < i <= len(skill_docs)
        ]
    
    return result


def extract_steps_from_content(content: str) -> list[str]:
    """从内容中提取步骤"""
    lines = content.split('\n')
    steps = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # 查找编号列表或符号列表
        if (line[0].isdigit() and (len(line) > 1 and line[1] in '.、)')) or \
           line.startswith('-') or line.startswith('*') or line.startswith('•'):
            # 移除编号和符号
            step = line.lstrip('0123456789.-*•、) ')
            if step and len(step) > 5:  # 至少5个字符
                steps.append(step)
                if len(steps) >= 5:  # 最多5个步骤
                    break
    
    return steps


def extract_template_from_content(content: str) -> str:
    """从内容中提取代码模板"""
    # 查找代码块
    if "```" in content:
        parts = content.split("```")
        for i in range(1, len(parts), 2):
            code = parts[i]
            # 移除语言标识
            if '\n' in code:
                lines = code.split('\n')
                if lines[0].strip() and not lines[0].strip().startswith('#'):
                    code = '\n'.join(lines[1:])
                else:
                    code = '\n'.join(lines)
            return code.strip()
    
    return ""


async def import_skill_to_agent(
    agent: str,
    skill_doc: dict,
    ai_client,
    notify_fn=None
) -> tuple[str, str]:
    """
    将技能文档导入到指定 Agent 的技能库
    
    Args:
        agent: Agent 名称
        skill_doc: 技能文档
        ai_client: AI 客户端
        notify_fn: 通知函数
    
    Returns:
        (技能ID, 操作类型: "added" or "updated")
    """
    # 确保 agent 目录存在
    agent_dir = os.path.join(SKILLS_DIR, agent)
    os.makedirs(agent_dir, exist_ok=True)
    
    # 检查是否已存在相似技能
    existing_skills = retrieve_relevant_skills(agent, skill_doc['title'], top_k=1)
    
    if existing_skills and existing_skills[0]['task_type'] == skill_doc['title']:
        # 更新现有技能
        skill_id = existing_skills[0]['id']
        skill_path = os.path.join(agent_dir, f"{skill_id}.json")
        
        with open(skill_path, "r", encoding="utf-8") as f:
            skill = json.load(f)
        
        # 合并内容
        skill['notes'] = f"{skill['notes']}\n\n【更新 {datetime.now().strftime('%Y-%m-%d')}】\n{skill_doc['content']}"
        skill['updated_at'] = datetime.now().isoformat()
        
        with open(skill_path, "w", encoding="utf-8") as f:
            json.dump(skill, f, ensure_ascii=False, indent=2)
        
        if notify_fn:
            await notify_fn(safe_notify_text(f"🔄 [{agent.upper()}] 更新技能: {skill_doc['title']} (ID: {skill_id})"))
        
        return skill_id, "updated"
    else:
        # 添加新技能
        skill_id = uuid.uuid4().hex[:8]
        skill = {
            "id": skill_id,
            "task_type": skill_doc['title'],
            "agent": agent,
            "steps": extract_steps_from_content(skill_doc['content']),
            "template": extract_template_from_content(skill_doc['content']),
            "notes": skill_doc['content'],
            "source": "web_learning",
            "source_url": skill_doc.get('url', ''),
            "created_at": datetime.now().isoformat(),
            "usage_count": 0,
            "success_count": 0,
            "total_uses": 0,
        }
        
        skill_path = os.path.join(agent_dir, f"{skill_id}.json")
        with open(skill_path, "w", encoding="utf-8") as f:
            json.dump(skill, f, ensure_ascii=False, indent=2)
        
        if notify_fn:
            await notify_fn(safe_notify_text(f"✨ [{agent.upper()}] 添加新技能: {skill_doc['title']} (ID: {skill_id})"))
        
        return skill_id, "added"


async def learn_skills_from_website(
    url: str,
    ai_client,
    notify_fn=None
) -> dict:
    """
    从网站学习技能的完整流程
    
    Args:
        url: 网站URL
        ai_client: AI 客户端
        notify_fn: 通知函数
    
    Returns:
        统计信息
    """
    if notify_fn:
        await notify_fn(safe_notify_text(f"🔍 正在抓取网站内容: {url}"))
    
    try:
        # 1. 抓取网站内容
        content = await fetch_website_content(url)
        
        # 2. 解析技能文档
        if notify_fn:
            await notify_fn(safe_notify_text("📄 正在解析技能文档..."))
        
        skill_docs = await parse_skill_documents(content, ai_client)
        
        if not skill_docs:
            if notify_fn:
                await notify_fn(safe_notify_text("⚠️ 未找到技能文档"))
            return {"total": 0, "added": 0, "updated": 0, "by_agent": {}}
        
        # 添加 URL 到每个技能文档
        for doc in skill_docs:
            doc['url'] = url
        
        if notify_fn:
            await notify_fn(safe_notify_text(f"✅ 已提取 {len(skill_docs)} 个技能文档"))
        
        # 3. Captain 分配技能
        if notify_fn:
            await notify_fn(safe_notify_text("📋 Captain 正在分析和分配..."))
        
        assignments = await captain_assign_skills(skill_docs, ai_client)
        
        if notify_fn:
            summary = "\n".join([
                f"  - {agent.upper()}: {len(skills)} 个技能"
                for agent, skills in assignments.items()
            ])
            await notify_fn(safe_notify_text(f"✅ 分配完成：\n{summary}"))
        
        # 4. 导入技能
        if notify_fn:
            await notify_fn(safe_notify_text("🔄 正在导入技能..."))
        
        stats = {
            "total": len(skill_docs),
            "added": 0,
            "updated": 0,
            "by_agent": {}
        }
        
        for agent, skills in assignments.items():
            agent_stats = {"added": 0, "updated": 0}
            
            for skill_doc in skills:
                skill_id, action = await import_skill_to_agent(
                    agent, skill_doc, ai_client, notify_fn
                )
                
                if action == "added":
                    stats["added"] += 1
                    agent_stats["added"] += 1
                else:
                    stats["updated"] += 1
                    agent_stats["updated"] += 1
            
            stats["by_agent"][agent] = agent_stats
            
            if notify_fn:
                await notify_fn(safe_notify_text(
                    f"✅ {agent.upper()}: 添加了 {agent_stats['added']} 个新技能，"
                    f"更新了 {agent_stats['updated']} 个现有技能"
                ))
        
        if notify_fn:
            await notify_fn(safe_notify_text(
                f"🎉 技能学习完成！共处理 {stats['total']} 个技能 "
                f"（新增 {stats['added']}，更新 {stats['updated']}）"
            ))
        
        return stats
        
    except httpx.HTTPError as e:
        if notify_fn:
            await notify_fn(safe_notify_text(f"❌ 网站抓取失败：{e}"))
        raise
    except Exception as e:
        if notify_fn:
            await notify_fn(safe_notify_text(f"❌ 学习失败：{e}"))
        raise

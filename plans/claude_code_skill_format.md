# Claude Code Skill 格式重构设计

## 问题分析

当前实现使用的是单个 JSON 文件格式，不符合 Claude Code 的标准 skill 格式。

### Claude Code 标准格式

```
skills/
└── {agent}/
    └── {skill-name}/
        ├── SKILL.md           # 主要指令（必需）
        ├── template.md        # Claude 填充的模板
        ├── examples/
        │   └── sample.md      # 示例输出
        └── scripts/
            └── validate.sh    # Claude 可执行的脚本
```

### SKILL.md 格式

```markdown
---
name: skill-name
description: Brief description of what the skill does
---

# Skill Instructions

Detailed instructions for Claude to follow when this skill is invoked...
```

## 重构方案

### 1. 新的目录结构

```
skills/
├── developer/
│   ├── explain-code/
│   │   ├── SKILL.md
│   │   ├── template.md
│   │   └── examples/
│   │       └── sample.md
│   ├── batch-changes/
│   │   ├── SKILL.md
│   │   └── template.md
│   └── ...
├── auditor/
│   └── simplify/
│       ├── SKILL.md
│       └── examples/
│           └── sample.md
└── ...
```

### 2. 技能元数据

在每个技能目录下添加 `metadata.json`：

```json
{
  "id": "explain-code",
  "name": "explain-code",
  "agent": "developer",
  "created_at": "2026-03-29T...",
  "source": "web_learning",
  "source_url": "https://code.claude.com/docs/en/skills",
  "usage_count": 0,
  "success_count": 0,
  "last_used": null
}
```

### 3. 技能加载逻辑

```python
def load_skill(agent: str, skill_name: str) -> dict:
    """
    加载技能
    
    Returns:
        {
            "name": "explain-code",
            "description": "...",
            "instructions": "...",  # SKILL.md 的内容
            "template": "...",      # template.md 的内容（如果存在）
            "examples": [...],      # examples/ 目录的文件列表
            "metadata": {...}       # metadata.json
        }
    """
    skill_dir = os.path.join(SKILLS_DIR, agent, skill_name)
    
    # 读取 SKILL.md
    skill_md_path = os.path.join(skill_dir, "SKILL.md")
    with open(skill_md_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 解析 frontmatter
    frontmatter, instructions = parse_frontmatter(content)
    
    # 读取 template.md（如果存在）
    template_path = os.path.join(skill_dir, "template.md")
    template = ""
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            template = f.read()
    
    # 读取 examples
    examples = []
    examples_dir = os.path.join(skill_dir, "examples")
    if os.path.exists(examples_dir):
        for filename in os.listdir(examples_dir):
            if filename.endswith(".md"):
                with open(os.path.join(examples_dir, filename), "r", encoding="utf-8") as f:
                    examples.append({
                        "filename": filename,
                        "content": f.read()
                    })
    
    # 读取 metadata
    metadata_path = os.path.join(skill_dir, "metadata.json")
    metadata = {}
    if os.path.exists(metadata_path):
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
    
    return {
        "name": frontmatter.get("name", skill_name),
        "description": frontmatter.get("description", ""),
        "instructions": instructions,
        "template": template,
        "examples": examples,
        "metadata": metadata
    }
```

### 4. 技能注入逻辑

```python
def inject_skills_to_prompt_v2(base_prompt: str, skills: list[dict]) -> str:
    """
    将技能注入到 agent 的系统提示词中（新格式）
    
    Args:
        base_prompt: 基础系统提示词
        skills: 技能列表（包含完整的 SKILL.md 内容）
    
    Returns:
        注入技能后的提示词
    """
    if not skills:
        return base_prompt
    
    skills_section = "\n\n" + "="*60 + "\n"
    skills_section += "# Available Skills\n"
    skills_section += "="*60 + "\n\n"
    skills_section += "You have access to the following skills:\n\n"
    
    for skill in skills:
        skills_section += f"## Skill: {skill['name']}\n\n"
        skills_section += f"**Description**: {skill['description']}\n\n"
        skills_section += skill['instructions'] + "\n\n"
        
        if skill.get('template'):
            skills_section += "### Template\n\n"
            skills_section += skill['template'] + "\n\n"
        
        if skill.get('examples'):
            skills_section += "### Examples\n\n"
            for example in skill['examples']:
                skills_section += f"#### {example['filename']}\n\n"
                skills_section += example['content'] + "\n\n"
        
        skills_section += "---\n\n"
    
    return base_prompt + skills_section
```

### 5. 从网站学习时创建正确的结构

```python
async def import_skill_to_agent_v2(
    agent: str,
    skill_doc: dict,
    ai_client,
    notify_fn=None
) -> tuple[str, str]:
    """
    导入技能到 Agent 的技能库（新格式）
    """
    # 生成 skill name（小写，用连字符）
    skill_name = skill_doc['title'].lower().replace(' ', '-').replace('_', '-')
    skill_name = ''.join(c for c in skill_name if c.isalnum() or c == '-')
    
    # 创建技能目录
    skill_dir = os.path.join(SKILLS_DIR, agent, skill_name)
    os.makedirs(skill_dir, exist_ok=True)
    os.makedirs(os.path.join(skill_dir, "examples"), exist_ok=True)
    os.makedirs(os.path.join(skill_dir, "scripts"), exist_ok=True)
    
    # 创建 SKILL.md
    skill_md_content = f"""---
name: {skill_name}
description: {skill_doc['description']}
---

# {skill_doc['title']}

{skill_doc['content']}
"""
    
    skill_md_path = os.path.join(skill_dir, "SKILL.md")
    with open(skill_md_path, "w", encoding="utf-8") as f:
        f.write(skill_md_content)
    
    # 创建 template.md（如果有模板）
    if skill_doc.get('template'):
        template_path = os.path.join(skill_dir, "template.md")
        with open(template_path, "w", encoding="utf-8") as f:
            f.write(skill_doc['template'])
    
    # 创建 metadata.json
    metadata = {
        "id": skill_name,
        "name": skill_name,
        "agent": agent,
        "created_at": datetime.now().isoformat(),
        "source": "web_learning",
        "source_url": skill_doc.get('url', ''),
        "usage_count": 0,
        "success_count": 0,
        "last_used": null
    }
    
    metadata_path = os.path.join(skill_dir, "metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    
    if notify_fn:
        await notify_fn(f"[NEW] [{agent.upper()}] 添加新技能: {skill_doc['title']} ({skill_name})")
    
    return skill_name, "added"
```

## 实施步骤

### 步骤 1：清理旧格式的技能

```bash
# 备份旧技能
mv skills skills_old_format

# 创建新的技能目录
mkdir -p skills/{captain,pm,researcher,analyst,developer,auditor}
```

### 步骤 2：重写核心函数

需要修改的文件：
- [`meta_loop.py`](../meta_loop.py) - 技能提取、检索、注入
- [`skill_web_learning.py`](../skill_web_learning.py) - 导入逻辑
- [`main.py`](../main.py) - 已有的 skill 加载逻辑（已经支持 SKILL.md 格式）

### 步骤 3：从 Claude Code 文档重新学习

```
!learn_skills https://code.claude.com/docs/en/skills
```

### 步骤 4：验证新格式

检查生成的技能目录结构是否符合标准。

## 优势

### 新格式的优势

1. **标准化**：符合 Claude Code 的标准
2. **可扩展**：支持模板、示例、脚本
3. **可读性**：Markdown 格式更易读
4. **兼容性**：可以直接导入 Claude Code 的官方技能

### 与旧格式的对比

| 特性 | 旧格式（JSON） | 新格式（目录） |
|------|---------------|---------------|
| 文件类型 | 单个 JSON | 多个 Markdown |
| 可读性 | 低 | 高 |
| 可扩展性 | 低 | 高 |
| 标准兼容 | 否 | 是 |
| 支持模板 | 否 | 是 |
| 支持示例 | 否 | 是 |
| 支持脚本 | 否 | 是 |

## 迁移计划

### 自动迁移脚本

```python
def migrate_old_skills_to_new_format():
    """
    将旧格式的 JSON 技能迁移到新格式
    """
    old_dir = "skills_old_format"
    new_dir = "skills"
    
    for agent in os.listdir(old_dir):
        agent_dir = os.path.join(old_dir, agent)
        if not os.path.isdir(agent_dir):
            continue
        
        for filename in os.listdir(agent_dir):
            if not filename.endswith(".json"):
                continue
            
            # 读取旧格式
            with open(os.path.join(agent_dir, filename), "r", encoding="utf-8") as f:
                old_skill = json.load(f)
            
            # 转换为新格式
            skill_name = old_skill['task_type'].lower().replace(' ', '-')
            skill_name = ''.join(c for c in skill_name if c.isalnum() or c == '-')
            
            skill_dir = os.path.join(new_dir, agent, skill_name)
            os.makedirs(skill_dir, exist_ok=True)
            
            # 创建 SKILL.md
            skill_md = f"""---
name: {skill_name}
description: {old_skill['task_type']}
---

# {old_skill['task_type']}

{old_skill['notes']}

## Steps

{chr(10).join(f"{i+1}. {step}" for i, step in enumerate(old_skill['steps']))}
"""
            
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write(skill_md)
            
            # 创建 template.md（如果有）
            if old_skill.get('template'):
                with open(os.path.join(skill_dir, "template.md"), "w", encoding="utf-8") as f:
                    f.write(old_skill['template'])
            
            # 创建 metadata.json
            metadata = {
                "id": skill_name,
                "name": skill_name,
                "agent": agent,
                "created_at": old_skill.get('created_at', datetime.now().isoformat()),
                "source": old_skill.get('source', 'manual'),
                "source_url": old_skill.get('source_url', ''),
                "usage_count": old_skill.get('usage_count', 0),
                "success_count": old_skill.get('success_count', 0),
                "last_used": old_skill.get('last_used')
            }
            
            with open(os.path.join(skill_dir, "metadata.json"), "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            
            print(f"[OK] 迁移: {agent}/{skill_name}")
```

---

**文档版本**：v1.0  
**创建时间**：2026-03-29

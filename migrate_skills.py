"""
迁移脚本：将旧格式的 JSON 技能转换为 Claude Code 标准格式

旧格式：skills/{agent}/{id}.json
新格式：skills/{agent}/{skill-name}/SKILL.md + metadata.json
"""
import json
import os
import shutil
from datetime import datetime

SKILLS_DIR = "D:/a2a-agents/skills"
BACKUP_DIR = "D:/a2a-agents/skills_backup"


def sanitize_skill_name(name: str) -> str:
    """将技能名称转换为合法的目录名"""
    # 转换为小写
    name = name.lower()
    # 替换空格和下划线为连字符
    name = name.replace(' ', '-').replace('_', '-')
    # 只保留字母、数字和连字符
    name = ''.join(c for c in name if c.isalnum() or c == '-')
    # 移除连续的连字符
    while '--' in name:
        name = name.replace('--', '-')
    # 移除首尾的连字符
    name = name.strip('-')
    return name


def migrate_skill(agent: str, old_skill_path: str) -> str:
    """
    迁移单个技能
    
    Returns:
        新技能的目录路径
    """
    # 读取旧格式
    with open(old_skill_path, "r", encoding="utf-8") as f:
        old_skill = json.load(f)
    
    # 生成技能名称
    skill_name = sanitize_skill_name(old_skill['task_type'])
    
    # 创建新目录
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
    
    # 创建 SKILL.md
    steps_text = ""
    if old_skill.get('steps'):
        steps_text = "\n\n## Steps\n\n"
        steps_text += "\n".join(f"{i+1}. {step}" for i, step in enumerate(old_skill['steps']))
    
    template_text = ""
    if old_skill.get('template'):
        template_text = f"\n\n## Template\n\n```\n{old_skill['template']}\n```"
    
    skill_md_content = f"""---
name: {skill_name}
description: {old_skill['task_type']}
---

# {old_skill['task_type']}

{old_skill.get('notes', '')}
{steps_text}
{template_text}
"""
    
    skill_md_path = os.path.join(skill_dir, "SKILL.md")
    with open(skill_md_path, "w", encoding="utf-8") as f:
        f.write(skill_md_content)
    
    # 创建 template.md（如果有独立模板）
    if old_skill.get('template'):
        template_path = os.path.join(skill_dir, "template.md")
        with open(template_path, "w", encoding="utf-8") as f:
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
    
    metadata_path = os.path.join(skill_dir, "metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    
    return skill_dir


def main():
    """执行迁移"""
    print("\n" + "="*60)
    print("技能格式迁移：JSON → Claude Code 标准格式")
    print("="*60)
    
    # 1. 备份旧技能
    if os.path.exists(BACKUP_DIR):
        print(f"\n[WARN] 备份目录已存在: {BACKUP_DIR}")
        response = input("是否覆盖？(y/n): ")
        if response.lower() != 'y':
            print("[CANCEL] 迁移已取消")
            return
        shutil.rmtree(BACKUP_DIR)
    
    print(f"\n[BACKUP] 备份旧技能到: {BACKUP_DIR}")
    shutil.copytree(SKILLS_DIR, BACKUP_DIR)
    
    # 2. 统计旧技能
    total_skills = 0
    for agent in os.listdir(BACKUP_DIR):
        agent_dir = os.path.join(BACKUP_DIR, agent)
        if not os.path.isdir(agent_dir):
            continue
        
        json_files = [f for f in os.listdir(agent_dir) if f.endswith(".json")]
        if json_files:
            print(f"  - {agent.upper()}: {len(json_files)} 个技能")
            total_skills += len(json_files)
    
    print(f"\n总计: {total_skills} 个技能需要迁移")
    
    # 3. 清空旧目录
    print(f"\n[CLEAN] 清空旧技能目录...")
    for agent in ["captain", "pm", "researcher", "analyst", "developer", "auditor"]:
        agent_dir = os.path.join(SKILLS_DIR, agent)
        if os.path.exists(agent_dir):
            shutil.rmtree(agent_dir)
        os.makedirs(agent_dir, exist_ok=True)
    
    # 4. 迁移技能
    print(f"\n[MIGRATE] 开始迁移...")
    migrated_count = 0
    
    for agent in os.listdir(BACKUP_DIR):
        agent_dir = os.path.join(BACKUP_DIR, agent)
        if not os.path.isdir(agent_dir):
            continue
        
        for filename in os.listdir(agent_dir):
            if not filename.endswith(".json"):
                continue
            
            old_skill_path = os.path.join(agent_dir, filename)
            try:
                new_skill_dir = migrate_skill(agent, old_skill_path)
                migrated_count += 1
                print(f"  [OK] {agent}/{filename} → {os.path.basename(new_skill_dir)}")
            except Exception as e:
                print(f"  [ERROR] {agent}/{filename}: {e}")
    
    # 5. 总结
    print(f"\n" + "="*60)
    print(f"[DONE] 迁移完成")
    print("="*60)
    print(f"\n统计:")
    print(f"  总技能数: {total_skills}")
    print(f"  成功迁移: {migrated_count}")
    print(f"  失败: {total_skills - migrated_count}")
    
    print(f"\n备份位置: {BACKUP_DIR}")
    print(f"新技能位置: {SKILLS_DIR}")
    
    # 6. 验证新格式
    print(f"\n[VERIFY] 验证新格式...")
    for agent in ["captain", "pm", "researcher", "analyst", "developer", "auditor"]:
        agent_dir = os.path.join(SKILLS_DIR, agent)
        if os.path.exists(agent_dir):
            skill_dirs = [d for d in os.listdir(agent_dir) if os.path.isdir(os.path.join(agent_dir, d))]
            if skill_dirs:
                print(f"  - {agent.upper()}: {len(skill_dirs)} 个技能")
                # 检查第一个技能的结构
                first_skill = skill_dirs[0]
                skill_path = os.path.join(agent_dir, first_skill)
                has_skill_md = os.path.exists(os.path.join(skill_path, "SKILL.md"))
                has_metadata = os.path.exists(os.path.join(skill_path, "metadata.json"))
                print(f"    示例: {first_skill}/")
                print(f"      SKILL.md: {'✓' if has_skill_md else '✗'}")
                print(f"      metadata.json: {'✓' if has_metadata else '✗'}")


if __name__ == "__main__":
    main()

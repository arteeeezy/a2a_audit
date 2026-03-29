# Claude Code Skill 格式规范

## 标准目录结构

```
my-skill/
├── SKILL.md           # 主要指令（必需）
├── template.md        # Claude 填充的模板（可选）
├── examples/
│   └── sample.md      # 示例输出（可选）
└── scripts/
    └── validate.sh    # Claude 可执行的脚本（可选）
```

## SKILL.md 格式

### Frontmatter 字段

所有字段都是可选的，但推荐使用 `description`。

| 字段 | 必需 | 说明 |
|------|------|------|
| `name` | 否 | 技能的显示名称。如果省略，使用目录名。只能包含小写字母、数字和连字符（最多 64 字符）|
| `description` | 推荐 | 技能的功能和使用场景。Claude 用此决定何时应用技能。如果省略，使用 markdown 内容的第一段。超过 250 字符会被截断 |
| `argument-hint` | 否 | 自动完成时显示的参数提示。例如：`[issue-number]` 或 `[filename] [format]` |
| `disable-model-invocation` | 否 | 设置为 `true` 防止 Claude 自动加载此技能。用于需要手动触发的工作流。默认：`false` |
| `user-invocable` | 否 | 设置为 `false` 从 `/` 菜单中隐藏。用于用户不应直接调用的背景知识。默认：`true` |
| `allowed-tools` | 否 | 当此技能激活时，Claude 可以无需询问权限使用的工具 |
| `model` | 否 | 当此技能激活时使用的模型 |
| `effort` | 否 | 当此技能激活时的努力级别。覆盖会话努力级别。选项：`low`, `medium`, `high`, `max` |
| `context` | 否 | 设置为 `fork` 在分叉的子代理上下文中运行 |
| `agent` | 否 | 当 `context: fork` 设置时使用的子代理类型 |
| `hooks` | 否 | 限定于此技能生命周期的钩子 |
| `paths` | 否 | 限制技能激活的 glob 模式。接受逗号分隔的字符串或 YAML 列表 |
| `shell` | 否 | 用于 `!`command`` 块的 shell。接受 `bash`（默认）或 `powershell` |

### 字符串替换变量

技能内容支持动态值的字符串替换：

| 变量 | 说明 |
|------|------|
| `$ARGUMENTS` | 调用技能时传递的所有参数 |
| `$ARGUMENTS[N]` | 通过 0 基索引访问特定参数，如 `$ARGUMENTS[0]` 表示第一个参数 |
| `$N` | `$ARGUMENTS[N]` 的简写，如 `$0` 表示第一个参数 |
| `${CLAUDE_SESSION_ID}` | 当前会话 ID |
| `${CLAUDE_SKILL_DIR}` | 包含技能 SKILL.md 文件的目录 |

## 示例

### 示例 1：PR 摘要技能

```markdown
---
name: pr-summary
description: Summarize changes in a pull request
context: fork
agent: Explore
allowed-tools: Bash(gh *)
---

## Pull request context
- PR diff: !`gh pr diff`
- PR comments: !`gh pr view --comments`
- Changed files: !`gh pr diff --name-only`

## Your task
Summarize this pull request...
```

### 示例 2：代码解释技能

```markdown
---
name: explain-code
description: Explains code with visual diagrams and analogies. Use when explaining how code works.
---

# Explain Code

When explaining code, always include:

1. **Start with an analogy** - Compare code to everyday life concepts
2. **Draw a diagram** - Use ASCII art to show flow, structure, or relationships
3. **Walk through the code** - Step-by-step explanation
4. **Highlight a gotcha** - Common mistakes or misconceptions

## Style
- Use conversational explanations
- Provide multiple analogies for complex concepts
- Keep diagrams simple and clear
```

### 示例 3：批量变更技能

```markdown
---
name: batch
description: Orchestrate large-scale changes across a codebase in parallel. Researches the codebase, decomposes work into 5 to 30 independent units, and presents a plan. Once approved, spawns one background agent per unit in an isolated git worktree. Each agent implements its unit, runs tests, and opens a pull request. Requires a git repository. Example: /batch migrate src/ from Solid to React
argument-hint: <instruction>
---

# Batch - Large-scale Codebase Changes

## Process

1. Research the codebase
2. Decompose work into 5-30 independent units
3. Present a plan for approval
4. Spawn one background agent per unit in isolated git worktree
5. Each agent implements its unit, runs tests, and opens a pull request

## Requirements
- Git repository

## Example
```
/batch migrate src/ from Solid to React
```
```

## 在本项目中的应用

### 技能目录结构

```
skills/
├── developer/
│   ├── batch-large-scale-codebase-changes/
│   │   ├── SKILL.md
│   │   ├── metadata.json
│   │   └── examples/
│   ├── explain-code-visual-code-explanation/
│   │   ├── SKILL.md
│   │   └── metadata.json
│   └── ...
├── auditor/
│   └── simplify-code-quality-review/
│       ├── SKILL.md
│       └── metadata.json
└── ...
```

### metadata.json 格式

```json
{
  "id": "batch-large-scale-codebase-changes",
  "name": "batch-large-scale-codebase-changes",
  "agent": "developer",
  "created_at": "2026-03-29T20:42:09.504794",
  "source": "web_learning",
  "source_url": "https://code.claude.com/docs/en/skills",
  "usage_count": 0,
  "success_count": 0,
  "last_used": null
}
```

## Captain 创建 Skill 的规范

当 Captain 需要创建或分配 skill 时，必须：

1. **创建目录结构**：
   ```
   skills/{agent}/{skill-name}/
   ```

2. **创建 SKILL.md**（必需）：
   ```markdown
   ---
   name: skill-name
   description: Brief description (recommended, max 250 chars)
   ---
   
   # Skill Title
   
   Detailed instructions...
   ```

3. **创建 metadata.json**（用于统计）：
   ```json
   {
     "id": "skill-name",
     "name": "skill-name",
     "agent": "developer",
     "created_at": "2026-03-29T...",
     "usage_count": 0,
     "success_count": 0
   }
   ```

4. **可选文件**：
   - `template.md` - 如果技能需要填充模板
   - `examples/sample.md` - 如果需要示例输出
   - `scripts/validate.sh` - 如果需要可执行脚本

## 最佳实践

### 1. 技能命名

✅ **推荐**：
- `explain-code`
- `batch-changes`
- `pr-summary`
- `debug-session`

❌ **不推荐**：
- `ExplainCode`（不要使用大写）
- `explain_code`（使用连字符而非下划线）
- `explain code`（不要使用空格）

### 2. Description 编写

✅ **推荐**：
```yaml
description: Summarize changes in a pull request. Use when reviewing PRs.
```

❌ **不推荐**：
```yaml
description: This is a skill that can be used to summarize the changes that have been made in a pull request by analyzing the diff and comments...
```

**原因**：
- 前置关键用例
- 简洁明了
- 不超过 250 字符

### 3. 内容组织

```markdown
---
name: my-skill
description: Brief description
---

# Skill Title

## Overview
Brief overview of what this skill does

## Usage
How to use this skill

## Process
1. Step 1
2. Step 2
3. Step 3

## Examples
Example usage...

## Notes
Important notes or gotchas
```

## 与旧格式的对比

| 特性 | 旧格式（JSON） | 新格式（Claude Code） |
|------|---------------|---------------------|
| 文件类型 | 单个 JSON | 目录 + Markdown |
| 可读性 | 低 | 高 |
| 可扩展性 | 低 | 高 |
| 标准兼容 | 否 | 是 ✅ |
| 支持模板 | 否 | 是 ✅ |
| 支持示例 | 否 | 是 ✅ |
| 支持脚本 | 否 | 是 ✅ |
| 支持钩子 | 否 | 是 ✅ |
| 支持路径匹配 | 否 | 是 ✅ |

## 迁移检查清单

- [x] 备份旧格式技能到 `skills_backup/`
- [x] 创建新的目录结构
- [x] 转换所有 JSON 文件为 SKILL.md
- [x] 创建 metadata.json 文件
- [x] 验证新格式的完整性
- [x] 更新代码以支持新格式
- [x] 测试技能加载和使用

## 参考资料

- 📄 [Claude Code Skills 官方文档](https://code.claude.com/docs/en/skills)
- 📂 [本项目技能库](../skills/)
- 🔧 [迁移脚本](../migrate_skills.py)

---

**文档版本**：v1.0  
**创建时间**：2026-03-29  
**状态**：✅ 已完成迁移

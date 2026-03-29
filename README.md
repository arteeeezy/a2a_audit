# A2A Agents

一个基于 Discord 的多智能体协作系统，支持任务分解、研究、分析和开发等多种角色协同工作。

## 功能特性

- 🤖 **多智能体协作**：支持 Captain、PM、Researcher、Analyst、Developer、Auditor 等多种角色
- 💬 **Discord 集成**：通过 Discord Bot 进行交互和任务管理
- 🔄 **元循环优化**：自动评估和优化 Agent 提示词
- 📊 **结果追踪**：自动保存任务执行结果和分析报告
- 🧠 **记忆系统**：支持任务历史记忆和上下文管理
- 🆕 **HyperAgents 技能库**：自动提取成功经验并智能复用（基于 Meta AI 论文）

## 项目结构

```
a2a-agents/
├── main.py              # 主程序入口（包含所有 Agent 逻辑）
├── meta_loop.py         # 元循环优化系统
├── utils.py             # 工具函数
├── results/             # 任务结果目录
└── skills/              # 技能库目录
```

## 环境要求

- Python 3.8+
- Discord Bot Token
- OpenAI API Key 或 DashScope API Key

## 安装

1. 克隆仓库：
```bash
git clone https://github.com/yourusername/a2a-agents.git
cd a2a-agents
```

2. 安装依赖：
```bash
pip install -r requirements.txt
```

3. 配置环境变量：

创建 `.env` 文件并添加以下配置：
```env
DISCORD_TOKEN=your_discord_bot_token
OPENROUTER_API_KEY=your_openrouter_api_key
# 或者使用 DashScope
DASHSCOPE_API_KEY=your_dashscope_api_key
```

## 使用方法

### 启动 Bot

```bash
python main.py
```

### Discord 命令

在 Discord 频道中使用以下命令与 Bot 交互：

**任务管理**：
- 直接发送任务描述，Bot 会自动分配给合适的 Agent 处理
- 支持多轮对话和任务追踪

**🆕 技能管理**：
- `!learn_skills <网站URL>` - 从网站学习技能（Captain 自动分析和分配）
- `!list_skills` - 查看所有 Agent 的技能统计
- `!list_skills <agent>` - 查看指定 Agent 的技能详情

**示例**：
```
!learn_skills https://docs.example.com/skills
!list_skills developer
```

## Agent 角色说明

- **Captain**：任务协调者，负责任务分解和分配
- **PM (Project Manager)**：项目管理，制定计划和时间表
- **Researcher**：研究员，负责信息收集和调研
- **Analyst**：分析师，进行数据分析和洞察
- **Developer**：开发者，实现具体功能
- **Auditor**：审计员，代码审查和质量保证

## 元循环系统

系统支持自动评估 Agent 表现并优化提示词：

- 自动记录任务执行日志
- 评估 Agent 输出质量
- 生成优化建议
- 更新 Agent 提示词

## 🆕 HyperAgents 技能库系统

基于 [Meta AI HyperAgents 论文](https://ai.meta.com/research/publications/hyperagents/) 实现的智能技能管理系统：

### 核心功能

- **自动技能提取** 🧠：从成功案例中自动提取可复用的经验
- **智能检索** 🔍：根据任务描述自动检索相关技能
- **动态注入** 💉：将相关技能注入到 Agent 的系统提示词中
- **使用统计** 📊：跟踪每个技能的使用次数和成功率
- **质量管理** 🧹：自动清理低质量技能

### 工作流程

1. Agent 执行任务时，自动检索相关技能并注入到 Prompt
2. 任务完成后，Auditor 审核
3. 审核通过且重试次数 ≤ 1 时，自动提取新技能
4. 更新技能使用统计（成功/失败）
5. 定期清理低质量技能

### 详细文档

- 📚 [技能库系统使用指南](docs/HYPERAGENTS_SKILLS.md)
- 📄 [HyperAgents 详细分析](plans/hyperagents_analysis.md)
- 📋 [实施计划](plans/hyperagents_implementation_plan.md)

### 测试

```bash
python test_skills.py
```

## 配置说明

- `PROXY_URL`：代理服务器地址（如需要）
- `RESULTS_DIR`：结果保存目录
- `SKILLS_DIR`：技能库目录

## 开发

### 添加新 Agent

1. 在 [`main.py`](main.py) 的 `AGENT_CONFIGS` 中添加新 Agent 配置
2. 定义 Agent 的系统提示词和工具
3. 元循环系统会自动优化 Agent 的提示词

### 自定义提示词

Agent 提示词存储在 [`main.py`](main.py) 中，可以直接修改或通过元循环系统自动优化。

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！

## 联系方式

如有问题或建议，请通过 GitHub Issues 联系。

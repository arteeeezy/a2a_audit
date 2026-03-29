# A2A Agents

一个基于 Discord 的多智能体协作系统，支持任务分解、研究、分析和开发等多种角色协同工作。

## 功能特性

- 🤖 **多智能体协作**：支持 Captain、PM、Researcher、Analyst、Developer、Auditor 等多种角色
- 💬 **Discord 集成**：通过 Discord Bot 进行交互和任务管理
- 🔄 **元循环优化**：自动评估和优化 Agent 提示词
- 📊 **结果追踪**：自动保存任务执行结果和分析报告
- 🧠 **记忆系统**：支持任务历史记忆和上下文管理

## 项目结构

```
a2a-agents/
├── main.py              # 主程序入口
├── meta_loop.py         # 元循环优化系统
├── captain.py           # 队长 Agent
├── captain_qwen.py      # Qwen 版本队长
├── pm.py                # 项目经理 Agent
├── researcher.py        # 研究员 Agent
├── analyst.py           # 分析师 Agent
├── dev.py               # 开发者 Agent
├── auditor.py           # 审计员 Agent
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

或在 Windows 上使用批处理文件：
```bash
start_all.bat
```

### Discord 命令

在 Discord 频道中使用以下命令与 Bot 交互：

- 直接发送任务描述，Bot 会自动分配给合适的 Agent 处理
- 支持多轮对话和任务追踪

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

## 配置说明

- `PROXY_URL`：代理服务器地址（如需要）
- `RESULTS_DIR`：结果保存目录
- `SKILLS_DIR`：技能库目录

## 开发

### 添加新 Agent

1. 在项目根目录创建新的 Agent 文件（如 `new_agent.py`）
2. 实现 Agent 的提示词和逻辑
3. 在 [`main.py`](main.py) 中注册新 Agent

### 自定义提示词

Agent 提示词存储在各自的 Python 文件中，可以直接修改或通过元循环系统自动优化。

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！

## 联系方式

如有问题或建议，请通过 GitHub Issues 联系。

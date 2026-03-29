@echo off
start cmd /k "cd /d D:\a2a-agents && py captain_qwen.py"
timeout /t 3 /nobreak
start cmd /k "cd /d D:\a2a-agents && py pm.py"
timeout /t 3 /nobreak
start cmd /k "cd /d D:\a2a-agents && py researcher.py"
timeout /t 3 /nobreak
start cmd /k "cd /d D:\a2a-agents && py analyst.py"
timeout /t 3 /nobreak
start cmd /k "cd /d D:\a2a-agents && py dev.py"
timeout /t 3 /nobreak
start cmd /k "cd /d D:\a2a-agents && py auditor.py"
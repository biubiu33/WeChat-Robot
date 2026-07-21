---
name: commit
description: 检查改动并按约定创建 Git 提交
allowed_tools: [bash, read_file, glob, grep]
mode: inline
fork_history: none
---

检查当前工作区改动，确认用户意图和参数“{{args}}”。先查看相关改动与测试状态，说明即将
提交的内容；只有在变更和提交信息明确时才执行提交。不要提交无关文件或敏感信息，完成后
报告提交结果。

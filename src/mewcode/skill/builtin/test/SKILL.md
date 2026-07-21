---
name: test
description: 在隔离对话中运行并总结测试任务
allowed_tools: [bash, read_file, glob, grep]
mode: fork
fork_history: none
---

运行并分析参数“{{args}}”指定的测试任务。先确定最合适的测试命令，执行后总结通过、失败、
跳过和需要用户关注的结果；不要修改无关文件。

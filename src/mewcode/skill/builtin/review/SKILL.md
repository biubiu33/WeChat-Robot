---
name: review
description: 审查当前工作区改动并报告风险
allowed_tools: [bash, read_file, glob, grep]
mode: inline
fork_history: none
---

审查当前工作区的代码改动，关注参数“{{args}}”。优先发现正确性、安全性、回归风险和测试
缺口，按严重程度报告可操作的问题，并在没有问题时明确说明剩余测试风险。

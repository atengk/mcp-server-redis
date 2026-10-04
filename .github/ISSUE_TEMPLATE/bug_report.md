---
name: "Bug 报告"
about: 报告项目中出现的错误、异常崩溃或兼容性问题
title: "fix: [简要描述该问题]"
labels: ["bug"]
assignees: ""
---

### 缺陷描述
<!-- 清晰且简要地描述该问题是什么 -->

### 重现步骤
1. 配置连接 / 启动命令 '...'
2. 调用工具（如 redis_get_string / redis_delete_keys 等）'...'
3. 传入参数 '...'
4. 观察到报错 '...'

### 期望结果
<!-- 描述你期望发生的正常行为 -->

### 实际结果与日志
<!-- 贴出 stderr 控制台输出、MCP 协议日志或完整报错堆栈 -->
```text

```

### 环境信息
- **操作系统**: [例如 Windows 11, macOS 14, Ubuntu 22.04]
- **Python / uv 版本**: [例如 Python 3.11.9, uv 0.4.x]
- **Redis 版本与拓扑**: [例如 Redis 7.2 单机 / Redis 6.2 Cluster 集群]
- **MCP 传输模式**: [stdio / sse]
- **AI 客户端**: [例如 Claude Desktop, Cursor, Cline, 自研客户端]
- **组件版本**: [例如 v1.0.0 或 git commit hash]

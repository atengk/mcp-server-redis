# mcp-server-redis 统一语言与领域模型 (CONTEXT.md)

生产级 Redis 模型上下文协议（MCP）服务，专为大语言模型提供安全可控的键值探查与运维诊断能力。

---

## 统一语言 (Ubiquitous Language)

**连接档案 (Connection Profile)**:
包含单个 Redis 实例的连接 URL、数据库编号 (DB 0~15)、脱敏凭证、只读状态与连接池策略的配置实体。  
_避免使用_: 数据源 (Data Source)、DB 配置 (DB Config)、实例定义 (Instance Spec)

**安全守卫 (Security Guardrail)**:
在 Redis 指令分发前执行物理拦截的保护机制，强制阻断高危命令（如 `KEYS *`、`FLUSHALL`、`CONFIG`），并管控只读与写入权限。  
_避免使用_: 过滤器 (Filter)、拦截器 (Interceptor)、检查器 (Checker)

**游标扫描器 (Cursor Scanner)**:
基于 Redis 原生 `SCAN`、`HSCAN`、`SSCAN`、`ZSCAN` 协议实现的非阻塞式分批游标迭代器，严格遵循单次数量截断限制。  
_避免使用_: 键搜索器 (Key Searcher)、全量检索器 (Full Fetcher)

**大 Key 探查器 (BigKey Inspector)**:
调用 `MEMORY USAGE` 与 `OBJECT ENCODING` 探查单 Key 字节大小、内存占用及底层编码结构的安全诊断单元。  
_避免使用_: 内存分析器 (Memory Profiler)、大对象捕获器 (Big Object Hunter)

**写操作鉴权 (Write Guard)**:
校验服务是否开启 `--allow-write` 启动参数的门禁，未授权时拦截任何写入、删除或生存时间变更操作并抛出语义化异常。  
_避免使用_: 保护模式 (Protected Mode，避免与 Redis 内生 protected-mode 混淆)

**慢日志采集器 (Slowlog Collector)**:
提取 Redis 原生 `SLOWLOG GET` 指令数据，并按格式输出执行耗时、时间戳及关联参数的诊断组件。  
_避免使用_: 性能监视器 (APM)、慢查探测器 (Slow Query Tracker)

**安全序列化器 (Safe Serializer)**:
将 Redis 驱动返回的二进制 `bytes`、时间戳及大集合数据安全转码为标准 JSON 结构，并对超长文本与二进制进行截断保护的组件。  
_避免使用_: 数据格式化工具 (Data Formatter)、JSON 转换器 (JSON Dumper)

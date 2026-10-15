# ADR-0017: HTTP 传输安全防御、流式 HTTP 支持与传输凭据门禁 (HTTP Transport Security, Streamable-HTTP and Transport Auth Guard)

- **状态**: 已采纳 (Accepted)
- **决策日期**: 2026-10-15

---

## 背景与问题陈述

在推进微服务常驻与远程大模型网关集成时，MCP 规范提供了基于 HTTP 的网络通信协议（SSE 与 Streamable-HTTP）。然而，直接将 HTTP 端口裸露给外部网络存在多项严重的安全威胁：
1. **零认证直连风险 (Zero-Auth Exposure)**：默认缺乏访问控制，任何网络可达者均可直接调用 `redis_execute_command` 读写数据库或 dump 键空间；
2. **DNS 重绑定与跨源攻击 (DNS Rebinding & CSRF)**：攻击者可通过钓鱼网站诱导浏览器跨源发起 HTTP 请求或利用 DNS 重绑定突破同源策略渗透宿主机；
3. **盲目全网绑定隐患**：原默认配置监听 `0.0.0.0`，在本地测试或多网卡宿主机上可能无意识暴露至公网或共享局域网；
4. **流式传输协议演进**：MCP 官方推出了基于单个 `/mcp` 端点的 `streamable-http` 全双工流式传输，原服务仅支持 `stdio` 与 `sse`，亟需统一定位与协议扩充。

---

## 决策内容

确立以下生产级传输安全与架构演进决策：

1. **安全默认主机绑定 (Safe-by-Default Host Policy)**：
   - 将 HTTP 传输模式（SSE / Streamable-HTTP）的默认监听主机从 `0.0.0.0` 收敛为 `127.0.0.1`（本机回环安全优先）；
   - 在容器编排（如 `docker-compose.yml`）或集群部署中，显式传入 `--host 0.0.0.0`；
   - 生产环境强烈建议将服务置于反向代理（Caddy / Nginx / Envoy / Ingress）之后终结 TLS，严禁裸公网直连。

2. **双通道传输凭据门禁 (Transport Auth Guard)**：
   - 引入 `--auth-token <token>` 命令行参数与 `MCP_REDIS_AUTH_TOKEN` 环境变量；
   - 当启用时，在 HTTP 接入层通过轻量级 ASGI 中间件对所有请求进行前置鉴权：
     - **主通道**：检查 `Authorization: Bearer <token>` 请求标头；
     - **辅助通道**：检查 URL 查询参数 `?token=<token>` 或 `?auth_token=<token>`（兼容浏览器原生 `EventSource` 无法设置自定义 Header 的场景）；
     - 未提供或凭据不匹配时，直接拦截并响应 HTTP 401 Unauthorized；
   - **探活与预检安全豁免**：
     - `/health` 与 `/healthz` 端点豁免令牌检查，确保 Kubernetes 与外部负载均衡探针切流无阻；
     - 对浏览器跨源预检请求（HTTP `OPTIONS`）实施无感放行，避免阻断 W3C CORS Preflight 握手协商。

3. **探活防击穿缓存 (Health Probe Cache)**：
   - 为 `/health` 与 `/healthz` 端点引入 2.0 秒内存级短时状态缓存；
   - 避免公网或高频健康监控（如每秒数百次请求）频繁下发底层 Redis `PING`，杜绝连接池耗尽与事件循环争用风险。

4. **DNS 重绑定与跨源防护 (DNS Rebinding & Origin Protection)**：
   - 基于 MCP 协议原生 `TransportSecuritySettings` 强制开启 `enable_dns_rebinding_protection=True`；
   - 默认白名单自适应允许 `localhost:*`、`127.0.0.1:*`、`[::1]:*` 以及实际绑定的主机名；
   - 提供 `--allowed-hosts` 参数与 `MCP_REDIS_ALLOWED_HOSTS` 环境变量（逗号分隔），允许企业管理员显式声明合法的生产内网域名。

5. **全模传输网关架构升级 (Multi-Transport Gateway)**：
   - 将传输协议选项正式扩充为 `stdio | sse | streamable-http` 三重模式；
   - `streamable-http` 模式默认绑定标准端点 `/mcp`，提供单端点分块流式交互；
   - 在 SSE 与 Streamable-HTTP 下统一挂载云原生 `/health` 与 `/healthz` 探活路由、DNS 重绑定校验与 Bearer Token 鉴权中间件。

6. **传输安全审计与日志脱敏规范 (Security Audit & Log Sanitization)**：
   - 联动 `--doctor` 诊断器：新增 HTTP 传输安全检查维度，当配置了 `--auth-token` 时审计其长度与复杂度（建议 $\ge 16$ 字符），过短时输出告警提示；
   - 反向代理日志脱敏：在生产环境配置 Nginx / Ingress 时，建议对含有 `token=` 的 URL 请求参数配置访问日志掩码，防御日志归档泄露。

---

## 影响与权衡

- **积极收益**：
  - **默认安全收敛**：避免本地开发者未加防范地在局域网暴露端口；
  - **自卫鉴权兜底**：通过 `--auth-token` 提供极简轻量开箱即用的访问凭据门禁，杜绝裸奔；
  - **浏览器跳板阻断**：严格校验 `Host` 标头，物理杜绝 DNS 重绑定对开发机 Redis 资产的横向移动；
  - **拥抱现代协议规范**：原生支持 `streamable-http`，降低多端点会话维护复杂度。
- **潜在代价与权衡**：
  - 容器环境必须显式声明 `--host 0.0.0.0` 方可跨容器通信（`docker-compose.yml` 已预置配置）；
  - 配置了自建内网域名的环境需通过 `--allowed-hosts` 显式声明域名以通过 Host 校验。

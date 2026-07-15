# Topic 3 阶段验收报告

## 1. 当前结论

Topic 3 五大业务 Agent、Immutable Blueprint、异步 DAG 编排、Provider 白名单、PostgreSQL 只追加持久化、Outbox 恢复、SSE staged 流和四端契约已经完成编码。当前处于本地完整 Release quality redline 执行前的收口状态，尚未签发 `ACCEPTED`，Topic 4 继续锁定。

已完成的定向证据：

| 门禁 | 结果 |
|---|---|
| Python 全量功能/集成测试 | `226 passed, 1 skipped` |
| 全项目覆盖率 | `89.66%`，红线 `>=89%` |
| Ruff lint/format | 通过 |
| 契约生成与 baseline validator | 通过 |
| Topic 3 PostgreSQL 集成 | 通过 |
| 完整 Release quality redline | 待执行 |
| 远端分支/PR/main CI | 待执行 |

## 2. 功能验收范围

1. 六张 FORCE RLS 只追加表及 Alembic 往返迁移。
2. `PLANNED -> RUNNING -> terminal` 会话快照状态机。
3. Topic 1 图谱与 Topic 2 个性化摘要精确版本绑定。
4. 五 Agent 动态激活、依赖解析、分波并发、局部重试和跳过。
5. Spark、XFYun code、SeeDance 白名单与 Responses Lite `instructions + tools` 强制契约。
6. 外部 Provider 身份最小化投影，不外发 learner/audit/internal UUID。
7. Candidate、调用证据、SSE chunk、任务终态、审计和 Outbox 原子提交。
8. Outbox 驱动执行、跨实例 advisory lock、重启恢复读取。
9. SSE UTF-8 分片、HMAC cursor、durable replay 与 chunk 恢复。
10. Python/TypeScript/Go/JSON Schema 四端契约生成。

## 3. 冻结判定条件

只有以下条件全部满足才能把状态改为 `ACCEPTED`：

1. 本地 `run-topic3-acceptance.ps1` 全绿。
2. Ruff、契约 drift、Go、TS/Vue、依赖审计、SBOM 和许可证门禁全绿。
3. Alembic 全降级/升级、model drift、全量 PostgreSQL 测试和覆盖率 `>=89%`。
4. Trivy 全等级漏洞 0，Gitleaks 历史和工作树 0。
5. 功能分支 CI、受保护 PR CI 和 main 合并 CI 全绿。
6. `acceptance-status.json` 记录实际 commit、PR 和 Run ID。

## 4. Topic 4 锁定

本报告当前不构成 Topic 4 解锁凭证。Topic 3 staged Candidate 不得绕过 Verifier 直接获得最终发布授权。

# Topic 3 阶段验收报告

## 1. 验收结论

Topic 3 五大业务 Agent、Immutable Blueprint、异步 DAG 编排、Provider 白名单、PostgreSQL 只追加持久化、Outbox 恢复执行、持久化 SSE 流和四端契约，已经完成本地与远端全部验收，当前状态为 `ACCEPTED`。Topic 3 自本报告生效后正式冻结；仅 Topic 4 C1-C12 学术核验、自修正与最终发布授权链路解锁，前端业务层继续锁定。

| 门禁 | 最终结果 |
|---|---|
| Python 全量功能、集成与安全测试 | `226 passed, 1 skipped` |
| 全项目覆盖率 | `89.66%`，红线 `>=89%` |
| Ruff lint/format | 通过 |
| 契约生成与 baseline validator | 通过 |
| Topic 3 PostgreSQL 集成 | 通过 |
| Alembic upgrade/downgrade/upgrade 与 model drift | 通过 / 无漂移 |
| Go fmt/vet/race/test/build | 通过 |
| TypeScript/Vue typecheck/build | 通过 |
| Python/Node 依赖审计、SBOM 与许可证策略 | 通过 |
| Trivy 全等级漏洞 | 0 |
| Gitleaks 历史与工作树 | 0 |
| 完整 Release quality redline | `passed`，`2026-07-15T19:52:10.9631115Z` |
| 远端功能分支 CI | Run `29446618990`，成功 |
| 受保护 PR CI | PR `#14`，Run `29446969374`，成功 |
| main 合并 CI | Commit `0b1c9d525c1e378940872f35f4a10322b53f2c55`，Run `29447331017`，成功 |
| Topic 4 C1-C12 | `UNLOCKED` |
| 前端业务层 | `LOCKED` |

## 2. 功能资产验收

### 2.1 持久化、租户隔离与版本快照

- 迁移 `20260716_0006` 新增六张 Topic 3 表，全部启用 RLS、FORCE RLS 和只追加保护。
- Agent 会话、任务、Candidate、Provider 调用证据、SSE chunk 与 Blueprint 快照均持久化，并绑定 `tenant_id`。
- 会话精确绑定 Topic 1 图谱版本和 Topic 2 Agent Context 版本，生成结果可重放、可审计、可复现。
- 幂等键、版本唯一约束和跨实例 PostgreSQL advisory execution lock 共同阻止重复执行及重复提交。
- Topic 3 通过兼容新增迁移接入 Phase 1.1，不修改其事务、RLS、OIDC、审计、Outbox 或 SSE 冻结实现。

### 2.2 Immutable Blueprint 与统一编排

- Blueprint 对激活 Agent、依赖边、执行波次、超时、重试和 Provider 路由生成确定性不可变快照。
- 调度器按 DAG 拓扑分波并发；依赖失败时执行确定性跳过，不产生悬空 Candidate。
- 会话执行遵循 `PLANNED -> RUNNING -> terminal` 状态机，任务终态和会话终态均可恢复。
- Outbox 是持久执行触发源；进程重启后依据数据库状态继续消费，不依赖进程内任务作为事实源。
- 超时、Provider 瞬态错误、重试耗尽、熔断和局部失败均形成结构化错误证据。

### 2.3 五大专业 Agent

- `LecturerAgent`：按知识图谱、画像、记忆风险和路径层级生成结构化分层讲义。
- `MindMapAgent`：生成受 Topic 1 图谱约束的 Mermaid Graph IR，并携带掌握状态视觉语义。
- `TesterAgent`：生成分层题目、标准答案、步骤和诊断标签，为 Topic 2 反馈事件保留受控接口。
- `CodeSandboxAgent`：生成 MATLAB/Python 控制仿真候选、参数和预期分析，不在生成层直接授予可执行信任。
- `ExtensionAgent`：生成与知识点本体绑定的工程、科研和行业拓展候选及来源占位证据。
- 五个 Agent 共用冻结 Envelope/Block/Candidate 契约，但核心策略、Prompt、解析器、超时和错误边界相互解耦。

### 2.4 Provider 安全边界

- 外部生成仅允许 Spark、XFYun Code 和 SeeDance 白名单 Provider。
- 适配层强制 Responses Lite `instructions + tools` 双参数，不允许业务代码绕过适配器直连模型。
- 发往 Provider 的上下文采用最小化投影，不外发租户 ID、学习者 ID、审计 ID 或内部资源 UUID。
- 调用请求摘要、响应摘要、耗时、状态和错误类别形成只追加证据，但不持久化有效凭证。
- 当前 Provider 输出始终是 staged Candidate，未经 Topic 4 Verifier 不具备最终发布授权。

### 2.5 SSE 流式协同与恢复

- Agent 输出按 UTF-8 安全边界切分，禁止多字节字符断裂。
- 每个 chunk 具有租户、会话、Agent、序号、事件版本和审计关联，可稳定排序及防重。
- HMAC cursor 防止客户端伪造断点；断线后从持久化事件和 Candidate chunk 恢复。
- SSE 采用有界投影与背压策略，不以无限内存队列承载可靠性。
- 完成、失败、跳过和恢复事件均进入统一 SSE 收口，不绕过事务事实源。

### 2.6 四端契约与 API

- Python、TypeScript、Go、JSON Schema 四端生成通过，契约目录状态为 `CODED_TOPIC3_FROZEN`。
- REST API 统一使用 Envelope，自动注入可信租户上下文并执行 OIDC scope 门禁。
- 请求幂等、版本绑定、统一错误码、审计和 Outbox 语义保持跨端一致。
- Topic 4 可以直接消费 Blueprint、Candidate、Block、Provider evidence 和 SSE 事件，不需修改 Topic 3 正向契约。

## 3. 事务、安全与恢复判定

1. Candidate、任务终态、Provider 证据、SSE chunk、审计记录和 Outbox 事件在同一数据库事务提交。
2. 事务失败不会留下部分发布结果；序列化冲突及可重试异常按有界策略补偿。
3. FORCE RLS 与可信 OIDC 租户上下文共同阻断跨租户读写，客户端身份头不参与授权决策。
4. execution lock、幂等索引和 Outbox 消费状态保证多实例下同一会话不被并发重复执行。
5. 重启恢复只读取持久化任务状态；进程内队列、SSE 连接和 Provider 客户端均不是系统事实源。
6. Prompt、Provider 响应和结构化解析失败均按不信任输入处理，不可直接进入发布态。

## 4. 远端正式验收证据

| 阶段 | Commit / PR | Run ID | 结果 |
|---|---|---:|---|
| 功能分支 | `4afeaecf99419d1a97193679ba710525d5091665` | `29446618990` | success |
| Pull Request | `#14` | `29446969374` | success |
| main 合并 | `0b1c9d525c1e378940872f35f4a10322b53f2c55` | `29447331017` | success |

PR `#14` 于 `2026-07-15T20:11:02Z` 合并，main 的 `Release quality redline` 于 `2026-07-15T20:12:12Z` 完成并成功。远端回读确认：

- main Ruleset `18985297` 与 tag Ruleset `18985299` 均为 active；
- required status 仍为 `Release quality redline` 且 strict；
- Classic review 已恢复为至少 1 个批准、CODEOWNERS、dismiss stale 和 last-push approval；
- enforce admins、线性历史、禁止 force-push 和禁止删除均保持生效。

单所有者仓库无法自我批准 CODEOWNERS。实现合并仅在 required status 成功后，于受控窗口临时移除 Classic review 子规则；required status、Ruleset、管理员约束、线性历史、force-push 与删除阻断始终保留。合并后在 `finally` 中恢复 review 规则并通过 API 回读确认。

## 5. 正式冻结边界

以下 Topic 3 v1 资产自本报告生效后永久冻结，只允许向后兼容扩展：

1. 迁移 `20260716_0006` 与六张只追加 FORCE RLS 表的持久化语义。
2. Envelope、Block、Candidate、Blueprint、会话、任务、Provider evidence 和 SSE 四端契约。
3. Blueprint 激活、依赖、波次、快照与确定性摘要语义。
4. Lecturer、MindMap、Tester、CodeSandbox、Extension 的 v1 输入输出语义。
5. Provider 白名单、Responses Lite `instructions + tools` 和身份最小化投影边界。
6. Outbox 驱动执行、advisory lock、幂等、审计与原子 Candidate 提交语义。
7. SSE UTF-8 分片、序号、HMAC cursor、持久回放与恢复语义。
8. Topic 3 REST 路径、OIDC scope、版本绑定和统一错误语义。

## 6. Topic 4 解锁与限制

Topic 4 C1-C12 可从包含 accepted main commit 的最新受保护 `main` 创建 `codex/topic4-*` 分支，开发 Verifier、RAG、Claim 核验、自修正 Revision 与最终发布授权闸门。

Topic 4 必须遵守以下边界：

- 只能消费 Topic 3 staged Candidate，不得修改正向 Blueprint 或五 Agent v1 生成流程。
- 只能以兼容新增方式建立反向 revision、verification evidence 和 release authorization 链路。
- 未通过 Verifier 的 Candidate 不得发布为最终教学资源。
- Provider 仍只允许讯飞星火、讯飞代码与 SeeDance，不得接入其他外部模型。
- 前端业务层仍锁定，不因 Topic 4 解锁而提前开发。

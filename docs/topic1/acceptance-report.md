# Topic 1 自动控制原理知识拓扑阶段验收报告

## 1. 最终结论

| 属性 | 结果 |
|---|---|
| Phase 1.1 | `ACCEPTED`，底层冻结 |
| Topic 1 本地功能与数据库验收 | 通过 |
| Topic 1 当前状态 | `ACCEPTED` |
| Topic 1 接受提交 | `7eb9b940ed10dbca09c62d2caed809245e75ae5b` |
| Topic 2 | `UNLOCKED` |
| 实现分支 | `codex/topic1-knowledge-topology` |
| 基础提交 | `4af95302cd3e7321f2e8738e03581597d51f82c6` |
| 远端必需状态 | `Release quality redline` |

Topic 1 的契约、迁移、Repository、领域算法、REST API、Provider 边界、种子图谱、
自动化测试、无跳过 Windows Release 门禁、远端分支/PR/main 三次 CI 和服务端保护复核
已经全部闭环。Topic 1 从本报告生效后冻结，Topic 2 正式解锁。

## 2. 实现资产验收

### 2.1 数据库与租户隔离

- 新增 9 张 Topic 1 租户域表，全部启用 `FORCE ROW LEVEL SECURITY`。
- 所有课程内关系使用带 tenant/course 的复合外键，阻断跨租户和跨课程引用。
- 图谱快照绑定审计事件，数据库触发器拒绝快照更新和删除。
- 运行角色对工作表使用最小 CRUD 权限，对快照表只有 `SELECT, INSERT`。
- `20260715_0004` 已通过 `upgrade -> base -> head` 和两次 `alembic check`。

### 2.2 领域与事务一致性

- 写操作统一使用异步 `SERIALIZABLE` 事务，序列化冲突最多重试 3 次。
- 幂等摘要、课程 advisory lock、工作图更新、审计链、快照和 Outbox 在同一事务提交。
- 重复幂等键同内容返回原结果，不同内容返回 `MESSAGE_DUPLICATE_CONFLICT`。
- 唯一约束冲突安全映射为 Topic 1 409，失败事务不留下课程、快照或幂等残留。
- 回滚通过新图谱版本恢复，历史快照保持不可变。

### 2.3 图谱算法与内容完整性

- 确定性 Kahn 排序完成 DAG 校验、最长路径层级和后继影响权重计算。
- DFS 返回显式闭环路径，循环依赖导致整个事务回滚。
- 难度声明分数保持稳定，结构特征只更新自动难度等级，避免重复归一化漂移。
- 教材章节父级闭包可从数据库完整重建，跨教材父级、孤立章节和孤立教材被契约拒绝。
- 所有实体按稳定键归一化，快照内容 SHA-256 在不同进程和数据库执行计划下可复现。
- `Topic1GraphSnapshotV1` 在反序列化时重新计算内容摘要，篡改快照会直接校验失败。

### 2.4 API、身份与资源保护

- 11 个 REST 端点统一返回 `topic1.api-envelope.v1`。
- OIDC scopes 分为 `topic1:read`、`topic1:write`、`topic1:import`、`topic1:freeze` 和
  `topic1:rollback`。
- 客户端租户与身份头仍由 Phase 1.1 中间件全局禁止。
- 所有写端点强制 16 至 160 字符的无空白幂等键，删除端点强制乐观修订号。
- 批量导入在 ASGI 层同时限制声明长度和 chunked 实际字节数，超限在 Pydantic 解析前返回
  413；领域层再执行 5 MiB、500 知识点和 2500 边的二次限制。

### 2.5 Provider 与四端契约

- Topic 1 仅允许 `spark_text` Provider alias，拒绝所有非白名单业务 AI Provider。
- 源文档必须绑定 64 位小写十六进制 SHA-256，Provider 不能直接写数据库。
- 11 个 Topic 1 Schema 已生成 JSON Schema、Python、TypeScript 和 Go 定义。
- `contract-catalog.json`、Schema registry、Go fmt/vet/race/build 和 TypeScript 编译均通过。

## 3. 自动控制原理权威种子资产

`data/topic1/automatic-control-principles.v1.json` 已通过契约、DAG 和真实 PostgreSQL 导入
回读测试，包含：

| 资产 | 数量 |
|---|---:|
| 核心知识点 | 13 |
| 先修依赖边 | 15 |
| 专业易错点 | 5 |
| 教材章节 | 7 |
| 知识点章节映射 | 13 |
| 黄金诊断题 | 5 |

资产覆盖建模、拉普拉斯变换、传递函数、时域指标、二阶响应、稳定性、劳斯判据、频率
响应、奈奎斯特判据、PID/串联校正、状态空间、能控性与能观性。公开文件只包含自编摘要、
结构化关系和诊断题，不复制教材正文，不包含有效服务凭据或未脱敏竞赛私有阈值。

## 4. 本地测试证据

| 门禁 | 结果 |
|---|---|
| Python 全量测试 | `164 passed, 1 skipped` |
| Windows skip | 仅符号链接能力不可用测试 |
| Python 行覆盖率 | `88.24%` |
| 覆盖率红线 | `>=88.00%` |
| Topic 1 PostgreSQL 集成 | `9 passed` |
| Topic 1 契约/API/算法/Provider | 全部通过 |
| 500 节点、2485 边拓扑性能基线 | `<5s` 红线通过 |
| Ruff lint/format | 0 findings |
| Alembic 往返与漂移 | 通过 / 0 drift |
| Go 契约 | fmt/vet/race/test/build 通过 |
| TypeScript 契约 | `tsc --noEmit` 通过 |
| Python / Node 依赖审计 | 0 blocking findings |
| Python / Node / Container SBOM | 已生成并通过许可证策略 |
| Non-root 生产容器 | `USER 10001:10001` 与最小运行时约束通过 |
| Trivy 容器漏洞 | 全等级 0 |
| Gitleaks 历史与工作树 | 0 findings |

无 `-Skip*` 参数的 `tools/windows/run-quality-gates.ps1` 已于
`2026-07-15T13:48:24Z` 完成，结果为 `passed`。机器证据保存在忽略提交的
`artifacts/quality-gates/`、`artifacts/coverage/`、`artifacts/sbom/` 和
`artifacts/security/`。

## 5. 分层兼容性结论

- 未修改 Phase 1.1 已冻结迁移 `20260714_0001` 至 `20260715_0003`。
- 未改变 TenantContext、数据库 session、Outbox、审计、幂等或持久化 SSE 语义。
- Topic 1 Outbox 事件外层复用冻结 `Topic3EnvelopeV1`，未改变 Envelope/Block/Candidate。
- 未实现或提前启动 Topic 2、Topic 3 Agent runtime、Topic 4 Verifier runtime 或前端业务层。
- Provider 范围仍严格限制为讯飞星火、讯飞代码和 SeeDance，本阶段只预留星火文本解析协议。

## 6. 远端正式验收证据

| 阶段 | Commit / PR | Run ID | Redline Job | 结果 |
|---|---|---:|---:|---|
| 功能分支 push | `691d4fa511b210c2cda5cd8294b81dd88615abd1` | `29421028846` | `87371628927` | success |
| Pull request | `#10` | `29421252666` | `87372190927` | success |
| main merge | `7eb9b940ed10dbca09c62d2caed809245e75ae5b` | `29421543279` | `87373314978` | success |

仓库只有一个管理员/CODEOWNER，GitHub 禁止最后推送者自我批准。两个远端门禁全绿后，
合并仅在受控窗口内临时移除 Classic 的 review 子规则；严格状态检查、管理员约束、PR
路径、线性历史、禁止 force-push/删除、main Ruleset 和标签 Ruleset 全程保留。合并后
`configure-repository-protection.ps1` 在 `finally` 中恢复完整 review 规则。

恢复后 API 回读确认至少 1 个批准、CODEOWNER、dismiss stale、last-push approval、严格
状态检查和管理员约束全部开启；直接 push、force-push、删除 main、删除受保护标签四类
探针全部被 GitHub 拒绝，远端 main 保持上述接受提交不变。

## 7. 冻结与解锁判定

以下 Topic 1 资产从 `ACCEPTED` 起不可侵入式修改：

- Alembic `20260715_0004` 及 9 张 Topic 1 表的租户/RLS/不可变约束；
- 11 个四端契约及 `topic1.graph-changed.v1` 事件语义；
- Repository、SERIALIZABLE 事务、幂等、审计、快照与 Outbox 原子顺序；
- DAG、层级、权重、难度等级、稳定排序和快照摘要规则；
- REST 路径、OIDC scopes、导入上限和 Spark-only Provider 边界。

后续只允许兼容式扩展。Topic 2 可读取版本化快照、知识点难度、拓扑层级、易错点和黄金
题库，禁止反向修改 Topic 1 数据语义或绕过 `snapshot_id + graph_version + content_sha256`
证据绑定。

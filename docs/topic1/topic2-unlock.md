# Topic 2 解锁凭证

## 1. 正式解锁状态

| 属性 | 值 |
|---|---|
| Topic 1 | `ACCEPTED` |
| Topic 1 main commit | `7eb9b940ed10dbca09c62d2caed809245e75ae5b` |
| Topic 2 | `UNLOCKED` |
| 解锁生效时间 | `2026-07-15T14:03:06Z` |

Topic 1 已完成本地与远端全部验收，服务端保护恢复并通过破坏性操作探针。依据不可逆
分层开发规则，现正式允许从最新受保护 main 创建 Topic 2 开发分支，开始六维无感画像、
艾宾浩斯记忆衰退和自适应学习路径运行时代码。

## 2. Topic 2 开发前置约束

- 从包含上述接受提交的最新 `main` 创建 `codex/topic2-*` 功能分支。
- 只读取 Topic 1 的版本化快照与公开 Repository/API，不修改 Topic 1 表和契约语义。
- 学生画像、遗忘参数和路径状态必须新建 Topic 2 租户域迁移，不复用 Topic 1 字段偷存。
- 所有画像更新继续复用 Phase 1.1 的 OIDC、RLS、幂等、审计和 Outbox。
- Topic 2 验收前不得启动 Topic 3 Agent runtime 或 Topic 4 Verifier runtime。

## 3. 解锁签发

本凭证由 Topic 1 分支、PR 和 main 三次远端 `Release quality redline`、受保护 PR #10、
main 提交及保护规则复核共同签发。Topic 2 从本文件生效后进入可编码状态。

# Topic 3 正式解锁凭证

## 1. 当前状态

| 属性 | 值 |
|---|---|
| Phase 1.1 | `ACCEPTED` |
| Topic 1 | `ACCEPTED` |
| Topic 2 | `ACCEPTED` |
| Topic 2 implementation commit | `00300f9797173275ab8743f2e089368370a0d85c` |
| Topic 2 accepted main commit | `327999c3eb230c572640a2f9772b2b185cb81107` |
| Topic 2 Pull Request | `#12` |
| Topic 3 | `UNLOCKED` |
| 解锁生效时间 | `2026-07-15T17:11:00Z` |

Topic 2 已完成完整本地 Release quality redline、功能分支远端 CI、受保护 Pull Request CI 和 main 合并 CI。依照不可逆分层开发规则，本文正式授权启动 Topic 3 五大业务 Agent 与 SSE 协同运行时编码。

## 2. 解锁证据

1. 本地全量测试 `195 passed, 1 skipped`，覆盖率 `89.14%`。
2. 功能分支 Run `29434959723` 成功。
3. PR `#12` Run `29435132359` 成功。
4. main Run `29435381238` 成功。
5. Trivy 全等级漏洞 0，Gitleaks 历史与工作树 0。
6. Classic review、main Ruleset 和 tags Ruleset 在合并后保持启用。

## 3. Topic 3 开发约束

- 必须从包含 accepted main commit 的最新 `main` 创建 `codex/topic3-*` 分支。
- 只能消费冻结的 `topic2.agent-context.v1` 和 `topic3.envelope.v1`。
- 不得修改迁移 `20260715_0005`、六维画像 v1、记忆策略 v1 或路径评分 v1 语义。
- Lecturer、MindMap、Tester、Code-Sandbox、Extension 必须通过兼容新增代码接入。
- Topic 4 与前端业务仍按既定分层锁定，不能因 Topic 3 解锁而提前侵入。

## 4. 解锁签发

本凭证由 Topic 2 本地验收、PR `#12`、三段远端 Release quality redline、受保护 main 提交和分支保护恢复校验共同签发。

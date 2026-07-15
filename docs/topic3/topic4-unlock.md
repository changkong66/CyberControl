# Topic 4 正式解锁凭证

## 1. 当前状态

| 属性 | 值 |
|---|---|
| Phase 1.1 | `ACCEPTED` |
| Topic 1 | `ACCEPTED` |
| Topic 2 | `ACCEPTED` |
| Topic 3 | `ACCEPTED` |
| Topic 3 implementation commit | `0ab96d283f30c97ee62292a383c33ac6797e327c` |
| Topic 3 branch evidence commit | `4afeaecf99419d1a97193679ba710525d5091665` |
| Topic 3 accepted main commit | `0b1c9d525c1e378940872f35f4a10322b53f2c55` |
| Topic 3 Pull Request | `#14` |
| Topic 4 C1-C12 | `UNLOCKED` |
| 前端业务层 | `LOCKED` |
| 解锁生效时间 | `2026-07-15T20:12:12Z` |

Topic 3 已完成本地 Release quality redline、功能分支远端 CI、受保护 Pull Request CI 和 main 合并 CI。依照不可逆分层开发规则，本文正式授权启动 Topic 4 C1-C12 学术防幻觉核验、自修正与最终发布闸门编码。

## 2. 解锁证据

1. 本地全量测试 `226 passed, 1 skipped`，覆盖率 `89.66%`，满足 `>=89%` 红线。
2. 功能分支 Run `29446618990` 成功。
3. PR `#14` Run `29446969374` 成功。
4. main Run `29447331017` 成功。
5. Trivy 全等级漏洞 0，Gitleaks 历史与工作树 0。
6. Topic 3 四端契约状态为 `CODED_TOPIC3_FROZEN`。
7. Classic review、main Ruleset、tag Ruleset、required status、force-push 和删除阻断均保持生效。

## 3. Topic 4 唯一授权范围

允许开发：

- C1 Verifier 统一调度、Claim 抽取、风险分级、聚合决策、SSE 发布闸门与审计恢复；
- C2 权威知识库、RAG 检索与版本化证据绑定；
- C3-C7 文本、公式/定理/数值、Mermaid、题库、代码沙箱、Extension 来源与许可证核验；
- C8 Self-Correction Revision 反向修正闭环；
- C9-C11 Prompt Injection、敏感信息、PII、多租户、审计、SBOM 与依赖治理；
- C12 全系统安全、压力、故障注入与端到端验收体系；
- 兼容新增 verification evidence、revision request 和 release authorization 契约及持久化资产。

## 4. 不可突破的冻结边界

- 不得修改 Phase 1.1、Topic 1、Topic 2 或 Topic 3 已冻结实现与 v1 契约语义。
- 不得改变 Topic 3 正向 Blueprint 的激活、依赖、波次、快照和执行状态机。
- 不得改变 Lecturer、MindMap、Tester、CodeSandbox、Extension 的 v1 输入输出语义。
- 不得让 staged Candidate 绕过 Verifier 获得最终发布授权。
- Topic 4 只能通过兼容新增反向 revision/release 链路接入。
- Provider 仅允许讯飞星火、讯飞代码与 SeeDance。
- 前端业务层继续锁定，直至 Topic 4 正式验收另行解锁。

## 5. 解锁签发

本凭证由 Topic 3 本地验收、PR `#14`、三段远端 Release quality redline、受保护 main 提交以及分支保护恢复回读共同签发。

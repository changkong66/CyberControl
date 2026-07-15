# Topic 4 解锁凭证

## 1. 当前状态

`LOCKED_PENDING_TOPIC3_REMOTE_ACCEPTANCE`

Topic 3 已完成编码并通过本地完整 Release quality redline，但尚未完成远端功能分支、受保护 Pull Request 和 main 合并后 CI。本文目前仅是待签发模板，不授权 Topic 4 编码。

## 2. 正式签发条件

- Topic 3 `acceptance-status.json` 为 `ACCEPTED`。
- Topic 3 implementation branch、PR 和 main 三段 CI 全绿。
- 覆盖率不低于 `89%`。
- Trivy 全等级漏洞 0，Gitleaks 历史与工作树 0。
- Topic 3 契约状态为 `CODED_TOPIC3_FROZEN`。
- 受保护 main 保留 required status、CODEOWNERS、禁止 force-push 和禁止删除规则。

## 3. 解锁后的唯一范围

满足条件后，只解锁 Topic 4 C1-C12 Verifier、RAG、学术事实核验、自修正和最终发布闸门。Topic 4 只能新增反向 revision/release 链路，不得修改 Topic 3 正向 Blueprint、Agent 或 Candidate v1 语义。

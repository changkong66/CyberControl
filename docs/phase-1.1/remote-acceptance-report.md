# Phase 1.1 GitHub 远端正式验收报告

## 1. 验收结论

| 项目 | 结果 |
|---|---|
| Repository | `changkong66/CyberControl` |
| Visibility | Public |
| Accepted baseline | `611375cd8f40dfb88d418685695b5bb1a9436d7d` |
| Required status | `Release quality redline` |
| Phase branch CI | 通过 |
| main CI | 通过 |
| Classic protection | API 回读通过 |
| Repository Rulesets | 2 个 Active 规则集，API 回读通过 |
| Public security audit | 0 findings / 0 open alerts |
| Phase status | `ACCEPTED` |
| Topic 1 | `UNLOCKED` |

Phase1.1 本地基础设施、GitHub Actions 远端复现、服务端主干保护、标签不可变规则和公开
仓库安全控制已经全部闭环。此前 GitHub Free 私有仓库返回 403 的阻塞通过项目所有者
批准切换为 Public 后消除；本报告替代所有旧的 `REMOTE_PENDING` 判定。

## 2. 远端 CI 证据

### 2.1 Phase1.1 分支最终基线

- Branch：`codex/phase-1.1-foundation`
- Commit：`611375cd8f40dfb88d418685695b5bb1a9436d7d`
- Workflow run：<https://github.com/changkong66/CyberControl/actions/runs/29400649820>
- Run ID：`29400649820`
- Redline job ID：`87304401906`
- Conclusion：`success`

### 2.2 main 最终基线

- Branch：`main`
- Commit：`611375cd8f40dfb88d418685695b5bb1a9436d7d`
- Workflow run：<https://github.com/changkong66/CyberControl/actions/runs/29400659103>
- Run ID：`29400659103`
- Redline job ID：`87304437634`
- Conclusion：`success`

验收文档与治理脚本后续提交仍必须触发同一聚合红线。提交无法在自身内容中写入尚未
生成的 run ID，因此精确的最新运行证据由 GitHub Actions 与提交 SHA 永久关联，并由
`tools/github/verify-remote-quality-gate.ps1` 写入本地机器证据。

## 3. Release 质量红线复现矩阵

| 门禁 | 远端结果 |
|---|---|
| Conventional Commit 全历史校验 | 通过 |
| Actionlint | 0 findings |
| Ruff lint/format | 0 findings |
| 冻结契约再生成与漂移 | 0 drift |
| Python 单元与 PostgreSQL 集成测试 | 115 passed, Linux 执行 Windows symlink skip 用例 |
| Alembic upgrade/downgrade/upgrade | 通过 |
| Python coverage redline | `>=85%`，基线 85.42% |
| Go fmt/vet/race/test/build | 通过 |
| Vue/TypeScript/Vite | 通过 |
| pnpm/Python dependency audit | 0 blocking findings |
| Python/Node/Container CycloneDX SBOM | 生成并上传 |
| License policy | 通过 |
| Non-root minimal container | 通过 |
| Trivy complete/fixable scan | 全等级 0 vulnerabilities |
| Gitleaks history/worktree | 0 findings |

## 4. Classic Branch Protection 验收

`tools/github/configure-repository-protection.ps1` 对 `main` 幂等应用并回读以下规则：

- strict required status：`Release quality redline`；
- 所有变更必须经 PR；
- 至少 1 个批准，强制 CODEOWNERS、dismiss stale reviews 和 last-push approval；
- required conversation resolution；
- required linear history；
- administrators enforced；
- force-push disabled；
- branch deletion disabled；
- Actions 默认 `GITHUB_TOKEN` 为 read-only，不能批准 PR。

Classic API PUT 与 GET 均返回成功，`api_readback_verified=true`。个人仓库对现有默认分支
固定回读 `block_creations=false`，但 `main` 删除已由 Classic 和 Ruleset 双层阻断，且
默认分支自身不能被删除，因此不构成验收缺口。

## 5. Repository Rulesets 验收

### 5.1 main-release-governance

| 属性 | 值 |
|---|---|
| Ruleset ID | `18985297` |
| Target | default branch |
| Enforcement | `active` |
| Rules | deletion, non-fast-forward, linear history, pull request, required status checks |
| Required status | `Release quality redline` |
| Bypass | Repository Admin, `pull_request` mode only |

仓库当前只有 `@changkong66` 一个管理员和 CODEOWNER。GitHub 禁止提交者自我批准，
因此 Admin 的 PR-only bypass 是避免所有者 PR 永久不可合并的最小临时通道；它不能用于
直接 push。新增第二名可信 CODEOWNER 后，应优先执行常规双门槛，不使用 bypass。

Repository Ruleset 元数据接口对当前个人公开仓库拒绝 `commit_message_pattern`。提交规范
由 GitHub Actions 的 `tools/validate_commit_messages.py` 执行，并被必需聚合状态绑定；
格式不合规的提交不能合并到 `main`。

### 5.2 immutable-release-tags

| 属性 | 值 |
|---|---|
| Ruleset ID | `18985299` |
| Target | `refs/tags/*` |
| Enforcement | `active` |
| Rules | deletion, non-fast-forward |
| Bypass actors | none |

## 6. Git 协议违规探针

执行 `tools/github/test-repository-protection.ps1`，结果如下：

| 探针 | GitHub 结果 | 远端影响 |
|---|---|---|
| 新提交直接 push 到 main | `GH013`, rejected | 无 |
| orphan commit force-push 到 main | `GH013`, rejected | 无 |
| 删除 main | remote rejected | 无 |
| 删除 `phase-1.1-baseline-611375c` 标签 | `GH013`, rejected | 无 |

探针完成后远端 `main` 仍为
`611375cd8f40dfb88d418685695b5bb1a9436d7d`。脚本只创建临时 Git object，不修改本地
分支或工作树。

## 7. Public 安全二次巡检

仓库切换 Public 后执行了独立安全复核：

- Gitleaks 8.30.1 发布包 SHA-256 固定并校验；
- 所有可达历史提交 findings：0；
- 当前工作树 findings：0；
- GitHub Secret Scanning：enabled；
- GitHub Push Protection：enabled；
- GitHub open secret alerts：0；
- 有效讯飞星火、讯飞代码、SeeDance 凭证：0；
- 生产数据库口令、JWT 私钥、PII：0；
- 未脱敏黄金评测集、完整私有 Prompt、核验阈值和评分权重：0。

完整范围与竞赛资产分级见
`docs/security/public-repository-security-audit.md`。

## 8. 解锁判定

Phase1.1 的代码质量、远端 CI、服务端分支保护、不可变标签和公开仓库安全前置条件均已
满足，状态正式切换为 `ACCEPTED`。允许创建
`codex/topic1-knowledge-topology` 并开始 Topic1 编码。

Topic2、Topic3 Agent runtime、Topic4 Verifier runtime 和前端业务工作台继续保持锁定，
直到各自直接前置阶段通过独立验收。Phase1.1 的租户身份、RLS、事务、Outbox、审计、
持久化 SSE 和冻结 Envelope 语义不得被 Topic1 侵入式修改。

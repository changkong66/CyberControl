# Phase 1.1 GitHub 远端正式验收报告

## 1. 验收结论

| 项目 | 结果 |
|---|---|
| Repository | `changkong66/CyberControl` |
| Visibility | Private |
| Code baseline | `bca073fc94ceaca1f5d20783705ae4b70c00e590` |
| Governance baseline | `39e7f016a071f435ad9fcf56876ae5866625ef97` |
| Required status | `Release quality redline` |
| Remote CI | 通过 |
| main protection | API 回读通过 |
| Phase status | `ACCEPTED` |
| Topic 1 | 正式解锁 |

## 2. 远端 CI 证据

### 2.1 Phase 1.1 分支

- Branch：`codex/phase-1.1-foundation`
- Commit：`39e7f016a071f435ad9fcf56876ae5866625ef97`
- Workflow run：<https://github.com/changkong66/CyberControl/actions/runs/29399037874>
- Run ID：`29399037874`
- Redline job ID：`87299312349`
- Conclusion：`success`

### 2.2 main 初始化基线

- Branch：`main`
- Commit：`39e7f016a071f435ad9fcf56876ae5866625ef97`
- Workflow run：<https://github.com/changkong66/CyberControl/actions/runs/29399212865>
- Run ID：`29399212865`
- Redline job ID：`87299892896`
- Conclusion：`success`

最终验收文档提交同样必须在 Phase 分支和 `main` 触发该工作流。由于提交无法在自身
内容中包含尚未生成的 run ID，最终 run 的精确机器证据由
`tools/github/verify-remote-quality-gate.ps1` 写入
`artifacts/quality-gates/remote-ci.json`，并由 GitHub Actions 永久关联到提交。

## 3. 远端门禁复现矩阵

| 门禁 | 远端结果 |
|---|---|
| Conventional Commit 全历史校验 | 通过 |
| Actionlint | 0 findings |
| Ruff lint/format | 0 findings |
| 冻结契约再生成与漂移 | 0 drift |
| Python 单元与 PostgreSQL 集成测试 | 通过 |
| Alembic upgrade/downgrade/upgrade | 通过 |
| Python coverage redline | `>=85%` |
| Go fmt/vet/race/test/build | 通过 |
| Vue/TypeScript/Vite | 通过 |
| pnpm/Python dependency audit | 0 blocking findings |
| Python/Node/Container CycloneDX SBOM | 生成并上传 |
| License policy | 通过 |
| Non-root minimal container | 通过 |
| Trivy complete/fixable scan | 0 vulnerabilities |
| Gitleaks history/worktree | 0 findings |

Windows 无法创建符号链接而跳过的路径安全用例在 GitHub Linux runner 中执行，远端
成功结果消除了本地单一 skip 的残余风险。

## 4. main 保护冻结

最终保护必须同时满足：

- strict required status：`Release quality redline`；
- PR required，至少一个批准；
- Code Owner review、stale review dismissal、last-push approval；
- conversation resolution 和 linear history；
- administrators enforced；
- force-push、branch deletion 和 matching-ref creation 禁止；
- Actions 默认 `GITHUB_TOKEN` 为 read-only，不能批准 PR。

配置与回读由 `tools/github/configure-repository-protection.ps1` 完成，机器证据保存在
`artifacts/quality-gates/branch-protection.json`。

## 5. 空仓库 bootstrap 边界

远端初始没有 `main` 引用，因此先把已经通过 Phase 分支远端红线的治理提交一次性
创建为 `main`，再执行 `main` 自身 CI。最终验收台账提交后立即应用保护。该过程只
用于首次仓库初始化；保护生效后不存在直接推送、管理员绕过或紧急例外。

## 6. 解锁判定

Phase 1.1 的事务、租户身份、RLS、Outbox、幂等、审计、Artifact、SSE、容器和供应链
边界全部冻结。Topic 1 可以从冻结数据模型的 repository/service 绑定开始；Topic 2、
Topic 3 Agent runtime、Topic 4 Verifier runtime 和前端业务工作台继续锁定。

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
| main protection | GitHub Free 私有仓库套餐阻塞 |
| Phase status | `REMOTE_PENDING` |
| Topic 1 | 锁定 |

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

### 2.3 最终验收台账提交

- Commit：`fe3482bb8662281c21359af66e952e69e827b958`
- Phase branch run：<https://github.com/changkong66/CyberControl/actions/runs/29399883914>
- Phase redline job ID：`87301948744`
- main run：<https://github.com/changkong66/CyberControl/actions/runs/29400001506>
- main redline job ID：`87302395191`
- 两次 conclusion：`success`

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

## 4. main 保护阻塞

最终保护必须同时满足：

- strict required status：`Release quality redline`；
- PR required，至少一个批准；
- Code Owner review、stale review dismissal、last-push approval；
- conversation resolution 和 linear history；
- administrators enforced；
- force-push、branch deletion 和 matching-ref creation 禁止；
- Actions 默认 `GITHUB_TOKEN` 为 read-only，不能批准 PR。

账户 `changkong66` 对仓库具有 admin 权限，但账户计划为 GitHub Free，仓库为
Private。经典 Branch Protection API 与 Repository Rulesets API 均返回 HTTP 403，
因此上述控制无法在服务器端生效。这不是 Token 权限问题，也不能用失败后报警的 CI
替代真正的 push 阻断。

套餐允许的治理项已经配置并回读：默认分支 `main`、禁用 merge commit、允许
squash/rebase、合并后删除分支、Actions 默认只读且不能批准 PR。

## 5. 空仓库 bootstrap 边界

远端初始没有 `main` 引用，因此先把已经通过 Phase 分支远端红线的治理提交一次性
创建为 `main`，再执行 `main` 自身 CI。由于保护 API 受套餐阻塞，bootstrap 已完成但
正式验收尚未完成；在升级 GitHub Pro/Team 或经项目所有者明确批准公开仓库前，不得
继续 Topic 1。

## 6. 解锁判定

Phase 1.1 的本地与远端 CI 已通过，但服务器端分支保护是硬性解锁条件。当前 Topic 1、
Topic 2、Topic 3 Agent runtime、Topic 4 Verifier runtime 和前端业务工作台全部锁定。

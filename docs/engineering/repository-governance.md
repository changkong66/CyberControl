# GitHub 仓库治理与远端验收规范

## 1. 仓库身份

| 项目 | 固定值 |
|---|---|
| Repository | `changkong66/CyberControl` |
| HTTPS remote | `https://github.com/changkong66/CyberControl.git` |
| Release branch | `main` |
| Phase 1.1 branch | `codex/phase-1.1-foundation` |
| Required status | `Release quality redline` |

绑定前必须读取并核对远端仓库身份，禁止把同名公开仓库当作目标：

```powershell
git remote add origin https://github.com/changkong66/CyberControl.git
git remote get-url origin
git fetch origin --prune
```

若 `origin` 已存在但 URL 不一致，停止操作并人工确认；禁止静默覆盖。

## 2. GH_TOKEN 最小权限

推荐创建仅授权 `changkong66/CyberControl` 的 fine-grained personal access token。

Repository permissions 必须包含：

| 权限 | 级别 | 用途 |
|---|---|---|
| Metadata | Read-only | 仓库身份和基础元数据 |
| Contents | Read and write | 分支推送、引用和提交读取 |
| Actions | Read and write | 读取、重跑和调度工作流 |
| Administration | Read and write | 分支保护和 Actions 默认权限 |
| Pull requests | Read and write | 创建、读取和合并受保护 PR |
| Commit statuses | Read and write | 查询/维护必需状态上下文 |

Classic PAT 仅作为兼容方案，至少需要 `repo` 和 `workflow` scope。Token 禁止写入
`.env`、Git config、PowerShell profile、脚本参数、命令历史或 CI artifact。

在当前 PowerShell 进程安全注入：

```powershell
. .\tools\github\set-gh-token.ps1
```

已通过 Git Credential Manager 登录时，可复用其当前凭据：

```powershell
. .\tools\github\set-gh-token.ps1 -FromGitCredentialManager
```

使用结束后立即清除：

```powershell
. .\tools\github\set-gh-token.ps1 -Clear
```

## 3. 分支与提交规则

- `main` 禁止直接推送、force-push 和删除。
- 所有变更必须来自 PR；至少一个批准且必须包含 Code Owner 审核。
- 必须解决全部 review conversation，使用线性历史。
- 管理员同样受保护规则约束。
- Commit/PR 标题遵循 `<type>(<optional-scope>)!: <summary>`，总长度不超过
  100 字符；允许类型由 `CONTRIBUTING.md` 冻结。
- `WIP`、`fixup!`、`squash!` 和 merge commit 不得进入受保护历史。

提交校验由 `tools/validate_commit_messages.py` 完成，并属于最终聚合状态的前置任务，
因此不能通过仅修改分支保护配置绕过。

## 4. 远端验收流程

推送 Phase 1.1 分支：

```powershell
git push --set-upstream origin codex/phase-1.1-foundation
```

等待并验证精确提交的远端红线：

```powershell
& .\tools\github\verify-remote-quality-gate.ps1 `
  -Repository "changkong66/CyberControl" `
  -Branch "codex/phase-1.1-foundation" `
  -ExpectedCommit (git rev-parse HEAD)
```

应用并回读 `main` 保护：

```powershell
& .\tools\github\configure-repository-protection.ps1 `
  -Repository "changkong66/CyberControl" `
  -Branch "main" `
  -RequiredContext "Release quality redline"
```

脚本必须确认严格状态检查、管理员约束、线性历史、conversation resolution、禁止
force-push 和禁止删除全部生效。API 回读证据写入受控验收台账。

### 4.1 服务端规则固定参数

| 控制面 | 规则 | 固定值 |
|---|---|---|
| Classic Protection | Required status | `Release quality redline`, strict |
| Classic Protection | Pull request reviews | 1 approval, CODEOWNERS, dismiss stale, last-push approval |
| Classic Protection | Admin enforcement | enabled |
| Classic Protection | History and refs | linear, no force-push, no deletion |
| Branch Ruleset | Name | `main-release-governance` |
| Branch Ruleset | Rules | deletion, non-fast-forward, PR, linear history, required status |
| Branch Ruleset | Bypass | Repository Admin, `pull_request` mode only |
| Tag Ruleset | Name | `immutable-release-tags` |
| Tag Ruleset | Match | `refs/tags/*` |
| Tag Ruleset | Rules | deletion and non-fast-forward blocked, no bypass actor |

仓库规则元数据接口当前不接受 `commit_message_pattern`。Conventional Commit 由 GitHub
Actions 中的 `tools/validate_commit_messages.py` 执行，并被最终必需状态上下文聚合；不合规
提交可以存在于开发分支，但不能合并到 `main`。这属于 GitHub 当前账户能力边界，不得在
验收材料中表述为推送阶段正则拦截。

### 4.2 GitHub 网页端复核路径

1. 打开 `Settings > Rules > Rulesets`，确认两个规则集均为 `Active`。
2. 打开 `main-release-governance`，确认目标为默认分支，且启用删除阻断、非快进阻断、
   PR、线性历史和 `Release quality redline`。
3. 确认唯一 bypass actor 是 `Repository Admin`，模式是 `For pull requests only`。
4. 打开 `immutable-release-tags`，确认包含 `refs/tags/*`，且 bypass actor 为空。
5. 打开 `Settings > Branches > Branch protection rules > main`，确认管理员同样受约束、
   CODEOWNER 审核、最后推送批准、对话解决和严格状态检查全部开启。
6. 打开 `Settings > Actions > General`，确认 `GITHUB_TOKEN` 默认权限为只读，Actions
   不得创建或批准 PR。

使用实际 Git 协议验证服务端阻断并生成证据：

```powershell
& .\tools\github\test-repository-protection.ps1
```

脚本使用 `git commit-tree` 创建不关联工作分支的探针对象，依次测试直接推送、强推、
删除 `main` 和删除受保护标签；完成后必须确认远端 SHA 未变化。

## 5. 一次性 main 初始化边界

空仓库没有可保护的 `main` 引用。仅允许将已经通过远端红线的 Phase 1.1 提交一次性
创建为 `main`，随后必须等待 `main` 自身工作流成功并立即应用保护。该动作属于仓库
bootstrap，不构成后续直接推送例外。

保护生效后，任何紧急修复也必须走 `security/*` 或 `fix/*` 分支和同一质量红线。

## 6. 公开仓库常态化安全管控

### 6.1 推送前强制检查

每次推送前必须执行：

```powershell
& .\tools\windows\invoke-public-security-audit.ps1
& .\tools\windows\run-quality-gates.ps1
```

仓库所有者首次切换为 Public 或安全设置漂移后，还必须执行：

```powershell
. .\tools\github\set-gh-token.ps1 -FromGitCredentialManager
& .\tools\github\configure-public-repository-security.ps1 `
  -Repository "changkong66/CyberControl"
. .\tools\github\set-gh-token.ps1 -Clear
```

该脚本启用 GitHub Secret Scanning、Push Protection、漏洞告警和自动安全修复，并要求
open secret-scanning alert 数为 0。

安全脚本固定下载 Gitleaks 8.30.1 Windows x64 发布包并校验 SHA-256，同时扫描工作树与
所有可达历史提交。报告只允许保存于已忽略的 `artifacts/security/`，且必须启用 100%
redaction。任何 finding 或意外敏感文件名均阻断推送。

### 6.2 月度全历史巡检

- 每月首个工作日重新执行全历史和工作树扫描。
- 回读 GitHub Secret Scanning alerts，要求 open alert 数为 0。
- 检查 `.gitignore`、`.gitleaks.toml` 和 Provider 配置模板是否仍覆盖新增文件类型。
- 将日期、提交 SHA、Gitleaks 版本、规则版本和 finding 数写入安全巡检报告。

### 6.3 竞赛资产分级披露

| 级别 | 可入公开仓库 | 处理规则 |
|---|---|---|
| Public | API 契约、通用架构、可复现测试、脱敏示例数据 | 正常 PR 与 CI |
| Controlled | Prompt 模板骨架、核验阈值接口、评测结构 | 仅发布去参数化版本 |
| Restricted | 完整系统 Prompt、黄金评测集、对抗样本、评分权重、未公开创新算法参数 | 仅存放于仓库外加密存储 |
| Secret | Provider 凭证、数据库口令、JWT 私钥、真实用户数据 | 密钥管理系统，禁止落盘入库 |

本地受控材料必须放入 `docs/private/`、`docs/drafts/`、`private-assets/` 或
`restricted-assets/`。这些路径由 `.gitignore` 阻断。公开代码仅保留 Provider 接口、环境
变量名和脱敏占位值。

### 6.4 密钥泄露响应

1. 立即吊销和轮换凭证，不等待 Git 历史清理完成。
2. 暂停发布并保全 GitHub alert、提交 SHA、访问日志和审计证据。
3. 使用 `git filter-repo` 在隔离镜像中重写全部受影响引用；禁止直接在主工作区试错。
4. 由仓库所有者临时停用冲突规则，镜像校验后强制替换远端全部受影响引用，并立即恢复规则。
5. 重新运行 Gitleaks 全历史扫描、CI、安全回归和 Provider 访问日志审计。
6. 记录根因、暴露窗口、轮换凭证、受影响租户和防复发控制；不得在公开 issue 粘贴密钥原文。

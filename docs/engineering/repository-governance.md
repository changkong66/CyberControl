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

## 5. 一次性 main 初始化边界

空仓库没有可保护的 `main` 引用。仅允许将已经通过远端红线的 Phase 1.1 提交一次性
创建为 `main`，随后必须等待 `main` 自身工作流成功并立即应用保护。该动作属于仓库
bootstrap，不构成后续直接推送例外。

保护生效后，任何紧急修复也必须走 `security/*` 或 `fix/*` 分支和同一质量红线。

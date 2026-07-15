# 公开仓库安全二次巡检验收报告

## 1. 验收身份

| 项目 | 结果 |
|---|---|
| Repository | `changkong66/CyberControl` |
| Visibility | `public` |
| 审计基线 | `611375cd8f40dfb88d418685695b5bb1a9436d7d` |
| 审计日期 | 2026-07-15 |
| Gitleaks | 8.30.1 |
| Windows x64 archive SHA-256 | `d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e` |

本报告覆盖仓库由 Private 切换为 Public 后的第二次安全验收。报告不记录任何 secret
原文；机器可读的本地扫描证据保存在被 `.gitignore` 排除的 `artifacts/security/` 和
`artifacts/quality-gates/`。

## 2. 扫描范围与方法

### 2.1 Git 历史与工作树

执行：

```powershell
& .\tools\windows\invoke-public-security-audit.ps1
```

脚本执行以下控制：

1. 校验 Gitleaks 发布包 SHA-256 后运行固定版本二进制。
2. 使用仓库自有 `.gitleaks.toml` 扫描所有可达 Git 历史提交。
3. 独立扫描当前工作树，包括未跟踪但未被允许列表排除的文件。
4. 以 `--redact=100` 输出 JSON 证据，禁止在日志暴露匹配内容。
5. 复核敏感文件名，允许的唯一候选是脱敏模板 `.env.example`。

### 2.2 GitHub 服务端控制

执行：

```powershell
. .\tools\github\set-gh-token.ps1 -FromGitCredentialManager
& .\tools\github\configure-public-repository-security.ps1 `
  -Repository "changkong66/CyberControl"
. .\tools\github\set-gh-token.ps1 -Clear
```

脚本通过 GitHub REST API 启用并回读 Secret Scanning、Push Protection、漏洞告警和
自动安全修复；验收要求 open secret-scanning alerts 为 0。

## 3. 量化结果

| 检查项 | 结果 | 判定 |
|---|---:|---|
| Gitleaks 全历史 findings | 0 | PASS |
| Gitleaks 工作树 findings | 0 | PASS |
| 意外敏感文件名 | 0 | PASS |
| GitHub open secret alerts | 0 | PASS |
| GitHub Secret Scanning | enabled | PASS |
| GitHub Push Protection | enabled | PASS |
| Provider 有效凭证 | 0 | PASS |
| JWT/签名私钥 | 0 | PASS |
| 生产数据库凭证 | 0 | PASS |
| 真实用户 PII/账号口令 | 0 | PASS |

`.env.example` 和测试基础设施包含明确标注为 `local-only` 的本机 PostgreSQL 开发口令、
空 Provider 变量和不可用于生产的占位值。这些值不具备外部系统访问能力，不属于有效
凭证；生产部署必须由密钥管理系统注入独立随机凭证。

## 4. 竞赛核心资产披露复核

### 4.1 允许公开的现有资产

- Phase1.1 通用持久化、事务、审计、SSE 和 OIDC 工程实现。
- Topic3 已冻结的 Envelope/Block/Candidate 公开契约与兼容边界。
- Provider 白名单接口、环境变量名称和禁用状态，不包含供应商有效凭证。
- 通用 RAG、SSE、CI、SBOM 与多租户安全 ADR，不包含私有黄金语料和运行参数。

### 4.2 仓库中不存在的受限资产

- 讯飞星火、讯飞代码、SeeDance 的有效 APP ID、API key、API secret 或签名材料。
- 完整系统 Prompt、Self-Correction 私有 Prompt 链和 Prompt Injection 对抗词库。
- 软件杯黄金评测集、未发布对抗样本、评审权重、核验阈值和差异化算法私有参数。
- 未脱敏学生数据、教师账号、租户标识映射和真实学习行为日志。
- 未成型创新草稿、内部风险分析原稿和仓库外商业合作材料。

后续受限资产只能进入仓库外加密存储。本地临时文件必须使用 `docs/private/`、
`docs/drafts/`、`private-assets/` 或 `restricted-assets/`，这些路径已由 `.gitignore`
阻断。

## 5. 风险处置与持续控制

| 风险 | 控制 |
|---|---|
| 开发者误提交 `.env` 或私钥 | `.gitignore` + Gitleaks 工作树扫描 + GitHub Push Protection |
| 历史提交残留凭证 | 月度 `gitleaks git --all` + GitHub Secret Scanning |
| 核心竞赛参数过度披露 | Public/Controlled/Restricted/Secret 四级分类 |
| 扫描工具供应链替换 | 固定版本、发布包 SHA-256 校验、CI 固定 Action SHA |
| 密钥泄露后仅删除文件 | 先吊销轮换，再隔离重写历史并全量复验 |

## 6. 验收结论

公开仓库二次安全巡检通过。工作树、全部可达历史提交与 GitHub 服务端告警均为零风险，
服务端 Push Protection 已启用，仓库未发现有效第三方凭证、生产数据库口令、JWT 私钥、
PII 或受限竞赛资产。该结果满足 Phase1.1 从 `REMOTE_PENDING` 切换为 `ACCEPTED` 的安全
前置条件。

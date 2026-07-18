# 立言 CyberControl

面向《自动控制原理》等自动化专业核心课程的个性化教学多智能体平台。系统使用
Python 3.11、全异步 FastAPI、SQLAlchemy Async、PostgreSQL RLS、Vue 3、Tailwind
CSS 与持久化 SSE，业务 AI Provider 严格限制为讯飞星火文本、讯飞代码和 SeeDance。

仓库地址：<https://github.com/changkong66/CyberControl>

## 当前工程阶段

- Phase 1.1 与 Topic 1-Topic 4 后端链路均已完成验收并冻结；Topic 4 PR
  [#16](https://github.com/changkong66/CyberControl/pull/16) 已通过受保护 PR 流程
  Squash Merge 到 `main`。
- 当前受保护主干为 `190ed863c13f8f71d909b6083b929c899e4db69f`，主干
  [Release Quality Gates Run 29639495363](https://github.com/changkong66/CyberControl/actions/runs/29639495363)
  八项任务全部成功。
- 当前正式阶段为 Phase 6 Frontend Integration；`codex/frontend-workbench` 已创建且
  前端解锁凭证生效。既有 Topic 1-Topic 4 契约和后端语义不得被前端反向修改。
- Phase 7 G0-G12 系统验收、长稳压测、灾难恢复与最终黄金数据集尚未执行，不得把
  Topic 4 模块验收等同于整套产品最终验收。

权威历史与当前状态分别见
[`docs/phase-1.1/acceptance-status.json`](docs/phase-1.1/acceptance-status.json)、
[`docs/topic1/acceptance-status.json`](docs/topic1/acceptance-status.json) 和
[`docs/topic4/acceptance-status.json`](docs/topic4/acceptance-status.json)。历史验收文件是
对应提交时点的证据快照，不因当前阶段推进而重写。

## 目录结构

```text
backend/                    FastAPI 服务、领域层和基础设施适配器
frontend/                   Vue 3 前端工程
packages/contracts-python/  Pydantic 契约唯一事实源
packages/contracts-ts/      自动生成的 TypeScript 契约
packages/contracts-go/      自动生成的 Go 契约
schemas/                    自动生成的 JSON Schema
config/                     非敏感 Provider 与运行策略
docs/                       ADR、专题冻结设计、工程和验收文档
infra/                      Docker、PostgreSQL 初始化与部署资产
tools/                      契约、质量门禁、GitHub 和 Windows 自动化脚本
```

## Windows 一键启动

前置条件：Docker Desktop 已启动，默认 `5432` 和 `8000` 端口空闲。

```powershell
& .\tools\windows\start-local.ps1
```

端口冲突时显式指定：

```powershell
& .\tools\windows\start-local.ps1 -PostgresPort 55433 -ApiPort 18000
```

停止服务并保留数据卷：

```powershell
& .\tools\windows\stop-local.ps1
```

停止服务并删除本地 Compose 数据卷：

```powershell
& .\tools\windows\stop-local.ps1 -RemoveVolumes
```

开发 Compose 不内置 OIDC Provider，因此 `/health/live` 应返回 `200`，而
`/health/ready` 在身份提供方未配置时按 fail-closed 规则返回 `503`。

## 可复现开发环境

```powershell
& .\tools\windows\sync-python-environment.ps1
pnpm --dir frontend install --frozen-lockfile
```

完整 Windows 环境、PostgreSQL 测试角色和质量门禁操作见
[`docs/engineering/windows-environment-reproduction.md`](docs/engineering/windows-environment-reproduction.md)。

## 质量红线

```powershell
& .\tools\windows\run-quality-gates.ps1
```

无参数运行才是本地发布等价验收。任何 `-Skip*` 参数仅用于故障诊断，不能作为验收
证据。远端合并必须通过 GitHub Actions 的 **Release quality redline**，覆盖：

- Conventional Commit 校验、Actionlint、Ruff 和冻结契约漂移；
- PostgreSQL 迁移往返、RLS/事务/恢复集成测试和覆盖率红线；
- Go fmt/vet/race/test/build 与 Vue/TypeScript/Vite；
- Python/Node 审计、CycloneDX SBOM、许可证策略；
- 非 root 最小容器、Trivy 和完整 Git 历史 Gitleaks。

Python 覆盖率的流水线硬阈值为 `90%`；`91.19%` 是 Topic 4 合并时的观测值，不是
可被文档重新定义的门禁配置。

## 分支与贡献

`main` 是受保护发布基线。功能开发使用 `codex/*`、`feature/*`、`fix/*`、
`security/*` 或 `release/*` 分支，通过 PR 合并。提交和 PR 标题必须符合 Conventional
Commits。完整策略见 [`CONTRIBUTING.md`](CONTRIBUTING.md) 和
[`docs/engineering/repository-governance.md`](docs/engineering/repository-governance.md)。

## 关键冻结文档

- [`docs/roadmap/implementation-sequence.md`](docs/roadmap/implementation-sequence.md)
- [`docs/topic3/envelope-and-infrastructure.md`](docs/topic3/envelope-and-infrastructure.md)
- [`docs/engineering/ci-quality-gates.md`](docs/engineering/ci-quality-gates.md)
- [`docs/phase-1.1/final-acceptance-report.md`](docs/phase-1.1/final-acceptance-report.md)
- [`docs/topic1/architecture.md`](docs/topic1/architecture.md)
- [`docs/topic1/api-examples.md`](docs/topic1/api-examples.md)

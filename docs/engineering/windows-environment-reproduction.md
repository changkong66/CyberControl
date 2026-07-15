# Windows 可复现开发环境与本地运行规范

## 1. 固定工具链

| 工具 | 基线 |
|---|---:|
| Windows | 10/11 x64，PowerShell 5.1 或 7 |
| Python | 3.11 |
| uv | 0.11.28 |
| Node.js | 22.20.0 |
| pnpm | 11.7.0 |
| Go | `go.mod` 兼容版本，CI 最低 1.22.x |
| Docker Desktop | 支持 Compose v2 和 Linux containers |
| PostgreSQL | digest-pinned 16 Alpine container |

## 2. 首次环境安装

管理员终端安装机器级工具：

```powershell
& .\tools\windows\install-dev-dependencies.ps1 -Scope Machine
```

普通终端安装用户级工具：

```powershell
& .\tools\windows\install-dev-dependencies.ps1 -Scope User
```

脚本只负责 Go/Ruff/GCC/Make 等原生工具。Node.js、pnpm、Python 3.11 和 Docker
Desktop 必须在执行后通过以下命令确认：

```powershell
python --version
uv --version
node --version
pnpm --version
go version
docker version
docker compose version
```

## 3. 锁文件复现

Python workspace：

```powershell
& .\tools\windows\sync-python-environment.ps1
```

前端：

```powershell
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend run typecheck
pnpm --dir frontend run build
```

任何命令不得更新 `uv.lock` 或 `frontend/pnpm-lock.yaml`。需要升级依赖时必须使用独立
`chore(deps-*)` 分支并重新生成 SBOM。

## 4. Docker 一键运行

```powershell
& .\tools\windows\start-local.ps1
```

自定义端口和 Compose project：

```powershell
& .\tools\windows\start-local.ps1 `
  -ProjectName "liyans-local-dev" `
  -PostgresPort 55433 `
  -ApiPort 18000
```

脚本执行以下硬检查：Docker daemon 可用、端口未占用、Compose 配置有效、migration
成功、API 容器健康和 `/health/live` 返回 `live`。失败时默认输出最近 200 行日志并
删除该 project 的容器和数据卷；`-KeepFailedStack` 仅用于诊断。

停止并保留 PostgreSQL/Artifact 数据：

```powershell
& .\tools\windows\stop-local.ps1 -ProjectName "liyans-local-dev"
```

停止并删除该 project 数据卷：

```powershell
& .\tools\windows\stop-local.ps1 `
  -ProjectName "liyans-local-dev" `
  -RemoveVolumes
```

## 5. PostgreSQL 集成测试

使用隔离测试数据库并配置三种最小权限角色 URL：

```powershell
$env:LIYAN_TEST_DATABASE_URL = `
  "postgresql+asyncpg://liyans_app:<password>@127.0.0.1:55432/liyans"
$env:LIYAN_TEST_MIGRATION_DATABASE_URL = `
  "postgresql+asyncpg://liyans_migrator:<password>@127.0.0.1:55432/liyans"
$env:LIYAN_TEST_DISPATCHER_DATABASE_URL = `
  "postgresql+asyncpg://liyans_dispatcher:<password>@127.0.0.1:55432/liyans"
& .\tools\windows\run-postgres-integration.ps1
```

凭据只能来自本地临时环境变量或受控 secret store，不得提交真实密码。

## 6. 发布等价质量门禁

```powershell
& .\tools\windows\run-quality-gates.ps1
```

无 skip 参数运行会执行提交规范、Ruff、契约漂移、Go、Vue/TS、依赖审计、SBOM、
许可证、PostgreSQL 迁移/覆盖率、非 root 容器、Trivy 和 Gitleaks。输出证据位于
`artifacts/quality-gates/`、`artifacts/coverage/`、`artifacts/sbom/` 和
`artifacts/security/`，这些目录不进入 Git。

## 7. 故障边界

- `/health/live` 仅证明进程存活。
- `/health/ready` 要求数据库、OIDC、队列、Message Bus、Outbox publisher 和 SSE
  bridge 同时可用。开发 Compose 未配置 OIDC 时返回 503 是预期 fail-closed 行为。
- 不允许用 `-SkipContainer`、`-SkipPostgresIntegration` 或 `-SkipSecretScan` 结果
  替代正式验收。
- 远端 GitHub Actions 是 Linux 权威复现环境，必须执行 Windows 无法创建符号链接而
 跳过的安全用例。

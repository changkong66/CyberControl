# Topic 1 REST API 调用规范与示例

## 1. 公共请求约束

```powershell
$BaseUrl = "http://127.0.0.1:8000/internal/topic1"
$AccessToken = "<OIDC access token>"
$ReadHeaders = @{
    Authorization = "Bearer $AccessToken"
}
$WriteHeaders = @{
    Authorization = "Bearer $AccessToken"
    "Idempotency-Key" = "topic1-course-create-000001"
}
```

访问令牌必须由受信 OIDC issuer 签发，并包含与端点匹配的 `topic1:*` scope。租户 ID、
subject、role 和 trace 上下文由服务端认证链生成，调用方不得使用自定义身份头覆盖。

所有成功响应使用 `topic1.api-envelope.v1`：

```json
{
  "schema_version": "topic1.api-envelope.v1",
  "request_id": "uuid",
  "trace_id": "32-character-trace-id",
  "data": {}
}
```

## 2. 创建课程

```powershell
$Course = @{
    expected_revision = $null
    course_code = "ATC101"
    title = "自动控制原理"
    description = "自动化专业核心课程权威知识拓扑"
    locale = "zh-CN"
    academic_level = "UNDERGRADUATE"
    credit_hours = 64
    status = "ACTIVE"
    authority_sources = @(
        @{
            source_id = "TEXTBOOK_ATC_5E"
            source_version = "5"
            locator = "chapter:1"
        }
    )
} | ConvertTo-Json -Depth 8

Invoke-RestMethod `
    -Method Put `
    -Uri "$BaseUrl/courses/CRS_ATC_001" `
    -Headers $WriteHeaders `
    -ContentType "application/json; charset=utf-8" `
    -Body $Course
```

更新已有课程时必须把最新 `revision` 放入 `expected_revision`，并使用新的幂等键。修订号
不一致返回 `TOPIC1_CONFLICT`，不会覆盖并发修改。

## 3. 写入知识点

```powershell
$Headers = @{
    Authorization = "Bearer $AccessToken"
    "Idempotency-Key" = "topic1-kp-transfer-function-0001"
}
$KnowledgePoint = @{
    expected_revision = $null
    title = "传递函数"
    aliases = @("Transfer Function")
    summary = "零初始条件下线性定常系统输出与输入拉普拉斯变换之比。"
    learning_objectives = @(
        "由微分方程推导传递函数"
        "识别极点、零点与系统阶次"
    )
    category = "MODELING"
    difficulty_level = 2
    difficulty_score = 0.42
    estimated_minutes = 90
    formula_signatures = @("G(s)=Y(s)/U(s)")
    tags = @("laplace", "modeling")
    status = "ACTIVE"
    authority_sources = @(
        @{
            source_id = "TEXTBOOK_ATC_5E"
            source_version = "5"
            locator = "chapter:2.1"
        }
    )
} | ConvertTo-Json -Depth 8

Invoke-RestMethod `
    -Method Put `
    -Uri "$BaseUrl/courses/CRS_ATC_001/knowledge-points/KP_ATC_301_TRANSFER_FUNCTION" `
    -Headers $Headers `
    -ContentType "application/json; charset=utf-8" `
    -Body $KnowledgePoint
```

`difficulty_score` 是权威声明基线；服务端根据结构特征自动计算最终
`difficulty_level`、`topology_level` 和 `topology_weight`。

## 4. 写入先修依赖

```powershell
$Headers = @{
    Authorization = "Bearer $AccessToken"
    "Idempotency-Key" = "topic1-edge-transfer-response-001"
}
$Edge = @{
    expected_revision = $null
    prerequisite_kp_id = "KP_ATC_301_TRANSFER_FUNCTION"
    dependent_kp_id = "KP_ATC_302_TIME_RESPONSE"
    relation_type = "REQUIRED"
    strength = 1.0
    rationale = "时域响应分析必须先掌握传递函数建模。"
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Put `
    -Uri "$BaseUrl/courses/CRS_ATC_001/prerequisites/EDGE_ATC_301_302" `
    -Headers $Headers `
    -ContentType "application/json; charset=utf-8" `
    -Body $Edge
```

若新增边形成有向环，服务端返回 `TOPIC1_CYCLE`，`details.cycle` 给出闭环路径，课程工作
图、审计、快照和 Outbox 均不产生部分写入。

## 5. 读取课程图谱与快照

```powershell
$Graph = Invoke-RestMethod `
    -Method Get `
    -Uri "$BaseUrl/courses/CRS_ATC_001/graph" `
    -Headers $ReadHeaders

$Snapshots = Invoke-RestMethod `
    -Method Get `
    -Uri "$BaseUrl/courses/CRS_ATC_001/snapshots" `
    -Headers $ReadHeaders
```

快照按 `graph_version` 降序返回。下游系统必须同时保存 `snapshot_id`、`graph_version` 和
`content_sha256`，不得只引用可变课程 ID。

## 6. 显式冻结与回滚

```powershell
$FreezeHeaders = @{
    Authorization = "Bearer $AccessToken"
    "Idempotency-Key" = "topic1-freeze-atc-graph-0001"
}
$Frozen = Invoke-RestMethod `
    -Method Post `
    -Uri "$BaseUrl/courses/CRS_ATC_001/snapshots" `
    -Headers $FreezeHeaders

$SnapshotId = $Frozen.data.snapshot.snapshot_id
$RollbackHeaders = @{
    Authorization = "Bearer $AccessToken"
    "Idempotency-Key" = "topic1-rollback-atc-graph-001"
}
Invoke-RestMethod `
    -Method Post `
    -Uri "$BaseUrl/snapshots/$SnapshotId/rollback" `
    -Headers $RollbackHeaders
```

回滚不会修改历史快照，而是从目标快照生成新的工作图和更高 `graph_version`，并填写
`restored_from_snapshot_id`。

## 7. 批量导入

```powershell
$ImportHeaders = @{
    Authorization = "Bearer $AccessToken"
    "Idempotency-Key" = "topic1-import-atc-textbook-0001"
}
$Bundle = Get-Content `
    -LiteralPath ".\data\topic1\automatic-control-principles.v1.json" `
    -Raw `
    -Encoding utf8
Invoke-RestMethod `
    -Method Post `
    -Uri "$BaseUrl/imports" `
    -Headers $ImportHeaders `
    -ContentType "application/json; charset=utf-8" `
    -Body $Bundle
```

`expected_parent_version` 必须等于当前最新图谱版本；首次导入使用 `null`。生产服务限制
请求体 5 MiB、知识点 500 个、依赖边 2500 条。讯飞星火解析结果也必须通过同一导入端点，
不能直接落库。

## 8. 错误处理

| 错误码 | HTTP | 调用方动作 |
|---|---:|---|
| `AUTH_TOKEN_INVALID` / `AUTH_SCOPE_DENIED` | 401/403 | 刷新令牌或申请正确 scope |
| `TOPIC1_NOT_FOUND` | 404 | 停止重试并刷新资源索引 |
| `TOPIC1_CONFLICT` | 409 | 重新读取 revision 后构造新请求和新幂等键 |
| `TOPIC1_CYCLE` | 409 | 根据闭环路径修正依赖关系 |
| `MESSAGE_DUPLICATE_CONFLICT` | 409 | 不得复用已绑定其他内容的幂等键 |
| `TOPIC1_IMPORT_LIMIT` | 413 | 拆分导入批次并保持父版本连续 |
| `DATABASE_UNAVAILABLE` | 503 | 按错误回执的 retriable 标识退避重试 |

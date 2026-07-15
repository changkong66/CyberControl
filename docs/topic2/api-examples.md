# Topic 2 REST API 调用规范

## 1. 公共约束

```powershell
$BaseUrl = "http://127.0.0.1:8000/internal/topic2"
$AccessToken = $env:LIYAN_ACCESS_TOKEN
$LearnerRef = "subject:student-001"
$CourseId = "CRS_ATC_001"
$ReadHeaders = @{ Authorization = "Bearer $AccessToken" }
```

令牌必须来自受信任 OIDC issuer。租户、subject、role、scope 和 trace 上下文由服务端认证链生成，调用方不得发送可覆盖身份的自定义头。所有写请求需要 16 至 160 字符的 `Idempotency-Key`。

## 2. 从 Topic 1 图谱初始化空白学习状态

```powershell
& .\tools\windows\initialize-topic2-learner.ps1 `
    -BaseUrl "http://127.0.0.1:8000" `
    -LearnerRef $LearnerRef `
    -CourseId $CourseId
```

初始化原子写入画像和全部活动知识点记忆状态。已有画像时返回 409，不会覆盖历史。

## 3. 写入答题行为

```powershell
$PayloadJson = '{"answer":"3/(s+2)","question_id":"QUESTION_ATC_001"}'
$PayloadBytes = [Text.Encoding]::UTF8.GetBytes($PayloadJson)
$PayloadSha256 = [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData($PayloadBytes)
).ToLowerInvariant()
$OperationId = [Guid]::NewGuid()
$Headers = @{
    Authorization = "Bearer $AccessToken"
    "Idempotency-Key" = "topic2-behavior-$($OperationId.ToString('N'))"
}
$Body = @{
    schema_version = "topic2.behavior-event-command.v1"
    event_id = $OperationId
    source_event_id = "tester-answer-$($OperationId.ToString('N'))"
    learner_ref = $LearnerRef
    course_id = $CourseId
    kp_id = "KP_ATC_301_TRANSFER_FUNCTION"
    event_type = "ANSWER_SUBMITTED"
    source_type = "TESTER"
    correctness = 1.0
    score = 0.9
    attempt_count = 1
    interaction_count = 2
    attention_ratio = 0.95
    misconception_ids = @()
    goal_tags = @("FOUNDATION")
    payload = ($PayloadJson | ConvertFrom-Json)
    payload_sha256 = $PayloadSha256
    occurred_at = [datetime]::UtcNow.ToString("o")
} | ConvertTo-Json -Depth 8

Invoke-RestMethod `
    -Method Post `
    -Uri "$BaseUrl/behavior-events" `
    -Headers $Headers `
    -ContentType "application/json; charset=utf-8" `
    -Body $Body
```

## 4. 重建六维画像

```powershell
$OperationId = [Guid]::NewGuid()
$Headers = @{
    Authorization = "Bearer $AccessToken"
    "Idempotency-Key" = "topic2-profile-$($OperationId.ToString('N'))"
}
$Command = @{
    schema_version = "topic2.operation-command.v1"
    operation_id = $OperationId
    requested_at = [datetime]::UtcNow.ToString("o")
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    -Uri "$BaseUrl/learners/$LearnerRef/courses/$CourseId/profiles/rebuild" `
    -Headers $Headers `
    -ContentType "application/json; charset=utf-8" `
    -Body $Command
```

相同 operation ID 可跨进程重试；服务端派生相同画像和 feature ID，并返回原结果。

## 5. 写入复习完成事件并刷新记忆

```powershell
$ReviewPayloadJson = '{"mode":"spaced-retrieval"}'
$ReviewPayloadBytes = [Text.Encoding]::UTF8.GetBytes($ReviewPayloadJson)
$ReviewPayloadSha256 = [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData($ReviewPayloadBytes)
).ToLowerInvariant()
$ReviewEventId = [Guid]::NewGuid()
$ReviewHeaders = @{
    Authorization = "Bearer $AccessToken"
    "Idempotency-Key" = "topic2-review-$($ReviewEventId.ToString('N'))"
}
$ReviewBody = @{
    schema_version = "topic2.behavior-event-command.v1"
    event_id = $ReviewEventId
    source_event_id = "learner-review-$($ReviewEventId.ToString('N'))"
    learner_ref = $LearnerRef
    course_id = $CourseId
    kp_id = "KP_ATC_301_TRANSFER_FUNCTION"
    event_type = "REVIEW_COMPLETED"
    source_type = "LEARNER_UI"
    correctness = 1.0
    score = 0.85
    attempt_count = 1
    interaction_count = 1
    attention_ratio = 0.9
    payload = ($ReviewPayloadJson | ConvertFrom-Json)
    payload_sha256 = $ReviewPayloadSha256
    occurred_at = [datetime]::UtcNow.ToString("o")
} | ConvertTo-Json -Depth 8

Invoke-RestMethod -Method Post -Uri "$BaseUrl/behavior-events" `
    -Headers $ReviewHeaders -ContentType "application/json" -Body $ReviewBody

$MemoryOperation = [Guid]::NewGuid()
$MemoryHeaders = @{
    Authorization = "Bearer $AccessToken"
    "Idempotency-Key" = "topic2-memory-$($MemoryOperation.ToString('N'))"
}
$MemoryCommand = @{
    schema_version = "topic2.operation-command.v1"
    operation_id = $MemoryOperation
    requested_at = [datetime]::UtcNow.ToString("o")
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
    -Uri "$BaseUrl/learners/$LearnerRef/courses/$CourseId/memory/refresh" `
    -Headers $MemoryHeaders -ContentType "application/json" -Body $MemoryCommand
```

刷新会消费尚未处理的复习事件、更新稳定度和风险等级，再保存接收游标。重复刷新不会重复强化。

## 6. 调度租户级到期记忆刷新

```powershell
$OperationId = [Guid]::NewGuid()
$Headers = @{
    Authorization = "Bearer $AccessToken"
    "Idempotency-Key" = "topic2-memory-batch-$($OperationId.ToString('N'))"
}
$Command = @{
    schema_version = "topic2.operation-command.v1"
    operation_id = $OperationId
    requested_at = [datetime]::UtcNow.ToString("o")
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
    -Uri "$BaseUrl/memory/jobs/refresh-due?limit=500" `
    -Headers $Headers -ContentType "application/json" -Body $Command
```

该端点只接受具有 `topic2:memory:batch` 的受信任服务账号。

## 7. 生成或重规划路径

```powershell
$OperationId = [Guid]::NewGuid()
$Headers = @{
    Authorization = "Bearer $AccessToken"
    "Idempotency-Key" = "topic2-path-$($OperationId.ToString('N'))"
}
$Body = @{
    schema_version = "topic2.path-generate-command.v1"
    operation_id = $OperationId
    requested_at = [datetime]::UtcNow.ToString("o")
    target_goal = "掌握经典控制系统稳定性分析"
    target_kp_ids = @("KP_ATC_305_STABILITY")
    change_type = "MASTERY_DEFICIT"
    trigger_reason = "PROFILE_OR_MEMORY_UPDATED"
} | ConvertTo-Json -Depth 6

Invoke-RestMethod -Method Post `
    -Uri "$BaseUrl/learners/$LearnerRef/courses/$CourseId/paths/generate" `
    -Headers $Headers -ContentType "application/json; charset=utf-8" -Body $Body
```

## 8. 画像历史恢复

```powershell
$ProfileId = "<historical profile UUID>"
$OperationId = [Guid]::NewGuid()
$Headers = @{
    Authorization = "Bearer $AccessToken"
    "Idempotency-Key" = "topic2-restore-$($OperationId.ToString('N'))"
}
$Command = @{
    schema_version = "topic2.operation-command.v1"
    operation_id = $OperationId
    requested_at = [datetime]::UtcNow.ToString("o")
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri "$BaseUrl/profiles/$ProfileId/restore" `
    -Headers $Headers -ContentType "application/json" -Body $Command
```

恢复不会修改历史版本，而是创建新画像版本并记录 `restored_from_profile_id`。

## 9. 读取 Topic 3 个性化上下文

```powershell
Invoke-RestMethod -Method Get `
    -Uri "$BaseUrl/learners/$LearnerRef/courses/$CourseId/agent-context" `
    -Headers $ReadHeaders
```

Topic 3 必须校验 `personalization_policy_digest`，并绑定返回的画像、记忆和路径版本。

## 10. 主要错误处理

| 错误码 | HTTP | 处理方式 |
|---|---:|---|
| `LIYAN-TOPIC2-NOT-FOUND` | 404 | 检查 Topic 1 图谱、画像或路径是否已初始化 |
| `LIYAN-TOPIC2-CONFLICT` | 409 | 使用新 operation ID 或等待进行中的幂等操作完成 |
| `LIYAN-TOPIC2-VERSION-CONFLICT` | 409 | 重新读取最新版本后重算 |
| `LIYAN-TOPIC2-BATCH-LIMIT` | 413 | 缩小批次或行为窗口 |
| `LIYAN-CONTRACT-INVALID` | 422 | 修正摘要、复习证据、外键或契约字段 |
| `LIYAN-AUTH-FORBIDDEN` | 403 | 申请正确 scope，不得伪造租户或学习者身份 |

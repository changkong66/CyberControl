# Topic 3 REST 与 SSE 调用规范

## 1. 公共变量

```powershell
$BaseUrl = "http://127.0.0.1:8000/internal/topic3"
$AccessToken = $env:LIYAN_ACCESS_TOKEN
$LearnerRef = "subject:student-001"
$CourseId = "CRS_ATC_001"
$Headers = @{ Authorization = "Bearer $AccessToken" }
```

令牌必须来自可信 OIDC issuer。客户端不得提交租户、角色或 scope 覆盖头。写请求的 `Idempotency-Key` 长度为 16 至 160 字符。

## 2. 创建五 Agent 生成工作流

```powershell
$OperationId = [Guid]::NewGuid()
$GenerationId = [Guid]::NewGuid()
$WriteHeaders = @{
    Authorization = "Bearer $AccessToken"
    "Idempotency-Key" = "topic3-generate-$($OperationId.ToString('N'))"
}
$Body = @{
    schema_version = "topic3.generation-command.v1"
    operation_id = $OperationId
    generation_session_id = $GenerationId
    learner_ref = $LearnerRef
    course_id = $CourseId
    target_kp_ids = @("KP_ATC_305_STABILITY")
    requested_resources = @(
        "Lecturer_Doc",
        "MindMap",
        "Gradient_Quiz",
        "Simulation_Code",
        "Extension_Material"
    )
    lecturer_depth = "ENGINEERING"
    learning_goal = "掌握闭环稳定性分析并完成工程仿真"
    locale = "zh-CN"
    max_parallelism = 3
    allow_partial = $true
    requested_at = [datetime]::UtcNow.ToString("o")
} | ConvertTo-Json -Depth 8

$Accepted = Invoke-RestMethod -Method Post -Uri "$BaseUrl/generations" `
    -Headers $WriteHeaders -ContentType "application/json; charset=utf-8" -Body $Body
$Accepted.payload
```

生产模式返回 `dispatch_mode=DURABLE_OUTBOX`；开发模式未启用 publisher 时返回 `LOCAL_QUEUE`。初始持久状态为 `PLANNED`。

## 3. 查询工作流结果

```powershell
$Result = Invoke-RestMethod -Method Get `
    -Uri "$BaseUrl/generations/$GenerationId" -Headers $Headers
$Result.payload.session
$Result.payload.tasks
$Result.payload.candidates
```

终态为 `COMPLETED`、`PARTIAL`、`FAILED` 或 `CANCELLED`。Candidate 仍处于 Topic 3 staged 范围，不能视为 Topic 4 学术核验通过。

## 4. 查询学习者生成历史

```powershell
Invoke-RestMethod -Method Get `
    -Uri "$BaseUrl/learners/$LearnerRef/courses/$CourseId/generations?limit=50" `
    -Headers $Headers
```

普通学习者只能读取自己的 learner ref；教师或后台服务需要 `topic3:learner:any` 或 `topic3:admin`。

## 5. SSE 连接与断点续传

```powershell
curl.exe -N `
    -H "Authorization: Bearer $AccessToken" `
    -H "Accept: text/event-stream" `
    "$BaseUrl/sse/stream"
```

断线后把上一条事件的 `id` 作为 `Last-Event-ID`：

```powershell
curl.exe -N `
    -H "Authorization: Bearer $AccessToken" `
    -H "Accept: text/event-stream" `
    -H "Last-Event-ID: <tenant-bound-HMAC-cursor>" `
    "$BaseUrl/sse/stream"
```

客户端必须按 `fragment_id` 幂等去重。`topic3.agent-task.completed` 的 durable Outbox 投影会给出 stream IDs；若实时分片缺失，使用下一节的 chunk API 恢复。

## 6. 恢复持久化分片

```powershell
$StreamId = "<stream UUID from the completion event>"
$Chunks = Invoke-RestMethod -Method Get `
    -Uri "$BaseUrl/streams/$StreamId/chunks?after_index=-1&limit=1000" `
    -Headers $Headers
$Chunks.payload.chunks | Sort-Object chunk_index
```

后续分页将最后一个 `chunk_index` 作为 `after_index`。分片内容必须重新校验 `data_sha256`。

## 7. 恢复非终态工作流

```powershell
Invoke-RestMethod -Method Post `
    -Uri "$BaseUrl/generations/$GenerationId/execute" `
    -Headers $Headers
```

该接口用于部署恢复或运维重放，不创建新的逻辑生成会话。跨实例 advisory lock 会拒绝并发重复执行，已终态工作流按幂等读取处理。

## 8. Tester 答题结果回流 Topic 2

Tester Candidate 只定义题目、答案和诊断标签。学生作答后，业务层调用冻结 Topic 2 行为接口：

```powershell
$AttemptId = [Guid]::NewGuid()
$AttemptPayload = @{ question_id = "q1"; answer = "..." } | ConvertTo-Json -Compress
$AttemptHash = [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData(
        [Text.Encoding]::UTF8.GetBytes($AttemptPayload)
    )
).ToLowerInvariant()
$AttemptHeaders = @{
    Authorization = "Bearer $AccessToken"
    "Idempotency-Key" = "topic2-tester-$($AttemptId.ToString('N'))"
}
$AttemptBody = @{
    schema_version = "topic2.behavior-event-command.v1"
    event_id = $AttemptId
    source_event_id = "tester-$($GenerationId.ToString('N'))-$($AttemptId.ToString('N'))"
    learner_ref = $LearnerRef
    course_id = $CourseId
    kp_id = "KP_ATC_305_STABILITY"
    event_type = "ANSWER_SUBMITTED"
    source_type = "TESTER"
    correctness = 1.0
    score = 0.9
    attempt_count = 1
    interaction_count = 1
    attention_ratio = 0.95
    misconception_ids = @()
    goal_tags = @("ENGINEERING")
    payload = ($AttemptPayload | ConvertFrom-Json)
    payload_sha256 = $AttemptHash
    occurred_at = [datetime]::UtcNow.ToString("o")
} | ConvertTo-Json -Depth 8

Invoke-RestMethod -Method Post `
    -Uri "http://127.0.0.1:8000/internal/topic2/behavior-events" `
    -Headers $AttemptHeaders -ContentType "application/json" -Body $AttemptBody
```

随后由 Topic 2 重建画像、刷新记忆并按需要重规划路径。Topic 3 不直接更新冻结的 Topic 2 表。

## 9. 主要错误码

| 错误码 | HTTP | 处理方式 |
|---|---:|---|
| `LIYAN-TOPIC3-NOT-FOUND` | 404 | 检查图谱、画像、路径或 generation ID |
| `LIYAN-TOPIC3-CONFLICT` | 409 | 等待现有执行完成，或重新读取最新快照 |
| `LIYAN-TOPIC3-VERSION-CONFLICT` | 409 | 使用最新任务版本恢复 |
| `LIYAN-TOPIC3-PROVIDER-UNAVAILABLE` | 503 | 检查白名单、配额和 Provider 配置 |
| `LIYAN-TOPIC3-AGENT-OUTPUT-INVALID` | 502 | Provider 输出未满足 JSON Schema 或领域规则 |
| `LIYAN-TIMEOUT` | 504 | Step 超时，可按任务预算重试 |
| `LIYAN-AUTH-FORBIDDEN` | 403 | 申请正确 scope，不得伪造学习者或租户身份 |

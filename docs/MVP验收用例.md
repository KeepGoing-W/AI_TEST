# MVP 验收用例

本文用于 M7 验收。所有 HTTP 调用仅可指向已登记、非生产且 Host 在白名单内的测试环境；执行写请求时必须在确认弹窗中确认完整目标 Host。

## 验收准备

1. 管理员创建一个 Java/Spring Boot 测试项目，并配置受控本地源码或 ZIP 源码、OpenAPI 来源和测试环境。
2. 测试源码包含一个创建接口：DTO 至少有 `@NotBlank`、`@Size`，Service 有唯一性校验；同时提供登录、查询、修改、删除接口。
3. 扫描完成后，使用已启用的 LLM 配置发起分析，生成用例并人工审核为 `approved`。
4. 测试环境的 Base URL Host 必须在 `host_allowlist` 中；生产环境仅用于验证拒绝策略，不得发送请求。

## AC-001：正常、边界、重复与权限

| 检查项 | 操作 | 预期结果 |
| --- | --- | --- |
| 正常创建 | 执行已审核的正常创建用例 | 请求通过，报告保存脱敏请求、响应和确定性断言结果。 |
| 必填校验 | 执行必填字段为空的用例 | 服务端校验结果符合断言；用例可追溯到 DTO 的 `@NotBlank` 来源。 |
| 长度边界 | 分别执行最小、最大和超过最大长度用例 | 每个边界结果独立记录，断言期望值与实际值均可查看。 |
| 重复数据 | 先创建，再执行相同唯一键的创建用例 | 重复请求按预期失败，关联 Service 唯一性规则。 |
| 未登录 | 执行未注入认证信息的用例 | 返回权限失败结果，关联接口安全定义或源码符号。 |

## AC-002：关联流程

在“测试流程与报告”中按下列顺序创建流程；每一步引用已审核用例。

| 步骤 | 变量提取或注入 | 预期结果 |
| --- | --- | --- |
| 登录 | 从 `$.data.token` 提取 `token` | 运行变量生成成功，报告只显示脱敏变量证据。 |
| 创建记录 | 请求使用 `{{runtime.token}}`；从响应提取 `id` | 创建成功并生成 `id`。 |
| 查询记录 | Path 或 Query 使用 `{{runtime.id}}` | 字段断言通过。 |
| 修改记录 | 使用 `{{runtime.id}}` | 修改结果符合断言。 |
| 删除记录 | 使用 `{{runtime.id}}` | 删除成功。 |
| 再次查询 | 使用 `{{runtime.id}}` | 不存在断言通过。 |

分别验证 `stop_on_failure=true` 时后续步骤记为 `skipped` 且有跳过原因，以及 `false` 时后续独立步骤继续执行。

## AC-003：超时错误隔离

1. 准备一个响应超过 `DEFAULT_REQUEST_TIMEOUT_SECONDS` 的测试接口，和一个可正常响应的独立接口。
2. 以 `stop_on_failure=false` 批量执行两个已审核用例。
3. 确认超时步骤记录为 `timeout` 分类及稳定错误码，后续接口仍被执行。
4. 再以 `stop_on_failure=true` 执行，确认后续步骤被标记为 `skipped`，并保留前序失败原因。

## AC-004：安全

| 检查项 | 操作 | 预期结果 |
| --- | --- | --- |
| 路径越界 | 登记允许根目录外的本地路径，或上传包含 `../`、绝对路径、符号链接条目的 ZIP | 被拒绝，不产生可扫描源码。 |
| SSRF 与 Host 白名单 | 创建 Base URL Host 不在 `host_allowlist` 中的环境，或绕过配置后向非白名单 Host 发送执行请求 | 前者返回 `ENVIRONMENT_BASE_URL_NOT_ALLOWED`；执行层仍以 `EXECUTION_HOST_NOT_ALLOWED` 拒绝后者。 |
| DNS Rebinding | 将已允许 Host 在两次解析间切换到其他地址或私网地址 | 被拒绝，错误码为 `EXECUTION_DNS_REBINDING_FORBIDDEN` 或 `EXECUTION_PRIVATE_ADDRESS_FORBIDDEN`。 |
| OpenAPI URL | 配置未在 `OPENAPI_HOST_ALLOWLIST` 中的 URL | 被拒绝，不会发起读取请求。 |
| 生产环境 | 对 `environment_type=production` 发起读或写执行 | 被拒绝，错误码为 `EXECUTION_PRODUCTION_FORBIDDEN`。 |
| 脱敏 | 在 Header、Query、Body、响应中分别放入 token、Cookie、password、API key | 报告、cURL、断言证据和变量证据均显示 `***`，不显示原值。 |
| 审核门禁 | 直接执行 `draft`、`pending_review` 或 `disabled` 用例 | 被拒绝，错误码为 `TEST_CASE_NOT_APPROVED`。 |

## AC-005：可追溯

打开任一执行报告的步骤详情并展开“可追溯证据”，确认以下字段均来自执行入队时的快照：

- `executionRunId`：执行版本。
- `testCase.id` 与 `testCase.version`：用例版本。
- `businessRules`：业务规则 ID 及来源类型。
- `sourceSymbols`：源码符号 ID、相对源码路径、全限定名和行号范围。
- `sourceScan.id` 与 `sourceScan.version`：扫描版本。
- `agentRun.promptVersion` 与 `agentRun.modelSnapshot`：Prompt 与模型参数版本。

在报告生成后尝试编辑另一条草稿用例或调整 LLM 配置，已完成报告的上述快照不得变化。

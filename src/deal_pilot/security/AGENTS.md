# 身份认证与资源授权

## 职责与入口

`auth.py:auth` 是 `langgraph.json` 的鉴权入口，通过 `Auth` 注册认证和资源授权处理器。`agent_token.py` 负责可信业务入口到 Server 的短期身份令牌；认证不再引用模拟用户表或接受模拟 token，生产用户中心尚未接入。

## 当前授权契约

- 认证要求 Bearer scheme，所有 token 均通过 JWT HS256 校验签名、sub、iss、aud、iat 和 exp；明文用户 ID 和旧模拟 token 均拒绝。`authenticate()` 只返回 identity，不返回 permissions；不定义角色、管理员身份或操作权限列表。
- `create_agent_token(user_id)` 只允许可信业务入口调用，不负责证明输入 ID 的真实性；`verify_agent_token` 返回认证 identity，不信任客户端提供的 permissions。复用锁定依赖中已有的 PyJWT（由 langgraph-api 引入），没有新增安装依赖。密钥与有效期见 `config/agent_settings.py`；无效令牌返回 401，缺少或过短密钥为配置故障，认证返回 503。
- 已移除操作白名单与全部 permissions 判断；对外开放哪些业务能力由入口控制，本模块仅做身份认证和资源隔离。隔离仍要求 Server 提供可信的 `ctx.user.identity`，不从请求参数选择用户身份。
- Store 的所有操作均要求非空 namespace 的第一段等于当前用户 identity；不满足时返回 False，保持这一用户边界。
- Assistants 为系统共享资源，专用处理器返回 True，不按操作拒绝或施加 owner 过滤。通用处理器对线程等用户资源写入当前用户 owner，并返回 owner 过滤条件；cron 等操作也不再受本模块的动作白名单限制。不要误称所有资源都使用同一套 owner 过滤。
- 身份缺失或 token 无效返回 401；资源隔离失败拒绝访问，不能回退到默认用户或管理员。
- `langgraph.json` 当前禁用 Studio 鉴权且未启用自定义路由鉴权，Webhook 的保护由 `app` 自行负责。

## 修改指引

- 目标：由业务入口控制开放能力，认证模块只验证身份并隔离用户资源。选定方案：保留 JWT 验签和 owner/namespace 过滤，移除操作白名单。原因：当前不区分用户角色，飞书入口按业务流程运行 Agent。实现状态：已实现并通过本地测试，未进行真实 Server 联调；飞书回复已通过 run_agent 签发 JWT 调用 Server，评测入口也会直接调用 Server；两条链路均未进行本轮真实联调。此设计要求部署端控制 Server 暴露范围和令牌分发，飞书 Events 本身不构成网络访问限制，本轮未验证该部署前提。
- 接入真实用户中心时同步 token 验证、权限查询、后台任务和工具上下文；当前验签证明令牌由可信入口签发，不代表已向外部用户中心查询账户状态。
- 身份变化影响 `utils/shared.py`、沙箱 key、卷名和 Deploy 对象前缀；跨用户访问规则必须一并核对。
- 调整入口能力、资源共享范围或 namespace 格式时检查现有调用方和存量数据，避免只改授权处理器。

## 验证方式

`tests/units/test_agent_token.py` 本地覆盖签名、过期/错误用途/错误算法拒绝、Bearer 格式、旧模拟 token 和明文 ID 拒绝、认证仅返回身份、无动作权限限制、上下文 permissions 不影响处理结果、owner/namespace 隔离，以及评测入口的签名请求；`test_run_agent.py` 覆盖 Mock HTTP 的签名请求。未验证真实 Agent Server 完整鉴权与排队行为。Deploy 集成测试注入上下文，只验证工具使用身份，不能证明完整 Agent Server 鉴权正确。

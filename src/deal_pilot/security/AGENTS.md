# 身份认证与资源授权

## 职责与入口

`auth.py:auth` 是 `langgraph.json` 的鉴权入口，通过 `Auth` 注册认证和资源授权处理器。当前用户来源为 `utils/mock_user.py`，生产用户中心尚未接入。

## 当前授权契约

- 认证解析 Authorization 中的 token，并通过模拟用户表取得 identity 和 permissions。当前实现尚未严格校验 Bearer scheme，不能把它描述为完整的生产令牌验证。
- 权限名使用 `{resource}:{action}`。`get_current_permissions` 优先使用请求权限；后台任务缺少权限时按当前 identity 重新查询，不信任客户端提交的权限列表。
- Store 请求除动作权限外还要求非空 namespace 的第一段等于当前用户 identity；保持这一用户边界。
- Assistants 使用动作权限检查；通用处理器写入当前用户 owner，并返回 owner 过滤条件。不要误称所有资源都使用同一套 owner 过滤。
- 身份缺失或 token 无效返回 401；无权限返回拒绝结果，不能回退到默认用户或管理员。
- `langgraph.json` 当前禁用 Studio 鉴权且未启用自定义路由鉴权，Webhook 的保护由 `app` 自行负责。

## 修改指引

- 接入真实用户中心时同步 token 验证、权限查询、后台任务和工具上下文；模拟数据只能用于明确的本地场景。
- 身份变化影响 `utils/shared.py`、沙箱 key、卷名和 Deploy 对象前缀；跨用户访问规则必须一并核对。
- 调整权限名或 namespace 格式时检查现有调用方和存量数据，避免只改授权处理器。

## 验证方式

当前没有专门的授权测试。针对改动验证无 token、无效 token、无权限、自己的资源、其他用户资源和后台权限查询。Deploy 集成测试注入上下文，只验证工具使用身份，不能证明完整 Agent Server 鉴权正确。

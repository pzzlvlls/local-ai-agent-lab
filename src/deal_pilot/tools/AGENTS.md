# 模型可调用工具

## 职责与注册

- 工具使用 LangChain `@tool`；复杂输入沿用 Pydantic `args_schema`，描述应让模型理解参数和副作用。
- `__init__.py:_AVAILABLE_TOOLS` 是内置注册表，`get_tools(names)` 按输入顺序选择，当前忽略未知名称。
- 新工具同步注册表、导出和远程 AgentSpec 的工具名称；用户身份从运行上下文读取，不能暴露为模型自由填写的参数。

## 现有工具约束

- `web_search`、`fetch_url` 调用同步 Tavily SDK，通过 `asyncio.to_thread` 隔离阻塞；保留原有结构化响应。
- `ask_user_question` 使用 LangGraph interrupt 暂停，返回恢复时的答案；问题为 2–5 个选项，标题唯一，最多一个推荐项。不要在可重放的 interrupt 前加入不可重复的外部副作用。
- `get_current_time` 当前返回宿主机本地时区的 ISO 时间，虽然工具描述称北京时间，实现未固定 `Asia/Shanghai`；修改时间语义时同时更新描述与测试。

## Deploy 数据与错误契约

- 文件留在用户沙箱内，通过 `/sandbox_utils` 的 Python 和 MinIO 客户端直传，不经宿主机下载再上传。沙箱镜像来自项目 `docker/sandbox/Dockerfile`。
- 使用固定桶 `agent-artifacts`，对象前缀为 `{认证用户ID}/{target_dirname}`。沙箱上传地址用 `MINIO_ENDPOINT_IN_SANDBOX`，返回 URL 使用宿主 `MINIO_ENDPOINT`。
- path 为不含 `..` 的沙箱绝对路径；目标和入口为非空相对路径，禁止空段、`.`、`..` 和空字符。入口必须实际存在，单文件入口必须为文件名。
- 目录部署先删除严格带末尾 `/` 的目标前缀，再上传新目录，避免删除名称相似的其他项目；单文件只覆盖同名对象并保留其他对象。
- 目录替换非原子，清理失败停止，上传失败不恢复旧文件。公共 MinIO `upload_dir` 本身不会清理旧对象，不混淆两层语义。
- 返回总数、成功数、失败数、失败原因和成功入口 URL；Deploy failures 的键是沙箱绝对路径，URL 保持入口顺序并编码特殊字符。
- 参数和产物路径错误使用可修复的工具错误；身份、配置、连接和旧对象清理错误终止运行。单文件上传失败计入结果，不能伪装全部成功。
- 上传脚本通过 shell 安全引用传入，结果从 `__DEPLOY_RESULT__=` 标记行解析；错误输出脱敏，不能泄露密钥或编码后的配置。
- 工具只上传产物，不改写网页资源路径；静态页面构建应支持部署子目录。

## 修改与验证

Deploy 修改运行 `tests/intergrations/test_deploy.py` 的相关场景，启用条件见根目录指令；参数 schema 可单独本地验证。测试使用独立随机桶和无持久卷沙箱，不能替换为生产资源。改变部署语义时同步 schema、docstring、测试契约与本文件；测试不覆盖完整 LLM 工具选择或 Agent Server 鉴权。

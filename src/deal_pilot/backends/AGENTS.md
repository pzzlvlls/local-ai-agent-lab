# OpenSandbox 后端适配

## 职责与入口

`sandbox_backend.py:SandboxBackend` 实现 Deep Agents `BaseSandbox` 协议，负责命令执行、文件上传、下载和删除。连接、创建与复用逻辑由 `utils/sandbox.py` 提供。

## 身份与卷约束

- 后端 ID 默认通过 `utils/shared.get_user_id()` 获取认证用户 identity；它是沙箱复用 key，不是 OpenSandbox 的实际 sandbox_id。
- `id_getter` 可由可信调用方注入，不作为模型可填写的工具参数。不能在认证失败时回退到公共 key。
- 私有卷挂载 `/root`，可写，卷名由 identity 将 `_` 替换为 `-` 得到；共享卷 `sandbox-shared-data` 挂载 `/shared`，只读。
- 改身份到卷名的映射时检查名称碰撞、已有卷兼容性和存量用户数据；不能单独改映射后声称隔离仍成立。
- Skill 维护通过另一共享沙箱完成，普通用户后端不得将共享卷改为可写。

## 执行与返回契约

- 异步调用使用 `aexecute`、`aupload_files`、`adownload_files`；同步包装使用 `asyncio.run`，不能在运行中的事件循环调用。
- 命令 timeout 未指定或为负数时读取远程 `command_timeout_seconds`；配置的生命周期、就绪等待和命令超时是不同参数。
- 命令结果转换为 `ExecuteResponse`；上传下载保留逐项成功或失败结果，不因单项失败丢失其他项的结果。
- `adelete` 当前通过 shell `rm -rf` 实现。修改涉及路径输入时正确转义并验证边界，不把现有字符串拼接视为已完成防注入保障。
- `enter_sandbox` 关闭的是连接，不能替换成每次操作后终止沙箱或删除持久卷。

## 修改与验证

协议调整同步检查 AgentFactory、Deploy 和沙箱公共函数。真实验证可选择 Deploy 集成测试，但它不覆盖所有后端文件操作或生产卷隔离；其余协议场景需要针对性验证，注明本地替代结果与真实 OpenSandbox 的区别。

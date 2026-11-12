# 飞书文档树

- 目标：将 `DocxAPI.list_blocks()` 返回的 `list[DocxBlock]` 表达为按标题层级组织的有序树。
- 选定方案：`block_node.py` 中的 `BlockNode` 使用标准库 dataclass，独立保存 `block_id`、`block_type`、`content` 和 JSON 兼容的 `payload`，不持有 `DocxBlock`；通过 `parent`、`children`、`prev`、`next` 引用其他节点。
- 原因：节点独立承载 ID、类型和自身内容，通过标题父子关系表达章节归属；payload 提取代码语言及表格行列数、合并信息，其他数据预留用户后续按需添加。所有块共用节点类型，兄弟引用与父节点的有序子列表保持一致。
- 实现状态：已有节点类型、`append(child)`、`remove()` 关系维护方法、`to_dict()` / `from_dict()` 树形转换及异步 `tree_builder.build_tree(blocks: list[DocxBlock]) -> BlockNode`，调用须 `await build_tree(blocks)`；已实现原始关系校验、按标题层级构树、纯文本、图片 token、代码语言、指定表格属性提取，以及构树完成后按文档顺序串行处理图片。Markdown 格式转换由 Loader 负责；`image_parser.parse_image_block` 当前仍是异步占位函数，未编排图片下载、上传或模型解析；仅补齐独立辅助函数。
- `append(child)` 将节点及其子树移动到子列表末尾，自动脱离原父节点；同父节点内调用会移到末尾，不重复添加。添加自身或祖先时先抛出 ValueError，不改变原树。
- `remove()` 按对象身份从父节点的子列表中移除当前节点，连接原前后兄弟，清空当前节点的 parent/prev/next；保留内容、payload 和子树内部引用。对根节点或已脱离节点重复调用无副作用；父节点存在但子列表没有当前对象时抛出 ValueError。
- 方法要求输入树关系一致，并维护父子及兄弟引用；直接赋值或修改 children 不会自动校验，不保证修复任意已损坏的树。
- `block_type.py` 的 `BlockType(IntEnum)` 定义已列出的飞书块类型，保留原始整数编号；枚举不代表对应解析器已实现，也不宣称覆盖全部扩展类型。节点的 `block_type: BlockType | int` 允许未列出类型保留原始编号；`UNDEFINED=999` 仅表示飞书自身的未支持块，不能作为所有未知编号的替代值。
- `code_language.py` 的 `CodeLanguage(IntEnum)` 按官方 Block 数据结构的 CodeLanguage 表定义语言编号（2026-10-16 核对为 1–75），如 `CodeLanguage.PYTHON=49`。构树时已知语言保存为枚举，未知编号保留 int，不替换为 PLAIN_TEXT；JSON 序列化仍为原始整数。
- 构树阶段 `content` 只存本节点内容，不重复拼接子树；代码块的 `payload` 为 `{"language": <原始整数编号>}`（有语言字段时），表格的 payload 提取 `column_size`、`row_size`、`merge_info`，其他节点为独立的空字典。不保存原始块或其他元数据，后续由用户按需扩展；图片处理函数可在构树完成后原地更新图片节点的 content/payload。
- 表格属性从 `raw["table"]["property"]` 按同名字段复制到 payload 顶层，仅复制来源中存在的字段，不补默认值，不保留 cells/column_width。对字段值深拷贝，merge_info 的顺序、跨度和值保持原样；本阶段不校验合并区域、不展开合并单元格，也不新增行节点。table 或 property 存在但不是对象时抛出 `ValueError`。
- `build_tree` 输入须包含完整树，列表可乱序；从 `parent_id` 为 None 或空字符串的唯一块确定根节点，校验 `DocxBlock.children` 和 parent_id 一致。来源关系以模型公共字段为准，不从 raw 重读；构树不改写输入 Block。
- 每个原始父块的 children 列表独立按标题级别重组：正文等普通块挂到前面最近的标题，低级标题挂到最近的高级标题下，同级或更高级标题结束当前章节。首个标题可从任意级别开始，跳级时不创建虚拟标题，首个标题前的内容仍属于原父块；阅读顺序保持不变。
- 保留列表、表格单元格、引用容器等原有子树，分别处理其内部标题，不将容器内标题提升到外层或跨容器收纳内容。标题自身原有 children 先于随后收纳的来源兄弟，节点的最终 parent/prev/next 反映章节归组后的关系。
- 代码语言读取 `raw["code"]["style"]["language"]`，保留原始编号，不映射名称或用默认值替代缺失字段；缺失/为 None 时 payload 为空，style 非对象或非空 language 不是整数时抛出 `ValueError`（不接受 bool）。
- 构树时已知块类型转换为 `BlockType`，未知编号保留为 int。图片节点 `content` 为 `raw["image"]["token"]`；页面、正文、heading1–heading9、列表、代码、引用、公式和待办按对应类型字段的 `elements` 顺序提取纯文本，保留空格和换行，不添加 Markdown 样式。无自身文本的容器及其他类型 content 为空。
- 行内支持 `text_run.content`、`equation.content`、`mention_doc`/`link_preview` 的 title（缺失/为空时使用 url）；未支持的行内元素或错误的文本结构抛出 `ValueError`，不静默丢弃。缺失类型字段或 elements 时视为空内容。文本提取不查询被提及用户或调用其他外部服务。
- 所有父子、标题及兄弟关系构建完成后，只沿 children 迭代遍历整棵树，收集全部 `BlockType.IMAGE` 节点（包括图片根节点），再按收集顺序串行 `await` 调用 `image_parser.parse_image_block(node) -> None`。直接传入原节点，不使用返回值替换节点；当前图片完成后才处理下一张，便于后续图片读取前方图片更新后的内容；无图片不调用，成功时等待全部处理完成再返回根。构树失败时不启动图片处理，图片处理异常与取消直接传播，不再处理后续图片，不返回伪装成功的树。
- 空输入、空/重复块 ID、非唯一根、缺失父/子块、父子声明不一致、重复子引用、未列入父块 children 的节点、环及图片缺少非空字符串 token 均抛出 `ValueError`，不返回部分树或静默丢弃节点。
- 构树校验和挂载使用迭代；校验后自底向上用标题栈确定章节父节点，通过 `append` 连接尚未挂载的块，避免深树的递归栈限制和反复移动节点。
- `prev`、`next` 仅表示同级相邻兄弟；首尾缺失引用为 None，根节点二者均为 None。
- 父子及兄弟双向引用存在循环，不能直接调用 dataclasses.asdict。`to_dict() -> BlockNodeDict` 只递归导出 block_id、整数 block_type、content、深拷贝 payload 和 children；不保存 parent/prev/next。`BlockNode.from_dict(data)` 将已知类型还原为枚举、未知编号保留为 int，通过 append 重建父子和兄弟引用，并再次深拷贝 payload；索引图据此传递 root 状态。两者为递归实现，不提供任意深树、损坏结构或外部字典的完整校验保证；构树阶段的迭代实现不代表转换方法同样没有递归深度限制。
- `image_parser._generate_dataurl(data, mime) -> str` 使用标准库 base64；`_upload_minio(data, mime, block_id)` 为 async，
  读取现有 `get_config("rag_config", RagConfig)` 的 image_parser.bucket_name，用标准库 mimetypes 推断后缀，
  保存为桶根目录 `{block_id}{后缀}`，返回 ImageLocation(bucket_name, filename)，Content-Type 使用传入 mime。
  未知/非图片 MIME 或带路径的块 ID 拒绝上传。按私有方式确保桶存在，再读取实际桶策略；
  存在匿名 GetObject/GetObjectVersion Allow（含通配动作）时拒绝，不撤销已有策略。对 NotPrincipal/NotAction 及带 Condition/Deny 的潜在公共授权保守拒绝，
  不实现完整 IAM 策略求值；当前 MinIO 的 GetBucketPolicyStatus 在公共读场景中返回非公开，不能用其代替此检查。
  无法读取策略时错误传播，只有 NoSuchBucketPolicy 表示无公共策略。检查与上传不是原子操作，不防止管理员并发修改桶策略。
- `await image_parser._attachment_info(image_block) -> AttachmentInfo` 读取同一配置的 sibling_count。
  parent_trace 按根到父排列，仅移除空字符串内容；prevs 取最近 n 个兄弟（包括已处理的图片），按文档顺序返回；
  nexts 跳过图片后补足最近 n 个非图片兄弟，按文档顺序返回。两侧均不跨父节点，空内容的兄弟仍计数，
  不递归拼接兄弟子树；n=0 两侧为空，负数抛 ValueError。辅助函数尚未接入 parse_image_block 的占位流程。
- 图片辅助函数本地验证：`.venv/bin/python -m pytest -q tests/units/test_feishu_doc_image_parser.py`；
  MinIO 真实验证：`MINIO_INTEGRATION=1 .venv/bin/python -m pytest -q --tb=short tests/intergrations/test_minio.py -k 'upload_bytes or image_upload_minio'`。
- 本次可用 `.venv/bin/pyright --pythonpath .venv/bin/python src/deal_pilot/rag/structure/feishu_doc` 检查类型；不依赖真实飞书服务。
- 单元测试：`.venv/bin/python -m pytest -q tests/units/test_feishu_doc_tree_builder.py`；覆盖阅读顺序、乱序输入、嵌套、各级标题归组及容器边界、父子/兄弟引用、未知类型、各文本字段和行内元素、图片 token、代码语言、表格属性复制、payload 独立性、输入不变、深树及异常输入；另验证构树后收集全部图片、文档顺序串行处理及前图完成后再启动后图、原地更新、无图片、图片根节点、失败及取消传播。测试通过 `asyncio.run` 调用异步入口，图片处理全部 Mock，无需新增 pytest 异步插件；不代表真实图片服务验证。temp 中的文档 JSON 是单独读取真实文档生成的检查产物，不属于单元测试 fixture。

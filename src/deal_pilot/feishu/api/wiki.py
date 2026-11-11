"""应用身份的知识空间与目录节点读取。"""

from collections import deque
from collections.abc import AsyncIterator
from urllib.parse import quote

from lark_oapi.api.wiki.v2 import (
    GetNodeSpaceRequest,
    GetSpaceRequest,
    ListSpaceNodeRequest,
    ListSpaceRequest,
)
from pydantic import JsonValue

from deal_pilot.feishu.api._client import (
    iter_items,
    object_value,
    resource_id,
    sdk_call,
    wiki_client,
)
from deal_pilot.feishu.api.errors import (
    FeishuAPIError,
    FeishuResponseError,
    UnsupportedWikiNodeTypeError,
)
from deal_pilot.feishu.api.models import WikiNode, WikiSpace


def _wiki_node(data: dict[str, JsonValue]) -> WikiNode:
    if data.get("obj_type") != "docx":
        raise UnsupportedWikiNodeTypeError("WikiAPI 当前仅支持 obj_type=docx 的节点")
    token = data.get("node_token")
    if not isinstance(token, str) or not token:
        raise FeishuResponseError("飞书节点响应缺少有效的 node_token")
    node_token = quote(resource_id(token, "响应 node_token"), safe="")
    return WikiNode.model_validate(
        {
            **data,
            "url": f"https://www.feishu.cn/wiki/{node_token}",
            "parent_node_token": data.get("parent_node_token") or None,
        }
    )


class WikiAPI:
    """读取应用身份有权限访问的知识空间及节点；不包含文档正文读取。"""

    async def list_spaces(self) -> list[WikiSpace]:
        """读取当前应用身份可访问的全部知识空间，内部完成翻页。

        Returns:
            全部可访问空间的列表；没有空间时返回空列表。
            任一页读取失败应抛出异常，不将部分列表作为完整结果返回。
        """
        return [space async for space in self._iter_spaces()]

    async def _iter_spaces(self) -> AsyncIterator[WikiSpace]:
        """按需读取空间分页，不提前请求下一页。"""
        api = wiki_client()

        async def fetch_page(page_token: str | None) -> dict[str, JsonValue]:
            builder = ListSpaceRequest.builder().page_size(50)
            if page_token is not None:
                builder.page_token(page_token)
            request = builder.build()
            return await sdk_call(lambda: api.space.list(request))

        async for item in iter_items(fetch_page):
            yield WikiSpace.model_validate(item)

    async def get_space(self, space_id: str) -> WikiSpace | None:
        """读取指定知识空间基本信息。

        Args:
            space_id: 知识空间 ID，不接受知识库链接或 node_token。

        Returns:
            空间 ID、名称和描述；明确不存在时返回 None。
            无权限、认证失败或服务错误应抛出异常。
        """
        space_id = resource_id(space_id, "space_id")
        api = wiki_client()
        request = GetSpaceRequest.builder().space_id(space_id).build()
        try:
            data = await sdk_call(lambda: api.space.get(request))
        except FeishuAPIError as error:
            if error.code == 131005 and error.http_status in {200, 400, 404}:
                return None
            raise
        return WikiSpace.model_validate(object_value(data.get("space"), "space"))

    async def get_node(self, node_token: str) -> WikiNode | None:
        """读取一个知识库节点，解析其实际内容类型与 token。

        Args:
            node_token: 知识库链接 /wiki/ 后面的 token，不是实际内容 obj_token。

        Returns:
            节点及 obj_type、obj_token、url；url 按
            https://www.feishu.cn/wiki/{node_token} 拼接，正文需继续调用 DocxAPI。
            明确不存在时返回 None；无权限、认证失败或服务错误应抛出异常。
        """
        resource_id(node_token, "node_token")
        api = wiki_client()
        request = (
            GetNodeSpaceRequest.builder().token(node_token).obj_type("wiki").build()
        )
        try:
            data = await sdk_call(lambda: api.space.get_node(request))
        except FeishuAPIError as error:
            if error.code in {131005, 131012} and error.http_status in {200, 400, 404}:
                return None
            raise
        return _wiki_node(object_value(data.get("node"), "node"))

    async def list_nodes(
        self,
        space_id: str,
        *,
        parent_node_token: str | None = None,
    ) -> list[WikiNode]:
        """读取全部直接子节点，内部完成翻页；不递归遍历后代。

        Args:
            space_id: 知识空间 ID。
            parent_node_token: 父节点 token；None 表示读取空间根目录的一级节点。

        Returns:
            指定父节点下的全部直接子节点；空目录返回空列表。
            任一页读取失败应抛出异常，不返回部分列表。
        """
        return [
            node
            async for node in self._iter_nodes(
                space_id, parent_node_token=parent_node_token
            )
        ]

    async def _iter_nodes(
        self,
        space_id: str,
        *,
        parent_node_token: str | None = None,
    ) -> AsyncIterator[WikiNode]:
        """按需读取直接子节点分页，不递归或预取。"""
        space_id = resource_id(space_id, "space_id")
        if parent_node_token is not None:
            resource_id(parent_node_token, "parent_node_token")
        api = wiki_client()

        async def fetch_page(page_token: str | None) -> dict[str, JsonValue]:
            builder = ListSpaceNodeRequest.builder().space_id(space_id).page_size(50)
            if parent_node_token is not None:
                builder.parent_node_token(parent_node_token)
            if page_token is not None:
                builder.page_token(page_token)
            request = builder.build()
            return await sdk_call(lambda: api.space_node.list(request))

        async for item in iter_items(fetch_page):
            yield _wiki_node(item)

    async def list_all_space_nodes(self) -> AsyncIterator[WikiNode]:
        """按需迭代所有可访问知识空间中、全部层级的节点。

        使用 async for 消费；开始迭代才请求网络，空间及目录分页均按需读取，
        不预取下一页或目录。请求随消费推进，但不提供固定请求速率限制。
        任一后续请求失败时向消费方抛出异常，已产出的节点不会撤回。

        Yields:
            根目录节点及全部后代节点，按空间和目录广度优先顺序产出。
            每项通过 space_id 标识所属空间；同一 (space_id, node_token) 只产出一次，
            指向相同 obj_token 的不同节点仍分别保留。没有节点时直接结束。
            不读取节点关联的文档正文。
        """
        seen: set[tuple[str, str]] = set()
        async for space in self._iter_spaces():
            # 迭代式广度遍历，避免深目录触发 Python 递归上限。
            parents: deque[str | None] = deque([None])
            while parents:
                parent = parents.popleft()
                async for node in self._iter_nodes(
                    space.space_id, parent_node_token=parent
                ):
                    key = (node.space_id, node.node_token)
                    if key in seen:
                        continue
                    seen.add(key)
                    if node.has_child:
                        parents.append(node.node_token)
                    yield node

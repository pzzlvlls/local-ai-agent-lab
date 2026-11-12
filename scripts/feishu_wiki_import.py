#!/usr/bin/env python3
"""把 resource/企业知识库 下的 Markdown 导入飞书知识库。

用法（在项目根目录执行）：
    uv run python scripts/feishu_wiki_import.py --dry-run   # 只打印计划，不写飞书
    uv run python scripts/feishu_wiki_import.py --only 01   # 只处理目录名包含 01 的子目录
    uv run python scripts/feishu_wiki_import.py             # 全量导入

约定：
- 子目录去掉前缀序号后就是知识空间名称，例如 01_产品与配置资料 -> 产品与配置资料。
- 先上传 Markdown 素材并创建导入任务，得到 docx 后移动到目标知识空间根目录。
- 同名文档已存在时跳过，可重复执行。
- 图片目录单独导入为知识空间中的文件节点（obj_type=file）。
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import lark_oapi as lark
from lark_oapi.api.docx.v1 import (
    ListDocumentBlockRequest,
    PatchDocumentBlockRequest,
    ReplaceImageRequest,
    UpdateBlockRequest,
)
from lark_oapi.api.drive.v1 import (
    CreateFolderFileRequest,
    CreateFolderFileRequestBody,
    CreateImportTaskRequest,
    DeleteFileRequest,
    GetImportTaskRequest,
    ImportTask,
    ImportTaskMountPoint,
    UploadAllFileRequest,
    UploadAllFileRequestBody,
    UploadAllMediaRequest,
    UploadAllMediaRequestBody,
)
from lark_oapi.api.wiki.v2 import (
    GetTaskRequest,
    ListSpaceNodeRequest,
    ListSpaceRequest,
    MoveDocsToWikiSpaceNodeRequest,
    MoveDocsToWikiSpaceNodeRequestBody,
)
from lark_oapi.core.enum import AccessTokenType, HttpMethod
from lark_oapi.core.model import BaseRequest, BaseResponse

from deal_pilot.config.feishu_settings import feishu_settings

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "resource" / "企业知识库"
TEMP_FOLDER_NAME = "wiki-import-temp"
IMPORT_TIMEOUT_SECONDS = 180
TASK_TIMEOUT_SECONDS = 120
POLL_INTERVAL_SECONDS = 1.0
IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
MAX_IMAGE_WIDTH = 1460


def build_client() -> lark.Client:
    if not feishu_settings.app_id.strip() or not feishu_settings.app_secret.strip():
        raise SystemExit(
            "缺少 FEISHU_APP_ID / FEISHU_APP_SECRET，请在项目根目录的 .env 中配置"
        )
    return (
        lark.Client.builder()
        .app_id(feishu_settings.app_id)
        .app_secret(feishu_settings.app_secret)
        .timeout(60)
        .log_level(lark.LogLevel.ERROR)
        .build()
    )


def space_name(folder: Path) -> str:
    """去掉目录名的数字前缀序号。"""
    name = folder.name
    head, sep, tail = name.partition("_")
    if sep and head.isdigit() and tail:
        return tail
    return name


def ensure_success(response: BaseResponse, action: str) -> Any:
    if not response.success():
        raise RuntimeError(
            f"{action}失败: code={response.code} msg={response.msg} log_id={response.get_log_id()}"
        )
    return response.data


def raw_get(client: lark.Client, uri: str) -> dict[str, Any]:
    request = BaseRequest()
    request.http_method = HttpMethod.GET
    request.uri = uri
    request.token_types = {AccessTokenType.TENANT, AccessTokenType.USER}
    response = client.request(request)
    raw = response.raw
    if raw is None or raw.status_code != 200 or raw.content is None:
        raise RuntimeError(
            f"请求 {uri} 失败: status={getattr(raw, 'status_code', None)}"
        )
    return json.loads(raw.content)


def root_folder_token(client: lark.Client) -> str:
    payload = raw_get(client, "/open-apis/drive/explorer/v2/root_folder/meta")
    token = payload.get("data", {}).get("token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("无法读取云空间根目录 token")
    return token


def ensure_temp_folder(client: lark.Client) -> str:
    """应用云空间中准备一个临时目录，用于接收导入的源文件。"""
    request = (
        CreateFolderFileRequest.builder()
        .request_body(
            CreateFolderFileRequestBody.builder()
            .name(TEMP_FOLDER_NAME)
            .folder_token(root_folder_token(client))
            .build()
        )
        .build()
    )
    data = ensure_success(client.drive.v1.file.create_folder(request), "创建临时目录")
    return data.token


def list_spaces(client: lark.Client) -> dict[str, str]:
    spaces: dict[str, str] = {}
    page_token: str | None = None
    while True:
        builder = ListSpaceRequest.builder().page_size(50)
        if page_token:
            builder.page_token(page_token)
        data = ensure_success(
            client.wiki.v2.space.list(builder.build()), "读取知识空间列表"
        )
        for item in data.items or []:
            spaces[item.name] = item.space_id
        if not data.has_more:
            return spaces
        page_token = data.page_token


def list_node_titles(client: lark.Client, space_id: str) -> set[str]:
    titles: set[str] = set()
    page_token: str | None = None
    while True:
        builder = ListSpaceNodeRequest.builder().space_id(space_id).page_size(50)
        if page_token:
            builder.page_token(page_token)
        data = ensure_success(
            client.wiki.v2.space_node.list(builder.build()), "读取知识空间节点"
        )
        for item in data.items or []:
            if item.title:
                titles.add(item.title)
        if not data.has_more:
            return titles
        page_token = data.page_token


def list_nodes(client: lark.Client, space_id: str) -> list[Any]:
    nodes: list[Any] = []
    page_token: str | None = None
    while True:
        builder = ListSpaceNodeRequest.builder().space_id(space_id).page_size(50)
        if page_token:
            builder.page_token(page_token)
        data = ensure_success(
            client.wiki.v2.space_node.list(builder.build()), "读取知识空间节点"
        )
        nodes.extend(data.items or [])
        if not data.has_more:
            return nodes
        page_token = data.page_token


def delete_space_nodes(client: lark.Client, space_id: str, name: str) -> int:
    """删除知识空间根目录下的全部节点；删除实体文档后节点随之消失。"""
    deleted = 0
    for node in list_nodes(client, space_id):
        request = (
            DeleteFileRequest.builder()
            .file_token(node.obj_token)
            .type(node.obj_type)
            .build()
        )
        try:
            ensure_success(client.drive.v1.file.delete(request), f"删除 {node.title}")
        except Exception as error:  # noqa: BLE001
            print(f"[失败] 删除 {name}/{node.title}: {error}")
            continue
        deleted += 1
        print(f"[删除] {name}/{node.title}")
    return deleted


def png_size(path: Path) -> tuple[int, int]:
    """读取 PNG 头部宽高，避免为一张图引入图像库依赖。"""
    header = path.read_bytes()[:24]
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path.name} 不是 PNG 文件")
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def display_size(path: Path) -> tuple[int, int]:
    """按原图比例计算显示尺寸，超宽时等比缩到页面宽度。"""
    width, height = png_size(path)
    scale = min(1.0, MAX_IMAGE_WIDTH / width)
    return max(1, round(width * scale)), max(1, round(height * scale))


def md_image_paths(markdown: Path) -> list[Path]:
    """按出现顺序返回 Markdown 中引用的本地图片，找不到的跳过并提示。"""
    paths: list[Path] = []
    for raw in IMAGE_PATTERN.findall(markdown.read_text(encoding="utf-8")):
        candidate = (markdown.parent / raw.strip()).resolve()
        if candidate.is_file():
            paths.append(candidate)
        else:
            print(f"[提示] {markdown.name} 引用的图片不存在: {raw.strip()}")
    return paths


def list_image_block_ids(client: lark.Client, document_id: str) -> list[str]:
    block_ids: list[str] = []
    page_token: str | None = None
    while True:
        builder = (
            ListDocumentBlockRequest.builder().document_id(document_id).page_size(500)
        )
        if page_token:
            builder.page_token(page_token)
        data = ensure_success(
            client.docx.v1.document_block.list(builder.build()), "读取文档块"
        )
        for block in data.items or []:
            if block.block_type == 27 and block.block_id:
                block_ids.append(block.block_id)
        if not data.has_more:
            return block_ids
        page_token = data.page_token


def upload_docx_image(client: lark.Client, block_id: str, path: Path) -> str:
    with path.open("rb") as file:
        request = (
            UploadAllMediaRequest.builder()
            .request_body(
                UploadAllMediaRequestBody.builder()
                .file_name(path.name)
                .parent_type("docx_image")
                .parent_node(block_id)
                .size(path.stat().st_size)
                .file(file)
                .build()
            )
            .build()
        )
        data = ensure_success(
            client.drive.v1.media.upload_all(request), f"上传图片 {path.name}"
        )
    return data.file_token


def replace_image(
    client: lark.Client,
    document_id: str,
    block_id: str,
    file_token: str,
    width: int,
    height: int,
) -> None:
    request = (
        PatchDocumentBlockRequest.builder()
        .document_id(document_id)
        .block_id(block_id)
        .request_body(
            UpdateBlockRequest.builder()
            .replace_image(
                ReplaceImageRequest.builder()
                .token(file_token)
                .width(width)
                .height(height)
                .build()
            )
            .build()
        )
        .build()
    )
    ensure_success(client.docx.v1.document_block.patch(request), "替换图片")


def embed_images(client: lark.Client, markdown: Path, document_id: str) -> None:
    """把 Markdown 引用的本地图片上传并替换文档里的占位图片块。"""
    paths = md_image_paths(markdown)
    if not paths:
        return
    block_ids = list_image_block_ids(client, document_id)
    if len(block_ids) != len(paths):
        print(
            f"[提示] {markdown.name} 图片数量不一致: markdown={len(paths)} "
            f"文档={len(block_ids)}，按顺序匹配"
        )
    for block_id, image_path in zip(block_ids, paths):
        file_token = upload_docx_image(client, block_id, image_path)
        width, height = display_size(image_path)
        replace_image(client, document_id, block_id, file_token, width, height)
        print(f"[图片] {markdown.name} <- {image_path.name} ({width}x{height})")


def upload_import_source(client: lark.Client, path: Path) -> str:
    with path.open("rb") as file:
        request = (
            UploadAllMediaRequest.builder()
            .request_body(
                UploadAllMediaRequestBody.builder()
                .file_name(path.name)
                .parent_type("ccm_import_open")
                .size(path.stat().st_size)
                .extra(
                    json.dumps(
                        {"obj_type": "docx", "file_extension": path.suffix.lstrip(".")},
                        ensure_ascii=False,
                    )
                )
                .file(file)
                .build()
            )
            .build()
        )
        data = ensure_success(
            client.drive.v1.media.upload_all(request), f"上传 {path.name}"
        )
    return data.file_token


def wait_import_task(client: lark.Client, ticket: str) -> str:
    deadline = time.monotonic() + IMPORT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        request = GetImportTaskRequest.builder().ticket(ticket).build()
        data = ensure_success(client.drive.v1.import_task.get(request), "查询导入任务")
        result = data.result
        if result is None:
            raise RuntimeError("导入任务响应缺少 result")
        if result.job_status == 0:
            if not result.token:
                raise RuntimeError(f"导入成功但缺少文档 token: {result.job_error_msg}")
            return result.token
        if result.job_status not in {1, 2}:
            raise RuntimeError(
                f"导入失败: status={result.job_status} msg={result.job_error_msg}"
            )
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"导入任务超时: ticket={ticket}")


def wait_wiki_task(client: lark.Client, task_id: str) -> str:
    """轮询移动任务；查询失败只提示，不把已提交的移动当成失败。"""
    deadline = time.monotonic() + TASK_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        request = (
            GetTaskRequest.builder()
            .task_id(task_id)
            .task_type("move_docs_to_wiki")
            .build()
        )
        response = client.wiki.v2.task.get(request)
        if not response.success():
            print(
                f"[提示] 查询移动任务失败: code={response.code} msg={response.msg}，"
                "任务可能仍在后台执行"
            )
            return ""
        task = response.data.task if response.data else None
        for move_result in task.move_result if task and task.move_result else []:
            if move_result.node is not None and move_result.node.node_token:
                return move_result.node.node_token
        time.sleep(POLL_INTERVAL_SECONDS)
    print(f"[提示] 移动任务查询超时: task_id={task_id}")
    return ""


def move_to_wiki(
    client: lark.Client, space_id: str, obj_type: str, obj_token: str
) -> str:
    request = (
        MoveDocsToWikiSpaceNodeRequest.builder()
        .space_id(space_id)
        .request_body(
            MoveDocsToWikiSpaceNodeRequestBody.builder()
            .obj_type(obj_type)
            .obj_token(obj_token)
            .parent_wiki_token("")
            .apply(True)
            .build()
        )
        .build()
    )
    data = ensure_success(
        client.wiki.v2.space_node.move_docs_to_wiki(request), "移动到知识库"
    )
    if data.wiki_token:
        return data.wiki_token
    if not data.task_id:
        raise RuntimeError("移动结果既没有 wiki_token 也没有 task_id")
    return wait_wiki_task(client, data.task_id)


def import_markdown(
    client: lark.Client, path: Path, space_id: str, folder_token: str
) -> str:
    file_token = upload_import_source(client, path)
    request = (
        CreateImportTaskRequest.builder()
        .request_body(
            ImportTask.builder()
            .file_extension("md")
            .file_token(file_token)
            .type("docx")
            .file_name(path.stem)
            .point(
                ImportTaskMountPoint.builder()
                .mount_type(1)
                .mount_key(folder_token)
                .build()
            )
            .build()
        )
        .build()
    )
    ticket = ensure_success(
        client.drive.v1.import_task.create(request), "创建导入任务"
    ).ticket
    doc_token = wait_import_task(client, ticket)
    embed_images(client, path, doc_token)
    return move_to_wiki(client, space_id, "docx", doc_token)


def import_file(
    client: lark.Client, path: Path, space_id: str, folder_token: str
) -> str:
    with path.open("rb") as file:
        request = (
            UploadAllFileRequest.builder()
            .request_body(
                UploadAllFileRequestBody.builder()
                .file_name(path.name)
                .parent_type("explorer")
                .parent_node(folder_token)
                .size(path.stat().st_size)
                .file(file)
                .build()
            )
            .build()
        )
        data = ensure_success(
            client.drive.v1.file.upload_all(request), f"上传 {path.name}"
        )
    return move_to_wiki(client, space_id, "file", data.file_token)


def main() -> None:
    parser = argparse.ArgumentParser(description="把本地 Markdown 导入飞书知识库")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不写入飞书")
    parser.add_argument("--only", default="", help="只处理目录名包含该关键字的子目录")
    parser.add_argument(
        "--reset", action="store_true", help="先删除目标知识空间中的全部节点再导入"
    )
    args = parser.parse_args()

    if not SOURCE_DIR.is_dir():
        raise SystemExit(f"源目录不存在: {SOURCE_DIR}")

    folders = sorted(p for p in SOURCE_DIR.iterdir() if p.is_dir())
    if args.only:
        folders = [p for p in folders if args.only in p.name]
    if not folders:
        raise SystemExit("没有匹配的子目录")

    client = build_client()
    spaces = list_spaces(client)
    print("可见知识空间:", ", ".join(sorted(spaces)) or "(无)")

    plans: list[tuple[Path, Path, str, str]] = []
    missing: list[str] = []
    for folder in folders:
        name = space_name(folder)
        space_id = spaces.get(name)
        if space_id is None:
            missing.append(name)
            continue
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix.lower() in {".md", ".mark"}:
                plans.append((folder, path, name, space_id))

    for name in missing:
        print(f"[跳过] 找不到同名知识空间: {name}")

    if args.reset and not args.dry_run:
        reset_targets = {name for _, _, name, _ in plans}
        if not args.only and (SOURCE_DIR / "图片素材").is_dir():
            reset_targets.add(space_name(SOURCE_DIR / "图片素材"))
        total = 0
        for name in sorted(reset_targets):
            space_id = spaces.get(name)
            if space_id is None:
                continue
            total += delete_space_nodes(client, space_id, name)
        print(f"已删除 {total} 个节点")

    print(f"待导入文档 {len(plans)} 个")
    if args.dry_run:
        for _, path, name, _ in plans:
            print(f"  {name} <- {path.name}")
        return

    folder_token = ensure_temp_folder(client)
    existing: dict[str, set[str]] = {}
    moved_count = 0
    for folder, path, name, space_id in plans:
        if space_id not in existing:
            existing[space_id] = list_node_titles(client, space_id)
        if path.stem in existing[space_id]:
            print(f"[跳过] {name}/{path.stem} 已存在")
            continue
        try:
            node_token = import_markdown(client, path, space_id, folder_token)
        except Exception as error:  # noqa: BLE001 - 单个文档失败不阻塞其余文档
            print(f"[失败] {name}/{path.name}: {error}")
            continue
        existing[space_id].add(path.stem)
        moved_count += 1
        print(f"[完成] {name}/{path.stem} -> {node_token}")

    image_folder = SOURCE_DIR / "图片素材"
    image_space = (
        spaces.get(space_name(image_folder)) if image_folder.is_dir() else None
    )
    if image_folder.is_dir() and image_space:
        image_titles = list_node_titles(client, image_space)
        for path in sorted(p for p in image_folder.iterdir() if p.is_file()):
            if path.name in image_titles:
                print(f"[跳过] 图片素材/{path.name} 已存在")
                continue
            try:
                node_token = import_file(client, path, image_space, folder_token)
            except Exception as error:  # noqa: BLE001
                print(f"[失败] 图片素材/{path.name}: {error}")
                continue
            moved_count += 1
            print(f"[完成] 图片素材/{path.name} -> {node_token}")
    elif image_folder.is_dir():
        print("[跳过] 没有名为「图片素材」的知识空间，未导入图片")

    print(f"本次导入 {moved_count} 个节点")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)

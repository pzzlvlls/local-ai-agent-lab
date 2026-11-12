#!/usr/bin/env python3
"""检查 Compose 服务在宿主机上的端口，必要时只重启端口转发失效的容器。

Docker Desktop 的 WSL 端口转发偶发失效时，容器本身仍然 healthy，但宿主机访问
已发布端口会收到空响应。默认探测失败后重启对应容器并等待恢复；使用 --no-restart
只检查不重启。Milvus 专用的 milvus-minio（19000/19001）仅供调试，不在检查范围。
"""

import argparse
import asyncio
from dataclasses import dataclass

import httpx

PROBE_TIMEOUT = 3.0
WAIT_TIMEOUT = 120.0
RETRY_INTERVAL = 2.0


@dataclass(frozen=True)
class Probe:
    """一个宿主机端口探测；URL 与 host/port 二选一。"""

    container: str
    name: str
    url: str | None = None
    host: str | None = None
    port: int | None = None


# 与 docker-compose.yml 的容器名和宿主机端口保持一致。
PROBES: tuple[Probe, ...] = (
    Probe("deal-pilot-nacos-1", "Nacos", url="http://127.0.0.1:8848/nacos/"),
    Probe("deal-pilot-milvus-1", "Milvus HTTP", url="http://127.0.0.1:9091/healthz"),
    Probe("deal-pilot-milvus-1", "Milvus gRPC", host="127.0.0.1", port=19530),
    Probe(
        "deal-pilot-shared-minio-1",
        "Shared MinIO",
        url="http://localhost:9002/minio/health/live",
    ),
    Probe(
        "deal-pilot-litellm-1",
        "LiteLLM",
        url="http://localhost:4000/health/liveliness",
    ),
    Probe(
        "deal-pilot-opensandbox-server-1",
        "OpenSandbox",
        url="http://127.0.0.1:8090/health",
    ),
    Probe(
        "deal-pilot-langfuse-web-1",
        "Langfuse",
        url="http://localhost:3000/api/public/health",
    ),
)


async def _probe(client: httpx.AsyncClient, probe: Probe, timeout: float) -> bool:
    """探测单个端口，任何连接或协议错误都视为不健康。"""
    try:
        if probe.url is not None:
            response = await client.get(probe.url, timeout=timeout)
            return response.is_success
        assert probe.host is not None and probe.port is not None
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(probe.host, probe.port), timeout
        )
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
        return True
    except (httpx.HTTPError, OSError, TimeoutError):
        return False


async def _is_running(container: str) -> bool:
    """读取容器运行状态；docker 不可用或容器不存在时返回 False。"""
    process = await asyncio.create_subprocess_exec(
        "docker",
        "inspect",
        "-f",
        "{{.State.Running}}",
        container,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await process.communicate()
    return process.returncode == 0 and stdout.decode(errors="replace").strip() == "true"


async def _restart(container: str) -> None:
    """重启容器，失败时抛出带 docker 错误输出的异常。"""
    process = await asyncio.create_subprocess_exec(
        "docker",
        "restart",
        container,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        message = stderr.decode(errors="replace").strip()
        raise RuntimeError(message or f"docker restart 退出码 {process.returncode}")


async def _wait_healthy(
    client: httpx.AsyncClient,
    probes: list[Probe],
    *,
    timeout: float,
    probe_timeout: float,
) -> bool:
    """轮询探测，直到全部通过或超时。"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        results = await asyncio.gather(
            *(_probe(client, probe, probe_timeout) for probe in probes)
        )
        if all(results):
            return True
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(RETRY_INTERVAL)


async def main() -> int:
    parser = argparse.ArgumentParser(description="检查本地 Compose 服务端口并重启异常容器")
    parser.add_argument("--no-restart", action="store_true", help="只检查，不重启容器")
    parser.add_argument("--timeout", type=float, default=PROBE_TIMEOUT, help="单次探测超时秒数")
    parser.add_argument(
        "--wait", type=float, default=WAIT_TIMEOUT, help="重启后等待服务恢复的秒数"
    )
    args = parser.parse_args()

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *(_probe(client, probe, args.timeout) for probe in PROBES)
        )
        for probe, healthy in zip(PROBES, results):
            print(f"{'OK  ' if healthy else 'FAIL'} {probe.name} ({probe.container})")

        failed = [probe for probe, healthy in zip(PROBES, results) if not healthy]
        if not failed:
            print("所有服务健康")
            return 0

        containers: list[str] = []
        for probe in failed:
            if probe.container not in containers:
                containers.append(probe.container)

        if args.no_restart:
            print(f"异常容器：{', '.join(containers)}（--no-restart，未处理）")
            return 1

        remaining: list[str] = []
        for container in containers:
            if not await _is_running(container):
                print(f"SKIP {container}（容器未运行，未自动重启）")
                remaining.append(container)
                continue
            print(f"RESTART {container}")
            try:
                await _restart(container)
            except RuntimeError as exc:
                print(f"FAIL {container} 重启失败：{exc}")
                remaining.append(container)
                continue
            probes = [probe for probe in failed if probe.container == container]
            if await _wait_healthy(
                client, probes, timeout=args.wait, probe_timeout=args.timeout
            ):
                print(f"OK   {container} 已恢复")
            else:
                print(f"FAIL {container} 重启后仍未恢复")
                remaining.append(container)

        if remaining:
            print(f"仍未恢复：{', '.join(remaining)}")
            return 1
        print("所有异常服务已恢复")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

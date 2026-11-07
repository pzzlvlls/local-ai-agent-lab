import httpx
from opensandbox import Sandbox
from deal_pilot.config.nacos_settings import nacos_settings
from deal_pilot.utils.sandbox import get_shared_sandbox
from deal_pilot.config.nacos.nacos_access_token import get_access_token
import asyncio


async def _save_skill(
    *, skill_name: str, sandbox: Sandbox, zip_path: str, skill_dir: str
):
    access_token = await get_access_token()

    async with httpx.AsyncClient(
        base_url=nacos_settings.server_address, headers={"accessToken": access_token}
    ) as client:
        response = await client.get(
            "/nacos/v3/client/ai/skills",
            params={
                "namespaceId": nacos_settings.namespace_id,
                "name": skill_name,
                "label": "production",
            },
        )
    # 校验 HTTP 状态与 Nacos 业务码，避免把错误 JSON 当 zip 落盘
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        body = response.json()
        if body.get("code") != 0:
            raise RuntimeError(
                f"拉取技能 {skill_name} 失败: code={body.get('code')} "
                f"message={body.get('message')} data={body.get('data')}"
            )
    zip_bytes = response.content
    await sandbox.files.write_file(zip_path, zip_bytes)
    # 解压缩 unzip -o 压缩包地址 -d 解压地址
    result = await sandbox.commands.run(
        f"mkdir -p {skill_dir} && " f"unzip -o {zip_path} -d {skill_dir}"
    )
    if result.exit_code != 0:
        raise RuntimeError(f"解压技能 {skill_name} 失败: {result.error}")

    print(len(zip_bytes))


async def save_skills(agent_name: str, skill_names: list[str] | None = None):
    "将指定的skills保存到共享卷中"
    if skill_names is None:
        skill_names = []
    sandbox = await get_shared_sandbox()
    skill_dir = f"/shared/skills/{agent_name}"
    await sandbox.commands.run(f"rm -rf {skill_dir}")
    await asyncio.gather(
        *[
            _save_skill(
                skill_name=skill_name,
                sandbox=sandbox,
                zip_path=f"/shared/skill_zips/{agent_name}/{skill_name}.zip",
                skill_dir=skill_dir,
            )
            for skill_name in skill_names
        ]
    )


if __name__ == "__main__":

    async def main():
        sandbox = await get_shared_sandbox()
        await _save_skill(
            skill_name="pptx",
            sandbox=sandbox,
            zip_path="/shared/skill_zips/main_agent/pptx.zip",
            skill_dir="/shared/skills/main_agent",
        )

    asyncio.run(main())

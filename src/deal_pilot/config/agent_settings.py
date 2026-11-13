from pydantic import Field, SecretStr

from deal_pilot.config.base_settings import BaseSettingsWithEnv


class AgentSettings(BaseSettingsWithEnv):
    server_url: str = "http://127.0.0.1:80"
    token_secret: SecretStr = SecretStr("")
    token_ttl_seconds: int = Field(default=300, gt=0)

    model_config = {"env_prefix": "AGENT_"}


agent_settings = AgentSettings()

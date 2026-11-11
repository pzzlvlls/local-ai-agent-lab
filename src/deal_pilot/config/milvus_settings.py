from deal_pilot.config.base_settings import BaseSettingsWithEnv


class MilvusSettings(BaseSettingsWithEnv):
    uri: str = "http://127.0.0.1:19530"
    db_name: str = "deal_pilot"

    model_config = {"env_prefix": "MILVUS_"}


milvus_settings = MilvusSettings()

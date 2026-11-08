from deal_pilot.config.base_settings import BaseSettingsWithEnv


class FeishuSettings(BaseSettingsWithEnv):
    app_id: str = ""
    app_secret: str = ""

    model_config = {"env_prefix": "FEISHU_"}


feishu_settings = FeishuSettings()

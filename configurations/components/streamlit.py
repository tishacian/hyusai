from pydantic_settings import BaseSettings, SettingsConfigDict


class StreamlitConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STREAMLIT_")

    server_address: str = "0.0.0.0"
    server_port: int = 8501
    server_enable_cors: bool = True
    server_enable_xsrf_protection: bool = True
    server_headless: bool = True
    server_max_upload_size: int = 200
    log_level: str = "info"
    browser_gather_usage_stats: bool = False

    def to_toml(self) -> dict:
        return {
            "logger": {"level": self.log_level},
            "server": {
                "address": self.server_address,
                "port": self.server_port,
                "enableCORS": self.server_enable_cors,
                "enableXsrfProtection": self.server_enable_xsrf_protection,
                "headless": self.server_headless,
                "maxUploadSize": self.server_max_upload_size,
            },
            "browser": {"gatherUsageStats": self.browser_gather_usage_stats},
        }

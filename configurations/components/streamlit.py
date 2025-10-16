from typing import Optional

from pydantic import BaseModel, Field


class LoggerConfig(BaseModel):
    level: str = Field(
        "info", description="Level of logging for Streamlit's internal logger"
    )


class ServerConfig(BaseModel):
    address: Optional[str] = Field(
        "0.0.0.0", description="Address to bind the server to"
    )
    port: int = Field(8501, description="Port to run the Streamlit server on")
    enableCORS: bool = Field(
        True, description="Whether to enable Cross-Origin Resource Sharing"
    )
    enableXsrfProtection: bool = Field(
        True, description="Whether to enable Cross-Site Request Forgery protection"
    )
    headless: bool = Field(
        True, description="Whether to run Streamlit in headless mode"
    )
    maxUploadSize: int = Field(200, description="Maximum upload size in MB")


class BrowserConfig(BaseModel):
    gatherUsageStats: bool = Field(
        False, description="Whether to gather anonymous usage stats"
    )


class StreamlitConfig(BaseModel):
    logger: LoggerConfig = Field(default_factory=LoggerConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)

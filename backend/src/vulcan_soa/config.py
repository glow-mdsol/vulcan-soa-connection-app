import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.environ.get("ENV_FILE", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    fhir_base_url: str
    oauth_authorize_url: str
    oauth_token_url: str
    smart_client_id: str
    smart_client_secret: str
    redirect_uri: str
    frontend_url: str = "http://localhost:5173"

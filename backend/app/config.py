from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./codesk.db"
    data_dir: Path = Path("./data")
    cors_origins: str = "http://localhost:5173"
    auth_enabled: bool = True
    auth_cookie_secure: bool = False  # set true when served over https
    session_days: int = 7
    seed_demo_data: bool = True  # fill an empty database with fictional drivers and 30 days of activity
    currency: str = "SAR"
    watch_enabled: bool = True  # look in the watch folder chosen on the Settings page
    watch_interval: int = 10    # seconds between looks


settings = Settings()

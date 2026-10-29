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
    ollama_url: str = "http://localhost:11434"  # the local AI that reads deposit slips (free, runs on this computer)
    slip_model: str = "qwen3-vl:4b"             # a small vision model that fits a laptop with 8 GB of memory
    slip_timeout: int = 300                     # seconds: a laptop without a graphics card reads a slip in 1-3 minutes


settings = Settings()

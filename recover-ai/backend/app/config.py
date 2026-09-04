from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "RecoverAI"
    database_url: str = "sqlite:///./recoverai.db"
    demo_data_path: str = "../data/demo_transactions.csv"
    cors_origins: list[str] = [
        "http://localhost:4000",
        "http://127.0.0.1:4000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    model_config = SettingsConfigDict(env_file=".env", env_prefix="RECOVERAI_")

    @property
    def sqlite_path(self) -> Path:
        if not self.database_url.startswith("sqlite:///"):
            raise ValueError("Initial RecoverAI version supports sqlite:/// database URLs only")
        raw_path = self.database_url.replace("sqlite:///", "", 1)
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        return path


settings = Settings()

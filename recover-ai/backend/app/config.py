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

    # LLM configuration (Ollama)
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:3b"
    llm_timeout: int = 30

    # Policy engine configuration
    max_retry_amount: float = 25000.0
    max_payment_link_amount: float = 50000.0
    min_ai_confidence: float = 0.6
    max_retry_count: int = 2

    # Razorpay Test Mode configuration
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_base_url: str = "https://api.razorpay.com/v1"
    razorpay_webhook_secret: str = ""

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

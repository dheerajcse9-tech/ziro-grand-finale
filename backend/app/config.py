from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(BACKEND_DIR / ".env", BACKEND_DIR.parent / ".env"), extra="ignore")

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout_s: float = 20.0
    gemini_max_retries: int = 1
    gemini_cooldown_s: float = 60.0
    database_url: str = "sqlite:///./data/doubtloop.db"
    chroma_persist_directory: str = "./data/chroma"
    upload_directory: str = "./data/uploads"
    frontend_origin: str = "http://localhost:3000"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    default_tenant_id: str = "demo-university"
    max_upload_mb: int = 25
    admin_token: str = ""  # if set, demo reset/test endpoints require X-Admin-Token; if empty they accept loopback clients only

    def _abs(self, p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else (BACKEND_DIR / path).resolve()

    @property
    def db_path(self) -> Path:
        return self._abs(self.database_url.removeprefix("sqlite:///"))

    @property
    def chroma_dir(self) -> Path:
        return self._abs(self.chroma_persist_directory)

    @property
    def upload_dir(self) -> Path:
        return self._abs(self.upload_directory)


@lru_cache
def get_settings() -> Settings:
    return Settings()

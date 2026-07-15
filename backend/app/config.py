from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用运行配置。"""

    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str
    jwt_secret: SecretStr
    encryption_key: SecretStr
    jwt_issuer: str = "ai-api-test-platform"
    jwt_access_token_expire_minutes: int = 60
    initial_admin_username: str | None = None
    initial_admin_password: SecretStr | None = None
    initial_admin_display_name: str = "系统管理员"
    frontend_origin: str = "http://localhost:5173"
    default_request_timeout_seconds: int = 20
    max_response_body_bytes: int = 1_048_576
    source_root_allowlist: str = ""
    source_upload_root: Path = Path("data/source-uploads")
    max_source_archive_bytes: int = 524_288_000
    max_source_file_bytes: int = 1_048_576
    max_source_file_count: int = 10_000
    max_source_total_bytes: int = 104_857_600
    max_openapi_document_bytes: int = 5_242_880
    embedding_dimensions: int = 1536
    embedding_model: str | None = None
    embedding_batch_size: int = 32
    embedding_max_attempts: int = 3
    embedding_timeout_seconds: int = 30
    knowledge_context_max_results: int = 20
    knowledge_context_max_characters: int = 12_000
    knowledge_vector_candidate_count: int = 20

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, value: SecretStr) -> SecretStr:
        """避免使用强度不足的 JWT 密钥。"""

        if len(value.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET 至少需要 32 个字符")
        return value

    @field_validator("initial_admin_password")
    @classmethod
    def validate_initial_admin_password(cls, value: SecretStr | None) -> SecretStr | None:
        """校验初始化管理员密码强度。"""

        if value is not None and len(value.get_secret_value()) < 12:
            raise ValueError("INITIAL_ADMIN_PASSWORD 至少需要 12 个字符")
        return value

    @field_validator("embedding_dimensions")
    @classmethod
    def validate_embedding_dimensions(cls, value: int) -> int:
        """当前 pgvector 索引固定使用 1536 维向量。"""

        if value != 1536:
            raise ValueError("EMBEDDING_DIMENSIONS 当前必须为 1536")
        return value

    @model_validator(mode="after")
    def validate_initial_admin(self) -> Self:
        """确保初始化管理员配置成对出现。"""

        if (self.initial_admin_username is None) != (self.initial_admin_password is None):
            raise ValueError("INITIAL_ADMIN_USERNAME 与 INITIAL_ADMIN_PASSWORD 必须同时配置")
        return self


@lru_cache
def get_settings() -> Settings:
    """获取缓存后的应用配置。"""

    return Settings()

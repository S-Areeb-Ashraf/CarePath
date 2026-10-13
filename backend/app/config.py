from functools import lru_cache
from pathlib import Path
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_env: str
    log_level: str = 'INFO'
    supabase_url: str
    supabase_service_role_key: str
    llm_provider: str = 'stub'
    llm_api_key: str
    llm_base_url: str = ''
    llm_model_primary: str
    llm_model_secondary: str
    llm_timeout_seconds: float = 10
    tool_timeout_seconds: float = 5
    cors_origins: list[str]
    admin_api_key: str
    enable_fault_injection: bool = False
    cancellation_auto_approve_hours: int = 24
    rag_min_relevance: float = 0.35
    rag_top_k: int = 4
    auth_secret: str = ''
    auth_token_ttl_hours: int = 72
    serper_api_key: str = ''
    web_search_num_results: int = 5
    chroma_persist_dir: str = './chroma_store'
    chroma_collection_name: str = 'clinic_knowledge'
    embedding_base_url: str = ''
    embedding_model: str = ''
    embedding_api_key: str = ''
    agent_max_iterations: int = 6
    clinic_timezone: str = 'Asia/Riyadh'
    clinic_utc_offset_hours: int = 3  # fallback when the IANA name is unavailable (Windows without tzdata)
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[1] / '.env', env_prefix='', case_sensitive=False)

    @field_validator('cors_origins', mode='before')
    @classmethod
    def split_origins(cls, value: object) -> list[str]:
        if isinstance(value, list):
            return [str(part).strip() for part in value if str(part).strip()]
        return [part.strip() for part in str(value).split(',') if part.strip()]

    @model_validator(mode='after')
    def require_llm_endpoint(self) -> 'Settings':
        if self.llm_provider != 'stub' and not self.llm_base_url:
            raise ValueError('LLM_BASE_URL is required when LLM_PROVIDER is not stub')
        return self

    def require_auth_secret(self) -> str:
        """Resolve the auth secret from configuration. Nothing is hardcoded."""
        if not self.auth_secret:
            raise ValueError('AUTH_SECRET is required for authentication endpoints')
        return self.auth_secret

@lru_cache
def get_settings() -> Settings:
    return Settings()

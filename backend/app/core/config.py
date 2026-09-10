from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"

    database_url: str
    test_database_url: str | None = None

    historical_backfill_years: int = 5

    sec_edgar_user_agent: str

    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    fmp_api_key: str = ""
    fred_api_key: str = ""
    marketaux_api_key: str = ""
    alpha_vantage_api_key: str = ""
    finnhub_api_key: str = ""

    # News extraction (spec §5): real Claude Haiku 4.5 via the Anthropic API,
    # not a heuristic — see docs/ai-stock-ranking-mvp-spec.md §5 for the
    # "LLM choice" rationale. Model is a setting, not hardcoded, so upgrading
    # to a larger model later is a one-line config change.
    anthropic_api_key: str = ""
    news_llm_model: str = "claude-haiku-4-5"
    news_lookback_hours: int = 24


@lru_cache
def get_settings() -> Settings:
    return Settings()

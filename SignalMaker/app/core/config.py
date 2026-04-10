from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="SignalMaker", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8080, alias="APP_PORT")
    database_url: str = Field(default="sqlite:///./signalmaker.db", alias="DATABASE_URL")
    sql_echo: bool = Field(default=False, alias="SQL_ECHO")
    create_tables_on_boot: bool = Field(default=True, alias="CREATE_TABLES_ON_BOOT")
    cors_origins: str = Field(default="http://localhost:3000,http://localhost:8080", alias="CORS_ORIGINS")

    binance_rest_base: str = Field(default="https://api.binance.com", alias="BINANCE_REST_BASE")
    binance_quote_assets: str = Field(default="USDT,USDC", alias="BINANCE_QUOTE_ASSETS")
    binance_symbol_status: str = Field(default="TRADING", alias="BINANCE_SYMBOL_STATUS")
    binance_max_symbols: int = Field(default=25, alias="BINANCE_MAX_SYMBOLS")
    binance_lookback_1m: int = Field(default=180, alias="BINANCE_LOOKBACK_1M")
    binance_lookback_5m: int = Field(default=180, alias="BINANCE_LOOKBACK_5M")
    binance_lookback_1h: int = Field(default=180, alias="BINANCE_LOOKBACK_1H")
    binance_lookback_4h: int = Field(default=120, alias="BINANCE_LOOKBACK_4H")

    session_timezone_offset_hours: int = Field(default=-4, alias="SESSION_TIMEZONE_OFFSET_HOURS")
    signal_rsi_period: int = Field(default=14, alias="SIGNAL_RSI_PERIOD")
    signal_swing_window: int = Field(default=8, alias="SIGNAL_SWING_WINDOW")
    signal_equal_level_tolerance_pct: float = Field(default=0.0015, alias="SIGNAL_EQUAL_LEVEL_TOLERANCE_PCT")
    signal_overbought: float = Field(default=70, alias="SIGNAL_OVERBOUGHT")
    signal_oversold: float = Field(default=30, alias="SIGNAL_OVERSOLD")
    signal_price_near_extreme_pct: float = Field(default=0.0025, alias="SIGNAL_PRICE_NEAR_EXTREME_PCT")
    signal_session_confirm_filter_enabled: bool = Field(default=True, alias="SIGNAL_SESSION_CONFIRM_FILTER_ENABLED")

    planner_min_score: float = Field(default=4, alias="PLANNER_MIN_SCORE")
    planner_min_rr: float = Field(default=0.8, alias="PLANNER_MIN_RR")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def quote_assets_list(self) -> list[str]:
        return [item.strip().upper() for item in self.binance_quote_assets.split(",") if item.strip()]

    def signal_config(self) -> dict:
        return {
            "rsi_period": self.signal_rsi_period,
            "swing_window": self.signal_swing_window,
            "equal_level_tolerance_pct": self.signal_equal_level_tolerance_pct,
            "session_timezone_offset_hours": self.session_timezone_offset_hours,
            "session_confirm_filter_enabled": self.signal_session_confirm_filter_enabled,
            "signals": {
                "overbought": self.signal_overbought,
                "oversold": self.signal_oversold,
                "price_near_extreme_pct": self.signal_price_near_extreme_pct,
            },
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

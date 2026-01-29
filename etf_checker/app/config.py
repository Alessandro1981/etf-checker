"""Configuration loading for the ETF Checker add-on."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

OPTIONS_PATH = Path("/data/options.json")
UI_CONFIG_PATH = Path("/data/ui_config.json")


@dataclass(slots=True)
class AddonOptions:
    """Supervisor-provided options."""

    homeassistant_url: str = "http://supervisor/core"
    homeassistant_token: str = ""
    notify_service: str = "notify/mobile_app_mio_telefono"
    alpha_vantage_api_key: str = ""
    poll_interval_seconds: int = 900
    default_threshold_percent: float = 2.0
    log_level: str = "INFO"


@dataclass(slots=True)
class UiConfig:
    """User-defined configuration stored via the add-on UI."""

    etf_symbols: list[str]
    threshold_percent: float
    market_open_retry_seconds: int
    finnhub_api_key: str = ""


@dataclass(slots=True)
class EffectiveConfig:
    """Merged configuration used by the monitor."""

    options: AddonOptions
    ui: UiConfig


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_addon_options() -> AddonOptions:
    raw = _load_json(OPTIONS_PATH)
    return AddonOptions(
        homeassistant_url=str(raw.get("homeassistant_url", AddonOptions.homeassistant_url)),
        homeassistant_token=str(raw.get("homeassistant_token", AddonOptions.homeassistant_token)),
        notify_service=str(raw.get("notify_service", AddonOptions.notify_service)),
        alpha_vantage_api_key=str(raw.get("alpha_vantage_api_key", AddonOptions.alpha_vantage_api_key)),
        poll_interval_seconds=int(raw.get("poll_interval_seconds", AddonOptions.poll_interval_seconds)),
        default_threshold_percent=float(
            raw.get("default_threshold_percent", AddonOptions.default_threshold_percent)
        ),
        log_level=str(raw.get("log_level", AddonOptions.log_level)),
    )


def load_ui_config(default_threshold: float) -> UiConfig:
    raw = _load_json(UI_CONFIG_PATH)
    symbols = raw.get("etf_symbols", [])
    if not isinstance(symbols, list):
        symbols = []
    cleaned_symbols = [str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()]
    threshold = raw.get("threshold_percent", default_threshold)
    try:
        threshold_value = float(threshold)
    except (TypeError, ValueError):
        threshold_value = default_threshold
    retry_raw = raw.get("market_open_retry_seconds", 60)
    try:
        retry_value = int(retry_raw)
    except (TypeError, ValueError):
        retry_value = 60
    retry_value = max(retry_value, 0)
    finnhub_api_key = str(raw.get("finnhub_api_key", "")).strip()
    return UiConfig(
        etf_symbols=cleaned_symbols,
        threshold_percent=max(threshold_value, 0.1),
        market_open_retry_seconds=retry_value,
        finnhub_api_key=finnhub_api_key,
    )


def save_ui_config(config: UiConfig) -> None:
    UI_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "etf_symbols": config.etf_symbols,
        "threshold_percent": config.threshold_percent,
        "market_open_retry_seconds": config.market_open_retry_seconds,
        "finnhub_api_key": config.finnhub_api_key,
    }
    with UI_CONFIG_PATH.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def load_effective_config() -> EffectiveConfig:
    options = load_addon_options()
    ui = load_ui_config(options.default_threshold_percent)
    return EffectiveConfig(options=options, ui=ui)

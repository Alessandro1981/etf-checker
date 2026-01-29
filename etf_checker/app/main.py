"""Entrypoint for the ETF Checker add-on."""

from __future__ import annotations

import logging
import os
import platform
import sys
from datetime import datetime
from typing import Any

from flask import Flask, jsonify, redirect, render_template, request, url_for

from pathlib import Path
from zoneinfo import ZoneInfo

from .config import EffectiveConfig, UiConfig, load_effective_config, save_ui_config
from .etf_monitor import EtfMonitor

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
LOGGER = logging.getLogger(__name__)

APP = Flask(__name__)
MONITOR = EtfMonitor(load_effective_config())
MONITOR.start()


def _ingress_root() -> str:
    return os.environ.get("SUPERVISOR_INGRESS", "").rstrip("/")


def _redact_token(token: str) -> str:
    if not token:
        return "<empty>"
    if len(token) <= 8:
        return "***"
    return f"{token[:4]}...{token[-4:]}"


def _log_startup_diagnostics() -> None:
    if not LOGGER.isEnabledFor(logging.DEBUG):
        return
    LOGGER.debug("Runtime: python=%s platform=%s", sys.version.replace("\n", " "), platform.platform())
    LOGGER.debug("Runtime: uid=%s gid=%s cwd=%s", os.getuid(), os.getgid(), os.getcwd())
    config = load_effective_config()
    options = config.options
    ui = config.ui
    LOGGER.debug("Effective config: homeassistant_url=%s", options.homeassistant_url)
    LOGGER.debug("Effective config: notify_service=%s", options.notify_service)
    LOGGER.debug("Effective config: alpha_vantage_api_key=%s", _redact_token(options.alpha_vantage_api_key))
    LOGGER.debug("Effective config: poll_interval_seconds=%s", options.poll_interval_seconds)
    LOGGER.debug("Effective config: default_threshold_percent=%s", options.default_threshold_percent)
    LOGGER.debug("Effective config: log_level=%s", options.log_level)
    LOGGER.debug("Effective config: homeassistant_token=%s", _redact_token(options.homeassistant_token))
    LOGGER.debug("UI config: symbols=%s", ", ".join(ui.etf_symbols) if ui.etf_symbols else "<none>")
    LOGGER.debug("UI config: threshold_percent=%s", ui.threshold_percent)
    LOGGER.debug("UI config: market_open_retry_seconds=%s", ui.market_open_retry_seconds)
    LOGGER.debug("UI config: finnhub_api_key=%s", _redact_token(ui.finnhub_api_key))
    data_path = Path("/data")
    LOGGER.debug("Data path exists: %s", data_path.exists())
    LOGGER.debug("Options file exists: %s", Path("/data/options.json").exists())
    LOGGER.debug("UI config file exists: %s", Path("/data/ui_config.json").exists())
    LOGGER.debug("State file exists: %s", Path("/data/monitor_state.json").exists())


def _install_exception_logging() -> None:
    def _log_exception(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
        LOGGER.exception("Unhandled exception", exc_info=(exc_type, exc, tb))

    sys.excepthook = _log_exception


def _merge_config(ui_config: UiConfig) -> EffectiveConfig:
    current = load_effective_config()
    return EffectiveConfig(options=current.options, ui=ui_config)


def _parse_symbols(raw_symbols: str) -> list[str]:
    symbols = [item.strip().upper() for item in raw_symbols.split(",")]
    return [symbol for symbol in symbols if symbol]


def _format_baseline_update(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Europe/Rome"))
    else:
        parsed = parsed.astimezone(ZoneInfo("Europe/Rome"))
    return parsed.strftime("%Y-%m-%d %H:%M:%S CET")


@APP.route("/")
def index() -> str:
    config = load_effective_config()
    state = MONITOR.state
    baselines = {
        symbol: state.baselines.get(symbol)
        for symbol in config.ui.etf_symbols
        if symbol in state.baselines
    }
    return render_template(
        "index.html",
        ingress_root=_ingress_root(),
        symbols=", ".join(config.ui.etf_symbols),
        threshold=config.ui.threshold_percent,
        market_open_retry_seconds=config.ui.market_open_retry_seconds,
        finnhub_api_key=config.ui.finnhub_api_key,
        poll_interval=config.options.poll_interval_seconds,
        notify_service=config.options.notify_service,
        baselines=baselines,
        last_baseline_update=_format_baseline_update(state.last_baseline_update),
    )


@APP.get("/api/config")
def get_config() -> Any:
    config = load_effective_config()
    state = MONITOR.state
    payload = {
        "etf_symbols": config.ui.etf_symbols,
        "threshold_percent": config.ui.threshold_percent,
        "market_open_retry_seconds": config.ui.market_open_retry_seconds,
        "poll_interval_seconds": config.options.poll_interval_seconds,
        "notify_service": config.options.notify_service,
        "baselines": state.baselines,
        "last_baseline_update": state.last_baseline_update,
    }
    return jsonify(payload)


@APP.post("/api/config")
def update_config() -> Any:
    data = request.get_json(silent=True) or {}
    raw_symbols = str(data.get("etf_symbols", ""))
    symbols = _parse_symbols(raw_symbols)
    threshold_raw = data.get("threshold_percent")
    try:
        threshold = float(threshold_raw)
    except (TypeError, ValueError):
        threshold = load_effective_config().options.default_threshold_percent
    threshold = max(threshold, 0.1)
    retry_raw = data.get("market_open_retry_seconds", load_effective_config().ui.market_open_retry_seconds)
    try:
        retry_after_open = int(retry_raw)
    except (TypeError, ValueError):
        retry_after_open = load_effective_config().ui.market_open_retry_seconds
    retry_after_open = max(retry_after_open, 0)
    finnhub_raw = data.get("finnhub_api_key", load_effective_config().ui.finnhub_api_key)
    finnhub_api_key = str(finnhub_raw or "").strip()
    ui_config = UiConfig(
        etf_symbols=symbols,
        threshold_percent=threshold,
        market_open_retry_seconds=retry_after_open,
        finnhub_api_key=finnhub_api_key,
    )
    save_ui_config(ui_config)
    MONITOR.update_config(_merge_config(ui_config))
    MONITOR.run_once()
    return jsonify(
        {
            "status": "ok",
            "etf_symbols": symbols,
            "threshold_percent": threshold,
            "market_open_retry_seconds": retry_after_open,
        }
    )


@APP.post("/api/poll")
def trigger_poll() -> Any:
    MONITOR.run_once()
    return jsonify({"status": "ok"})


@APP.route("/health")
def health() -> Any:
    return jsonify({"status": "ok"})


@APP.route("/ingress")
def ingress_redirect() -> Any:
    root = _ingress_root()
    if root:
        return redirect(f"{root}/")
    return redirect(url_for("index"))


def main() -> None:
    port = int(os.environ.get("PORT", "8099"))
    ingress_entry = _ingress_root()
    _install_exception_logging()
    LOGGER.info("Starting ETF Checker on port %s (ingress root: %s)", port, ingress_entry or "-")
    _log_startup_diagnostics()
    try:
        APP.run(host="0.0.0.0", port=port, debug=False)
    except Exception:  # noqa: BLE001
        LOGGER.exception("Flask server failed to start")
        raise


if __name__ == "__main__":
    main()

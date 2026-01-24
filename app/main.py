"""Entrypoint for the ETF Checker add-on."""

from __future__ import annotations

import logging
import os
from typing import Any

from flask import Flask, jsonify, redirect, render_template, request, url_for

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


def _merge_config(ui_config: UiConfig) -> EffectiveConfig:
    current = load_effective_config()
    return EffectiveConfig(options=current.options, ui=ui_config)


def _parse_symbols(raw_symbols: str) -> list[str]:
    symbols = [item.strip().upper() for item in raw_symbols.split(",")]
    return [symbol for symbol in symbols if symbol]


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
        poll_interval=config.options.poll_interval_seconds,
        notify_service=config.options.notify_service,
        baselines=baselines,
    )


@APP.get("/api/config")
def get_config() -> Any:
    config = load_effective_config()
    state = MONITOR.state
    payload = {
        "etf_symbols": config.ui.etf_symbols,
        "threshold_percent": config.ui.threshold_percent,
        "poll_interval_seconds": config.options.poll_interval_seconds,
        "notify_service": config.options.notify_service,
        "baselines": state.baselines,
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
    ui_config = UiConfig(etf_symbols=symbols, threshold_percent=threshold)
    save_ui_config(ui_config)
    MONITOR.update_config(_merge_config(ui_config))
    MONITOR.run_once()
    return jsonify({"status": "ok", "etf_symbols": symbols, "threshold_percent": threshold})


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
    LOGGER.info("Starting ETF Checker on port %s (ingress root: %s)", port, ingress_entry or "-")
    APP.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()

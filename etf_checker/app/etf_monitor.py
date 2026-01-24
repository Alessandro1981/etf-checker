"""ETF monitoring logic."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable

from .config import EffectiveConfig
from .ha_client import HomeAssistantClient
from .storage import MonitorState, load_state, save_state

LOGGER = logging.getLogger(__name__)

PriceProvider = Callable[[Iterable[str]], dict[str, float]]
Notifier = Callable[[str, str], None]


def default_price_provider(symbols: Iterable[str]) -> dict[str, float]:
    """Fetch latest ETF prices from Yahoo Finance without heavy dependencies."""

    symbol_list = [symbol.strip().upper() for symbol in symbols if symbol]
    if not symbol_list:
        return {}
    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    headers = {"User-Agent": "ETF-Checker/1.0"}
    try:
        import requests

        params = {"symbols": ",".join(symbol_list)}
        for attempt in range(2):
            response = requests.get(url, params=params, headers=headers, timeout=15)
            if response.status_code == 429 and attempt == 0:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and str(retry_after).isdigit() else 2.0
                LOGGER.warning("Yahoo Finance rate limited (429). Retrying in %.1fs.", delay)
                time.sleep(delay)
                continue
            response.raise_for_status()
            break
    except ModuleNotFoundError:
        LOGGER.warning("requests is not installed; cannot fetch prices.")
        return {}
    except requests.RequestException as err:
        LOGGER.warning("Yahoo Finance request failed: %s", err)
        return {}
    payload = response.json()
    results = payload.get("quoteResponse", {}).get("result", [])
    prices: dict[str, float] = {}
    for item in results:
        symbol = str(item.get("symbol", "")).upper()
        price = item.get("regularMarketPrice")
        if symbol and price is not None:
            try:
                prices[symbol] = float(price)
            except (TypeError, ValueError):
                continue
    missing = [symbol for symbol in symbol_list if symbol not in prices]
    if missing:
        LOGGER.warning("No prices returned for symbols: %s", ", ".join(missing))
    return prices


def percent_change(reference: float, current: float) -> float:
    if reference == 0:
        return 0.0
    return ((current - reference) / reference) * 100.0


@dataclass(slots=True)
class MonitorDependencies:
    price_provider: PriceProvider = default_price_provider


class EtfMonitor:
    """Background monitor that checks ETF changes and sends notifications."""

    def __init__(self, config: EffectiveConfig, dependencies: MonitorDependencies | None = None) -> None:
        self._config = config
        self._deps = dependencies or MonitorDependencies()
        self._state: MonitorState = load_state()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._ha_client = HomeAssistantClient(
            base_url=config.options.homeassistant_url.rstrip("/"),
            token=config.options.homeassistant_token,
            notify_service=config.options.notify_service,
        )

    @property
    def state(self) -> MonitorState:
        with self._lock:
            return MonitorState(baselines=dict(self._state.baselines))

    def update_config(self, config: EffectiveConfig) -> None:
        with self._lock:
            self._config = config
            self._ha_client = HomeAssistantClient(
                base_url=config.options.homeassistant_url.rstrip("/"),
                token=config.options.homeassistant_token,
                notify_service=config.options.notify_service,
            )

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="etf-monitor", daemon=True)
        self._thread.start()
        LOGGER.info("ETF monitor started.")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        LOGGER.info("ETF monitor stopped.")

    def run_once(self) -> None:
        with self._lock:
            config = self._config
            symbols = list(dict.fromkeys(config.ui.etf_symbols))
            threshold = config.ui.threshold_percent
        if not symbols:
            LOGGER.debug("No ETF symbols configured; skipping poll.")
            return
        try:
            prices = self._deps.price_provider(symbols)
        except Exception as err:  # noqa: BLE001
            LOGGER.exception("Failed to fetch ETF prices: %s", err)
            return
        if not prices:
            LOGGER.warning("Price provider returned no prices.")
            return
        alerts: list[tuple[str, float, float, float]] = []
        with self._lock:
            for symbol, current_price in prices.items():
                baseline = self._state.baselines.get(symbol)
                if baseline is None:
                    self._state.baselines[symbol] = current_price
                    continue
                change = percent_change(baseline, current_price)
                if abs(change) >= threshold:
                    alerts.append((symbol, baseline, current_price, change))
                    self._state.baselines[symbol] = current_price
            save_state(self._state)
        for symbol, baseline, current_price, change in alerts:
            self._notify(symbol, baseline, current_price, change, threshold)

    def _notify(self, symbol: str, baseline: float, current_price: float, change: float, threshold: float) -> None:
        direction = "salito" if change > 0 else "sceso"
        title = f"ETF {symbol} {direction}"
        message = (
            f"{symbol} è {direction} del {change:.2f}% (soglia {threshold:.2f}%). "
            f"Baseline: {baseline:.2f}, attuale: {current_price:.2f}."
        )
        if not self._ha_client.is_configured():
            LOGGER.warning("Home Assistant client non configurato; alert non inviato: %s", message)
            return
        try:
            self._ha_client.send_notification(title=title, message=message)
            LOGGER.info("Alert inviato per %s: %s", symbol, message)
        except Exception as err:  # noqa: BLE001
            LOGGER.exception("Invio alert fallito per %s: %s", symbol, err)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self.run_once()
            with self._lock:
                interval = max(self._config.options.poll_interval_seconds, 60)
            self._stop_event.wait(interval)

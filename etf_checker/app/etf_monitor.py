"""ETF monitoring logic."""

from __future__ import annotations

import csv
import io
import logging
import threading
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Callable, Iterable

from .config import EffectiveConfig
from .ha_client import HomeAssistantClient
from .storage import MonitorState, load_state, save_state

LOGGER = logging.getLogger(__name__)

PriceProvider = Callable[[Iterable[str]], dict[str, float]]
Notifier = Callable[[str, str], None]
_YAHOO_CRUMB_TTL_SECONDS = 1800
_yahoo_session: "requests.Session | None" = None
_yahoo_crumb: str | None = None
_yahoo_crumb_timestamp: float | None = None


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    try:
        parsed = parsedate_to_datetime(value)
        if parsed is None:
            return None
        seconds = (parsed - parsed.now(parsed.tzinfo)).total_seconds()
        return max(seconds, 0.0)
    except (TypeError, ValueError, OverflowError):
        return None


def _sleep_for_retry_after(retry_after: str | None, fallback_delay: float, context: str) -> None:
    delay = _retry_after_seconds(retry_after)
    if delay is None:
        delay = fallback_delay
    LOGGER.warning("Yahoo Finance rate limited (%s). Retrying in %.1fs.", context, delay)
    time.sleep(delay)


def _fetch_prices_batch(symbols: list[str]) -> dict[str, float]:
    urls = [
        "https://query2.finance.yahoo.com/v7/finance/quote",
        "https://query1.finance.yahoo.com/v7/finance/quote",
    ]
    headers = {"User-Agent": "ETF-Checker/1.0", "Accept": "application/json"}
    try:
        import requests

        params = {"symbols": ",".join(symbols)}
        last_error: Exception | None = None
        for url in urls:
            delay = 2.0
            for attempt in range(3):
                response = requests.get(url, params=params, headers=headers, timeout=15)
                if response.status_code == 429 and attempt < 2:
                    _sleep_for_retry_after(response.headers.get("Retry-After"), delay, "quote")
                    delay *= 2
                    continue
                if response.status_code == 401:
                    last_error = requests.HTTPError("401 Unauthorized")
                    break
                response.raise_for_status()
                last_error = None
                break
            if last_error is None:
                break
        if last_error is not None:
            raise last_error
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
    return prices


def _fetch_prices_yahoo_with_crumb(symbols: list[str]) -> dict[str, float]:
    """Fallback provider using Yahoo Finance crumb/cookie flow."""
    if not symbols:
        return {}
    headers = {"User-Agent": "ETF-Checker/1.0", "Accept": "application/json"}
    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    url_no_crumb = "https://query2.finance.yahoo.com/v7/finance/quote"
    prices: dict[str, float] = {}
    try:
        import requests

        global _yahoo_session
        global _yahoo_crumb
        global _yahoo_crumb_timestamp
        if _yahoo_session is None:
            _yahoo_session = requests.Session()
            _yahoo_session.get("https://fc.yahoo.com", headers=headers, timeout=10)
        session = _yahoo_session
        params = {"symbols": ",".join(symbols)}
        response = None
        delay = 2.0
        for attempt in range(3):
            response = session.get(url_no_crumb, params=params, headers=headers, timeout=15)
            if response.status_code == 429 and attempt < 2:
                _sleep_for_retry_after(response.headers.get("Retry-After"), delay, "quote")
                delay *= 2
                continue
            break
        if response is None:
            return {}
        if response.status_code in {401, 429}:
            now = time.monotonic()
            if (
                _yahoo_crumb
                and _yahoo_crumb_timestamp
                and now - _yahoo_crumb_timestamp < _YAHOO_CRUMB_TTL_SECONDS
            ):
                crumb = _yahoo_crumb
            else:
                crumb = ""
                delay = 2.0
                for attempt in range(3):
                    crumb_response = session.get(
                        "https://query1.finance.yahoo.com/v1/test/getcrumb", headers=headers, timeout=10
                    )
                    if crumb_response.status_code == 429 and attempt < 2:
                        _sleep_for_retry_after(crumb_response.headers.get("Retry-After"), delay, "crumb")
                        delay *= 2
                        continue
                    crumb_response.raise_for_status()
                    crumb = crumb_response.text.strip()
                    break
                if crumb:
                    _yahoo_crumb = crumb
                    _yahoo_crumb_timestamp = now
            if not crumb:
                return {}
            params = {"symbols": ",".join(symbols), "crumb": crumb}
            delay = 2.0
            for attempt in range(3):
                response = session.get(url, params=params, headers=headers, timeout=15)
                if response.status_code == 429 and attempt < 2:
                    _sleep_for_retry_after(response.headers.get("Retry-After"), delay, "quote")
                    delay *= 2
                    continue
                break
        response.raise_for_status()
    except ModuleNotFoundError:
        LOGGER.warning("requests is not installed; cannot fetch crumb prices.")
        return {}
    except requests.RequestException as err:
        LOGGER.warning("Yahoo Finance crumb request failed: %s", err)
        return {}
    payload = response.json()
    results = payload.get("quoteResponse", {}).get("result", [])
    for item in results:
        symbol = str(item.get("symbol", "")).upper()
        price = item.get("regularMarketPrice")
        if symbol and price is not None:
            try:
                prices[symbol] = float(price)
            except (TypeError, ValueError):
                continue
    return prices


def _fetch_prices_stooq(symbols: list[str]) -> dict[str, float]:
    """Fallback provider using Stooq CSV endpoint."""
    if not symbols:
        return {}
    headers = {"User-Agent": "ETF-Checker/1.0", "Accept": "text/csv"}
    url = "https://stooq.com/q/l/"
    prices: dict[str, float] = {}
    try:
        import requests

        for symbol in symbols:
            params = {"s": symbol.lower(), "f": "sd2t2ohlcv", "h": "", "e": "csv"}
            response = requests.get(url, params=params, headers=headers, timeout=15)
            response.raise_for_status()
            reader = csv.DictReader(io.StringIO(response.text))
            row = next(reader, None)
            if not row:
                continue
            close_value = row.get("Close")
            if close_value in (None, "", "N/A"):
                continue
            try:
                prices[symbol.upper()] = float(close_value)
            except (TypeError, ValueError):
                continue
    except ModuleNotFoundError:
        LOGGER.warning("requests is not installed; cannot fetch fallback prices.")
        return {}
    except requests.RequestException as err:
        LOGGER.warning("Stooq request failed: %s", err)
        return {}
    return prices


def _fetch_prices_with_suffixes(
    symbols: list[str], suffixes: Iterable[str], fetcher: Callable[[list[str]], dict[str, float]]
) -> dict[str, float]:
    if not symbols:
        return {}
    mapped: dict[str, float] = {}
    for suffix in suffixes:
        lookup = {symbol: f"{symbol}{suffix}" for symbol in symbols if "." not in symbol}
        if not lookup:
            continue
        fetched = fetcher(list(lookup.values()))
        for original, candidate in lookup.items():
            if original in mapped:
                continue
            price = fetched.get(candidate.upper())
            if price is not None:
                mapped[original] = price
        symbols = [symbol for symbol in symbols if symbol not in mapped]
        if not symbols:
            break
    return mapped


def default_price_provider(symbols: Iterable[str]) -> dict[str, float]:
    """Fetch latest ETF prices from Yahoo Finance without heavy dependencies."""

    symbol_list = [symbol.strip().upper() for symbol in symbols if symbol]
    if not symbol_list:
        return {}
    prices: dict[str, float] = {}
    batch_size = 5
    for index in range(0, len(symbol_list), batch_size):
        batch = symbol_list[index : index + batch_size]
        prices.update(_fetch_prices_batch(batch))
        if index + batch_size < len(symbol_list):
            time.sleep(0.5)
    missing = [symbol for symbol in symbol_list if symbol not in prices]
    if missing:
        LOGGER.warning("Attempting Yahoo Finance crumb fallback for symbols: %s", ", ".join(missing))
        prices.update(_fetch_prices_yahoo_with_crumb(missing))
        missing = [symbol for symbol in symbol_list if symbol not in prices]
    if missing:
        LOGGER.warning("Attempting Stooq fallback for symbols: %s", ", ".join(missing))
        prices.update(_fetch_prices_stooq(missing))
        missing = [symbol for symbol in symbol_list if symbol not in prices]
    if missing:
        suffixes = [".MI", ".DE", ".PA", ".L"]
        LOGGER.warning(
            "Attempting suffix fallback for symbols: %s (suffixes: %s)",
            ", ".join(missing),
            ", ".join(suffixes),
        )
        prices.update(_fetch_prices_with_suffixes(missing, suffixes, _fetch_prices_stooq))
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

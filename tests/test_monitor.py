from __future__ import annotations

from pathlib import Path

from app.config import AddonOptions, EffectiveConfig, UiConfig
from app.etf_monitor import EtfMonitor, MonitorDependencies, percent_change


def test_percent_change_handles_growth_and_zero_reference() -> None:
    assert percent_change(100.0, 110.0) == 10.0
    assert percent_change(0.0, 110.0) == 0.0


def test_monitor_triggers_alert_and_resets_baseline(monkeypatch, tmp_path: Path) -> None:
    state_path = tmp_path / "monitor_state.json"
    monkeypatch.setattr("app.storage.STATE_PATH", state_path)

    sent_messages: list[tuple[str, str]] = []

    def fake_send_notification(self, title: str, message: str, data=None) -> None:  # noqa: ANN001
        sent_messages.append((title, message))

    monkeypatch.setattr("app.ha_client.HomeAssistantClient.send_notification", fake_send_notification)

    prices = [
        {"SWDA.MI": 100.0},
        {"SWDA.MI": 103.0},
        {"SWDA.MI": 106.5},
    ]

    def fake_price_provider(symbols):  # noqa: ANN001
        return prices.pop(0)

    config = EffectiveConfig(
        options=AddonOptions(
            homeassistant_url="http://homeassistant.local:8123",
            homeassistant_token="token",
            notify_service="notify/mobile_app_phone",
            poll_interval_seconds=300,
            default_threshold_percent=2.0,
        ),
        ui=UiConfig(etf_symbols=["SWDA.MI"], threshold_percent=2.0),
    )

    monitor = EtfMonitor(config, dependencies=MonitorDependencies(price_provider=fake_price_provider))

    monitor.run_once()
    assert sent_messages == []

    monitor.run_once()
    assert len(sent_messages) == 1

    monitor.run_once()
    assert len(sent_messages) == 2

    saved_state = state_path.read_text(encoding="utf-8")
    assert "SWDA.MI" in saved_state

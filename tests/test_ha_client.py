from __future__ import annotations

import pytest

from app.ha_client import HomeAssistantClient


def test_split_service_accepts_slash_and_dot() -> None:
    assert HomeAssistantClient._split_service("notify/mobile_app_pixel") == (
        "notify",
        "mobile_app_pixel",
    )
    assert HomeAssistantClient._split_service("notify.mobile_app_pixel") == (
        "notify",
        "mobile_app_pixel",
    )


def test_split_service_rejects_invalid_format() -> None:
    with pytest.raises(ValueError):
        HomeAssistantClient._split_service("mobile_app_pixel")

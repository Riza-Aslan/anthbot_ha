"""Diagnostics for the Anthbot integration.

Downloading diagnostics is how a user shares device state for a bug report, so
everything that identifies the mower or the network it sits on is redacted.

The map file is included base64-encoded: its binary format is not yet
understood (see PROTOCOL.md), and having a real sample is what makes analysing
it possible. It contains lawn geometry only, no account data.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import AnthbotGenieApiError
from .const import DOMAIN
from .coordinator import AnthbotGenieDataUpdateCoordinator

# Identifiers and network details, wherever they appear in the shadow.
TO_REDACT = {
    "sn",
    "serial_number",
    "sta_ip_addr",
    "sta_ssid",
    "ip",
    "ssid",
    "4g_ccid",
    "pin_code",
    "uuid",
    "map_file_name",
    "md5",
    "access_key_id",
    "secret_access_key",
    "session_token",
}

# A map big enough to blow up a diagnostics download is more likely a sign the
# filename was wrong than a genuinely huge lawn.
MAX_MAP_BYTES = 2 * 1024 * 1024


def _map_files(state: dict[str, Any]) -> list[str]:
    """Return map file names advertised in the shadow."""
    multi_maps = state.get("multi_maps")
    if not isinstance(multi_maps, dict):
        return []
    map_list = multi_maps.get("map_list")
    if not isinstance(map_list, list):
        return []
    return [
        name
        for entry in map_list
        if isinstance(entry, dict)
        and isinstance((name := entry.get("map_file_name")), str)
        and name
    ]


async def _async_map_file_diagnostics(
    coordinator: AnthbotGenieDataUpdateCoordinator,
) -> list[dict[str, Any]]:
    """Fetch each advertised map file and describe it."""
    results: list[dict[str, Any]] = []
    for filename in _map_files(coordinator.reported_state):
        entry: dict[str, Any] = {"sub_category": "map"}
        try:
            raw = await coordinator.account_client.async_get_device_file(
                coordinator.client.serial_number,
                filename=filename,
                sub_category="map",
            )
        except AnthbotGenieApiError as err:
            entry["error"] = str(err)
            results.append(entry)
            continue

        entry["size"] = len(raw)
        entry["sha256"] = hashlib.sha256(raw).hexdigest()
        # First bytes make the container obvious (gzip, PNG, protobuf, ...)
        # even when the payload itself is too large to include.
        entry["head_hex"] = raw[:64].hex(" ")
        if len(raw) <= MAX_MAP_BYTES:
            entry["base64"] = base64.b64encode(raw).decode("ascii")
        else:
            entry["base64_omitted"] = f"file larger than {MAX_MAP_BYTES} bytes"
        results.append(entry)
    return results


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinators: list[AnthbotGenieDataUpdateCoordinator] = hass.data[DOMAIN][
        entry.entry_id
    ]

    devices: list[dict[str, Any]] = []
    for coordinator in coordinators:
        devices.append(
            {
                "model": coordinator.device.model,
                "update_success": coordinator.last_update_success,
                "iot_endpoint": coordinator.client.iot_endpoint,
                "signing_region": coordinator.client.signing_region,
                "reported_state": async_redact_data(
                    coordinator.reported_state, TO_REDACT
                ),
                "map_files": await _async_map_file_diagnostics(coordinator),
            }
        )

    return {"device_count": len(devices), "devices": devices}

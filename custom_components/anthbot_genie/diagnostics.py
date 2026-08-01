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
import io
import json
import tarfile
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


def _describe_archive(raw: bytes) -> dict[str, Any]:
    """Unpack the map archive and describe what is inside.

    The archive is a gzipped tar named ``map_manager_<sn>.tar.gz`` (the app's
    ``genZipFilename``). It holds ``map_<mapId>.bin``, ``bridge_<mapId>.bin``,
    ``area_<areaId>.json`` and ``time_<planId>.json`` (``genMapFilepath``).

    JSON members are included parsed; binary members get their head as hex plus
    the payload base64-encoded, which is what the format analysis needs.
    """
    members: list[dict[str, Any]] = []
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as archive:
            for info in archive.getmembers():
                if not info.isfile():
                    continue
                member: dict[str, Any] = {"name": info.name, "size": info.size}
                handle = archive.extractfile(info)
                content = handle.read() if handle is not None else b""
                if info.name.endswith(".json"):
                    try:
                        member["json"] = json.loads(content.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as err:
                        member["json_error"] = str(err)
                        member["head_hex"] = content[:64].hex(" ")
                else:
                    member["head_hex"] = content[:64].hex(" ")
                    if len(content) <= MAX_MAP_BYTES:
                        member["base64"] = base64.b64encode(content).decode("ascii")
                    else:
                        member["base64_omitted"] = f"larger than {MAX_MAP_BYTES} bytes"
                members.append(member)
    except (tarfile.TarError, EOFError, OSError) as err:
        return {"archive_error": f"{type(err).__name__}: {err}"}
    return {"members": members}


async def _async_map_file_diagnostics(
    hass: HomeAssistant, coordinator: AnthbotGenieDataUpdateCoordinator
) -> dict[str, Any]:
    """Fetch the mower's map archive and describe its contents."""
    serial_number = coordinator.client.serial_number
    filename = f"map_manager_{serial_number}.tar.gz"
    result: dict[str, Any] = {"sub_category": "map"}

    try:
        raw = await coordinator.account_client.async_get_device_file(
            serial_number, filename=filename, sub_category="map"
        )
    except AnthbotGenieApiError as err:
        result["error"] = str(err)
        return result

    result["size"] = len(raw)
    result["sha256"] = hashlib.sha256(raw).hexdigest()
    result["head_hex"] = raw[:64].hex(" ")
    # Decompressing and un-tarring is blocking work.
    result.update(await hass.async_add_executor_job(_describe_archive, raw))
    return result


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
                "map_archive": await _async_map_file_diagnostics(hass, coordinator),
            }
        )

    return {"device_count": len(devices), "devices": devices}

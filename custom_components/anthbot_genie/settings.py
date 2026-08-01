"""Settings access layer for Anthbot mowers.

Mirrors how the Anthbot app reads and writes device settings. Two paths exist,
and which one applies depends on what the mower reports in its property shadow
rather than on its model name (the app itself never branches on model):

* Devices that report a ``device_config`` object (M-series / the app's ``pion``
  UI) read and write every general setting through that object, using the
  ``device_config`` command with a partial update.
* Older devices (Genie) have no ``device_config`` object and use one dedicated
  command per setting (``volume_ctl``, ``ctl_rainer``, ``indoor_switch``, ...).

Mowing parameters live in ``param_set`` on both, written with a partial
``param_set`` update.

See PROTOCOL.md for where each of these comes from in the app.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.exceptions import HomeAssistantError


class AnthbotUnsupportedSettingError(HomeAssistantError):
    """Raised when a mower cannot be asked to change a setting this way.

    A HomeAssistantError (rather than ValueError) so Home Assistant shows the
    user a message instead of an unhandled-exception traceback.
    """


# Keys carried by the device_config property object and the device_config
# command, in the order the app's useDeviceConfig hook reads them.
DEVICE_CONFIG_KEYS: tuple[str, ...] = (
    "log_switch",
    "indoor_switch",
    "rain_switch",
    "rain_continue_time",
    "anti_loss_switch",
    "anti_loss_radius",
    "pobctl_switch",
    "pobctl_level",
    "volume",
    "camera_switch",
)

# Keys carried by the param_set property object and the param_set command.
PARAM_SET_KEYS: tuple[str, ...] = (
    "mow_count",
    "mow_mode",
    "cutter_height",
    "mow_head",
    "rid_switch",
    "enable_adaptive_head",
    "nest_switch",
    "mow_sweep",
    "mow_shred",
    "mow_collect",
)

OBSTACLE_LEVEL_LOW = "low"
OBSTACLE_LEVEL_MEDIUM = "medium"
OBSTACLE_LEVEL_HIGH = "high"

OBSTACLE_LEVEL_OPTIONS: tuple[str, ...] = (
    OBSTACLE_LEVEL_LOW,
    OBSTACLE_LEVEL_MEDIUM,
    OBSTACLE_LEVEL_HIGH,
)

_OBSTACLE_LEVEL_BY_OPTION: dict[str, int] = {
    OBSTACLE_LEVEL_LOW: 0,
    OBSTACLE_LEVEL_MEDIUM: 1,
    OBSTACLE_LEVEL_HIGH: 2,
}
_OBSTACLE_OPTION_BY_LEVEL: dict[int, str] = {
    value: key for key, value in _OBSTACLE_LEVEL_BY_OPTION.items()
}


def obstacle_level_to_option(level: int | None) -> str | None:
    """Map a raw pobctl_level to a select option."""
    if level is None:
        return None
    return _OBSTACLE_OPTION_BY_LEVEL.get(level)


def obstacle_option_to_level(option: str) -> int:
    """Map a select option back to a raw pobctl_level."""
    return _OBSTACLE_LEVEL_BY_OPTION[option]


def coerce_bool(value: object) -> bool:
    """Map Anthbot integer/bool/string toggles to a Python bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "on", "enabled", "enable"}
    return False


def coerce_int(value: object) -> int | None:
    """Return an integer from the shapes Anthbot shadows use."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.lstrip("-").isdigit():
            return int(stripped)
    if isinstance(value, dict):
        return coerce_int(value.get("value"))
    return None


def _sub_object(state: dict[str, Any], name: str) -> dict[str, Any]:
    value = state.get(name)
    return value if isinstance(value, dict) else {}


def device_config(state: dict[str, Any]) -> dict[str, Any]:
    """Return the reported device_config object (empty if unsupported)."""
    return _sub_object(state, "device_config")


def param_set(state: dict[str, Any]) -> dict[str, Any]:
    """Return the reported param_set object."""
    return _sub_object(state, "param_set")


def nest_param_set(state: dict[str, Any]) -> dict[str, Any]:
    """Return the reported nest_param_set object.

    Base-station ("nest") settings are reported inside this object as
    ``mow_count``, ``cutter_height``, ``pobctl_switch`` and ``pobctl_level`` —
    not as top-level ``nest_*`` keys.
    """
    return _sub_object(state, "nest_param_set")


def nest_param_value(state: dict[str, Any], key: str) -> Any:
    """Read a nest_param_set key."""
    return nest_param_set(state).get(key)


def supports_device_config(state: dict[str, Any]) -> bool:
    """Return whether this mower exposes the unified device_config object."""
    return bool(device_config(state))


def device_config_value(state: dict[str, Any], key: str) -> Any:
    """Read a device_config key, falling back to the legacy top-level key.

    Genie-era firmware reports these settings at the top level of the property
    shadow instead of inside a ``device_config`` object.
    """
    config = device_config(state)
    if key in config:
        return config[key]
    return state.get(key)


def has_device_config_value(state: dict[str, Any], key: str) -> bool:
    """Return whether the mower reports a value for a device_config key."""
    return device_config_value(state, key) is not None


def param_set_value(state: dict[str, Any], key: str) -> Any:
    """Read a param_set key, falling back to the legacy top-level key.

    Genie-era firmware reports some of these (notably ``cutter_height``) at the
    top level of the property shadow as well as inside ``param_set``.
    """
    params = param_set(state)
    if key in params:
        return params[key]
    return state.get(key)


@dataclass(frozen=True, slots=True)
class Command:
    """A service-shadow command ready to publish."""

    cmd: str
    data: Any


# Legacy per-setting commands, used when the mower has no device_config object.
# The payload shape differs per command — see PROTOCOL.md.
def _legacy_command(key: str, value: int, state: dict[str, Any]) -> Command:
    if key == "volume":
        return Command("volume_ctl", {"volume": value})
    if key == "anti_loss_radius":
        return Command("anti_loss_radius", {"data": value})
    if key in ("indoor_switch", "anti_loss_switch", "log_switch"):
        # These take a bare scalar, not an object.
        return Command(key, value)
    if key == "camera_switch":
        return Command("camera_switch", {"sub_cmd": value})
    if key == "rain_switch":
        continue_time = coerce_int(device_config_value(state, "rain_continue_time"))
        return Command(
            "ctl_rainer",
            {"switch": value, "continue_time": continue_time or 10800},
        )
    if key == "rain_continue_time":
        switch = 1 if coerce_bool(device_config_value(state, "rain_switch")) else 0
        return Command("ctl_rainer", {"switch": switch, "continue_time": value})
    if key == "pobctl_switch":
        return Command("perception_obstacle_ctl", {"switch": value})
    if key == "pobctl_level":
        return Command("perception_obstacle_ctl", {"level": value})
    raise AnthbotUnsupportedSettingError(
        f"This mower has no command for the {key!r} setting"
    )


def build_device_config_command(
    state: dict[str, Any], **changes: int
) -> Command:
    """Build the command that applies ``changes`` to the general settings.

    On device_config-capable mowers this is a single partial ``device_config``
    update, exactly as the app sends it. Otherwise it falls back to the legacy
    per-setting command.
    """
    if not changes:
        raise AnthbotUnsupportedSettingError("No settings to change")

    for key in changes:
        if key not in DEVICE_CONFIG_KEYS:
            raise AnthbotUnsupportedSettingError(f"Unknown device_config key {key!r}")

    if supports_device_config(state):
        return Command("device_config", dict(changes))

    if len(changes) != 1:
        # The legacy path has no batch command; callers must change one at a time.
        raise AnthbotUnsupportedSettingError(
            "This mower accepts only one setting change per command, got: "
            + ", ".join(sorted(changes))
        )
    key, value = next(iter(changes.items()))
    return _legacy_command(key, value, state)


def build_param_set_command(**changes: int) -> Command:
    """Build a partial ``param_set`` update."""
    if not changes:
        raise AnthbotUnsupportedSettingError("No parameters to change")
    for key in changes:
        if key not in PARAM_SET_KEYS:
            raise AnthbotUnsupportedSettingError(f"Unknown param_set key {key!r}")
    return Command("param_set", dict(changes))


def build_nest_param_set_command(**changes: int) -> Command:
    """Build a partial ``nest_param_set`` update.

    Note the keys are unprefixed here even though the property shadow reports
    them as ``nest_*``.
    """
    allowed = {"cutter_height", "mow_count", "pobctl_switch", "pobctl_level"}
    if not changes:
        raise AnthbotUnsupportedSettingError("No nest parameters to change")
    for key in changes:
        if key not in allowed:
            raise AnthbotUnsupportedSettingError(f"Unknown nest_param_set key {key!r}")
    return Command("nest_param_set", dict(changes))

"""Helpers for Anthbot mowing parameter state.

Thin, correctness-focused layer over :mod:`settings`, kept as its own module
because the sensor platforms read state through these helpers.

Base-station ("nest") values are reported inside the ``nest_param_set`` object
as ``mow_count`` / ``cutter_height`` / ``pobctl_switch`` / ``pobctl_level`` —
*not* as top-level ``nest_*`` keys, which is what earlier versions looked for.
"""

from __future__ import annotations

from typing import Any

from .settings import (
    OBSTACLE_LEVEL_OPTIONS,
    coerce_bool,
    coerce_int,
    device_config_value,
    nest_param_value,
    obstacle_level_to_option,
    obstacle_option_to_level,
    param_set_value,
)

# Re-exported under the older names used by the sensor platforms.
NEST_VISUAL_INSPECTION_OPTIONS = OBSTACLE_LEVEL_OPTIONS
coerce_enabled_value = coerce_bool
raw_int_value = coerce_int
nest_visual_inspection_level_from_option = obstacle_option_to_level


def custom_direction_enabled_from_state(data: dict[str, Any]) -> bool:
    """Return whether a user-chosen mowing direction is in effect.

    The mower reports the inverse: ``enable_adaptive_head`` means it picks the
    direction itself.
    """
    return not coerce_bool(param_set_value(data, "enable_adaptive_head"))


def custom_direction_from_state(data: dict[str, Any]) -> int | None:
    """Return the configured mowing direction in degrees."""
    return coerce_int(param_set_value(data, "mow_head"))


def cutting_height_from_state(data: dict[str, Any]) -> int | None:
    """Return the configured cutting height in mm."""
    return coerce_int(param_set_value(data, "cutter_height"))


def volume_from_state(data: dict[str, Any]) -> int | None:
    """Return the configured voice volume."""
    return coerce_int(device_config_value(data, "volume"))


def rain_continue_time_from_state(data: dict[str, Any]) -> int | None:
    """Return the rain delay in seconds."""
    return coerce_int(device_config_value(data, "rain_continue_time"))


def nest_mowing_enabled_from_state(data: dict[str, Any]) -> bool:
    """Return whether base-station mowing is enabled."""
    return coerce_bool(param_set_value(data, "nest_switch"))


def nest_mow_count_from_state(data: dict[str, Any]) -> int | None:
    """Return the base-station mow count."""
    return coerce_int(nest_param_value(data, "mow_count"))


def nest_cutter_height_from_state(data: dict[str, Any]) -> int | None:
    """Return the base-station cutting height in mm."""
    return coerce_int(nest_param_value(data, "cutter_height"))


def nest_visual_inspection_enabled_from_state(data: dict[str, Any]) -> bool:
    """Return whether base-station obstacle avoidance is enabled."""
    return coerce_bool(nest_param_value(data, "pobctl_switch"))


def nest_visual_inspection_level_from_state(data: dict[str, Any]) -> int | None:
    """Return the raw base-station obstacle avoidance level."""
    return coerce_int(nest_param_value(data, "pobctl_level"))


def nest_visual_inspection_option_from_state(data: dict[str, Any]) -> str | None:
    """Return the labelled base-station obstacle avoidance level."""
    return obstacle_level_to_option(nest_visual_inspection_level_from_state(data))

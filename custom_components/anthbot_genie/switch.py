"""Switch platform for Anthbot settings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import AnthbotGenieDataUpdateCoordinator
from .entity import AnthbotSettingEntity
from .settings import (
    Command,
    build_device_config_command,
    build_nest_param_set_command,
    build_param_set_command,
    coerce_bool,
    device_config_value,
    has_device_config_value,
    nest_param_value,
    param_set_value,
)


@dataclass(frozen=True, kw_only=True)
class AnthbotSwitchDescription(SwitchEntityDescription):
    """Describes an Anthbot switch setting."""

    # Reads the current value out of the reported state.
    value_fn: Callable[[dict[str, Any]], bool]
    # Builds the command that writes the new value.
    command_fn: Callable[[dict[str, Any], bool], Command]
    # Whether the mower reports this setting at all.
    supported_fn: Callable[[dict[str, Any]], bool]


def _device_config_switch(
    key: str,
    *,
    translation_key: str,
    name: str,
    icon: str | None = None,
    entity_category: EntityCategory | None = EntityCategory.CONFIG,
    invert: bool = False,
) -> AnthbotSwitchDescription:
    """Build a switch backed by a device_config key."""

    def value_fn(state: dict[str, Any]) -> bool:
        raw = coerce_bool(device_config_value(state, key))
        return not raw if invert else raw

    def command_fn(state: dict[str, Any], enabled: bool) -> Command:
        target = (not enabled) if invert else enabled
        return build_device_config_command(state, **{key: int(target)})

    return AnthbotSwitchDescription(
        key=translation_key,
        translation_key=translation_key,
        name=name,
        icon=icon,
        entity_category=entity_category,
        value_fn=value_fn,
        command_fn=command_fn,
        supported_fn=lambda state: has_device_config_value(state, key),
    )


SWITCHES: tuple[AnthbotSwitchDescription, ...] = (
    # Key kept as rain_perception_enabled so existing entity IDs survive.
    _device_config_switch(
        "rain_switch",
        translation_key="rain_perception_enabled",
        name="Rain detection",
        icon="mdi:weather-rainy",
    ),
    _device_config_switch(
        "camera_switch",
        translation_key="camera_enabled",
        name="Camera",
        icon="mdi:camera",
    ),
    _device_config_switch(
        "pobctl_switch",
        translation_key="obstacle_avoidance_enabled",
        name="Obstacle avoidance",
        icon="mdi:eye",
    ),
    _device_config_switch(
        "anti_loss_switch",
        translation_key="anti_theft_enabled",
        name="Anti-theft protection",
        icon="mdi:shield-lock",
    ),
    _device_config_switch(
        "indoor_switch",
        translation_key="indoor_mode_enabled",
        name="Indoor mode",
        icon="mdi:home",
    ),
    _device_config_switch(
        "log_switch",
        translation_key="diagnostics_logging_enabled",
        name="Diagnostics logging",
        icon="mdi:file-document-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # enable_adaptive_head = 1 means the mower chooses the mowing direction.
    # Exposed the other way round so "on" means the user's angle is used.
    AnthbotSwitchDescription(
        key="custom_mowing_direction_enabled",
        translation_key="custom_mowing_direction_enabled",
        name="Custom mowing direction",
        icon="mdi:compass",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda state: not coerce_bool(
            param_set_value(state, "enable_adaptive_head")
        ),
        command_fn=lambda state, enabled: build_param_set_command(
            enable_adaptive_head=0 if enabled else 1
        ),
        supported_fn=lambda state: param_set_value(state, "enable_adaptive_head")
        is not None,
    ),
    AnthbotSwitchDescription(
        key="base_station_mowing_enabled",
        translation_key="base_station_mowing_enabled",
        name="Base station mowing",
        icon="mdi:home-import-outline",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda state: coerce_bool(param_set_value(state, "nest_switch")),
        command_fn=lambda state, enabled: build_param_set_command(
            nest_switch=int(enabled)
        ),
        supported_fn=lambda state: param_set_value(state, "nest_switch") is not None,
    ),
    AnthbotSwitchDescription(
        key="base_station_visual_inspection_enabled",
        translation_key="base_station_visual_inspection_enabled",
        name="Base station obstacle avoidance",
        icon="mdi:eye",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda state: coerce_bool(nest_param_value(state, "pobctl_switch")),
        command_fn=lambda state, enabled: build_nest_param_set_command(
            pobctl_switch=int(enabled)
        ),
        supported_fn=lambda state: nest_param_value(state, "pobctl_switch")
        is not None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Anthbot switch entities from config entry."""
    coordinators: list[AnthbotGenieDataUpdateCoordinator] = hass.data[DOMAIN][
        entry.entry_id
    ]
    async_add_entities(
        AnthbotSwitchEntity(coordinator, description)
        for coordinator in coordinators
        for description in SWITCHES
    )


class AnthbotSwitchEntity(AnthbotSettingEntity, SwitchEntity):
    """Anthbot switch entity."""

    entity_description: AnthbotSwitchDescription

    @property
    def available(self) -> bool:
        """Return whether this mower reports the setting."""
        return super().available and self.entity_description.supported_fn(self.state)

    @property
    def is_on(self) -> bool:
        """Return the current setting value."""
        return self.entity_description.value_fn(self.state)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the setting."""
        await self.async_apply(self.entity_description.command_fn(self.state, True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the setting."""
        await self.async_apply(self.entity_description.command_fn(self.state, False))

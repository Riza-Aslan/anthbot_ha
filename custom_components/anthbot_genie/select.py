"""Select platform for Anthbot settings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import AnthbotGenieDataUpdateCoordinator
from .entity import AnthbotSettingEntity
from .settings import (
    OBSTACLE_LEVEL_OPTIONS,
    Command,
    build_device_config_command,
    build_nest_param_set_command,
    coerce_int,
    device_config_value,
    nest_param_value,
    obstacle_level_to_option,
    obstacle_option_to_level,
)


@dataclass(frozen=True, kw_only=True)
class AnthbotSelectDescription(SelectEntityDescription):
    """Describes an Anthbot select setting."""

    value_fn: Callable[[dict[str, Any]], str | None]
    command_fn: Callable[[dict[str, Any], str], Command]
    supported_fn: Callable[[dict[str, Any]], bool]


SELECTS: tuple[AnthbotSelectDescription, ...] = (
    AnthbotSelectDescription(
        key="obstacle_avoidance_level",
        translation_key="obstacle_avoidance_level",
        name="Obstacle avoidance level",
        icon="mdi:eye-settings",
        options=list(OBSTACLE_LEVEL_OPTIONS),
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda state: obstacle_level_to_option(
            coerce_int(device_config_value(state, "pobctl_level"))
        ),
        command_fn=lambda state, option: build_device_config_command(
            state, pobctl_level=obstacle_option_to_level(option)
        ),
        supported_fn=lambda state: device_config_value(state, "pobctl_level")
        is not None,
    ),
    # Key kept as base_station_visual_inspection_level so existing entity IDs
    # survive.
    AnthbotSelectDescription(
        key="base_station_visual_inspection_level",
        translation_key="base_station_visual_inspection_level",
        name="Base station obstacle avoidance level",
        icon="mdi:eye-settings",
        options=list(OBSTACLE_LEVEL_OPTIONS),
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda state: obstacle_level_to_option(
            coerce_int(nest_param_value(state, "pobctl_level"))
        ),
        command_fn=lambda state, option: build_nest_param_set_command(
            pobctl_level=obstacle_option_to_level(option)
        ),
        supported_fn=lambda state: nest_param_value(state, "pobctl_level") is not None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Anthbot select entities from config entry."""
    coordinators: list[AnthbotGenieDataUpdateCoordinator] = hass.data[DOMAIN][
        entry.entry_id
    ]
    async_add_entities(
        AnthbotSelectEntity(coordinator, description)
        for coordinator in coordinators
        for description in SELECTS
    )


class AnthbotSelectEntity(AnthbotSettingEntity, SelectEntity):
    """Anthbot select entity."""

    entity_description: AnthbotSelectDescription

    @property
    def available(self) -> bool:
        """Return whether this mower reports the setting."""
        return super().available and self.entity_description.supported_fn(
            self.mower_state
        )

    @property
    def current_option(self) -> str | None:
        """Return the selected option."""
        return self.entity_description.value_fn(self.mower_state)

    async def async_select_option(self, option: str) -> None:
        """Write the setting to the mower."""
        await self.async_apply(
            self.entity_description.command_fn(self.mower_state, option)
        )

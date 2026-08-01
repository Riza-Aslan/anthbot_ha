"""Number platform for Anthbot settings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfLength, UnitOfTime
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
    coerce_int,
    device_config_value,
    nest_param_value,
    param_set_value,
)


@dataclass(frozen=True, kw_only=True)
class AnthbotNumberDescription(NumberEntityDescription):
    """Describes an Anthbot number setting."""

    value_fn: Callable[[dict[str, Any]], int | None]
    command_fn: Callable[[dict[str, Any], int], Command]
    supported_fn: Callable[[dict[str, Any]], bool]


NUMBERS: tuple[AnthbotNumberDescription, ...] = (
    AnthbotNumberDescription(
        key="mow_height_setting",
        translation_key="mow_height_setting",
        name="Cutting height",
        icon="mdi:arrow-up-down",
        native_min_value=30,
        native_max_value=70,
        native_step=5,
        native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda state: coerce_int(param_set_value(state, "cutter_height")),
        command_fn=lambda state, value: build_param_set_command(cutter_height=value),
        supported_fn=lambda state: param_set_value(state, "cutter_height") is not None,
    ),
    AnthbotNumberDescription(
        key="custom_mowing_direction_setting",
        translation_key="custom_mowing_direction_setting",
        name="Mowing direction",
        icon="mdi:compass",
        native_min_value=0,
        native_max_value=180,
        native_step=1,
        native_unit_of_measurement="°",
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda state: coerce_int(param_set_value(state, "mow_head")),
        # Setting an explicit angle also disables the adaptive head, otherwise
        # the mower keeps choosing the direction itself and the value is moot.
        command_fn=lambda state, value: build_param_set_command(
            mow_head=value, enable_adaptive_head=0
        ),
        supported_fn=lambda state: param_set_value(state, "mow_head") is not None,
    ),
    AnthbotNumberDescription(
        key="voice_volume_setting",
        translation_key="voice_volume_setting",
        name="Volume",
        icon="mdi:volume-high",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda state: coerce_int(device_config_value(state, "volume")),
        command_fn=lambda state, value: build_device_config_command(
            state, volume=value
        ),
        supported_fn=lambda state: device_config_value(state, "volume") is not None,
    ),
    AnthbotNumberDescription(
        key="rain_continue_time_setting",
        translation_key="rain_continue_time_setting",
        name="Rain delay",
        icon="mdi:weather-rainy",
        native_min_value=0,
        native_max_value=12,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.HOURS,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        # Reported in seconds, presented in hours.
        value_fn=lambda state: (
            None
            if (raw := coerce_int(device_config_value(state, "rain_continue_time")))
            is None
            else raw // 3600
        ),
        command_fn=lambda state, value: build_device_config_command(
            state, rain_continue_time=value * 3600
        ),
        supported_fn=lambda state: device_config_value(state, "rain_continue_time")
        is not None,
    ),
    AnthbotNumberDescription(
        key="anti_loss_radius_setting",
        translation_key="anti_loss_radius_setting",
        name="Anti-theft radius",
        icon="mdi:shield-lock",
        native_min_value=1,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=UnitOfLength.METERS,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda state: coerce_int(
            device_config_value(state, "anti_loss_radius")
        ),
        command_fn=lambda state, value: build_device_config_command(
            state, anti_loss_radius=value
        ),
        supported_fn=lambda state: device_config_value(state, "anti_loss_radius")
        is not None,
    ),
    AnthbotNumberDescription(
        key="base_station_mow_count_setting",
        translation_key="base_station_mow_count_setting",
        name="Base station mow count",
        icon="mdi:counter",
        native_min_value=1,
        native_max_value=2,
        native_step=1,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda state: coerce_int(nest_param_value(state, "mow_count")),
        command_fn=lambda state, value: build_nest_param_set_command(mow_count=value),
        supported_fn=lambda state: nest_param_value(state, "mow_count") is not None,
    ),
    AnthbotNumberDescription(
        key="base_station_mow_height_setting",
        translation_key="base_station_mow_height_setting",
        name="Base station cutting height",
        icon="mdi:arrow-up-down",
        native_min_value=30,
        native_max_value=70,
        native_step=5,
        native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda state: coerce_int(nest_param_value(state, "cutter_height")),
        command_fn=lambda state, value: build_nest_param_set_command(
            cutter_height=value
        ),
        supported_fn=lambda state: nest_param_value(state, "cutter_height") is not None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Anthbot number entities from config entry."""
    coordinators: list[AnthbotGenieDataUpdateCoordinator] = hass.data[DOMAIN][
        entry.entry_id
    ]
    async_add_entities(
        AnthbotNumberEntity(coordinator, description)
        for coordinator in coordinators
        for description in NUMBERS
    )


class AnthbotNumberEntity(AnthbotSettingEntity, NumberEntity):
    """Anthbot number entity."""

    entity_description: AnthbotNumberDescription

    @property
    def available(self) -> bool:
        """Return whether this mower reports the setting."""
        return super().available and self.entity_description.supported_fn(
            self.mower_state
        )

    @property
    def native_value(self) -> float | None:
        """Return the current setting value."""
        value = self.entity_description.value_fn(self.mower_state)
        return None if value is None else float(value)

    async def async_set_native_value(self, value: float) -> None:
        """Write the setting to the mower."""
        description = self.entity_description
        step = description.native_step or 1
        minimum = description.native_min_value
        # Snap to the device's own grid so we never send a value it will reject.
        snapped = int(round((value - minimum) / step)) * step + minimum
        snapped = int(min(max(snapped, minimum), description.native_max_value))
        await self.async_apply(description.command_fn(self.mower_state, snapped))

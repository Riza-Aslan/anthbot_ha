"""Select platform for Anthbot Genie settings."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AnthbotGenieDataUpdateCoordinator
from .mow_params import (
    NEST_VISUAL_INSPECTION_OPTIONS,
    build_nest_mow_params_payload,
    nest_visual_inspection_level_from_option,
    nest_visual_inspection_option_from_state,
)


@dataclass(frozen=True, kw_only=True)
class AnthbotSelectDescription(SelectEntityDescription):
    """Describes an Anthbot select setting."""


SELECTS: tuple[AnthbotSelectDescription, ...] = (
    AnthbotSelectDescription(
        key="base_station_visual_inspection_level",
        translation_key="base_station_visual_inspection_level",
        name="Base station visual inspection level",
        options=list(NEST_VISUAL_INSPECTION_OPTIONS),
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


class AnthbotSelectEntity(
    CoordinatorEntity[AnthbotGenieDataUpdateCoordinator], SelectEntity
):
    """Anthbot select entity."""

    entity_description: AnthbotSelectDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AnthbotGenieDataUpdateCoordinator,
        description: AnthbotSelectDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.client.serial_number}_{self.entity_description.key}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.client.serial_number)},
            manufacturer="Anthbot",
            model=coordinator.device.model,
            name=coordinator.device.alias,
        )

    @property
    def current_option(self) -> str | None:
        """Return the selected option."""
        return nest_visual_inspection_option_from_state(self.coordinator.reported_state)

    async def async_select_option(self, option: str) -> None:
        """Update the selected option."""
        await self.coordinator.client.async_publish_service_command(
            cmd="set_mow_params",
            data=build_nest_mow_params_payload(
                self.coordinator.reported_state,
                nest_pobctl_level=nest_visual_inspection_level_from_option(option),
            ),
        )
        await self.coordinator.client.async_request_all_properties()
        await asyncio.sleep(1)
        await self.coordinator.async_request_refresh()

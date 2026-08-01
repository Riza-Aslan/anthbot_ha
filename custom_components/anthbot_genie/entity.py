"""Shared entity base for Anthbot settings platforms."""

from __future__ import annotations

import asyncio

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AnthbotGenieDataUpdateCoordinator
from .settings import Command

# The mower applies a command and then re-reports its state asynchronously.
# Give it a moment before asking for a fresh snapshot, otherwise the refresh
# races the device and the entity snaps back to its old value in the UI.
_SETTLE_SECONDS = 1.5


class AnthbotSettingEntity(CoordinatorEntity[AnthbotGenieDataUpdateCoordinator]):
    """Base for Anthbot entities that write a setting back to the mower."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AnthbotGenieDataUpdateCoordinator,
        description: EntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.client.serial_number}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.client.serial_number)},
            manufacturer="Anthbot",
            model=coordinator.device.model,
            name=coordinator.device.alias,
        )

    @property
    def mower_state(self) -> dict:
        """Return the mower's latest reported shadow state.

        Deliberately *not* called ``state``: that name belongs to
        ``Entity.state`` and overriding it hands Home Assistant the whole
        shadow dict as the entity's state string.
        """
        return self.coordinator.reported_state

    async def async_apply(self, command: Command) -> None:
        """Publish a command and refresh once the mower has applied it."""
        await self.coordinator.client.async_publish_service_command(
            cmd=command.cmd, data=command.data
        )
        await self.coordinator.client.async_request_all_properties()
        await asyncio.sleep(_SETTLE_SECONDS)
        await self.coordinator.async_request_refresh()

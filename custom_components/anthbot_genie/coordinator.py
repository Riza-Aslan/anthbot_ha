"""Data coordinator for Anthbot Genie."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    AnthbotBoundDevice,
    AnthbotCloudApiClient,
    AnthbotGenieApiError,
    AnthbotShadowApiClient,
)
from .const import DOMAIN
from .map import MowerMap, parse_archive


class AnthbotGenieDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to fetch and cache Anthbot shadow state."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        account_client: AnthbotCloudApiClient,
        client: AnthbotShadowApiClient,
        device: AnthbotBoundDevice,
        update_interval: timedelta,
    ) -> None:
        super().__init__(
            hass,
            logger=logging.getLogger(__name__),
            name=DOMAIN,
            update_interval=update_interval,
        )
        self.account_client = account_client
        self.client = client
        self.device = device
        self._map = MowerMap()
        self._map_revision: tuple[Any, Any] | None = None

    @property
    def reported_state(self) -> dict[str, Any]:
        """Return the latest reported state."""
        return self.data if isinstance(self.data, dict) else {}

    @property
    def mower_map(self) -> MowerMap:
        """Return the parsed map, empty if it could not be fetched."""
        return self._map

    @staticmethod
    def _map_revision_of(state: dict[str, Any]) -> tuple[Any, Any]:
        """Return a key that changes whenever the map or its areas change."""
        map_info = state.get("map")
        if isinstance(map_info, dict):
            return (map_info.get("map_id"), map_info.get("area_id"))
        # Genie-era firmware reports these at the top level instead.
        return (state.get("map_time"), state.get("area_time"))

    async def _async_refresh_map(self, state: dict[str, Any]) -> None:
        """Fetch and parse the map archive when the mower says it changed."""
        revision = self._map_revision_of(state)
        if self._map_revision == revision and not self._map.is_empty:
            return

        serial_number = self.client.serial_number
        try:
            raw = await self.account_client.async_get_device_file(
                serial_number,
                filename=f"map_manager_{serial_number}.tar.gz",
                sub_category="map",
            )
        except AnthbotGenieApiError as err:
            # A missing map is normal before the lawn has been mapped; keep
            # whatever we had rather than dropping the zones on a hiccup.
            self.logger.debug("Anthbot map archive unavailable: %s", err)
            return

        parsed = await self.hass.async_add_executor_job(parse_archive, raw)
        if parsed.is_empty and not parsed.area_definition:
            self.logger.debug("Anthbot map archive contained no usable geometry")
            return
        self._map = parsed
        self._map_revision = revision

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the latest state from the cloud endpoint."""
        try:
            await self.client.async_ensure_temporary_credentials(self.account_client)
            property_state = await self.client.async_get_shadow_reported_state()
            try:
                service_state = await self.client.async_get_service_reported_state()
            except AnthbotGenieApiError:
                service_state = {}

            await self._async_refresh_map(property_state)

            merged_state = dict(property_state)
            merged_state["_service_reported"] = service_state
            merged_state["_area_definition"] = self._map.area_definition
            return merged_state
        except AnthbotGenieApiError as err:
            raise UpdateFailed(str(err)) from err

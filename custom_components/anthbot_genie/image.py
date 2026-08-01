"""Image platform showing the mower's map."""

from __future__ import annotations

from homeassistant.components.image import ImageEntity, ImageEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import AnthbotGenieDataUpdateCoordinator
from .entity import AnthbotSettingEntity
from .map import render_svg

MAP_DESCRIPTION = ImageEntityDescription(
    key="map",
    translation_key="map",
    name="Map",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Anthbot map image."""
    coordinators: list[AnthbotGenieDataUpdateCoordinator] = hass.data[DOMAIN][
        entry.entry_id
    ]
    async_add_entities(
        AnthbotMapImage(hass, coordinator) for coordinator in coordinators
    )


class AnthbotMapImage(AnthbotSettingEntity, ImageEntity):
    """The mown area, its zones and the bridges between them.

    Drawn as SVG so it stays sharp at any dashboard size and needs no image
    library.
    """

    _attr_content_type = "image/svg+xml"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: AnthbotGenieDataUpdateCoordinator,
    ) -> None:
        # ImageEntity wants hass for its own URL handling; it also sets
        # _attr_image_last_updated, so initialise it before the shared base.
        ImageEntity.__init__(self, hass)
        AnthbotSettingEntity.__init__(self, coordinator, MAP_DESCRIPTION)
        self._cached: bytes | None = None
        self._cached_for: int | None = None

    @property
    def available(self) -> bool:
        """Return whether a map has been fetched."""
        return super().available and not self.coordinator.mower_map.is_empty

    def _handle_coordinator_update(self) -> None:
        """Redraw only when the mower reports a different map."""
        map_id = self.coordinator.mower_map.map_id
        if map_id != self._cached_for:
            self._cached = None
            self._attr_image_last_updated = dt_util.utcnow()
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        """Return the rendered map."""
        mower_map = self.coordinator.mower_map
        if mower_map.is_empty:
            return None
        if self._cached is None or self._cached_for != mower_map.map_id:
            self._cached = render_svg(mower_map).encode("utf-8")
            self._cached_for = mower_map.map_id
        return self._cached

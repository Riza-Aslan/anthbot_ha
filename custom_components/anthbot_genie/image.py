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
from .map import parse_curpath, parse_position, render_svg

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
        self._cached_key: tuple | None = None

    @property
    def available(self) -> bool:
        """Return whether a map has been fetched."""
        return super().available and not self.coordinator.mower_map.is_empty

    def _render_key(self) -> tuple:
        """Return what the drawing depends on: the map, the mower and its track."""
        state = self.mower_state
        curpath = state.get("curpath")
        return (
            self.coordinator.mower_map.map_id,
            parse_position(state),
            curpath.get("value") if isinstance(curpath, dict) else None,
        )

    def _handle_coordinator_update(self) -> None:
        """Redraw when the map, the position or the track changed."""
        if self._render_key() != self._cached_key:
            self._cached = None
            self._attr_image_last_updated = dt_util.utcnow()
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        """Return the rendered map."""
        mower_map = self.coordinator.mower_map
        if mower_map.is_empty:
            return None
        key = self._render_key()
        if self._cached is None or self._cached_key != key:
            state = self.mower_state
            curpath = state.get("curpath")
            self._cached = render_svg(
                mower_map,
                path=parse_curpath(
                    curpath.get("value") if isinstance(curpath, dict) else None
                ),
                position=parse_position(state),
            ).encode("utf-8")
            self._cached_key = key
        return self._cached

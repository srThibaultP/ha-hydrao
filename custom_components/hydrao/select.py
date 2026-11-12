"""Hydrao selects: colors of the LED thresholds."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import protocol as proto
from .const import THRESHOLD_COLORS, THRESHOLD_COUNT
from .coordinator import HydraoConfigEntry
from .entity import HydraoThresholdEntity

# The request is queued, nothing is sent from here
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HydraoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the selects."""
    async_add_entities(
        HydraoThresholdColor(entry.runtime_data, index, "color")
        for index in range(THRESHOLD_COUNT)
    )


class HydraoThresholdColor(HydraoThresholdEntity, SelectEntity):
    """Color the shower head shows up to the volume of a threshold.

    The choices are the colors of the Hydrao app.
    """

    _attr_translation_key = "threshold_color"
    _attr_options = list(THRESHOLD_COLORS)

    @property
    def current_option(self) -> str:
        """Return the color of the threshold."""
        return proto.threshold_color_name(self._thresholds[self._index]["color"])

    async def async_select_option(self, option: str) -> None:
        """Change the color of the threshold."""
        self._change("color", THRESHOLD_COLORS[option])

"""Hydrao button: end the current shower."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import BUTTON_END_SHOWER
from .coordinator import HydraoConfigEntry, HydraoCoordinator
from .entity import HydraoEntity

# The request is queued, nothing is sent from here
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HydraoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the button."""
    async_add_entities([HydraoEndShowerButton(entry.runtime_data)])


class HydraoEndShowerButton(HydraoEntity, ButtonEntity):
    """The "I have finished my shower" button of the Hydrao app.

    Without it, water running again within two minutes goes on with the same
    shower. The volume of the shower head is reset the next time it is
    reachable, so the button works between showers too.
    """

    _attr_translation_key = BUTTON_END_SHOWER

    def __init__(self, coordinator: HydraoCoordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator, BUTTON_END_SHOWER)

    @property
    def available(self) -> bool:
        """Always available, the request waits for the shower head."""
        return True

    async def async_press(self) -> None:
        """End the shower."""
        self.coordinator.device.end_shower()

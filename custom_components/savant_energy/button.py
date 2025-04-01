"""Button platform for Savant Energy."""

import logging
from typing import Final

from homeassistant.components.button import ButtonEntity, ButtonDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER

_LOGGER = logging.getLogger(__name__)

ALL_LOADS_BUTTON_NAME: Final = "All Loads On"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Savant Energy button."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    # Only add the all loads button if we have data
    if (
        coordinator.data
        and isinstance(coordinator.data, dict)
        and "presentDemands" in coordinator.data
    ):
        async_add_entities(
            [
                SavantAllLoadsButton(hass, coordinator),
                SavantApiCommandLogButton(hass, coordinator),
            ]
        )


class SavantAllLoadsButton(ButtonEntity):
    """Button to turn on all Savant Energy loads."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, coordinator) -> None:
        """Initialize the button."""
        self.hass = hass
        self.coordinator = coordinator
        self._attr_name = ALL_LOADS_BUTTON_NAME
        self._attr_unique_id = f"{DOMAIN}_all_loads_on_button"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "savant_energy_controller")},
            name="Savant Energy",
            manufacturer=MANUFACTURER,
        )

    async def async_press(self) -> None:
        """Handle the button press - send command to turn on all loads."""
        if not self.coordinator.data or "presentDemands" not in self.coordinator.data:
            _LOGGER.warning(
                "No device data available, cannot send all loads on command"
            )
            return

        # Always set ALL channels to 255 regardless of availability
        devices_count = len(self.coordinator.data["presentDemands"])
        channel_values = ["255"] * devices_count

        # Get IP address from config entry
        ip_address = self.coordinator.config_entry.data.get("address")
        if not ip_address:
            _LOGGER.warning("No IP address available, cannot send all loads on command")
            return

        # Format the command string
        formatted_string = f'curl -X POST -d "u=1&d={",".join(channel_values)}" http://{ip_address}:9090/set_dmx'

        # Log the command
        _LOGGER.debug("Sending all loads on command: %s", formatted_string)

        # Note: No longer attempting to update other entities


class SavantApiCommandLogButton(ButtonEntity):
    """Button that logs an example DMX API command."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = ButtonDeviceClass.UPDATE

    def __init__(self, hass: HomeAssistant, coordinator) -> None:
        """Initialize the button."""
        self.hass = hass
        self.coordinator = coordinator
        self._attr_name = "DMX API Command Log"
        self._attr_unique_id = f"{DOMAIN}_dmx_api_command_log"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "savant_energy_controller")},
            name="Savant Energy",
            manufacturer=MANUFACTURER,
        )

    @property
    def icon(self) -> str:
        """Return the button icon."""
        return "mdi:console"

    async def async_press(self) -> None:
        """Handle the button press - log the curl command."""
        # Only log the curl command without executing it
        ip_address = self.coordinator.config_entry.data.get("address")
        if not ip_address:
            _LOGGER.warning(
                "No IP address available, cannot generate curl command example"
            )
            return

        # Generate an example curl command for all loads
        if self.coordinator.data and "presentDemands" in self.coordinator.data:
            devices_count = len(self.coordinator.data["presentDemands"])
            channel_values = ["255"] * devices_count
            curl_command = f'curl -X POST -d "u=1&d={",".join(channel_values)}" http://{ip_address}:9090/set_dmx'
            _LOGGER.info("DMX API command example: %s", curl_command)
        else:
            _LOGGER.warning(
                "No device data available, cannot generate curl command example"
            )

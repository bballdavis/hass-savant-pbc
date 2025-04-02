"""Button platform for Savant Energy."""

import logging
from typing import Final

from homeassistant.components.button import ButtonEntity, ButtonDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, DEFAULT_OLA_PORT
from .utils import async_set_dmx_values, get_dmx_api_stats

_LOGGER = logging.getLogger(__name__)

ALL_LOADS_BUTTON_NAME: Final = "All Loads On"
DEFAULT_CHANNEL_COUNT: Final = 50


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Savant Energy button."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    # Only add buttons if we have data
    snapshot_data = coordinator.data.get("snapshot_data", {})
    if (
        snapshot_data
        and isinstance(snapshot_data, dict)
        and "presentDemands" in snapshot_data
    ):
        async_add_entities(
            [
                SavantAllLoadsButton(hass, coordinator),
                SavantApiCommandLogButton(hass, coordinator),
                SavantApiStatsButton(hass, coordinator),
            ]
        )
    else:
        _LOGGER.warning(
            "No presentDemands data found in coordinator snapshot_data, buttons not added"
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
        # Set all channels to ON (255)
        channel_values = {}
        
        # Try to determine actual count from data
        if self.coordinator.data and "presentDemands" in self.coordinator.data:
            # Find all device channels
            for device in self.coordinator.data["presentDemands"]:
                if "channel" in device:
                    try:
                        channel = int(device["channel"])
                        # Set the channel to "on"
                        channel_values[channel] = "255"
                    except (ValueError, TypeError):
                        continue
            
            # If no valid channels found, create some defaults
            if not channel_values:
                # Default to handling channels 1-50
                for ch in range(1, DEFAULT_CHANNEL_COUNT + 1):
                    channel_values[ch] = "255"
        else:
            # Default to handling channels 1-50
            for ch in range(1, DEFAULT_CHANNEL_COUNT + 1):
                channel_values[ch] = "255"

        # Get IP address from config entry
        ip_address = self.coordinator.config_entry.data.get("address")
        if not ip_address:
            _LOGGER.warning("No IP address available, cannot send all loads on command")
            return

        # Get OLA port from config entry or use default
        ola_port = self.coordinator.config_entry.data.get("ola_port", DEFAULT_OLA_PORT)

        # Use utility function to send command
        success = await async_set_dmx_values(ip_address, channel_values, ola_port)
        
        if success:
            _LOGGER.info("All loads turned on successfully")
        else:
            _LOGGER.warning("Failed to turn on all loads")


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

        # Get OLA port from config entry or use default
        ola_port = self.coordinator.config_entry.data.get("ola_port", DEFAULT_OLA_PORT)

        # Example channel values to turn everything on
        channel_values = {}
        
        # Try to determine actual channels from data
        if self.coordinator.data and "presentDemands" in self.coordinator.data:
            for device in self.coordinator.data["presentDemands"]:
                if "channel" in device:
                    try:
                        channel = int(device["channel"])
                        channel_values[channel] = "255"
                    except (ValueError, TypeError):
                        continue
        
        # If no valid channels found, create some defaults
        if not channel_values:
            # Default to handling channels 1-50
            for ch in range(1, DEFAULT_CHANNEL_COUNT + 1):
                channel_values[ch] = "255"
        
        # Find the maximum channel number
        max_channel = max(channel_values.keys()) if channel_values else DEFAULT_CHANNEL_COUNT
        
        # Create array of values where index position corresponds to channel-1
        value_array = ["0"] * max_channel
        
        # Set values in the array
        for channel, value in channel_values.items():
            if 1 <= channel <= max_channel:
                value_array[channel-1] = value
        
        # Format the data as simple comma-separated values
        data_param = ",".join(value_array)
        
        # Format the curl command properly
        curl_command = f'curl -X POST -d "u=1&d={data_param}" http://{ip_address}:{ola_port}/set_dmx'
        _LOGGER.info("DMX API command example: %s", curl_command)


class SavantApiStatsButton(ButtonEntity):
    """Button to display DMX API statistics."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(self, hass: HomeAssistant, coordinator) -> None:
        """Initialize the button."""
        self.hass = hass
        self.coordinator = coordinator
        self._attr_name = "DMX API Statistics"
        self._attr_unique_id = f"{DOMAIN}_dmx_api_stats"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "savant_energy_controller")},
            name="Savant Energy",
            manufacturer=MANUFACTURER,
        )

    @property
    def icon(self) -> str:
        """Return the button icon."""
        return "mdi:chart-line"

    async def async_press(self) -> None:
        """Handle the button press - display API statistics."""
        stats = get_dmx_api_stats()
        
        last_success = "Never" if stats["last_successful_call"] is None else stats["last_successful_call"].isoformat()
        
        _LOGGER.info(
            "DMX API Stats: Success rate: %.1f%%, Requests: %d, Failures: %d, Last success: %s",
            stats["success_rate"],
            stats["request_count"],
            stats["failure_count"],
            last_success
        )
        
        # Display a notification in Home Assistant
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "DMX API Statistics",
                "message": f"""
Success Rate: {stats['success_rate']:.1f}%
Total Requests: {stats['request_count']}
Failed Requests: {stats['failure_count']}
Last Success: {last_success}
                """,
                "notification_id": f"{DOMAIN}_api_stats",
            },
        )

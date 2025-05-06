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
        dmx_values = {}
        max_dmx_address = 0
        
        # Try to determine actual count from DMX address sensors
        if self.coordinator.data and "presentDemands" in self.coordinator.data:
            # Collect DMX addresses for all devices
            for device in self.coordinator.data["presentDemands"]:
                device_uid = device["uid"]
                device_name = device["name"]
                
                # Try to get DMX address from sensor entity
                dmx_address = None
                
                # Try different entity_id patterns
                entity_id_patterns = [
                    f"sensor.{device_name.lower().replace(' ', '_')}_dmx_address",
                    f"sensor.savantenergy_{device_uid}_dmx_address",
                    f"sensor.savant_energy_{device_uid}_dmx_address"
                ]
                
                for entity_id in entity_id_patterns:
                    state = self.hass.states.get(entity_id)
                    if state and state.state not in ("unknown", "unavailable"):
                        try:
                            dmx_address = int(state.state)
                            # Set this DMX address to "on"
                            dmx_values[dmx_address] = "255"
                            if dmx_address > max_dmx_address:
                                max_dmx_address = dmx_address
                            _LOGGER.debug(f"Found DMX address {dmx_address} for device {device_name}")
                            break
                        except (ValueError, TypeError):
                            continue
            
            # If no valid DMX addresses found, create some defaults
            if not dmx_values:
                _LOGGER.warning("No DMX addresses found, defaulting to addresses 1-%d", DEFAULT_CHANNEL_COUNT)
                for addr in range(1, DEFAULT_CHANNEL_COUNT + 1):
                    dmx_values[addr] = "255"
                max_dmx_address = DEFAULT_CHANNEL_COUNT
        else:
            # Default to handling addresses 1-50
            _LOGGER.warning("No presentDemands data found, defaulting to addresses 1-%d", DEFAULT_CHANNEL_COUNT)
            for addr in range(1, DEFAULT_CHANNEL_COUNT + 1):
                dmx_values[addr] = "255"
            max_dmx_address = DEFAULT_CHANNEL_COUNT

        # Get IP address from config entry
        ip_address = self.coordinator.config_entry.data.get("address")
        if not ip_address:
            _LOGGER.warning("No IP address available, cannot send all loads on command")
            return

        # Get OLA port from config entry or use default
        ola_port = self.coordinator.config_entry.data.get("ola_port", DEFAULT_OLA_PORT)

        _LOGGER.info(f"Turning on all {len(dmx_values)} loads (max DMX address: {max_dmx_address})")
        
        # Use utility function to send command
        success = await async_set_dmx_values(ip_address, dmx_values, ola_port)
        
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
        dmx_values = {}
        max_dmx_address = 0
        
        # Try to determine actual DMX addresses from sensors
        if self.coordinator.data and "presentDemands" in self.coordinator.data:
            # Collect DMX addresses for all devices
            for device in self.coordinator.data["presentDemands"]:
                device_uid = device["uid"]
                device_name = device["name"]
                
                # Try different entity_id patterns for DMX address sensors
                entity_id_patterns = [
                    f"sensor.{device_name.lower().replace(' ', '_')}_dmx_address",
                    f"sensor.savantenergy_{device_uid}_dmx_address",
                    f"sensor.savant_energy_{device_uid}_dmx_address"
                ]
                
                for entity_id in entity_id_patterns:
                    state = self.hass.states.get(entity_id)
                    if state and state.state not in ("unknown", "unavailable"):
                        try:
                            dmx_address = int(state.state)
                            # Set this DMX address to "on"
                            dmx_values[dmx_address] = "255"
                            if dmx_address > max_dmx_address:
                                max_dmx_address = dmx_address
                            break
                        except (ValueError, TypeError):
                            continue
        
        # If no valid DMX addresses found, create some defaults
        if not dmx_values or max_dmx_address == 0:
            _LOGGER.warning("No DMX addresses found, defaulting to addresses 1-%d", DEFAULT_CHANNEL_COUNT)
            for addr in range(1, DEFAULT_CHANNEL_COUNT + 1):
                dmx_values[addr] = "255"
            max_dmx_address = DEFAULT_CHANNEL_COUNT
        
        # Create array of values where index position corresponds to address-1
        value_array = ["0"] * max_dmx_address
        
        # Set values in the array
        for address, value in dmx_values.items():
            if 1 <= address <= max_dmx_address:
                value_array[address-1] = value
        
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

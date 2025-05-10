"""
Button platform for Savant Energy.
Provides diagnostic and control buttons for the integration.
"""

import logging
from typing import Final

from homeassistant.components.button import ButtonEntity, ButtonDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, DEFAULT_OLA_PORT, CONF_DMX_TESTING_MODE
from .utils import async_set_dmx_values, get_dmx_api_stats

_LOGGER = logging.getLogger(__name__)

ALL_LOADS_BUTTON_NAME: Final = "All Loads On"
DEFAULT_CHANNEL_COUNT: Final = 50


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """
    Set up Savant Energy button entities.
    Adds diagnostic and control buttons if presentDemands data is available.
    """
    coordinator = hass.data[DOMAIN][entry.entry_id]
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
    """
    Button to turn on all Savant Energy loads (relays).
    """
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, coordinator) -> None:
        """
        Initialize the All Loads On button.
        """
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
        """
        Handle the button press - send command to turn on all loads.
        """
        dmx_values = {}
        max_dmx_address = 0

        # Get all sensor entities that might be DMX address sensors
        all_entity_ids = self.hass.states.async_entity_ids("sensor")
        dmx_address_sensors = [entity_id for entity_id in all_entity_ids 
                              if entity_id.endswith("_dmx_address")]
        
        _LOGGER.debug(f"Found {len(dmx_address_sensors)} potential DMX address sensors")
        
        # Extract DMX addresses from all matching sensors
        for entity_id in dmx_address_sensors:
            state = self.hass.states.get(entity_id)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    dmx_address = int(state.state)
                    # Set this DMX address to "on"
                    dmx_values[dmx_address] = "255"
                    if dmx_address > max_dmx_address:
                        max_dmx_address = dmx_address
                    _LOGGER.debug(f"Found DMX address {dmx_address} from sensor {entity_id}")
                except (ValueError, TypeError):
                    _LOGGER.debug(f"Invalid DMX address value in sensor {entity_id}: {state.state}")
        
        # Only use default if we didn't find any valid DMX addresses
        if max_dmx_address == 0:
            _LOGGER.warning("No valid DMX addresses found from sensors, defaulting to addresses 1-%d", DEFAULT_CHANNEL_COUNT)
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
        
        # Get DMX testing mode from config
        dmx_testing_mode = self.coordinator.config_entry.options.get(
            CONF_DMX_TESTING_MODE,
            self.coordinator.config_entry.data.get(CONF_DMX_TESTING_MODE, False)
        )

        _LOGGER.info(f"Turning on all {len(dmx_values)} loads (max DMX address: {max_dmx_address})")
        
        # Use utility function to send command - this will both log and send the command
        success = await async_set_dmx_values(ip_address, dmx_values, ola_port, dmx_testing_mode)
        
        if success:
            _LOGGER.info("All loads turned on successfully")
        else:
            _LOGGER.warning("Failed to turn on all loads")


class SavantApiCommandLogButton(ButtonEntity):
    """
    Button that logs an example DMX API command.
    """
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = ButtonDeviceClass.UPDATE

    def __init__(self, hass: HomeAssistant, coordinator) -> None:
        """
        Initialize the DMX API Command Log button.
        """
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
        """
        Return the button icon.
        """
        return "mdi:console"

    async def async_press(self) -> None:
        """
        Handle the button press - log the curl command.
        """
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
        
        # Get all sensor entities that might be DMX address sensors
        all_entity_ids = self.hass.states.async_entity_ids("sensor")
        dmx_address_sensors = [entity_id for entity_id in all_entity_ids 
                              if entity_id.endswith("_dmx_address")]
        
        _LOGGER.debug(f"Found {len(dmx_address_sensors)} potential DMX address sensors")
        
        # Extract DMX addresses from all matching sensors
        for entity_id in dmx_address_sensors:
            state = self.hass.states.get(entity_id)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    dmx_address = int(state.state)
                    # Set this DMX address to "on"
                    dmx_values[dmx_address] = "255"
                    if dmx_address > max_dmx_address:
                        max_dmx_address = dmx_address
                    _LOGGER.debug(f"Found DMX address {dmx_address} from sensor {entity_id}")
                except (ValueError, TypeError):
                    _LOGGER.debug(f"Invalid DMX address value in sensor {entity_id}: {state.state}")
        
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
    """
    Button to display DMX API statistics.
    """
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(self, hass: HomeAssistant, coordinator) -> None:
        """
        Initialize the DMX API Statistics button.
        """
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
        """
        Return the button icon.
        """
        return "mdi:chart-line"

    async def async_press(self) -> None:
        """
        Handle the button press - display API statistics.
        """
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

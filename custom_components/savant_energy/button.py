"""
Button platform for Savant Energy.
Provides diagnostic and control buttons for the integration.
"""

import logging
from typing import Final
from datetime import timedelta

from homeassistant.components.button import ButtonEntity, ButtonDeviceClass  # type: ignore
from homeassistant.config_entries import ConfigEntry  # type: ignore
from homeassistant.const import EntityCategory  # type: ignore
from homeassistant.core import HomeAssistant  # type: ignore
from homeassistant.helpers.entity import DeviceInfo  # type: ignore
from homeassistant.helpers.entity_platform import AddEntitiesCallback  # type: ignore
from homeassistant.helpers.event import async_track_time_interval  # type: ignore

from .const import DOMAIN, MANUFACTURER, DEFAULT_OLA_PORT, CONF_DMX_TESTING_MODE
from .utils import async_set_dmx_values, get_dmx_api_stats
from .scene import SavantSceneStorage, SavantSceneManager

_LOGGER = logging.getLogger(__name__)

ALL_LOADS_BUTTON_NAME: Final = "All Breakers On Scene"
DEFAULT_CHANNEL_COUNT: Final = 50


class SavantSceneButton(ButtonEntity):
    """
    Button entity to execute a Savant scene.
    When pressed, always uses the latest scene data from storage and ensures all DMX addresses are included.
    """
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass, scene_manager, scene_id, scene_name):
        self._hass = hass
        self._scene_manager = scene_manager
        self._scene_id = scene_id
        self._attr_name = f"Savant {scene_name} Scene"
        self._attr_unique_id = f"savant_scene_button_{scene_id}"
        self._attr_device_info = DeviceInfo(
            identifiers = {(DOMAIN, "scenes")},
            name = "Savant Scenes",
            manufacturer = MANUFACTURER,
        )

    @property
    def available(self):
        return self._scene_id in self._scene_manager.storage.scenes

    async def async_press(self):
        """
        When pressed, dynamically loads the latest scene data and sends the DMX command.
        """
        scene = self._scene_manager.storage.scenes.get(self._scene_id)
        if not scene:
            _LOGGER.warning(f"Scene {self._scene_id} not found in storage when button pressed.")
            return
        relay_states = scene.get("relay_states", {})
        all_entity_ids = self._hass.states.async_entity_ids("sensor")
        dmx_address_sensors = [eid for eid in all_entity_ids if eid.endswith("_dmx_address")]
        dmx_values = {}
        for entity_id in dmx_address_sensors:
            state = self._hass.states.get(entity_id)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    dmx_address = int(state.state)
                    breaker_entity_id = entity_id.replace("_dmx_address", "")
                    value = 255 if relay_states.get(breaker_entity_id, True) else 0
                    dmx_values[dmx_address] = str(value)
                except (ValueError, TypeError):
                    _LOGGER.debug(f"Invalid DMX address value in sensor {entity_id}: {state.state}")
        if not dmx_values:
            _LOGGER.warning("No DMX addresses found for scene button press. No DMX command sent.")
            return
        ip_address = self._scene_manager.coordinator.config_entry.data.get("address")
        ola_port = self._scene_manager.coordinator.config_entry.data.get("ola_port", DEFAULT_OLA_PORT)
        dmx_testing_mode = self._scene_manager.coordinator.config_entry.options.get(
            CONF_DMX_TESTING_MODE,
            self._scene_manager.coordinator.config_entry.data.get(CONF_DMX_TESTING_MODE, False)
        )
        _LOGGER.info(f"Executing Savant Scene '{scene['name']}' with {len(dmx_values)} DMX addresses.")
        success = await async_set_dmx_values(ip_address, dmx_values, ola_port, dmx_testing_mode)
        if success:
            _LOGGER.info(f"Savant Scene '{scene['name']}' executed successfully.")
        else:
            _LOGGER.warning(f"Failed to execute Savant Scene '{scene['name']}'.")


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """
    Set up Savant Energy button entities.
    Adds diagnostic and control buttons if presentDemands data is available.
    """
    # Add Savant Scene Buttons for each scene in storage, and keep them in sync
    storage = SavantSceneStorage(hass)
    await storage.async_load()
    coordinator = hass.data[DOMAIN][entry.entry_id]
    scene_manager = SavantSceneManager(hass, coordinator, storage)
    button_manager = SavantSceneButtonManager(hass, scene_manager, async_add_entities)
    hass.data.setdefault(f"{DOMAIN}_scene_button_managers", {})[entry.entry_id] = button_manager
    await button_manager.async_setup()

    # Always trigger a refresh to ensure polling starts
    await coordinator.async_request_refresh()
    if coordinator.data is not None:
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


class SavantSceneButtonManager:
    """
    Manages dynamic creation and removal of SavantSceneButton entities as scenes are added/removed.
    Periodically refreshes to keep button entities in sync with storage.
    Ensures on load-in that all scenes have a button, even if the button didn't exist yet.
    """
    def __init__(self, hass, scene_manager, async_add_entities):
        self.hass = hass
        self.scene_manager = scene_manager
        self.async_add_entities = async_add_entities
        self.buttons = {}  # scene_id -> SavantSceneButton
        self._unsub_refresh = None
        self._last_scene_ids = set()

    async def async_setup(self):
        # On initial setup, ensure all scenes have a button entity
        await self._refresh_buttons()
        self._unsub_refresh = async_track_time_interval(self.hass, self._periodic_refresh, timedelta(seconds=10))

    async def _periodic_refresh(self, *_):
        await self._refresh_buttons()

    async def _refresh_buttons(self):
        await self.scene_manager.storage.async_load()
        scene_ids = set(self.scene_manager.storage.scenes.keys())
        # Add new buttons for any scenes that don't have one yet
        new_ids = scene_ids - self._last_scene_ids
        for scene_id in new_ids:
            scene_data = self.scene_manager.storage.scenes[scene_id]
            if scene_id not in self.buttons:
                button = SavantSceneButton(self.hass, self.scene_manager, scene_id, scene_data["name"])
                self.async_add_entities([button])
                self.buttons[scene_id] = button
                _LOGGER.info(f"Created Savant Scene Button for scene: {scene_data['name']} ({scene_id})")
        # Remove deleted buttons
        removed_ids = self._last_scene_ids - scene_ids
        for scene_id in removed_ids:
            button = self.buttons.pop(scene_id, None)
            if button:
                await button.async_remove()
                _LOGGER.info(f"Removed Savant Scene Button for deleted scene: {scene_id}")
        self._last_scene_ids = scene_ids

    async def async_unload(self):
        if self._unsub_refresh:
            self._unsub_refresh()
            self._unsub_refresh = None
        for button in self.buttons.values():
            await button.async_remove()
        self.buttons.clear()


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

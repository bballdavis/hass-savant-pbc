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

    def __init__(self, hass, scene_manager, scene_id, stored_scene_name):
        self._hass = hass
        self._scene_manager = scene_manager
        self._scene_id = scene_id # This is the normalized ID, e.g., savant_my_scene_scene
        
        # stored_scene_name is the base name, e.g., "My Scene"
        # We need to construct the full display name for the button/device
        _base_label, self._full_display_name, _final_id = scene_manager.storage._get_normalized_scene_parts(stored_scene_name)
        
        self._attr_name = None # Results in entity friendly name being the device name
        self._attr_unique_id = f"button.{scene_id}" 
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, scene_id)}, 
            name=self._full_display_name, # Device name is "Savant My Scene Scene"
            manufacturer=MANUFACTURER,
            model="Savant Scene Control Button"
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
        await self.scene_manager.storage.async_load() # Ensure latest scenes are loaded
        current_scene_data = self.scene_manager.storage.scenes
        current_scene_ids = set(current_scene_data.keys())

        new_ids = current_scene_ids - self._last_scene_ids
        buttons_to_add = []
        for scene_id in new_ids:
            if scene_id in self.buttons:
                _LOGGER.warning(f"Scene button for {scene_id} already exists in manager, skipping add.")
                continue
            scene_info = current_scene_data.get(scene_id)
            # scene_info["name"] is now the base name, e.g., "My Scene"
            if scene_info and "name" in scene_info:
                stored_base_name = scene_info["name"]
                # The SavantSceneButton constructor will use _get_normalized_scene_parts
                # to generate the full display name for the button entity itself.
                button = SavantSceneButton(self.hass, self.scene_manager, scene_id, stored_base_name)
                self.buttons[scene_id] = button
                buttons_to_add.append(button)
                _LOGGER.info(f"Creating button for new scene (Stored Name: {stored_base_name}, ID: {scene_id})")
            else:
                _LOGGER.warning(f"Scene ID {scene_id} found but data or name is missing, cannot create button.")
        
        if buttons_to_add:
            self.async_add_entities(buttons_to_add)

        # Remove deleted buttons
        removed_ids = self._last_scene_ids - current_scene_ids
        buttons_to_remove_entities = []
        for scene_id in removed_ids:
            if scene_id in self.buttons:
                button_entity = self.buttons.pop(scene_id)
                # HA should handle removal from the entity registry if the entity signals it's unavailable
                # or if we explicitly remove it. For buttons, it might be cleaner to remove them.
                # This requires the button entity to be registered with HA first.
                # We will rely on HA to remove entities that are no longer added by the platform.
                # However, we need to tell HA to remove them if they were previously added.
                # This is typically handled by returning them from an async_remove_entity method if the platform supports it,
                # or by ensuring they are not added again and HA cleans them up.
                # For now, just removing from our internal tracking. HA should remove if not re-added.
                _LOGGER.info(f"Removing button for deleted scene ID: {scene_id}")
                # To explicitly remove, we might need to call entity_registry.async_remove_entity
                # For now, let's assume HA handles it if we don't add them again.
                # If explicit removal is needed, this part needs more work with entity_registry.
                # Let's try to remove them from hass.entities
                try:
                    await button_entity.async_remove()
                    _LOGGER.debug(f"Successfully called async_remove for button {scene_id}")
                except Exception as e:
                    _LOGGER.error(f"Error calling async_remove for button {scene_id}: {e}")

            else:
                _LOGGER.warning(f"Attempted to remove button for non-tracked scene ID: {scene_id}")

        self._last_scene_ids = current_scene_ids

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

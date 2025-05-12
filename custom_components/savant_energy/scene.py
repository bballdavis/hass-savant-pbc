"""
Scene platform for Savant Energy.
Provides scene entities that can control multiple relays with a single command.
"""

import logging
import json
from typing import Any, Dict, Final, List, Optional

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import voluptuous as vol

from .const import (
    DOMAIN, 
    MANUFACTURER, 
    DEFAULT_OLA_PORT, 
    CONF_DMX_TESTING_MODE
)
from .utils import async_set_dmx_values

_LOGGER = logging.getLogger(__name__)

# Storage constants
STORAGE_KEY = f"{DOMAIN}_scenes"
STORAGE_VERSION = 1

# Scene device constants
SCENE_DEVICE_ID: Final = f"{DOMAIN}_scenes"
SCENE_DEVICE_NAME: Final = "Savant Scenes"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """
    Set up Savant Energy scene entities.
    """
    coordinator = hass.data[DOMAIN][entry.entry_id]
    # Always trigger a refresh to ensure polling starts
    await coordinator.async_request_refresh()
    if coordinator.data is not None:
        # Initialize storage
        storage = SavantSceneStorage(hass)
        await storage.async_load()
        # Create the scene manager
        scene_manager = SavantSceneManager(hass, coordinator, storage)
        # Register scene manager in hass.data for access from services
        hass.data.setdefault(f"{DOMAIN}_scene_managers", {})[entry.entry_id] = scene_manager
        # Create entities for existing scenes
        entities = []
        for scene_id, scene_data in storage.scenes.items():
            entities.append(
                SavantSceneButton(
                    hass, 
                    coordinator, 
                    scene_data["name"], 
                    scene_id, 
                    scene_data["relay_states"],
                    scene_manager
                )
            )
        # Add a button for creating a new scene
        entities.append(SavantSceneCreatorButton(hass, coordinator, scene_manager))
        if entities:
            async_add_entities(entities)
        # Register Home Assistant services for scene management
        async def handle_create_scene(call):
            """Handle service call to create a new scene."""
            name = call.data["name"]
            relay_states = call.data["relay_states"]
            entry_id = entry.entry_id
            scene_manager = hass.data[f"{DOMAIN}_scene_managers"][entry_id]
            await scene_manager.async_create_scene(name, relay_states)
            await hass.config_entries.async_reload(entry_id)

        async def handle_update_scene(call):
            """Handle service call to update an existing scene."""
            scene_id = call.data["scene_id"]
            name = call.data.get("name")
            relay_states = call.data.get("relay_states")
            entry_id = entry.entry_id
            scene_manager = hass.data[f"{DOMAIN}_scene_managers"][entry_id]
            await scene_manager.async_update_scene(scene_id, name, relay_states)
            await hass.config_entries.async_reload(entry_id)

        async def handle_delete_scene(call):
            """Handle service call to delete a scene."""
            scene_id = call.data["scene_id"]
            entry_id = entry.entry_id
            scene_manager = hass.data[f"{DOMAIN}_scene_managers"][entry_id]
            await scene_manager.async_delete_scene(scene_id)
            await hass.config_entries.async_reload(entry_id)

        hass.services.async_register(
            DOMAIN,
            "create_scene",
            handle_create_scene,
            schema=vol.Schema({
                vol.Required("name"): str,
                vol.Required("relay_states"): dict,
            })
        )
        hass.services.async_register(
            DOMAIN,
            "update_scene",
            handle_update_scene,
            schema=vol.Schema({
                vol.Required("scene_id"): str,
                vol.Optional("name"): str,
                vol.Optional("relay_states"): dict,
            })
        )
        hass.services.async_register(
            DOMAIN,
            "delete_scene",
            handle_delete_scene,
            schema=vol.Schema({
                vol.Required("scene_id"): str,
            })
        )


class SavantSceneStorage:
    """Class to handle scene storage."""
    
    def __init__(self, hass: HomeAssistant):
        """Initialize the storage."""
        self.hass = hass
        self.store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.scenes: Dict[str, Dict] = {}
    
    async def async_load(self) -> None:
        """Load scenes from storage."""
        data = await self.store.async_load()
        if data:
            self.scenes = data.get("scenes", {})
        else:
            self.scenes = {}
    
    async def async_save(self) -> None:
        """Save scenes to storage."""
        await self.store.async_save({"scenes": self.scenes})
    
    async def async_create_scene(self, name: str, relay_states: Dict[str, bool]) -> str:
        """Create a new scene."""
        scene_id = f"scene_{len(self.scenes) + 1}"
        self.scenes[scene_id] = {"name": name, "relay_states": relay_states}
        await self.async_save()
        return scene_id
    
    async def async_update_scene(self, scene_id: str, name: str = None, relay_states: Dict[str, bool] = None) -> None:
        """Update an existing scene."""
        if scene_id not in self.scenes:
            _LOGGER.error(f"Cannot update non-existent scene {scene_id}")
            return
            
        scene = self.scenes[scene_id]
        if name is not None:
            scene["name"] = name
        if relay_states is not None:
            scene["relay_states"] = relay_states
            
        await self.async_save()
    
    async def async_delete_scene(self, scene_id: str) -> None:
        """Delete a scene."""
        if scene_id in self.scenes:
            self.scenes.pop(scene_id)
            await self.async_save()


class SavantSceneManager:
    """Manager for Savant Energy scenes."""
    
    def __init__(self, hass: HomeAssistant, coordinator, storage: SavantSceneStorage):
        """Initialize the scene manager."""
        self.hass = hass
        self.coordinator = coordinator
        self.storage = storage
        
    async def async_create_scene(self, name: str, relay_states: Dict[str, bool]) -> str:
        """Create a new scene and return its ID."""
        return await self.storage.async_create_scene(name, relay_states)
    
    async def async_update_scene(self, scene_id: str, name: str = None, relay_states: Dict[str, bool] = None) -> None:
        """Update an existing scene."""
        await self.storage.async_update_scene(scene_id, name, relay_states)
    
    async def async_delete_scene(self, scene_id: str) -> None:
        """Delete a scene."""
        await self.storage.async_delete_scene(scene_id)
    
    async def async_execute_scene(self, scene_id: str) -> bool:
        """Execute a scene by sending DMX commands for all included relays."""
        if scene_id not in self.storage.scenes:
            _LOGGER.error(f"Cannot execute non-existent scene {scene_id}")
            return False
            
        scene = self.storage.scenes[scene_id]
        relay_states = scene["relay_states"]
        
        # Get DMX addresses and values
        dmx_values = {}
        
        # First get all DMX address sensors
        all_entity_ids = self.hass.states.async_entity_ids("sensor")
        dmx_address_sensors = [
            entity_id for entity_id in all_entity_ids 
            if entity_id.endswith("_dmx_address")
        ]
        
        # For each DMX address sensor, check if it's in our scene and set the value
        for entity_id in dmx_address_sensors:
            state = self.hass.states.get(entity_id)
            if not state or state.state in ("unknown", "unavailable"):
                continue
                
            # Extract device name from the entity_id
            device_name = state.attributes.get("friendly_name", "").replace(" DMX Address", "")
            if not device_name:
                device_parts = entity_id.split(".", 1)[1].replace("_dmx_address", "").split("_")
                device_name = " ".join([part.capitalize() for part in device_parts])
            
            # Check if this device is in our scene
            if device_name in relay_states:
                try:
                    dmx_address = int(state.state)
                    # Set DMX value based on the desired state
                    dmx_values[dmx_address] = "255" if relay_states[device_name] else "0"
                    _LOGGER.debug(f"Setting DMX address {dmx_address} for {device_name} to {dmx_values[dmx_address]}")
                except (ValueError, TypeError):
                    _LOGGER.warning(f"Invalid DMX address value in sensor {entity_id}: {state.state}")
        
        if not dmx_values:
            _LOGGER.warning(f"No valid DMX addresses found for scene {scene_id}")
            return False
            
        # Get IP address and OLA port from config entry
        ip_address = self.coordinator.config_entry.data.get("address")
        ola_port = self.coordinator.config_entry.data.get("ola_port", DEFAULT_OLA_PORT)
        
        # Get DMX testing mode from config
        dmx_testing_mode = self.coordinator.config_entry.options.get(
            CONF_DMX_TESTING_MODE,
            self.coordinator.config_entry.data.get(CONF_DMX_TESTING_MODE, False)
        )
        
        _LOGGER.info(f"Executing scene {scene['name']} with {len(dmx_values)} relays")
        
        # Send the DMX command
        success = await async_set_dmx_values(ip_address, dmx_values, ola_port, dmx_testing_mode)
        
        if success:
            _LOGGER.info(f"Scene {scene['name']} executed successfully")
        else:
            _LOGGER.error(f"Failed to execute scene {scene['name']}")
            
        return success
        
    def get_all_available_devices(self) -> Dict[str, bool]:
        """Get a list of all available relay devices and their current states."""
        devices = {}
        
        # Get all binary sensor entities that are relay status sensors
        all_entity_ids = self.hass.states.async_entity_ids("binary_sensor")
        relay_status_sensors = [
            entity_id for entity_id in all_entity_ids 
            if "relay_status" in entity_id
        ]
        
        for entity_id in relay_status_sensors:
            state = self.hass.states.get(entity_id)
            if not state or state.state in ("unknown", "unavailable"):
                continue
                
            device_name = state.attributes.get("friendly_name", "").replace(" Relay Status", "")
            if not device_name:
                continue
                
            devices[device_name] = state.state.lower() == "on"
            
        return devices


class SavantSceneButton(CoordinatorEntity, ButtonEntity):
    """Button entity to execute a saved scene."""
    
    def __init__(self, hass: HomeAssistant, coordinator, name: str, scene_id: str, 
                 relay_states: Dict[str, bool], scene_manager: SavantSceneManager):
        """Initialize the scene button."""
        super().__init__(coordinator)
        self._hass = hass
        self._scene_id = scene_id
        self._relay_states = relay_states
        self._scene_manager = scene_manager
        
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_scene_{scene_id}"
        self._attr_entity_category = None  # Normal entity, not diagnostic or config
        
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, SCENE_DEVICE_ID)},
            name=SCENE_DEVICE_NAME,
            manufacturer=MANUFACTURER,
            model="Scene Controller",
        )

    async def async_press(self) -> None:
        """Handle button press - execute the scene."""
        await self._scene_manager.async_execute_scene(self._scene_id)


class SavantSceneCreatorButton(CoordinatorEntity, ButtonEntity):
    """Button entity to create a new scene from current relay states."""
    
    _attr_entity_category = EntityCategory.CONFIG
    
    def __init__(self, hass: HomeAssistant, coordinator, scene_manager: SavantSceneManager):
        """Initialize the scene creator button."""
        super().__init__(coordinator)
        self._hass = hass
        self._scene_manager = scene_manager
        
        self._attr_name = "Create New Scene"
        self._attr_unique_id = f"{DOMAIN}_scene_creator"
        
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, SCENE_DEVICE_ID)},
            name=SCENE_DEVICE_NAME,
            manufacturer=MANUFACTURER,
            model="Scene Controller",
        )

    async def async_press(self) -> None:
        """Handle button press - create a new scene with current relay states."""
        # Get current state of all relays
        current_states = self._scene_manager.get_all_available_devices()
        
        if not current_states:
            _LOGGER.warning("No relay devices found to create a scene")
            return
            
        # Create a new scene with default name
        scene_id = await self._scene_manager.async_create_scene(
            f"Scene {len(self._scene_manager.storage.scenes)}", 
            current_states
        )
        
        _LOGGER.info(f"Created new scene {scene_id} with {len(current_states)} relays")
        
        # Reload the integration to create the new scene button entity
        await self._hass.config_entries.async_reload(self.coordinator.config_entry.entry_id)

"""
Scene platform for Savant Energy.
Provides scene entities that can control multiple relays with a single command.

All Savant scenes are now managed with the 'savant_' prefix in their ID. Legacy/duplicate scenes are cleared on startup.
Scene creation and storage enforces unique names (case-insensitive) and a single source of truth.
Manual creation of Home Assistant scenes with similar names is discouraged and will be removed on integration startup.
Only use the integration's services or UI to manage Savant scenes.
"""

import logging
import json
import asyncio
import voluptuous as vol # type: ignore
from typing import Any, Dict, Final, List, Optional

from homeassistant.config_entries import ConfigEntry  # type: ignore
from homeassistant.core import HomeAssistant, callback  # type: ignore
from homeassistant.helpers.entity_platform import AddEntitiesCallback  # type: ignore
from homeassistant.helpers.storage import Store  # type: ignore
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry  # type: ignore
from homeassistant.components.http import HomeAssistantView  # type: ignore
from .api import register_scene_services  # type: ignore
from homeassistant.exceptions import HomeAssistantError  # type: ignore

from .const import (
    DOMAIN, 
    MANUFACTURER, 
    DEFAULT_OLA_PORT, 
    CONF_DMX_TESTING_MODE
)
from .utils import async_set_dmx_values, slugify

_LOGGER = logging.getLogger(__name__)

# Storage constants
STORAGE_KEY = f"{DOMAIN}_scenes"
STORAGE_VERSION = 1

# Scene device constants
SCENE_DEVICE_ID: Final = f"{DOMAIN}_scenes"
SCENE_DEVICE_NAME: Final = "Savant Scenes"


class SavantScenesRestView(HomeAssistantView):
    url = "/api/savant_energy/scenes"
    name = "api:savant_energy:scenes"
    requires_auth = True

    async def get(self, request):
        try:
            hass = request.app["hass"]
            storage = SavantSceneStorage(hass)
            await storage.async_load()
            scenes_meta = [
                {"scene_id": scene_id, "name": scene_data["name"]}
                for scene_id, scene_data in storage.scenes.items()
            ]
            response = {"scenes": scenes_meta}
            _LOGGER.debug(f"[REST] Returning scenes response: {json.dumps(response)}")
            return self.json(response)
        except Exception as e:
            _LOGGER.error(f"[REST] Exception in SavantScenesRestView: {e}", exc_info=True)
            return self.json({"status": "error", "message": str(e)}, status_code=500)

    async def post(self, request):
        """Create a new Savant scene via REST."""
        data = None # Initialize data to handle potential unbound error
        try:
            data = await request.json()
            hass = request.app["hass"]
            
            # Call the service. handle_create_scene always returns a dictionary.
            service_response = await hass.services.async_call(
                DOMAIN, "create_scene", data, blocking=True
            )

            # The service_response is the dictionary returned by handle_create_scene
            if service_response:
                if service_response.get("status") == "error":
                    _LOGGER.warning(f"[REST] 'create_scene' service reported error: {service_response.get('message')}")
                    return self.json({
                        "status": "error", 
                        "message": service_response.get("message", "Error during scene creation."),
                        "error": service_response.get("error", "service_handler_error") 
                    }, status_code=400) # Bad Request (e.g., for scene_exists)
                elif service_response.get("status") == "ok":
                    scene_id = service_response.get("scene_id")
                    # Fallback for scene_id generation if not in response, though it should be.
                    if not scene_id and data and "name" in data:
                         _LOGGER.error(f"[REST] 'create_scene' service reported 'ok' but no scene_id. Data: {data}")
                         scene_id = f"savant_{slugify(data['name'])}"
                    elif not scene_id:
                         _LOGGER.error(f"[REST] 'create_scene' service reported 'ok' but no scene_id and no name in data. Data: {data}")
                         # Cannot generate a meaningful scene_id if name is also missing
                         return self.json({"status": "error", "message": "Scene created but scene_id missing and could not be generated.", "error": "internal_error"}, status_code=500)
                    return self.json({"status": "ok", "scene_id": scene_id})
            
            # Fallback for unexpected/empty service_response (should not happen with current handle_create_scene)
            _LOGGER.error(f"[REST] Unexpected or empty response from 'create_scene' service. Data: {data}, Response: {service_response}")
            return self.json({"status": "error", "message": "Unexpected response from scene creation service.", "error": "unexpected_service_response"}, status_code=500)

        except vol.Invalid as vol_err: # Schema validation error for the service call
            _LOGGER.warning(f"[REST] Invalid data for 'create_scene' service call. Data: {data}. Error: {vol_err}", exc_info=True)
            return self.json({"status": "error", "message": f"Invalid data: {vol_err.error_message}", "error": "validation_error", "path": vol_err.path}, status_code=400)
        except HomeAssistantError as ha_err: 
            # Catches HomeAssistantError if the service call itself fails (e.g., service not found)
            # or if the handler re-raised it (which handle_create_scene doesn't for "scene_exists").
            _LOGGER.warning(f"[REST] HomeAssistantError during 'create_scene' service invocation. Data: {data}. Error: {ha_err}", exc_info=True)
            return self.json({"status": "error", "message": str(ha_err), "error": "service_invocation_error"}, status_code=400) 
        except json.JSONDecodeError as json_err: # Specifically catch errors from await request.json()
            _LOGGER.warning(f"[REST] Invalid JSON received: {json_err}", exc_info=True)
            return self.json({"status": "error", "message": "Invalid JSON format in request body.", "error": "json_decode_error"}, status_code=400)
        except Exception as e: 
            _LOGGER.error(f"[REST] General error in POST /api/savant_energy/scenes. Data: {data}. Error: {e}", exc_info=True)
            return self.json({"status": "error", "message": "An unexpected server error occurred.", "error": "unknown_server_error"}, status_code=500)


class SavantSceneBreakersRestView(HomeAssistantView):
    url = "/api/savant_energy/scene_breakers/{scene_id}"
    name = "api:savant_energy:scene_breakers"
    requires_auth = True

    async def get(self, request, scene_id):
        try:
            hass = request.app["hass"]
            storage = SavantSceneStorage(hass)
            await storage.async_load()
            if scene_id not in storage.scenes:
                error_resp = {"status": "error", "message": f"Scene {scene_id} not found"}
                _LOGGER.debug(f"[REST] Scene not found: {json.dumps(error_resp)}")
                return self.json(error_resp, status_code=404)
            saved_states = dict(storage.scenes[scene_id].get("relay_states", {}))
            coordinator = None
            for entry_id, data in hass.data.get(DOMAIN, {}).items():
                if hasattr(data, "config_entry"):
                    coordinator = data
                    break
            all_breakers = SavantSceneManager(hass, coordinator, storage).get_all_available_devices() if coordinator else {}
            # For any breaker in all_breakers not in saved_states, set to True (on) by default
            merged = {**{k: saved_states.get(k, True) for k in all_breakers}, **{k: v for k, v in saved_states.items() if k not in all_breakers}}
            response = {"scene_id": scene_id, "breakers": merged}
            _LOGGER.debug(f"[REST] Returning scene_breakers response: {json.dumps(response)}")
            return self.json(response)
        except Exception as e:
            _LOGGER.error(f"[REST] Exception in SavantSceneBreakersRestView: {e}", exc_info=True)
            return self.json({"status": "error", "message": str(e)}, status_code=500)


class SavantSceneDetailRestView(HomeAssistantView):
    """
    REST API for individual scene operations: delete and update.
    """
    url = "/api/savant_energy/scenes/{scene_id}"
    name = "api:savant_energy:scene_detail"
    requires_auth = True

    async def delete(self, request, scene_id):
        try:
            hass = request.app["hass"]
            await hass.services.async_call(
                DOMAIN, "delete_scene", {"scene_id": scene_id}, blocking=True
            )
            return self.json({"status": "ok", "scene_id": scene_id})
        except Exception as e:
            _LOGGER.error(f"[REST] Error deleting scene {scene_id}: {e}", exc_info=True)
            return self.json({"status": "error", "message": str(e)}, status_code=500)

    async def post(self, request, scene_id):
        try:
            data = await request.json()
            hass = request.app["hass"]
            payload = {"scene_id": scene_id}
            if "name" in data:
                payload["name"] = data["name"]
            if "relay_states" in data:
                payload["relay_states"] = data["relay_states"]
            await hass.services.async_call(
                DOMAIN, "update_scene", payload, blocking=True
            )
            return self.json({"status": "ok", "scene_id": scene_id})
        except Exception as e:
            _LOGGER.error(f"[REST] Error updating scene {scene_id}: {e}", exc_info=True)
            return self.json({"status": "error", "message": str(e)}, status_code=500)


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
        storage = SavantSceneStorage(hass)
        entity_registry = async_get_entity_registry(hass)
        # Create the scene manager
        scene_manager = SavantSceneManager(hass, coordinator, storage)
        hass.data.setdefault(f"{DOMAIN}_scene_managers", {})[entry.entry_id] = scene_manager
        # Do NOT create scene entities for Savant scenes anymore
        # Register all Savant Energy scene API/service handlers
        register_scene_services(hass, scene_manager, storage, coordinator)
        # Register REST API views
        hass.http.register_view(SavantScenesRestView)
        _LOGGER.info("SavantScenesRestView registered at /api/savant_energy/scenes")
        hass.http.register_view(SavantSceneDetailRestView)
        _LOGGER.info("SavantSceneDetailRestView registered at /api/savant_energy/scenes/{scene_id}")
        hass.http.register_view(SavantSceneBreakersRestView)
        _LOGGER.info("SavantSceneBreakersRestView registered at /api/savant_energy/scene_breakers/{scene_id}")


class SavantSceneStorage:
    """Class to handle scene storage."""
    
    def __init__(self, hass: HomeAssistant):
        """Initialize the storage."""
        self.hass = hass
        self.store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.scenes: Dict[str, Dict] = {}
        self._lock = asyncio.Lock()
        self._last_saved_state: Dict[str, Dict] = {}  # Keep track of last successfully saved state
    
    async def async_load(self) -> None:
        """Load scenes from storage and migrate relay_states keys to breaker IDs only (no fallback to friendly name)."""
        data = await self.store.async_load()
        _LOGGER.debug(f"Loading scenes from storage.")
        if data and "scenes" in data:
            self.scenes = data["scenes"]
            
            # Get all valid breaker switch entity IDs from HASS
            valid_breaker_entity_ids = set()
            all_hass_switch_ids = self.hass.states.async_entity_ids("switch")
            for entity_id in all_hass_switch_ids:
                state = self.hass.states.get(entity_id)
                if not state: # Should generally not happen if entity_id came from async_entity_ids
                    continue
                friendly_name = state.attributes.get("name", "").lower()
                entity_id_lower = entity_id.lower()
                # Define what constitutes a "breaker" switch relevant to scenes
                # This logic should align with how breakers are identified elsewhere (e.g., SavantSceneManager.get_all_available_devices)
                if "breaker" in entity_id_lower or "breaker" in friendly_name:
                    valid_breaker_entity_ids.add(entity_id)

            _LOGGER.debug(f"Found {len(valid_breaker_entity_ids)} valid breaker switch entity IDs for scene validation")

            for scene_id_key, scene_data in list(self.scenes.items()): # Use list(self.scenes.items()) for safe iteration if modifying
                original_relay_states = scene_data.get("relay_states", {})
                new_relay_states = {}
                
                scene_name_for_log = scene_data.get('name', scene_id_key)

                if not isinstance(original_relay_states, dict):
                    _LOGGER.warning(f"Scene '{scene_name_for_log}' has malformed relay_states (not a dict): {original_relay_states}. Clearing relay_states for this scene.")
                    original_relay_states = {}

                for key, value in original_relay_states.items():
                    if key in valid_breaker_entity_ids:
                        new_relay_states[key] = value
                    else:
                        _LOGGER.warning(f"Ignoring relay_states key '{key}' in scene '{scene_name_for_log}' because it is not a recognized valid breaker switch entity_id.")
                scene_data["relay_states"] = new_relay_states
            _LOGGER.debug(f"Loaded and validated {len(self.scenes)} scenes from storage.")
        else:
            _LOGGER.warning("No scenes found in storage or data is invalid")
            self.scenes = {}
    
    async def async_save(self) -> None:
        """Save current self.scenes to storage."""
        async with self._lock:
            _LOGGER.debug(f"Preparing to save scenes. Current scene count: {len(self.scenes)}. Last saved count: {len(self._last_saved_state)}")

            if self._last_saved_state and not self.scenes:
                _LOGGER.warning(f"Attempt to save an empty scene list over a previously populated one (last had {len(self._last_saved_state)} scenes). Restoring from last known good state.")
                self.scenes = dict(self._last_saved_state)
            await self.store.async_save({"scenes": self.scenes})
            self._last_saved_state = dict(self.scenes)
            _LOGGER.info(f"[Storage] Scenes saved to storage. Current scenes: {json.dumps(self.scenes)}")
    
    async def async_create_scene(self, name: str, relay_states: Dict[str, bool]) -> str:
        """Create a new scene and save it to storage."""
        async with self._lock:
            scene_id = f"savant_{slugify(name)}"
            if scene_id in self.scenes:
                raise HomeAssistantError(f"Scene {name} already exists")
                return  # Defensive: will never be reached, but clarifies intent
            for existing_scene in self.scenes.values():
                if existing_scene["name"].strip().lower() == name.strip().lower():
                    raise HomeAssistantError(f"Scene {name} already exists")
                    return  # Defensive: will never be reached, but clarifies intent
            relay_states = relay_states or {}
            all_entity_ids = self.hass.states.async_entity_ids("switch")
            for entity_id_str in all_entity_ids:
                state = self.hass.states.get(entity_id_str)
                if not state or state.state in ("unknown", "unavailable"):
                    continue
                friendly_name = state.attributes.get("friendly_name", "")
                if "breaker" in entity_id_str.lower() or "breaker" in friendly_name.lower():
                    relay_states[entity_id_str] = True
            self.scenes[scene_id] = {"name": name, "relay_states": relay_states or {}}
            await self.store.async_save({"scenes": self.scenes})
            self._last_saved_state = dict(self.scenes)
            _LOGGER.info(f"[Storage] Scene '{name}' (ID: {scene_id}) created and saved to storage. Current scenes: {json.dumps(self.scenes)}")
            return scene_id
    
    async def async_update_scene(self, scene_id: str, name: Optional[str] = None, relay_states: Optional[Dict[str, bool]] = None) -> None:
        """Update an existing scene in the JSON file.
        If the name changes, the entity in Home Assistant will be updated.
        """
        async with self._lock:
            data = await self.store.async_load()
            self.scenes = (data or {}).get("scenes", {})
            if scene_id not in self.scenes:
                raise HomeAssistantError(f"Scene {scene_id} not found")
            scene = self.scenes[scene_id]
            old_name = scene["name"]
            name_changed = False
            if name is not None and name != old_name:
                for existing_id, existing_scene_data in self.scenes.items():
                    if existing_id != scene_id and existing_scene_data["name"].strip().lower() == name.strip().lower():
                        raise HomeAssistantError(f"A scene with the name '{name}' already exists.")
                scene["name"] = name
                name_changed = True
                _LOGGER.debug(f"[Storage] Scene '{scene_id}' name changed from '{old_name}' to '{name}'.")
            if relay_states is not None:
                scene["relay_states"] = relay_states
                _LOGGER.debug(f"[Storage] Scene '{scene_id}' relay_states updated to: {relay_states}")
            await self.store.async_save({"scenes": self.scenes})
            self._last_saved_state = dict(self.scenes)
            _LOGGER.info(f"[Storage] Scene '{scene_id}' updated and saved to storage. Current scenes: {json.dumps(self.scenes)}")

    async def async_delete_scene(self, scene_id: str) -> None:
        """Delete a scene from storage."""
        _LOGGER.debug(f"[Storage] Attempting to delete scene: {scene_id}")
        async with self._lock:
            data = await self.store.async_load()
            self.scenes = (data or {}).get("scenes", {})
            if scene_id in self.scenes:
                _LOGGER.debug(f"[Storage] Found scene {scene_id} in storage. Current scenes before delete: {json.dumps(self.scenes)}")
                del self.scenes[scene_id]
                await self.store.async_save({"scenes": self.scenes})
                self._last_saved_state = dict(self.scenes)
                _LOGGER.info(f"[Storage] Scene '{scene_id}' deleted and saved to storage. Current scenes: {json.dumps(self.scenes)}")
            else:
                _LOGGER.warning(f"[Storage] Attempted to delete non-existent scene: '{scene_id}'. Current scenes: {json.dumps(self.scenes)}")
                raise HomeAssistantError(f"Scene '{scene_id}' not found for deletion.")

    async def async_overwrite_scenes(self, scenes: list) -> None:
        """Overwrite all scenes in storage."""
        async with self._lock:
            self.scenes = {f"savant_{slugify(scene['name'])}": scene for scene in scenes}
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
    
    async def async_update_scene(self, scene_id: str, name: Optional[str] = None, relay_states: Optional[Dict[str, bool]] = None) -> None:
        """Update an existing scene."""
        await self.storage.async_update_scene(scene_id, name, relay_states)
    
    async def async_delete_scene(self, scene_id: str) -> None:
        """Delete a scene."""
        await self.storage.async_delete_scene(scene_id)
    
    async def async_execute_scene(self, scene_id: str) -> bool:
        """Execute a scene by sending DMX commands for all included relays."""
        if scene_id not in self.storage.scenes:
            raise HomeAssistantError(f"Scene {scene_id} not found")
            
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
                
            try:
                dmx_address = int(state.state)
            except Exception:
                continue
            
            # Use the entity_id (breaker id) as the key for relay_states lookup
            breaker_id = entity_id
            # If breaker_id is in relay_states, use its value, else ON (255)
            value = 255 if breaker_id not in relay_states else (255 if relay_states[breaker_id] else 0)
            dmx_values[dmx_address] = str(value)
        
        if not dmx_values:
            _LOGGER.warning(f"No DMX addresses found for scene {scene['name']}")
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
            _LOGGER.info(f"Scene {scene['name']} executed successfully.")
        else:
            _LOGGER.error(f"Scene {scene['name']} failed to execute.")
            
        return success
        
    def get_all_available_devices(self) -> Dict[str, bool]:
        """Get a list of all available breaker switch devices and their current states."""
        devices = {}
        # Get all switch entities that are breaker switches
        all_entity_ids = self.hass.states.async_entity_ids("switch")
        for entity_id in all_entity_ids:
            state = self.hass.states.get(entity_id)
            if not state or state.state in ("unknown", "unavailable"):
                continue
            # Check if 'breaker' is in the entity_id or friendly_name
            friendly_name = state.attributes.get("friendly_name", "")
            if "breaker" in entity_id.lower() or "breaker" in friendly_name.lower():
                devices[entity_id] = state.state == "on"
        return devices
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
import voluptuous as vol  # type: ignore
from typing import Any, Dict, Final, List, Optional
import re # Added for name normalization

from homeassistant.config_entries import ConfigEntry  # type: ignore
from homeassistant.core import HomeAssistant, callback  # type: ignore
from homeassistant.helpers.entity_platform import AddEntitiesCallback  # type: ignore
from homeassistant.helpers.storage import Store  # type: ignore
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry  # type: ignore
from homeassistant.components.http import HomeAssistantView  # type: ignore
from .api import register_scene_services  # type: ignore
from homeassistant.exceptions import HomeAssistantError  # type: ignore

from .const import DOMAIN, MANUFACTURER, DEFAULT_OLA_PORT, CONF_DMX_TESTING_MODE
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
            _LOGGER.error(
                f"[REST] Exception in SavantScenesRestView: {e}", exc_info=True
            )
            return self.json({"status": "error", "message": str(e)}, status_code=500)

    async def post(self, request):
        """Create a new Savant scene via REST, handling logic directly."""
        data = None
        try:
            data = await request.json()
            hass = request.app["hass"]

            savant_domain_data = hass.data.get(DOMAIN)
            if (
                not savant_domain_data
                or "scene_manager" not in savant_domain_data
                or "storage" not in savant_domain_data
            ):
                _LOGGER.error(
                    "[REST] Savant scene_manager or storage not found in hass.data"
                )
                return self.json(
                    {
                        "status": "error",
                        "message": "Internal server configuration error. Scene manager or storage not initialized.",
                    },
                    status_code=500,
                )

            scene_manager = savant_domain_data["scene_manager"]
            storage = savant_domain_data["storage"]

            name = data.get("name")
            relay_states = data.get("relay_states")

            if (
                not name
                or not isinstance(name, str)
                or not isinstance(relay_states, dict)
            ):
                _LOGGER.warning(
                    f"[REST] Invalid data for scene creation: Name or relay_states missing/invalid. Data: {data}"
                )
                return self.json(
                    {
                        "status": "error",
                        "message": "Invalid input: 'name' (string) and 'relay_states' (object) are required.",
                    },
                    status_code=400,
                )

            try:
                scene_id = await scene_manager.async_create_scene(name, relay_states)
                # Ensure storage is up-to-date for subsequent reads if any happen in same context (though less critical here)
                await storage.async_load()
                _LOGGER.info(
                    f"[REST] Scene '{name}' (ID: {scene_id}) created successfully via REST POST."
                )
                return self.json({"status": "ok", "scene_id": scene_id})
            except HomeAssistantError as hae:
                _LOGGER.warning(f"[REST] Scene creation failed: {hae}. Data: {data}")
                error_message = str(hae)
                # Check if the error is due to the scene already existing
                error_type = (
                    "scene_exists"
                    if "already exists" in error_message.lower()
                    else "creation_failed"
                )
                return self.json(
                    {"status": "error", "message": error_message, "error": error_type},
                    status_code=400,
                )
            except Exception as e:
                _LOGGER.error(
                    f"[REST] Unexpected error creating scene '{name}': {e}. Data: {data}",
                    exc_info=True,
                )
                return self.json(
                    {
                        "status": "error",
                        "message": f"An unexpected error occurred: {str(e)}",
                    },
                    status_code=500,
                )

        except json.JSONDecodeError as json_err:
            _LOGGER.warning(
                f"[REST] Invalid JSON received for scene creation: {json_err}",
                exc_info=True,
            )
            return self.json(
                {
                    "status": "error",
                    "message": "Invalid JSON format in request body.",
                    "error": "json_decode_error",
                },
                status_code=400,
            )
        except Exception as e:
            # Catch-all for errors before scene creation logic (e.g., hass.data access issues if not caught above)
            _LOGGER.error(
                f"[REST] General error in POST /api/savant_energy/scenes (pre-creation). Data: {data}. Error: {e}",
                exc_info=True,
            )
            return self.json(
                {
                    "status": "error",
                    "message": "An unexpected server error occurred.",
                    "error": "unknown_server_error",
                },
                status_code=500,
            )


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
                error_resp = {
                    "status": "error",
                    "message": f"Scene {scene_id} not found",
                }
                _LOGGER.debug(f"[REST] Scene not found: {json.dumps(error_resp)}")
                return self.json(error_resp, status_code=404)
            saved_states = dict(storage.scenes[scene_id].get("relay_states", {}))
            coordinator = None
            for entry_id, data in hass.data.get(DOMAIN, {}).items():
                if hasattr(data, "config_entry"):
                    coordinator = data
                    break
            all_breakers = (
                SavantSceneManager(
                    hass, coordinator, storage
                ).get_all_available_devices()
                if coordinator
                else {}
            )
            # For any breaker in all_breakers not in saved_states, set to True (on) by default
            merged = {
                **{k: saved_states.get(k, True) for k in all_breakers},
                **{k: v for k, v in saved_states.items() if k not in all_breakers},
            }
            response = {"scene_id": scene_id, "breakers": merged}
            _LOGGER.debug(
                f"[REST] Returning scene_breakers response: {json.dumps(response)}"
            )
            return self.json(response)
        except Exception as e:
            _LOGGER.error(
                f"[REST] Exception in SavantSceneBreakersRestView: {e}", exc_info=True
            )
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

        # Store manager and storage in hass.data for REST views
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][entry.entry_id] = coordinator  # Existing coordinator storage
        hass.data[DOMAIN]["scene_manager"] = scene_manager
        hass.data[DOMAIN]["storage"] = storage

        hass.data.setdefault(f"{DOMAIN}_scene_managers", {})[entry.entry_id] = (
            scene_manager
        )
        # Do NOT create scene entities for Savant scenes anymore
        # Register all Savant Energy scene API/service handlers
        register_scene_services(hass, scene_manager, storage, coordinator)
        # Register REST API views
        hass.http.register_view(SavantScenesRestView)
        _LOGGER.info("SavantScenesRestView registered at /api/savant_energy/scenes")
        hass.http.register_view(SavantSceneDetailRestView)
        _LOGGER.info(
            "SavantSceneDetailRestView registered at /api/savant_energy/scenes/{scene_id}"
        )
        hass.http.register_view(SavantSceneBreakersRestView)
        _LOGGER.info(
            "SavantSceneBreakersRestView registered at /api/savant_energy/scene_breakers/{scene_id}"
        )


class SavantSceneStorage:
    """Class to handle scene storage."""

    def __init__(self, hass: HomeAssistant):
        """Initialize the storage."""
        self.hass = hass
        self.store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.scenes: Dict[str, Dict] = {}
        self._lock = asyncio.Lock()
        self._last_saved_state: Dict[str, Dict] = {}

    def _get_normalized_scene_parts(self, raw_name: str) -> tuple[str, str, str]:
        """
        Normalizes a raw scene name to a base label, then formats it into
        a final scene name and a scene ID.
        Returns: (base_label, final_scene_name, final_scene_id)
        """
        # Remove any existing Savant prefix/suffix before reapplying
        base_label = re.sub(r'^[Ss]avant\s+', '', raw_name, flags=re.IGNORECASE)
        base_label = re.sub(r'\s+[Ss]cene$', '', base_label, flags=re.IGNORECASE).strip()
        final_name = f"Savant {base_label} Scene"
        slug = slugify(base_label)
        final_id = f"savant_{slug}_scene"
        return base_label, final_name, final_id

    async def async_load(self) -> None:
        data = await self.store.async_load()
        _LOGGER.debug("Loading scenes from storage.")
        if data and "scenes" in data:
            self.scenes = data["scenes"]
            # Validate relay_states keys
            valid_switches = set(
                eid for eid in self.hass.states.async_entity_ids("switch")
                if (st:=self.hass.states.get(eid)) and "breaker" in eid.lower()
            )
            for sid, sd in list(self.scenes.items()):
                orig = sd.get("relay_states", {}) or {}
                cleaned = {k: v for k, v in orig.items() if k in valid_switches}
                sd["relay_states"] = cleaned
            _LOGGER.debug(f"Loaded and validated {len(self.scenes)} scenes.")
        else:
            _LOGGER.warning("No valid scenes in storage; resetting.")
            self.scenes = {}


    async def async_save(self) -> None:
        async with self._lock:
            if self._last_saved_state and not self.scenes:
                _LOGGER.warning("Preventing overwrite with empty scenes; restoring last state.")
                self.scenes = dict(self._last_saved_state)
            await self.store.async_save({"scenes": self.scenes})
            self._last_saved_state = dict(self.scenes)
            # Only keep this info log for successful save
            _LOGGER.info("Scenes saved to storage.")

    async def async_create_scene(self, name: str, relay_states: Dict[str, bool]) -> str:
        """Create a new scene and save it to storage."""
        async with self._lock:
            raw_name = name  # Keep original input
            base_label, final_name, final_id = self._get_normalized_scene_parts(raw_name)

            data = await self.store.async_load()
            self.scenes = (data or {}).get("scenes", {})

            if final_id in self.scenes:
                # This checks ID conflict, which is derived from base_label
                raise HomeAssistantError(f"A scene derived from '{raw_name}' (ID: {final_id}) already exists.")

            # Check for display name conflicts
            for existing_scene_id, existing_scene_data in self.scenes.items():
                existing_base_label = existing_scene_data.get("name", "")
                _ex_base, existing_final_name, _ex_id = self._get_normalized_scene_parts(existing_base_label)
                if existing_final_name.strip().lower() == final_name.strip().lower():
                    raise HomeAssistantError(
                        f"A scene with the display name '{final_name}' already exists (derived from stored name '{existing_base_label}', ID: {existing_scene_id})."
                    )
            
            relay_states = relay_states or {}
            if not relay_states:
                all_entity_ids = self.hass.states.async_entity_ids("switch")
                populated_relay_states = {}
                for entity_id_str in all_entity_ids:
                    state = self.hass.states.get(entity_id_str)
                    if not state or state.state in ("unknown", "unavailable"):
                        continue
                    friendly_name_attr = state.attributes.get("friendly_name", "")
                    if "breaker" in entity_id_str.lower() or "breaker" in friendly_name_attr.lower():
                        populated_relay_states[entity_id_str] = True
                relay_states = populated_relay_states

            # Store the base_label as the scene's "name"
            self.scenes[final_id] = {"name": base_label, "relay_states": relay_states}
            await self.store.async_save({"scenes": self.scenes})
            self._last_saved_state = dict(self.scenes)
            _LOGGER.info(f"Scene '{final_name}' (ID: {final_id}, Stored Name: '{base_label}') created and saved.")
            return final_id

    async def async_update_scene(self, scene_id: str, name: Optional[str] = None, relay_states: Optional[Dict[str, bool]] = None) -> None:
        """Update an existing scene in the JSON file."""
        async with self._lock:
            data = await self.store.async_load()
            self.scenes = (data or {}).get("scenes", {})

            if scene_id not in self.scenes:
                raise HomeAssistantError(f"Scene with ID '{scene_id}' not found.")

            scene = self.scenes[scene_id]
            original_stored_name = scene.get("name", scene_id) # This is a base_label
            _orig_base, original_full_name, _orig_id = self._get_normalized_scene_parts(original_stored_name)

            new_stored_name = original_stored_name
            new_full_name = original_full_name

            if name is not None:
                raw_update_name = name
                update_base_label, updated_full_name, _update_final_id = self._get_normalized_scene_parts(raw_update_name)

                # Scene ID does not change on update, but the name might.
                # Check for conflict if the full display name is changing.
                if updated_full_name.strip().lower() != original_full_name.strip().lower():
                    for existing_id, existing_scene_data in self.scenes.items():
                        if existing_id == scene_id:
                            continue
                        existing_stored_base = existing_scene_data.get("name", "")
                        _ex_base, existing_final_name, _ex_id = self._get_normalized_scene_parts(existing_stored_base)
                        if existing_final_name.strip().lower() == updated_full_name.strip().lower():
                            raise HomeAssistantError(
                                f"Cannot update scene '{original_full_name}': another scene with the name '{updated_full_name}' already exists (ID: {existing_id})."
                            )
                    scene["name"] = update_base_label # Store the new base_label
                    new_stored_name = update_base_label
                    new_full_name = updated_full_name
                    _LOGGER.debug(f"[Storage] Scene '{scene_id}' name changed from '{original_full_name}' to '{new_full_name}' (Stored: '{update_base_label}').")
                else:
                    _LOGGER.debug(f"[Storage] Scene '{scene_id}' name update requested with '{raw_update_name}', but normalized full name '{updated_full_name}' is the same as current. No change made to name.")

            if relay_states is not None:
                scene["relay_states"] = relay_states
                _LOGGER.debug(f"[Storage] Scene '{scene_id}' relay_states updated.")

            await self.store.async_save({"scenes": self.scenes})
            self._last_saved_state = dict(self.scenes)
            _LOGGER.info(f"[Storage] Scene '{scene_id}' (Name: '{new_full_name}', Stored: '{new_stored_name}') updated and saved.")

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
        async with self._lock:
            self.scenes = {}
            processed_scene_ids = set() # To detect duplicate final_ids from input list

            for s_data in scenes:
                raw_name_from_input = s_data.get("name", "")
                # If the input name is already a base_label, _get_normalized_scene_parts handles it.
                # If it's a full "Savant X Scene", it also handles it.
                base_label, final_name, final_id = self._get_normalized_scene_parts(raw_name_from_input)
                
                relay_states_from_input = s_data.get("relay_states", {}) or {}

                # Use the derived final_id as the primary key.
                # The 'id' field in s_data is ignored in favor of our normalized one.
                if final_id in processed_scene_ids:
                    _LOGGER.warning(f"Duplicate scene ID '{final_id}' (derived from raw name '{raw_name_from_input}') encountered during overwrite. Skipping subsequent entry for this ID.")
                    continue
                
                # Check for display name conflict within the list being imported
                # This is a bit more complex as we build the list, simpler to check against already added ones.
                for added_id, added_data in self.scenes.items():
                    added_base = added_data.get("name", "")
                    _ad_base, added_final_name, _ad_id = self._get_normalized_scene_parts(added_base)
                    if added_final_name.strip().lower() == final_name.strip().lower():
                        _LOGGER.warning(f"Scene name '{final_name}' (from raw input '{raw_name_from_input}') conflicts with already processed scene '{added_final_name}' (ID: {added_id}). Skipping this entry.")
                        # Mark as processed to avoid re-evaluating if it appears again with a different raw name but same final_id
                        processed_scene_ids.add(final_id) 
                        break 
                else: # No break, so no conflict with already added scenes
                    self.scenes[final_id] = {
                        "id": final_id, # Store normalized ID also in 'id' field for consistency
                        "name": base_label, # Store the base_label
                        "relay_states": relay_states_from_input
                    }
                    processed_scene_ids.add(final_id)

            _LOGGER.info(f"Overwriting scenes. {len(self.scenes)} scenes prepared after processing input list.")
            await self.async_save() # async_save logs its own success
            _LOGGER.info("Scenes successfully overwritten and saved via async_overwrite_scenes.")


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

    async def async_update_scene(
        self,
        scene_id: str,
        name: Optional[str] = None,
        relay_states: Optional[Dict[str, bool]] = None,
    ) -> None:
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
            entity_id
            for entity_id in all_entity_ids
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
            value = (
                255
                if breaker_id not in relay_states
                else (255 if relay_states[breaker_id] else 0)
            )
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
            self.coordinator.config_entry.data.get(CONF_DMX_TESTING_MODE, False),
        )

        _LOGGER.info(f"Executing scene {scene['name']} with {len(dmx_values)} relays")

        # Send the DMX command
        success = await async_set_dmx_values(
            ip_address, dmx_values, ola_port, dmx_testing_mode
        )

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

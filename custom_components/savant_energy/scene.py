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
        _LOGGER.info("[SceneStorage] async_load called.")
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
        _LOGGER.info(f"[SceneStorage] async_load complete. Scene count: {len(self.scenes)}")

    async def async_save(self) -> None:
        _LOGGER.info(f"[SceneStorage] async_save called. Scene count: {len(self.scenes)}")
        _LOGGER.debug(f"[SceneStorage] Scenes to save: {json.dumps(self.scenes, default=str)}")
        async with self._lock:
            if self._last_saved_state and not self.scenes:
                _LOGGER.warning("Preventing overwrite with empty scenes; restoring last state.")
                self.scenes = dict(self._last_saved_state)
            await self.store.async_save({"scenes": self.scenes})
            _LOGGER.info(f"[SceneStorage] Data written to store: {json.dumps({'scenes': self.scenes}, default=str)}")
            self._last_saved_state = dict(self.scenes)
            _LOGGER.info("Scenes saved to storage.")

    async def async_create_scene(self, name: str, relay_states: Dict[str, bool]) -> str:
        _LOGGER.info(f"[SceneStorage] async_create_scene called with name={name}, relay_states={relay_states}")
        async with self._lock:
            _, final_name, final_id = self._get_normalized_scene_parts(name)
            _LOGGER.debug(f"[SceneStorage] Normalized scene: id={final_id}, name={final_name}")
            if final_id in self.scenes:
                _LOGGER.error(f"[SceneStorage] Scene ID '{final_id}' exists. Cannot create.")
                raise HomeAssistantError(f"Scene ID '{final_id}' exists.")
            if any(s.get("name","").lower() == final_name.lower() for s in self.scenes.values()):
                _LOGGER.error(f"[SceneStorage] Scene name '{final_name}' exists. Cannot create.")
                raise HomeAssistantError(f"Scene name '{final_name}' exists.")
            self.scenes[final_id] = {"id": final_id, "name": final_name, "relay_states": relay_states}
            _LOGGER.info(f"[SceneStorage] Scene dict after add: {json.dumps(self.scenes, default=str)}")
            await self.async_save()
            _LOGGER.info(f"[SceneStorage] Scene created: id={final_id}, name={final_name}")
            return final_id

    async def async_update_scene(self, scene_id: str, name: Optional[str]=None, relay_states: Optional[Dict[str, bool]]=None) -> None:
        _LOGGER.info(f"[SceneStorage] async_update_scene called with scene_id={scene_id}, name={name}, relay_states={relay_states}")
        async with self._lock:
            if scene_id not in self.scenes:
                _LOGGER.error(f"[SceneStorage] Scene '{scene_id}' not found for update.")
                raise HomeAssistantError(f"Scene '{scene_id}' not found.")
            sd = self.scenes[scene_id]
            changed = False
            if name is not None:
                _, new_name, _ = self._get_normalized_scene_parts(name)
                if new_name.lower() != sd.get("name", "").lower():
                    if any(v.get("name", "").lower() == new_name.lower() and other_id != scene_id for other_id, v in self.scenes.items()):
                        _LOGGER.error(f"[SceneStorage] Scene name '{new_name}' already exists. Cannot update.")
                        raise HomeAssistantError(f"Scene name '{new_name}' already exists.")
                    sd["name"] = new_name
                    changed = True
            if relay_states is not None and sd.get("relay_states") != relay_states:
                sd["relay_states"] = relay_states
                changed = True
            if changed:
                await self.async_save()
                _LOGGER.info(f"[SceneStorage] Scene '{scene_id}' updated. New name: '{sd.get('name')}', relay_states: {sd.get('relay_states')}")
            else:
                _LOGGER.info(f"[SceneStorage] No changes applied to scene '{scene_id}' during update attempt.")

    async def async_delete_scene(self, scene_id: str) -> None:
        _LOGGER.info(f"[SceneStorage] async_delete_scene called with scene_id={scene_id}")
        async with self._lock:
            data = await self.store.async_load() or {}
            disk = data.get("scenes", {}) or {}
            self.scenes = disk
            if scene_id not in self.scenes:
                _LOGGER.error(f"[SceneStorage] Scene '{scene_id}' not found for deletion.")
                raise HomeAssistantError(f"Scene '{scene_id}' not found.")
            del self.scenes[scene_id]
            if len(self.scenes) < len(self._last_saved_state)-1:
                _LOGGER.error(f"[SceneStorage] Aborting delete; data loss risk. Scene count after delete: {len(self.scenes)}")
                raise HomeAssistantError("Aborting delete; data loss risk.")
            await self.store.async_save({"scenes": self.scenes})
            self._last_saved_state = dict(self.scenes)
            _LOGGER.info(f"[SceneStorage] Scene '{scene_id}' deleted.")

    async def async_overwrite_scenes(self, scenes: list) -> None:
        _LOGGER.info(f"[SceneStorage] async_overwrite_scenes called with scenes={scenes}")
        async with self._lock:
            self.scenes = {}
            for s in scenes:
                bid = s.get("scene_id") or s.get("id")
                name = s.get("name","")
                states = s.get("relay_states",{}) or {}
                _, final_name, final_id = self._get_normalized_scene_parts(name)
                sid = bid if bid and bid.startswith("savant_") else final_id
                self.scenes[sid] = {"id": sid, "name": final_name, "relay_states": states}
            await self.async_save()
            _LOGGER.info(f"[SceneStorage] Scenes overwritten. New scene count: {len(self.scenes)}")


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

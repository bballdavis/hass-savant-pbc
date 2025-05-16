"""
API endpoints and service handlers for Savant Energy scene management.
Handles all create, update, delete, and query operations for scenes.
"""

import logging
import json
import voluptuous as vol # type: ignore
from homeassistant.exceptions import HomeAssistantError # type: ignore
from .const import DOMAIN 
from .utils import slugify

_LOGGER = logging.getLogger(__name__)


def register_scene_services(hass, scene_manager, storage, coordinator):
    """
    Register all Savant Energy scene management services and REST API endpoints.
    """
    # Helper to return scenes in consistent format
    def get_scenes_response():
        scenes_meta = [
            {"scene_id": scene_id, "name": scene_data["name"]}
            for scene_id, scene_data in storage.scenes.items()
        ]
        return {"scenes": scenes_meta}

    # --- Service Handlers ---
    async def handle_create_scene(call):
        _LOGGER.debug(f"[API] create_scene called with data: {call.data}")
        name = call.data["name"]
        relay_states = call.data["relay_states"]
        try:
            scene_id = await scene_manager.async_create_scene(name, relay_states)
        except HomeAssistantError as hae:
            _LOGGER.warning(f"[API] Scene creation failed: {hae}")
            error_message = str(hae)
            error_type = "scene_exists" if "already exists" in error_message.lower() else "homeassistant_error"
            return {"status": "error", "message": error_message, "error": error_type}
        except Exception as e:
            _LOGGER.error(f"[API] Error creating scene '{name}': {e}", exc_info=True)
            return {"status": "error", "message": str(e)}
        await storage.async_load()  # Only called if no exception
        resp = {"status": "ok", "scene_id": scene_id}
        _LOGGER.info(f"[API] create_scene response: {json.dumps(resp)}")
        return resp

    async def handle_update_scene(call):
        _LOGGER.debug(f"[API] update_scene called with data: {call.data}")
        scene_id = call.data["scene_id"]
        name = call.data.get("name")
        relay_states = call.data.get("relay_states")
        try:
            await scene_manager.async_update_scene(scene_id, name, relay_states)
            await storage.async_load()
            resp = {"status": "ok", "scene_id": scene_id}
            _LOGGER.info(f"[API] update_scene response: {json.dumps(resp)}")
            return resp
        except Exception as e:
            _LOGGER.error(f"[API] update_scene error: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def handle_delete_scene(call):
        _LOGGER.debug(f"[API] delete_scene called with data: {call.data}")
        scene_id = call.data["scene_id"]
        try:
            await scene_manager.async_delete_scene(scene_id)
            await storage.async_load()
            resp = {"status": "ok", "scene_id": scene_id}
            _LOGGER.info(f"[API] delete_scene response: {json.dumps(resp)}")
            return resp
        except Exception as e:
            _LOGGER.error(f"[API] delete_scene error: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def handle_save_scenes(call):
        _LOGGER.debug(f"[API] save_scenes called with data: {call.data}")
        scenes = call.data["scenes"]
        await storage.async_overwrite_scenes(scenes)
        await storage.async_load()
        resp = {"status": "ok", "count": len(scenes)}
        _LOGGER.info(f"[API] save_scenes completed. Scenes count: {len(scenes)}")
        return resp

    async def handle_get_scenes(call):
        _LOGGER.debug(f"[API] get_scenes called with data: {call.data if hasattr(call, 'data') else None}")
        resp = get_scenes_response()
        _LOGGER.debug(f"[API] get_scenes response: {str(resp)[:50]}")
        return resp

    async def handle_get_scene_breakers(call):
        _LOGGER.debug(f"[API] get_scene_breakers called with data: {call.data}")
        scene_id = call.data["scene_id"]
        await storage.async_load()
        if scene_id not in storage.scenes:
            resp = {"error": "scene_not_found", "message": f"Scene {scene_id} not found"}
            _LOGGER.debug(f"[API] get_scene_breakers response: {str(resp)[:50]}")
            return resp
        saved_states = dict(storage.scenes[scene_id].get("relay_states", {}))
        all_breakers = scene_manager.get_all_available_devices()
        merged = {**{k: saved_states.get(k, False) for k in all_breakers}, **{k: v for k, v in saved_states.items() if k not in all_breakers}}
        resp = {"scene_id": scene_id, "breakers": merged}
        _LOGGER.debug(f"[API] get_scene_breakers response: {str(resp)[:50]}")
        return resp

    # --- Register Services ---
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
    hass.services.async_register(
        DOMAIN,
        "save_scenes",
        handle_save_scenes,
        schema=vol.Schema({
            vol.Required("scenes"): list,
        })
    )
    hass.services.async_register(
        DOMAIN,
        "get_scenes",
        handle_get_scenes,
    )
    hass.services.async_register(
        DOMAIN,
        "get_scene_breakers",
        handle_get_scene_breakers,
        schema=vol.Schema({
            vol.Required("scene_id"): str,
        })
    )

    # Return handlers for testing or extension
    return {
        "create_scene": handle_create_scene,
        "update_scene": handle_update_scene,
        "delete_scene": handle_delete_scene,
        "save_scenes": handle_save_scenes,
        "get_scenes": handle_get_scenes,
        "get_scene_breakers": handle_get_scene_breakers,
    }

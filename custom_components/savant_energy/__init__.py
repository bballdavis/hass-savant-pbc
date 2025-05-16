"""
Integration for Savant Energy.
Provides Home Assistant integration for Savant relay and energy monitoring devices.
"""

import logging
from datetime import timedelta, datetime
import shutil
import os
import traceback

import homeassistant.helpers.config_validation as cv # type: ignore
import voluptuous as vol # type: ignore

from homeassistant.config_entries import ConfigEntry # type: ignore
from homeassistant.core import HomeAssistant # type: ignore
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator  # type: ignore
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry # type: ignore
from homeassistant.helpers.translation import async_get_translations # type: ignore

from .const import (
    DOMAIN,
    CONF_ADDRESS,
    CONF_PORT,
    CONF_OLA_PORT,
    CONF_SCAN_INTERVAL,
    DEFAULT_OLA_PORT,
    PLATFORMS,
)
from .snapshot_data import get_current_energy_snapshot
from .utils import async_get_all_dmx_status, DMX_CACHE_SECONDS

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_ADDRESS): cv.string,
                vol.Required(CONF_PORT): cv.port,
                vol.Optional(CONF_SCAN_INTERVAL, default=15): cv.positive_int,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

# Lovelace card file information - follow HACS convention
LOVELACE_CARD_FILENAME = "savant-energy-scenes-card.js"
HACS_COMMUNITY_DIR = "community"
INTEGRATION_DIR_NAME = "savant_energy"
HACS_CARD_DIR = os.path.join(HACS_COMMUNITY_DIR, INTEGRATION_DIR_NAME)
LOVELACE_CARD_SOURCE = os.path.join(os.path.dirname(__file__), LOVELACE_CARD_FILENAME)


class SavantEnergyCoordinator(DataUpdateCoordinator):
    """
    Coordinator for Savant Energy data updates.
    Handles periodic polling of the Savant controller for energy and relay status data.
    """
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """
        Initialize the coordinator.
        Args:
            hass: Home Assistant instance
            entry: ConfigEntry for this integration
        """
        scan_interval = entry.options.get(
            CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, 15)
        )
        super().__init__(
            hass,
            logger=_LOGGER,
            name="SavantEnergyCoordinator",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.address = entry.data[CONF_ADDRESS]
        self.port = entry.data[CONF_PORT]
        self.config_entry = entry  # Store config entry directly
        self.dmx_data = {}  # Mapping of channel -> status (for debugging)
        self.dmx_last_update = None
        
    async def _async_update_data(self):
        """
        Fetch data from the Savant controller and update DMX status (for debugging).
        Returns a dict with snapshot_data and dmx_data.
        Ensures proper error handling and logging to diagnose data issues.
        """
        try:
            # Get snapshot data from energy controller
            snapshot_data = await self.hass.async_add_executor_job(
                get_current_energy_snapshot, self.address, self.port
            )
            
            # Log diagnostic information for troubleshooting entity availability
            if snapshot_data is None:
                _LOGGER.error("Received no data from Savant controller - check connection settings")
                return self.data  # Keep previous data rather than None
                
            if "presentDemands" not in snapshot_data:
                _LOGGER.error(f"Missing 'presentDemands' in snapshot data: {snapshot_data}")
                
            # Check if we have valid device data to report for debugging
            if "presentDemands" in snapshot_data:
                device_count = len(snapshot_data["presentDemands"])
                _LOGGER.debug(f"Retrieved {device_count} devices in presentDemands")
                
                # Debug log each device found for troubleshooting
                for device in snapshot_data["presentDemands"]:
                    has_uid = "uid" in device
                    has_name = "name" in device
                    has_percent = "percentCommanded" in device
                    if not all([has_uid, has_name, has_percent]):
                        _LOGGER.warning(f"Incomplete device data: uid={has_uid}, name={has_name}, percentCommanded={has_percent}. Device: {device}")
            
            # Update DMX status for debugging if cache expired
            now = datetime.now()
            if (not self.dmx_last_update or 
                (now - self.dmx_last_update).total_seconds() > DMX_CACHE_SECONDS):
                _LOGGER.debug("Updating DMX status data for debugging purposes only")
                ola_port = self.config_entry.data.get("ola_port", DEFAULT_OLA_PORT)
                self.dmx_data = {}
                self.dmx_last_update = now
                
            return {
                "snapshot_data": snapshot_data,
                "dmx_data": self.dmx_data
            }
        except Exception as exc:
            _LOGGER.error(f"Error updating data: {exc}")
            raise


async def _async_register_frontend_resource(hass: HomeAssistant) -> None:
    """
    Ensure the custom Lovelace card JS resource is registered for storage-mode dashboards.
    """
    resource_url = f"/hacsfiles/savant_energy/{LOVELACE_CARD_FILENAME}"
    resource_type = "module"
    _LOGGER.debug(f"[LovReg] Starting frontend resource registration: url={resource_url}, type={resource_type}")

    # Always patch .storage/lovelace_resources file (storage mode)
    storage_path = hass.config.path(".storage", "lovelace_resources")
    _LOGGER.debug(f"[LovReg] Storage-mode fallback, patching storage file at: {storage_path}")
    def _patch_storage() -> None:
        import json, os, uuid
        if not os.path.exists(storage_path):
            _LOGGER.debug(f"[LovReg] Storage file not found, skipping patch: {storage_path}")
            return
        with open(storage_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        items = data.get('data', {}).get('items', [])
        if any(item.get('url') == resource_url for item in items):
            _LOGGER.debug(f"[LovReg] Resource already in storage, no patch needed.")
            return
        # Append new resource entry
        items.append({
            'id': uuid.uuid4().hex,
            'url': resource_url,
            'type': resource_type
        })
        data.setdefault('data', {})['items'] = items
        with open(storage_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        _LOGGER.debug(f"[LovReg] Appended new resource entry to storage file.")
    await hass.async_add_executor_job(_patch_storage)
    _LOGGER.info(f"Patched .storage/lovelace_resources to include resource: {resource_url}")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Set up Savant Energy from a config entry.
    Registers the coordinator and forwards setup to all platforms.
    """
    # Preload translations for config options (for UI friendly names)
    await async_get_translations(hass, hass.config.language, "options", DOMAIN)

    # Check for disable_scene_builder option
    disable_scene_builder = entry.options.get(
        "disable_scene_builder",
        entry.data.get("disable_scene_builder", False)
    )
    if not disable_scene_builder:
        # Copy Lovelace card JS into HACS www directory for hosting at /local/community/<integration>/
        try:
            www_root = hass.config.path("www")
            hacs_www = os.path.join(www_root, "community", INTEGRATION_DIR_NAME)
            # Ensure HACS community directory exists
            if not os.path.exists(hacs_www):
                await hass.async_add_executor_job(os.makedirs, hacs_www)
            src_file = os.path.join(os.path.dirname(__file__), LOVELACE_CARD_FILENAME)
            dest_file = os.path.join(hacs_www, LOVELACE_CARD_FILENAME)
            await hass.async_add_executor_job(shutil.copyfile, src_file, dest_file)
            _LOGGER.info(f"Copied Savant Energy Lovelace card to {dest_file}")
        except Exception as copy_err:
            _LOGGER.error(f"Error copying Lovelace card to www folder: {copy_err}")

    # Resource management is now handled by HACS; no manual asset copy or registration here.
    # Remove custom logic—HACS will deploy the lovelace card and register the resource.

    # Create coordinator and proceed with normal setup
    coordinator = SavantEnergyCoordinator(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    
    # Get initial data before setting up platforms
    _LOGGER.info("Fetching initial data from Savant Energy controller")
    await coordinator.async_config_entry_first_refresh()
    
    if coordinator.data is None or not coordinator.data.get("snapshot_data"):
        _LOGGER.warning("Initial data fetch failed or returned no data - entities may be unavailable")
    
    # Register platforms
    _LOGGER.info("Setting up Savant Energy platforms")
    platforms = ["sensor", "switch", "button", "binary_sensor"]
    if not disable_scene_builder:
        platforms.append("scene")
    await hass.config_entries.async_forward_entry_setups(
        entry, platforms
    )
    
    # Ensure frontend resource registration
    if not disable_scene_builder:
        hass.async_create_task(_async_register_frontend_resource(hass))
    
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Unload a config entry and all associated platforms.
    """
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS + ["scene"])
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """
    Handle options update by reloading the config entry.
    """
    await hass.config_entries.async_reload(entry.entry_id)

# All classes and functions are now documented for clarity and open source maintainability.

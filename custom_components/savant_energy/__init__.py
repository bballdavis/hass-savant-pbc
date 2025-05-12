"""
Integration for Savant Energy.
Provides Home Assistant integration for Savant relay and energy monitoring devices.
"""

import logging
from datetime import timedelta, datetime
import shutil
import os
import traceback

import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from .const import DOMAIN, PLATFORMS, CONF_ADDRESS, CONF_PORT, CONF_SCAN_INTERVAL, DEFAULT_OLA_PORT
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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Set up Savant Energy from a config entry.
    Registers the coordinator and forwards setup to all platforms.
    Also handles Lovelace card installation and resource registration.
    """
    # Step 1: Copy the Lovelace card JS file
    card_copied_successfully = False
    resource_url = f"/local/{LOVELACE_CARD_FILENAME}"
    resource_type = "module"

    try:
        # Ensure www directory exists
        www_dir = hass.config.path("www")
        if not os.path.exists(www_dir):
            await hass.async_add_executor_job(os.makedirs, www_dir)
        
        # Copy the card file
        dest_path = os.path.join(www_dir, LOVELACE_CARD_FILENAME)
        src_path = os.path.join(os.path.dirname(__file__), LOVELACE_CARD_FILENAME)

        await hass.async_add_executor_job(shutil.copyfile, src_path, dest_path)
        _LOGGER.info(f"Copied Savant Energy Lovelace card to {dest_path}")
        card_copied_successfully = True
    except Exception as copy_exc:
        _LOGGER.error(f"Error copying Lovelace card: {copy_exc}\n{traceback.format_exc()}")
    
    # Step 2: Register the resource directly using the service call
    if card_copied_successfully:
        try:
            # Make absolutely sure the resource URL starts with /local/
            if not resource_url.startswith("/local/"):
                resource_url = f"/local/{LOVELACE_CARD_FILENAME}"

            _LOGGER.info(f"Attempting to register Lovelace resource: {resource_url}")

            # Check if the lovelace integration is loaded
            if "lovelace" not in hass.data:
                _LOGGER.warning("Lovelace integration not loaded yet, resource will need to be added manually")
            else:
                # Check if resource already exists to avoid duplicates
                resources_state = hass.states.get("lovelace.resources")
                resource_exists = False

                if resources_state and hasattr(resources_state, "attributes"):
                    resources = resources_state.attributes.get("resources", [])
                    _LOGGER.info(f"Found {len(resources)} existing Lovelace resources")
                    for resource in resources:
                        if resource.get("url") == resource_url:
                            _LOGGER.info(f"Resource already exists: {resource_url}")
                            resource_exists = True
                            break

                if not resource_exists:
                    # Add resource using service call
                    _LOGGER.info(f"Registering new Lovelace resource: {resource_url}")
                    services = hass.services.async_services()
                    if "lovelace" in services and "resources" in services.get("lovelace", {}):
                        try:
                            await hass.services.async_call(
                                "lovelace",
                                "resources",
                                {
                                    "url": resource_url,
                                    "resource_type": resource_type,
                                    "mode": "add"
                                },
                                blocking=True
                            )
                            _LOGGER.info(f"Successfully registered Lovelace resource: {resource_url}")
                        except Exception as service_exc:
                            _LOGGER.error(f"Service call failed: {service_exc}")
                            _LOGGER.warning("Please manually add the resource in Home Assistant UI")
                    else:
                        _LOGGER.warning("Lovelace resources service not available")
        except Exception as e:
            _LOGGER.warning(
                f"Could not register the Lovelace resource. "
                f"Please add it manually in Home Assistant UI: URL: {resource_url}, Type: {resource_type}. "
                f"Error: {e}"
            )
    
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
    await hass.config_entries.async_forward_entry_setups(
        entry, ["sensor", "switch", "button", "binary_sensor", "scene"]
    )
    
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

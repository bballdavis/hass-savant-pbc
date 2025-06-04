"""
Integration for Savant Energy.
Provides Home Assistant integration for Savant relay and energy monitoring devices.
"""

import logging
from datetime import timedelta, datetime
import os
import traceback

import homeassistant.helpers.config_validation as cv  # type: ignore
import voluptuous as vol  # type: ignore

from homeassistant.config_entries import ConfigEntry  # type: ignore
from homeassistant.core import HomeAssistant  # type: ignore
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator  # type: ignore
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry  # type: ignore
from homeassistant.helpers.translation import async_get_translations  # type: ignore
from homeassistant.components import frontend  # type: ignore

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_ADDRESS,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    DEFAULT_OLA_PORT,
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

# Lovelace card file information
LOVELACE_CARD_FILENAME = "savant-energy-scenes-card.js"


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
            name=DOMAIN,
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
                _LOGGER.error(
                    "Received no data from Savant controller - check connection settings"
                )
                return self.data  # Keep previous data rather than None

            if "presentDemands" not in snapshot_data:
                _LOGGER.error(
                    f"Missing 'presentDemands' in snapshot data: {snapshot_data}"
                )

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
                        _LOGGER.warning(
                            f"Incomplete device data: uid={has_uid}, name={has_name}, percentCommanded={has_percent}. Device: {device}"
                        )

            # Update DMX status for debugging if cache expired
            now = datetime.now()
            if (
                not self.dmx_last_update
                or (now - self.dmx_last_update).total_seconds() > DMX_CACHE_SECONDS
            ):
                _LOGGER.debug("Updating DMX status data for debugging purposes only")
                ola_port = self.config_entry.data.get("ola_port", DEFAULT_OLA_PORT)
                self.dmx_data = {}
                self.dmx_last_update = now

            return {"snapshot_data": snapshot_data, "dmx_data": self.dmx_data}
        except Exception as exc:
            _LOGGER.error(f"Error updating data: {exc}")
            raise


async def _async_register_frontend_resource(hass: HomeAssistant) -> None:
    """
    Register the custom Lovelace card using Home Assistant's proper frontend system.
    This is the correct way to register custom cards that other integrations use.
    """
    try:
        # Register the static path for serving the card file
        card_path = os.path.join(os.path.dirname(__file__), LOVELACE_CARD_FILENAME)
        
        # Use Home Assistant's HTTP component to register static path
        # This serves the file at /local/savant_energy/savant-energy-scenes-card.js
        local_path = f"/local/{DOMAIN}"
        
        # Try the new method first (HA 2024.7+)
        try:
            from homeassistant.components.http import StaticPathConfig
            await hass.http.async_register_static_paths([
                StaticPathConfig(local_path, os.path.dirname(__file__), True)
            ])
            resource_url = f"{local_path}/{LOVELACE_CARD_FILENAME}"
            _LOGGER.info(f"Registered static path for card using new method: {resource_url}")
        except (ImportError, AttributeError):
            # Fallback to legacy method
            hass.http.register_static_path(local_path, os.path.dirname(__file__), True)
            resource_url = f"{local_path}/{LOVELACE_CARD_FILENAME}"
            _LOGGER.info(f"Registered static path for card using legacy method: {resource_url}")
        
        # Register the JavaScript resource with Home Assistant's frontend
        frontend.add_extra_js_url(hass, resource_url)
        _LOGGER.info(f"Successfully registered Lovelace card resource: {resource_url}")
        
    except Exception as e:
        _LOGGER.error(f"Failed to register frontend resource: {e}")
        _LOGGER.exception("Full traceback:")


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Savant Energy component from yaml configuration."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Savant Energy from a config entry."""
    # Preload translations for the domain, making them available for UI flows and other parts of the integration
    await async_get_translations(hass, hass.config.language, DOMAIN)

    # Check for disable_scene_builder option
    disable_scene_builder = entry.options.get(
        "disable_scene_builder", entry.data.get("disable_scene_builder", False)
    )

    # Create coordinator and proceed with normal setup
    coordinator = SavantEnergyCoordinator(hass, entry)

    # Get initial data before setting up platforms
    _LOGGER.info("Fetching initial data from Savant Energy controller")
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    if coordinator.data is None or not coordinator.data.get("snapshot_data"):
        _LOGGER.warning(
            "Initial data fetch failed or returned no data - entities may be unavailable"
        )

    # Use PLATFORMS from const.py
    _LOGGER.info("Setting up Savant Energy platforms")
    setup_platforms = list(PLATFORMS)  # Make a copy to avoid modifying the original
    if not disable_scene_builder:
        setup_platforms.append("scene")

    await hass.config_entries.async_forward_entry_setups(entry, setup_platforms)

    # Register frontend resource after platforms are set up
    if not disable_scene_builder:
        await _async_register_frontend_resource(hass)

    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Use the same platform logic as in setup
    disable_scene_builder = entry.options.get(
        "disable_scene_builder", entry.data.get("disable_scene_builder", False)
    )

    unload_platforms = list(PLATFORMS)
    if not disable_scene_builder:
        unload_platforms.append("scene")

    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, unload_platforms
    )

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """
    Handle options update by reloading the config entry.
    """
    await hass.config_entries.async_reload(entry.entry_id)


# All classes and functions are now documented for clarity and open source maintainability.

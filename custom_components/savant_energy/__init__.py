"""Integration for Savant Energy."""

import logging
from datetime import timedelta, datetime

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


class SavantEnergyCoordinator(DataUpdateCoordinator):
    """Coordinator for Savant Energy data updates."""
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """Initialize the coordinator."""
        scan_interval = entry.options.get(
            CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, 15)
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.address = entry.data[CONF_ADDRESS]
        self.port = entry.data[CONF_PORT]
        self.config_entry = entry  # Store config entry directly
        self.dmx_data = {}  # Will contain mapping of channel -> status
        self.dmx_last_update = None

    async def _async_update_data(self):
        """Fetch data from API endpoints."""
        # Get snapshot data from energy controller
        snapshot_data = await self.hass.async_add_executor_job(
            get_current_energy_snapshot, self.address, self.port
        )
        
        # Continue to get DMX status (for logging/debugging purposes only)
        # but don't rely on it for device status
        now = datetime.now()
        if (not self.dmx_last_update or 
            (now - self.dmx_last_update).total_seconds() > DMX_CACHE_SECONDS):
            _LOGGER.debug("Updating DMX status data for debugging purposes only")
            
            # We no longer extract channels from snapshot data since we're using DMX addresses instead
            
            # Get OLA port from config entry or use default
            ola_port = self.config_entry.data.get("ola_port", DEFAULT_OLA_PORT)
              # Since we don't track channels anymore, we reset the dmx_data
            self.dmx_data = {}
            self.dmx_last_update = now
        
        # Return full data with snapshot and dmx data
        return {
            "snapshot_data": snapshot_data,
            "dmx_data": self.dmx_data
        }


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Savant Energy from a config entry."""
    coordinator = SavantEnergyCoordinator(hass, entry)
    
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Forward the config entry setup to the platforms
    await hass.config_entries.async_forward_entry_setups(
        entry, ["sensor", "switch", "button", "binary_sensor"]
    )

    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)

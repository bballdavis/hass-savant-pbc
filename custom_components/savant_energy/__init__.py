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
    
    def __init__(self, hass: HomeAssistant, address: str, port: int, scan_interval: int):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.address = address
        self.port = port
        self._config_entry = None
        self.dmx_data = {}  # Will contain mapping of channel -> status
        self.device_channel_map = {}  # Maps device UID -> channel for lookup
        self.dmx_last_update = None

    @property
    def config_entry(self) -> ConfigEntry:
        """Return the config entry."""
        return self._config_entry
    
    @config_entry.setter
    def config_entry(self, entry: ConfigEntry) -> None:
        """Set the config entry."""
        self._config_entry = entry

    async def _async_update_data(self):
        """Fetch data from API endpoints."""
        # Get snapshot data from energy controller
        snapshot_data = await self.hass.async_add_executor_job(
            get_current_energy_snapshot, self.address, self.port
        )
        
        # Get DMX status for all devices in one batch
        now = datetime.now()
        if (not self.dmx_last_update or 
            (now - self.dmx_last_update).total_seconds() > DMX_CACHE_SECONDS):
            _LOGGER.warning(f"Updating DMX status data for all devices")
            
            # Extract all device channels from snapshot data
            if snapshot_data and "presentDemands" in snapshot_data:
                # Collect channels from both snapshot data and existing channel sensors
                dmx_channels = set()  # Use a set to avoid duplicates
                device_channel_map = {}
                
                # First, extract channels from snapshot data
                for device in snapshot_data["presentDemands"]:
                    uid = device["uid"]
                    channel = device.get("channel")
                    
                    if channel is not None:
                        try:
                            # Convert to integer to ensure proper handling
                            dmx_channels.add(int(channel))
                            device_channel_map[uid] = int(channel)
                        except (ValueError, TypeError):
                            _LOGGER.warning(f"Invalid channel value for device {uid}: {channel}")
                    else:
                        _LOGGER.warning(f"No channel information for device {uid} in snapshot data")
                
                # Second, try to look up any channel sensors that might have channel info
                if self.hass:
                    for entity_id in self.hass.states.async_entity_ids("sensor"):
                        if "_channel" in entity_id and DOMAIN in entity_id:
                            state = self.hass.states.get(entity_id)
                            if state and state.state not in ('unknown', 'unavailable', ''):
                                try:
                                    channel = int(state.state)
                                    dmx_channels.add(channel)
                                    _LOGGER.debug(f"Added channel {channel} from sensor {entity_id}")
                                except (ValueError, TypeError):
                                    _LOGGER.warning(f"Invalid channel value in sensor {entity_id}: {state.state}")
                
                # Get OLA port from config entry or use default
                ola_port = self.config_entry.data.get("ola_port", DEFAULT_OLA_PORT) if self.config_entry else DEFAULT_OLA_PORT
                
                # Retrieve DMX status for all channels in one request
                if dmx_channels:
                    self.dmx_data = await async_get_all_dmx_status(
                        self.address, list(dmx_channels), ola_port
                    )
                    self.device_channel_map = device_channel_map
                    self.dmx_last_update = now
                    
                    # Log the results
                    #_LOGGER.warning(f"Updated DMX data for {len(dmx_channels)} channels: {self.dmx_data}")
                else:
                    _LOGGER.warning("No devices with valid channel information found, skipping DMX update")
        
        # Return combined data
        result = {
            "snapshot_data": snapshot_data, 
            "dmx_data": self.dmx_data,
            "device_channel_map": self.device_channel_map
        }
        return result


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Savant Energy from a config entry."""
    address = entry.data[CONF_ADDRESS]
    port = entry.data[CONF_PORT]
    scan_interval = entry.options.get(
        CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, 15)
    )

    coordinator = SavantEnergyCoordinator(hass, address, port, scan_interval)
    coordinator.config_entry = entry  # Store config entry in coordinator
    
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

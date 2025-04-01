"""Integration for Savant Energy."""

import logging
from datetime import timedelta

import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from .const import DOMAIN, PLATFORMS, CONF_ADDRESS, CONF_PORT, CONF_SCAN_INTERVAL
from .snapshot_data import get_current_energy_snapshot

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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Savant Energy from a config entry."""
    address = entry.data[CONF_ADDRESS]
    port = entry.data[CONF_PORT]
    scan_interval = entry.options.get(
        CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, 15)
    )

    async def async_update_data():
        """Fetch data from API endpoint."""
        return await hass.async_add_executor_job(
            get_current_energy_snapshot, address, port
        )

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=timedelta(seconds=scan_interval),
    )

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

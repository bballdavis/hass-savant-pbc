"""Sensor platform for Energy Snapshot."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from . import EnergyDeviceSensor

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Energy Snapshot sensor entities."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities = []
    if coordinator.data and isinstance(coordinator.data, dict) and "presentDemands" in coordinator.data:
        for device in coordinator.data["presentDemands"]:
            entities.append(EnergyDeviceSensor(coordinator, device))

    async_add_entities(entities)
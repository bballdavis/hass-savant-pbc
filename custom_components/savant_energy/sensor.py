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

class EnergyDeviceSensor(CoordinatorEntity, SensorEntity):
    """Representation of an Energy Snapshot Sensor."""

    def __init__(self, coordinator, device):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device = device
        self._attr_name = f"{device['name']} Demand"
        self._attr_unique_id = f"{DOMAIN}_{device['id']}_demand"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device['id']))},
            name=device['name'],
        )
        self._attr_native_unit_of_measurement = "kW"  # Adjust as needed
        self._attr_state_class = "measurement" # adjust as needed

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.coordinator.data and "presentDemands" in self.coordinator.data:
            for device in self.coordinator.data["presentDemands"]:
                if device['id'] == self._device['id']:
                    return device['demand']
        return None
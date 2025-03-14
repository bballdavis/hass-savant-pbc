"""Switch platform for Energy Snapshot."""
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from . import EnergyDeviceSwitch

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Energy Snapshot switch entities."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities = []
    if coordinator.data and isinstance(coordinator.data, dict) and "presentDemands" in coordinator.data:
        for device in coordinator.data["presentDemands"]:
            entities.append(EnergyDeviceSwitch(coordinator, device))

    async_add_entities(entities)

class EnergyDeviceSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of an Energy Snapshot Switch."""

    def __init__(self, coordinator, device):
        """Initialize the switch."""
        super().__init__(coordinator)
        self._device = device
        self._attr_name = f"{device['name']} Switch"
        self._attr_unique_id = f"{DOMAIN}_{device['id']}_switch"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device['id']))},
            name=device['name'],
        )
        self._attr_is_on = False # Default state. Change as needed.

    @property
    def is_on(self):
        """Return the state of the switch."""
        # Replace with the actual logic to get the switch state from your device
        # For example, you might need to query the device through the coordinator
        # and update self._attr_is_on accordingly.
        return self._attr_is_on

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        # Replace with the actual logic to turn the switch on in your device
        # For example, you might need to send a command to the device through the coordinator.
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        # Replace with the actual logic to turn the switch off in your device
        # For example, you might need to send a command to the device through the coordinator.
        self._attr_is_on = False
        self.async_write_ha_state()
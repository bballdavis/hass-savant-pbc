"""Switch platform for Energy Snapshot."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.core import HomeAssistant, callback
import logging

_LOGGER = logging.getLogger(__name__)

from ..custom_components.savant_energy.const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    """Set up Energy Snapshot switch entities."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities = []
    if (
        coordinator.data
        and isinstance(coordinator.data, dict)
        and "presentDemands" in coordinator.data
    ):
        for device in coordinator.data["presentDemands"]:
            entities.append(EnergyDeviceSwitch(hass, coordinator, device))

    async_add_entities(entities)


class EnergyDeviceSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of an Energy Snapshot Switch."""

    def __init__(self, hass: HomeAssistant, coordinator, device):
        """Initialize the switch."""
        super().__init__(coordinator)
        self._hass = hass
        self._device = device
        self._attr_name = f"{device['name']} Switch"
        self._attr_unique_id = f"{DOMAIN}_{device['uid']}_switch"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device["uid"]))},
            name=device["name"],
        )
        self._sensor_entity_id = f"sensor.{device['name'].lower()}_relay_status"
        self._attr_is_on = self._get_initial_state()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    def _get_initial_state(self) -> bool:
        """Get the initial state of the switch from the relay_status sensor."""
        state = self._hass.states.get(self._sensor_entity_id)
        if state:
            _LOGGER.debug("[_get_initial_state] relay_status value: %s", state.state)
            return state.state == "on"
        return False

    @property
    def is_on(self) -> bool:
        """Return the state of the switch."""
        return self._attr_is_on

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        if not self.is_on:
            # Add the actual API call to turn the switch on
            # For example, you might need to send a command to the device through the coordinator.
            self._attr_is_on = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        if self.is_on:
            # Add the actual API call to turn the switch off
            # For example, you might need to send a command to the device through the coordinator.
            self._attr_is_on = False
            self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        state = self._hass.states.get(self._sensor_entity_id)
        if state:
            self._attr_is_on = state.state == "on"
        else:
            self._attr_is_on = False
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True if the entity is available."""
        return (
            self.coordinator.data is not None
            and "presentDemands" in self.coordinator.data
        )

"""Binary sensor platform for Energy Snapshot integration."""

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .sensor import calculate_dmx_uid, get_device_model

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Energy Snapshot binary sensor entities."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities = []
    if (
        coordinator.data
        and isinstance(coordinator.data, dict)
        and "presentDemands" in coordinator.data
    ):
        for device in coordinator.data["presentDemands"]:
            uid = device["uid"]
            dmx_uid = calculate_dmx_uid(uid)
            entities.append(
                EnergyDeviceBinarySensor(
                    coordinator, device, f"SavantEnergy_{uid}_relay_status", dmx_uid
                )
            )

    async_add_entities(entities)


class EnergyDeviceBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of an Energy Snapshot Binary Sensor."""

    def __init__(self, coordinator, device, unique_id, dmx_uid):
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._device = device
        self._attr_name = f"{device['name']} Relay Status"
        self._attr_unique_id = unique_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device["uid"]))},
            name=device["name"],
            serial_number=dmx_uid,  # Set DMX UID as the serial number
            manufacturer="Savant",
            model=get_device_model(device.get("capacity", 0)),  # Determine model
        )

    @property
    def is_on(self) -> bool | None:
        """Return true if the relay status is on."""
        if self.coordinator.data and "presentDemands" in self.coordinator.data:
            for device in self.coordinator.data["presentDemands"]:
                if device["uid"] == self._device["uid"]:
                    value = device.get("percentCommanded")
                    if isinstance(value, int):
                        return value == 100  # Relay is on if percentCommanded is 100
                    return None
        return None

    @property
    def available(self) -> bool:
        """Return True if the entity is available."""
        return (
            self.coordinator.data is not None
            and "presentDemands" in self.coordinator.data
        )

    @property
    def icon(self) -> str:
        """Return the icon for the binary sensor."""
        return "mdi:toggle-switch-outline"

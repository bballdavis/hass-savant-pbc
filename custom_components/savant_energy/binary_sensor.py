"""Binary sensor platform for Energy Snapshot integration."""

import logging
from datetime import datetime, timedelta
from typing import Optional, Final

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.core import callback

from .const import DOMAIN, MANUFACTURER, DEFAULT_OLA_PORT
from .models import get_device_model
# Import with explicit name to verify we're using the right function
from .utils import calculate_dmx_uid, DMX_CACHE_SECONDS

_LOGGER = logging.getLogger(__name__)
_LOGGER.warning("Savant Energy binary_sensor module loaded")


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Energy Snapshot binary sensor entities."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities = []
    snapshot_data = coordinator.data.get("snapshot_data", {})
    if (
        snapshot_data
        and isinstance(snapshot_data, dict)
        and "presentDemands" in snapshot_data
    ):
        for device in snapshot_data["presentDemands"]:
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
        self._dmx_uid = dmx_uid  # Still store for device info
        self._device_uid = device["uid"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device["uid"]))},
            name=device["name"],
            serial_number=dmx_uid,  # Set DMX UID as the serial number
            manufacturer=MANUFACTURER,
            model=get_device_model(device.get("capacity", 0)),  # Determine model
        )

    @property
    def is_on(self) -> Optional[bool]:
        """Return true if the relay status is on, based solely on presentDemands data."""
        # Only use snapshot_data for state determination - ignore DMX data
        snapshot_data = self.coordinator.data.get("snapshot_data", {})
        if snapshot_data and "presentDemands" in snapshot_data:
            for device in snapshot_data["presentDemands"]:
                if device["uid"] == self._device_uid:
                    if "percentCommanded" in device:
                        return device["percentCommanded"] == 100
        return None

    @property
    def available(self) -> bool:
        """Return True if the entity is available."""
        # We're available if we have coordinator data with the device in it
        snapshot_data = self.coordinator.data.get("snapshot_data", {})
        if not snapshot_data or "presentDemands" not in snapshot_data:
            return False
            
        # Check if our device exists in the presentDemands data
        for device in snapshot_data["presentDemands"]:
            if device["uid"] == self._device_uid:
                return "percentCommanded" in device
        
        return False

    @property
    def icon(self) -> str:
        """Return the icon for the binary sensor."""
        return "mdi:toggle-switch-outline"

"""
Binary sensor platform for Savant Energy integration.
Creates binary sensors for relay status of each Savant device.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Final

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.core import callback

from .const import DOMAIN, MANUFACTURER, DEFAULT_OLA_PORT
from .models import get_device_model
from .utils import calculate_dmx_uid, DMX_CACHE_SECONDS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """
    Set up Savant Energy binary sensor entities.
    Creates a binary sensor for each relay device found in presentDemands.
    """
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
    """
    Representation of a Savant relay status as a binary sensor.
    Shows ON if the relay is commanded ON, OFF otherwise.
    """
    def __init__(self, coordinator, device, unique_id, dmx_uid):
        """
        Initialize the binary sensor.
        Args:
            coordinator: DataUpdateCoordinator
            device: Device dict from presentDemands
            unique_id: Unique entity ID
            dmx_uid: DMX UID for device
        """
        super().__init__(coordinator)
        self._device = device
        self._attr_name = f"{device['name']} Relay Status"
        self._attr_unique_id = unique_id
        self._dmx_uid = dmx_uid
        self._device_uid = device["uid"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device["uid"]))},
            name=device["name"],
            serial_number=dmx_uid,
            manufacturer=MANUFACTURER,
            model=get_device_model(device.get("capacity", 0)),
        )

    @property
    def is_on(self) -> Optional[bool]:
        """
        Return True if the relay is ON, based on percentCommanded == 100.
        """
        snapshot_data = self.coordinator.data.get("snapshot_data", {})
        if snapshot_data and "presentDemands" in snapshot_data:
            for device in snapshot_data["presentDemands"]:
                if device["uid"] == self._device_uid:
                    if "percentCommanded" in device:
                        return device["percentCommanded"] == 100
        return None

    @property
    def available(self) -> bool:
        """
        Return True if the entity is available (device present in snapshot).
        """
        snapshot_data = self.coordinator.data.get("snapshot_data", {})
        if not snapshot_data or "presentDemands" not in snapshot_data:
            return False
        for device in snapshot_data["presentDemands"]:
            if device["uid"] == self._device_uid:
                return "percentCommanded" in device
        return False

    @property
    def icon(self) -> str:
        """
        Return the icon for the binary sensor.
        """
        return "mdi:toggle-switch-outline"

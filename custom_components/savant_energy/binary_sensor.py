"""
Binary sensor platform for Savant Energy integration.
Creates binary sensors for relay status of each Savant device.
"""

import logging
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .models import get_device_model
from .utils import calculate_dmx_uid

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """
    Set up Savant Energy binary sensor entities for relay status.
    """
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    await coordinator.async_config_entry_first_refresh()
    snapshot_data = coordinator.data.get("snapshot_data", {}) if coordinator.data else {}
    entities = []
    if snapshot_data and "presentDemands" in snapshot_data:
        for device in snapshot_data["presentDemands"]:
            if "uid" in device and "percentCommanded" in device:
                uid = device["uid"]
                dmx_uid = calculate_dmx_uid(uid)
                entities.append(
                    EnergyDeviceBinarySensor(coordinator, device, f"SavantEnergy_{uid}_relay_status", dmx_uid)
                )
    async_add_entities(entities)


class EnergyDeviceBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """
    Representation of a Savant relay status as a binary sensor.
    Shows ON if the relay is commanded ON, OFF otherwise.
    """
    def __init__(self, coordinator, device, unique_id, dmx_uid):
        super().__init__(coordinator)
        self._device_uid = device["uid"]
        self._attr_unique_id = unique_id
        self._dmx_uid = dmx_uid
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device["uid"]))},
            name=device.get("name", f"Savant Device {device['uid']}"),
            serial_number=dmx_uid,
            manufacturer=MANUFACTURER,
            model=get_device_model(device.get("capacity", 0)),
        )
        self._attr_extra_state_attributes = {"uid": self._device_uid}

    @property
    def name(self):
        # Always use the latest name from coordinator data if available
        snapshot_data = self.coordinator.data.get("snapshot_data", {})
        if snapshot_data and "presentDemands" in snapshot_data:
            for device in snapshot_data["presentDemands"]:
                if device["uid"] == self._device_uid:
                    return f"{device.get('name', self._device_uid)} Relay Status"
        return f"Relay {self._device_uid} Status"

    @property
    def is_on(self):
        """
        Return True if the relay is ON, based on percentCommanded == 100.
        """
        snapshot_data = self.coordinator.data.get("snapshot_data", {})
        if snapshot_data and "presentDemands" in snapshot_data:
            for device in snapshot_data["presentDemands"]:
                if device["uid"] == self._device_uid:
                    return device.get("percentCommanded") == 100
        return None

    @property
    def available(self):
        """
        Return True if the entity is available (device present in snapshot).
        """
        if not self.coordinator.last_update_success:
            return False
        snapshot_data = self.coordinator.data.get("snapshot_data", {})
        if not snapshot_data or "presentDemands" not in snapshot_data:
            return False
        for device in snapshot_data["presentDemands"]:
            if device["uid"] == self._device_uid and "percentCommanded" in device:
                return True
        return False

    @property
    def icon(self):
        return "mdi:toggle-switch-outline"

    @property
    def device_info(self) -> DeviceInfo:
        """
        Return dynamic DeviceInfo with the current device name.
        """
        snapshot_data = self.coordinator.data.get("snapshot_data", {})
        device_name = self._device["name"]
        if snapshot_data and "presentDemands" in snapshot_data:
            for device in snapshot_data["presentDemands"]:
                if device["uid"] == self._device["uid"]:
                    device_name = device["name"]
                    break
        return DeviceInfo(
            identifiers={(DOMAIN, str(self._device["uid"]))},
            name=device_name,
            serial_number=self._dmx_uid,
            manufacturer=MANUFACTURER,
            model=get_device_model(self._device.get("capacity", 0)),
        )

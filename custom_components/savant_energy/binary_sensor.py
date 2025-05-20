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
        # Store initial name and capacity for fallbacks and consistent DeviceInfo
        self._initial_name = device.get("name", f"Savant Device {self._device_uid}")
        self._initial_capacity = device.get("capacity", 0)

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(self._device_uid))},
            name=self._initial_name,  # Use stored initial name
            serial_number=self._dmx_uid,
            manufacturer=MANUFACTURER,
            model=get_device_model(self._initial_capacity),  # Use stored initial capacity
        )
        self._attr_extra_state_attributes = {"uid": self._device_uid}

    @property
    def name(self):
        # Always use the latest name from coordinator data if available
        snapshot_data = self.coordinator.data.get("snapshot_data", {}) if self.coordinator.data else {}
        device_name_from_coordinator = None
        if snapshot_data and "presentDemands" in snapshot_data and isinstance(snapshot_data["presentDemands"], list):
            for dev_in_snapshot in snapshot_data["presentDemands"]:
                if dev_in_snapshot.get("uid") == self._device_uid:
                    device_name_from_coordinator = dev_in_snapshot.get("name")
                    break
        
        base_name = device_name_from_coordinator or self._initial_name
        return f"{base_name} Relay Status"

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

        if not self.coordinator.data:
            return False
            
        snapshot_data = self.coordinator.data.get("snapshot_data", {})
        if not snapshot_data:
            return False

        if "presentDemands" not in snapshot_data or not isinstance(snapshot_data.get("presentDemands"), list):
            return False
        
        if not snapshot_data["presentDemands"]:
            return False

        for device_in_list in snapshot_data["presentDemands"]:
            if device_in_list.get("uid") == self._device_uid:
                if "percentCommanded" in device_in_list:
                    return True
        
        return False

    @property
    def icon(self):
        return "mdi:toggle-switch-outline"

    @property
    def device_info(self) -> DeviceInfo:
        """
        Return dynamic DeviceInfo with the current device name and model.
        """
        current_name_val = self._initial_name  # Default to initial name
        current_capacity_val = self._initial_capacity  # Default to initial capacity

        snapshot_data = self.coordinator.data.get("snapshot_data", {}) if self.coordinator.data else {}
        if snapshot_data and "presentDemands" in snapshot_data and isinstance(snapshot_data["presentDemands"], list):
            for device_in_snapshot in snapshot_data["presentDemands"]:
                if device_in_snapshot.get("uid") == self._device_uid:
                    current_name_val = device_in_snapshot.get("name", self._initial_name)
                    current_capacity_val = device_in_snapshot.get("capacity", self._initial_capacity)
                    break
        
        return DeviceInfo(
            identifiers={(DOMAIN, str(self._device_uid))},
            name=current_name_val,
            serial_number=self._dmx_uid,
            manufacturer=MANUFACTURER,
            model=get_device_model(current_capacity_val),
        )

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
    _LOGGER.info("Starting async_setup_entry for savant_energy binary_sensor platform.") # Added log
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
        entity_id_for_log = self._attr_unique_id or f"UID_{self._device_uid}"
        _LOGGER.debug(f"[{entity_id_for_log}] Checking availability for device UID: {self._device_uid}")

        if not self.coordinator.last_update_success:
            _LOGGER.debug(f"[{entity_id_for_log}] Coordinator last update was not successful. Available: False")
            return False

        if not self.coordinator.data:
            _LOGGER.debug(f"[{entity_id_for_log}] Coordinator data is None. Available: False")
            return False
            
        snapshot_data = self.coordinator.data.get("snapshot_data", {})
        if not snapshot_data:
            _LOGGER.debug(f"[{entity_id_for_log}] Snapshot data is empty. Available: False")
            return False

        if "presentDemands" not in snapshot_data or not isinstance(snapshot_data.get("presentDemands"), list):
            _LOGGER.debug(f"[{entity_id_for_log}] 'presentDemands' is missing or not a list in snapshot_data. Available: False. Data: {snapshot_data.get('presentDemands')}")
            return False
        
        if not snapshot_data["presentDemands"]:
            _LOGGER.debug(f"[{entity_id_for_log}] 'presentDemands' is empty. Available: False")
            return False

        # To see the data being searched, you can uncomment the following line, but be cautious if the data is very large.
        # _LOGGER.debug(f"[{entity_id_for_log}] Searching for UID '{self._device_uid}' in presentDemands: {snapshot_data['presentDemands']}")

        for i, device_in_list in enumerate(snapshot_data["presentDemands"]):
            current_device_uid = device_in_list.get("uid")
            # Check if the current device in the list matches our target UID
            if current_device_uid == self._device_uid:
                _LOGGER.debug(f"[{entity_id_for_log}] Found matching UID '{self._device_uid}' in presentDemands at index {i}.")
                # Now check if 'percentCommanded' is present for this specific device
                if "percentCommanded" in device_in_list:
                    _LOGGER.debug(f"[{entity_id_for_log}] 'percentCommanded' key IS PRESENT. Value: {device_in_list['percentCommanded']}. Entity available: True")
                    return True
                else:
                    # Device found, but 'percentCommanded' is missing.
                    # According to the original logic, this specific entry doesn't make the entity available.
                    # The loop would continue, but if this is the only entry for this UID, it will become unavailable.
                    _LOGGER.debug(f"[{entity_id_for_log}] 'percentCommanded' key IS MISSING for device UID '{self._device_uid}'. This specific entry does not make it available.")
                    # To strictly make it unavailable if the matched device is incomplete:
                    # return False
                    # However, to maintain original behavior (in case of multiple entries for same UID, though unlikely):
                    # We continue, and if no *complete* entry is found, it will fall through to return False.
                    # For unique UIDs, this means if the key is missing, it will eventually be False.

        _LOGGER.debug(f"[{entity_id_for_log}] Device UID '{self._device_uid}' not found in presentDemands with 'percentCommanded' key, or 'presentDemands' list did not yield a match. Entity available: False")
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

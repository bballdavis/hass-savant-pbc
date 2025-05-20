"""Energy Device Sensor for Savant Energy.
Provides power and voltage sensor entities for each relay device.

All classes and functions are now documented for clarity and open source maintainability.
"""

import logging
from typing import Any, Optional

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .models import get_device_model
from .utils import slugify

_LOGGER = logging.getLogger(__name__)


class EnergyDeviceSensor(CoordinatorEntity, SensorEntity):
    """
    Representation of a Savant Energy Sensor (power or voltage).
    """
    def __init__(self, coordinator, device, sensor_type, unique_id, dmx_uid):
        """
        Initialize the sensor.
        Args:
            coordinator: DataUpdateCoordinator
            device: Device dict from presentDemands
            sensor_type: 'power' or 'voltage'
            unique_id: Unique entity ID
            dmx_uid: DMX UID for device
        """
        super().__init__(coordinator)
        self._device = device
        self._sensor_type = sensor_type
        self._attr_name = f"{device['name']} {sensor_type.capitalize()}"
        self._slug_name = slugify(device["name"])
        self._attr_unique_id = unique_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device["uid"]))},
            name=device["name"],
            serial_number=dmx_uid,
            manufacturer=MANUFACTURER,
            model=get_device_model(device.get("capacity", 0)),
        )
        self._attr_native_unit_of_measurement = self._get_unit_of_measurement(sensor_type)
        self._dmx_uid = dmx_uid

    @property
    def name(self) -> str:
        """
        Return the dynamic friendly name for the entity, based on the current device name.
        """
        # Try to get the latest device name from coordinator data
        snapshot_data = self.coordinator.data.get("snapshot_data", {})
        device_name = self._device["name"]
        if snapshot_data and "presentDemands" in snapshot_data:
            for device in snapshot_data["presentDemands"]:
                if device["uid"] == self._device["uid"]:
                    device_name = device["name"]
                    break
        return f"{device_name} {self._sensor_type.capitalize()}"

    def _get_unit_of_measurement(self, sensor_type: str) -> str | None:
        """
        Return the unit of measurement for the sensor type.
        """
        match sensor_type:
            case "voltage":
                return "V"
            case "power":
                return "W"
            case _:
                return None

    @property
    def _current_device_name(self):
        """
        Fetch the current device name by UID from coordinator data.
        """
        snapshot_data = self.coordinator.data.get("snapshot_data", {})
        if snapshot_data and "presentDemands" in snapshot_data:
            for device in snapshot_data["presentDemands"]:
                if device["uid"] == self._device["uid"]:
                    return device["name"]
        return self._device["name"]

    # Do NOT override entity_id. Home Assistant manages entity_id and expects it to be settable.
    # Only the name property is dynamic, so the UI/friendly_name updates on device rename.
    # unique_id remains stable and is used for entity tracking.
    @property
    def name(self):
        """
        Return the name of the sensor using the latest device name.
        """
        return f"{self._current_device_name} {self._sensor_type.capitalize()}"

    @property
    def state_class(self) -> SensorStateClass | None:
        """
        Return the state class of the sensor (always MEASUREMENT).
        """
        return SensorStateClass.MEASUREMENT

    @property
    def device_class(self) -> str | None:
        """
        Return the device class of the sensor (POWER or VOLTAGE).
        """
        match self._sensor_type:
            case "power":
                return SensorDeviceClass.POWER
            case "voltage":
                return SensorDeviceClass.VOLTAGE
            case _:
                return None

    @property
    def native_value(self) -> float | None:
        """
        Return the state of the sensor (power in W, voltage in V).
        """
        snapshot_data = self.coordinator.data.get("snapshot_data", {})
        if snapshot_data and "presentDemands" in snapshot_data:
            for device in snapshot_data["presentDemands"]:
                if device["uid"] == self._device["uid"]:
                    value = device.get(self._sensor_type)
                    if self._sensor_type == "power" and value is not None:
                        try:
                            return round(float(value) * 1000.0)
                        except (ValueError, TypeError):
                            _LOGGER.error(
                                "Invalid power value %s for device %s", 
                                value, device["uid"]
                            )
                            return None
                    if value is not None:
                        try:
                            return float(value)
                        except (ValueError, TypeError):
                            return value
        return None

    @property
    def icon(self) -> str:
        """
        Return the icon for the sensor.
        """
        match self._sensor_type:
            case "voltage":
                return "mdi:flash"
            case "power":
                return "mdi:lightning-bolt"
            case _:
                return "mdi:gauge"

    @property
    def available(self) -> bool:
        """
        Return True if the sensor is available (device present in snapshot).
        """
        snapshot_data = self.coordinator.data.get("snapshot_data", {})
        if not snapshot_data or "presentDemands" not in snapshot_data:
            return False
        for device in snapshot_data["presentDemands"]:
            if device["uid"] == self._device["uid"]:
                return self._sensor_type in device
        return False

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

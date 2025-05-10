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

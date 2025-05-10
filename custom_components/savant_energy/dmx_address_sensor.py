"""DMX Address Sensor for Savant Energy.
Provides a sensor entity that shows the DMX address for each relay device.

All classes and functions are now documented for clarity and open source maintainability.
"""

import logging
from typing import Any, Optional

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .models import get_device_model
from .utils import async_get_dmx_address

_LOGGER = logging.getLogger(__name__)


class DMXAddressSensor(CoordinatorEntity, SensorEntity):
    """
    Representation of the DMX Address Sensor.
    Shows the DMX address assigned to a Savant relay device.
    """
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, device, unique_id, dmx_uid):
        """
        Initialize the DMX Address sensor.
        Args:
            coordinator: DataUpdateCoordinator
            device: Device dict from presentDemands
            unique_id: Unique entity ID
            dmx_uid: DMX UID for device
        """
        super().__init__(coordinator)
        self._device = device
        self._attr_name = f"{device['name']} DMX Address"
        self._attr_unique_id = unique_id
        self._dmx_uid = dmx_uid
        self._dmx_address = None  # Will be populated on first update
        self._attr_native_unit_of_measurement = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device["uid"]))},
            name=device["name"],
            serial_number=dmx_uid,
            manufacturer=MANUFACTURER,
            model=get_device_model(device.get("capacity", 0)),
        )

    async def async_added_to_hass(self):
        """
        Called when entity is added to Home Assistant.
        Fetches the DMX address from the API.
        """
        await super().async_added_to_hass()
        await self._fetch_dmx_address()

    async def _fetch_dmx_address(self):
        """
        Fetch the DMX address from the OLA/DMX API.
        Updates the sensor state if successful.
        """
        if not self.coordinator.config_entry:
            _LOGGER.warning(f"No config entry available for {self.name}")
            return
        ip_address = self.coordinator.config_entry.data.get("address")
        ola_port = self.coordinator.config_entry.data.get("ola_port", 9090)
        if not ip_address:
            _LOGGER.warning(f"No IP address available for {self.name}")
            return
        universe = 1  # Default universe
        address = await async_get_dmx_address(ip_address, ola_port, universe, self._dmx_uid)
        if address is not None:
            self._dmx_address = address
            self.async_write_ha_state()
            _LOGGER.info(f"Updated DMX address for {self.name}: {address}")
        else:
            _LOGGER.warning(f"Failed to fetch DMX address for {self.name}")

    @property
    def native_value(self):
        """
        Return the DMX address (int) or None if not available.
        """
        return self._dmx_address

    @property
    def icon(self):
        """
        Return the icon for the DMX address sensor.
        """
        return "mdi:identifier"

    @property
    def available(self):
        """
        Return True if the DMX address is available.
        """
        return self._dmx_address is not None

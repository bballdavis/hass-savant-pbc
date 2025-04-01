"""Binary sensor platform for Energy Snapshot integration."""

import logging
from datetime import datetime, timedelta
import aiohttp
import asyncio
from typing import Final, ClassVar

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .sensor import calculate_dmx_uid, get_device_model

_LOGGER = logging.getLogger(__name__)

# DMX API constants
DMX_PORT: Final = 9090
DMX_ON_VALUE: Final = 255
DMX_OFF_VALUE: Final = 0
DMX_CACHE_SECONDS: Final = 30
DMX_API_TIMEOUT: Final = 30  # Time in seconds to consider API down


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

    # Class variables to track DMX API status across all instances
    _last_successful_api_call: ClassVar[datetime | None] = None
    _api_failure_count: ClassVar[int] = 0
    _api_request_count: ClassVar[int] = 0

    def __init__(self, coordinator, device, unique_id, dmx_uid):
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._device = device
        self._attr_name = f"{device['name']} Relay Status"
        self._attr_unique_id = unique_id
        self._dmx_uid = dmx_uid
        self._dmx_status = None
        self._dmx_last_update = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device["uid"]))},
            name=device["name"],
            serial_number=dmx_uid,  # Set DMX UID as the serial number
            manufacturer="Savant",
            model=get_device_model(device.get("capacity", 0)),  # Determine model
        )

    async def async_update(self) -> None:
        """Update the entity."""
        await super().async_update()
        # Try to fetch the DMX status
        await self._update_dmx_status()

    async def _update_dmx_status(self) -> None:
        """Update the DMX status via HTTP request."""
        # Check if we need to update the cached value
        now = datetime.now()
        if self._dmx_last_update is None or now - self._dmx_last_update > timedelta(
            seconds=DMX_CACHE_SECONDS
        ):
            # Get IP address from config entry
            ip_address = self.coordinator.config_entry.data.get("address")
            if not ip_address:
                _LOGGER.debug("No IP address available for DMX request")
                return

            url = f"http://{ip_address}:{DMX_PORT}/get_dmx?u={self._dmx_uid}"

            try:
                # Increment request counter
                EnergyDeviceBinarySensor._api_request_count += 1

                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=10) as response:
                        if response.status == 200:
                            data = await response.text()
                            try:
                                value = int(data.strip())
                                self._dmx_status = value == DMX_ON_VALUE
                                self._dmx_last_update = now

                                # Update API status tracking
                                EnergyDeviceBinarySensor._last_successful_api_call = now

                                _LOGGER.debug(
                                    "DMX status for %s: %s",
                                    self._dmx_uid,
                                    self._dmx_status,
                                )
                            except ValueError:
                                _LOGGER.debug("Invalid DMX response format: %s", data)
                                EnergyDeviceBinarySensor._api_failure_count += 1
                        else:
                            _LOGGER.debug(
                                "DMX request failed with status %s", response.status
                            )
                            EnergyDeviceBinarySensor._api_failure_count += 1
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                _LOGGER.debug("Error making DMX request: %s", err)
                EnergyDeviceBinarySensor._api_failure_count += 1
            except Exception as err:
                _LOGGER.debug("Unexpected error in DMX request: %s", err)
                EnergyDeviceBinarySensor._api_failure_count += 1

    @property
    def is_on(self) -> bool | None:
        """Return true if the relay status is on."""
        # First try to use DMX status if available and recent
        if self._dmx_status is not None and self._dmx_last_update is not None:
            if datetime.now() - self._dmx_last_update <= timedelta(
                seconds=DMX_CACHE_SECONDS
            ):
                return self._dmx_status

        # Fall back to the existing method using coordinator data
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
        # We're available if we have recent DMX data OR coordinator data
        has_dmx_data = (
            self._dmx_status is not None
            and self._dmx_last_update is not None
            and datetime.now() - self._dmx_last_update
            <= timedelta(seconds=DMX_CACHE_SECONDS * 2)
        )

        has_coordinator_data = (
            self.coordinator.data is not None
            and "presentDemands" in self.coordinator.data
        )

        return has_dmx_data or has_coordinator_data

    @property
    def icon(self) -> str:
        """Return the icon for the binary sensor."""
        return "mdi:toggle-switch-outline"

    @classmethod
    def is_dmx_api_available(cls) -> bool:
        """Check if the DMX API is currently available."""
        # If we've never made a successful call, can't determine status
        if cls._last_successful_api_call is None:
            return True  # Assume available until proven otherwise

        # If the last successful call was too long ago, consider API down
        time_since_last_success = datetime.now() - cls._last_successful_api_call
        return time_since_last_success.total_seconds() < DMX_API_TIMEOUT

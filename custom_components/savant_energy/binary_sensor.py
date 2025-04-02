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

    def _get_channel_value(self) -> Optional[int]:
        """Get the channel value from the channel sensor if available."""
        # Find the channel sensor for this device
        channel_sensor_entity_id = f"sensor.{self._device['name'].lower().replace(' ', '_')}_channel"
        
        if self.hass and channel_sensor_entity_id in self.hass.states.async_entity_ids("sensor"):
            channel_state = self.hass.states.get(channel_sensor_entity_id)
            if channel_state and channel_state.state not in ('unknown', 'unavailable', ''):
                try:
                    return int(channel_state.state)
                except (ValueError, TypeError):
                    _LOGGER.warning(f"Invalid channel value in sensor {channel_sensor_entity_id}: {channel_state.state}")

        # Alternative entity ID format - try with UID
        alt_channel_sensor_entity_id = f"sensor.savantenergy_{self._device_uid}_channel"
        if self.hass and alt_channel_sensor_entity_id in self.hass.states.async_entity_ids("sensor"):
            channel_state = self.hass.states.get(alt_channel_sensor_entity_id)
            if channel_state and channel_state.state not in ('unknown', 'unavailable', ''):
                try:
                    return int(channel_state.state)
                except (ValueError, TypeError):
                    _LOGGER.warning(f"Invalid channel value in sensor {alt_channel_sensor_entity_id}: {channel_state.state}")
                    
        return None

    @property
    def is_on(self) -> Optional[bool]:
        """Return true if the relay status is on."""
        # Get DMX data
        dmx_data = self.coordinator.data.get("dmx_data", {})
        
        # Try to get channel from channel sensor first, then from device_channel_map if needed
        channel = self._get_channel_value()
        channel_source = "channel_sensor"
        
        if channel is None:
            device_channel_map = self.coordinator.data.get("device_channel_map", {})
            if self._device_uid in device_channel_map:
                channel = device_channel_map[self._device_uid]
                channel_source = "device_channel_map"
        
        # If we have a channel and DMX data for it, use that
        if channel is not None and channel in dmx_data:
            # Simplified logging - only log the channel and its source once
            #_LOGGER.debug(f"DMX status for {self._attr_name} (channel {channel} from {channel_source}): {dmx_data[channel]}")
            return dmx_data[channel]

        # Real fallback: presentDemands data from coordinator when DMX data not available
        _LOGGER.debug(f"No DMX data for {self._attr_name} (channel {channel}), using presentDemands data")
        snapshot_data = self.coordinator.data.get("snapshot_data", {})
        if snapshot_data and "presentDemands" in snapshot_data:
            for device in snapshot_data["presentDemands"]:
                if device["uid"] == self._device_uid:
                    value = device.get("percentCommanded")
                    if isinstance(value, int):
                        return value == 100  # Relay is on if percentCommanded is 100
                    return None
        return None

    @property
    def available(self) -> bool:
        """Return True if the entity is available."""
        # We're available if we have DMX data for our channel OR coordinator data
        dmx_data = self.coordinator.data.get("dmx_data", {})
        
        # Check if we can get channel data
        channel = self._get_channel_value()
        
        has_dmx_data = False
        if channel is not None:
            has_dmx_data = channel in dmx_data
        else:
            # Fallback to device_channel_map
            device_channel_map = self.coordinator.data.get("device_channel_map", {})
            if self._device_uid in device_channel_map:
                channel = device_channel_map[self._device_uid]
                has_dmx_data = channel in dmx_data
        
        snapshot_data = self.coordinator.data.get("snapshot_data", {})
        has_coordinator_data = (
            snapshot_data is not None
            and "presentDemands" in snapshot_data
        )

        return has_dmx_data or has_coordinator_data

    @property
    def icon(self) -> str:
        """Return the icon for the binary sensor."""
        return "mdi:toggle-switch-outline"

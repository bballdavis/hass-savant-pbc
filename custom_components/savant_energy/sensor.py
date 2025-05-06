"""Sensor platform for Savant Energy."""

import logging

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .models import get_device_model
from .utility_meter_sensor import EnhancedUtilityMeterSensor
from .utils import calculate_dmx_uid, async_get_dmx_address

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Savant Energy sensor entities."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities = []
    power_sensors = []  # Keep track of power sensors for utility meter creation

    snapshot_data = coordinator.data.get("snapshot_data", {})
    if (
        snapshot_data
        and isinstance(snapshot_data, dict)
        and "presentDemands" in snapshot_data
    ):
        demands_str = str(snapshot_data["presentDemands"])
        _LOGGER.debug(
            "Processing presentDemands: %.50s... (total length: %d)",
            demands_str,
            len(demands_str),
        )
        for device in snapshot_data["presentDemands"]:
            uid = device["uid"]
            dmx_uid = calculate_dmx_uid(uid)
            _LOGGER.debug(
                "Creating sensors for device: %s with DMX UID: %s", device, dmx_uid
            )

            # Create device info once for all sensors
            device_info = DeviceInfo(
                identifiers={(DOMAIN, str(device["uid"]))},
                name=device["name"],
                serial_number=dmx_uid,
                manufacturer=MANUFACTURER,
                model=get_device_model(device.get("capacity", 0)),
            )

            # Create regular sensors
            power_sensor = EnergyDeviceSensor(
                coordinator, device, "power", f"SavantEnergy_{uid}_power", dmx_uid
            )
            entities.append(power_sensor)
            power_sensors.append(power_sensor)

            # Add other sensors
            entities.append(
                EnergyDeviceSensor(
                    coordinator,
                    device,
                    "voltage",
                    f"SavantEnergy_{uid}_voltage",
                    dmx_uid,
                )
            )
            
            # Add DMX address sensor instead of channel
            entities.append(
                DMXAddressSensor(
                    coordinator,
                    device,
                    f"SavantEnergy_{uid}_dmx_address",
                    dmx_uid,
                )
            )
    else:
        _LOGGER.debug("No presentDemands data found in coordinator")

    # Add all entities first to ensure they get entity_ids assigned
    async_add_entities(entities)
    _LOGGER.debug("Added %d sensor entities", len(entities))

    # Create enhanced utility meter sensors
    utility_meter_sensors = []

    for power_sensor in power_sensors:
        if not power_sensor.entity_id:
            # Skip if entity_id isn't available yet
            _LOGGER.warning(
                "Power sensor %s has no entity_id yet, skipping meter creation",
                power_sensor.name,
            )
            continue

        device_name = power_sensor._device["name"]
        uid = power_sensor._device["uid"]
        device_info = power_sensor._attr_device_info

        # Create a single enhanced utility meter that tracks all periods
        utility_meter_sensors.append(
            EnhancedUtilityMeterSensor(
                hass,
                power_sensor.entity_id,
                "Energy",  # Use a short label to avoid duplicated device name
                f"SavantEnergy_{uid}_energy",
                device_info,
            )
        )

    if utility_meter_sensors:
        async_add_entities(utility_meter_sensors)
        _LOGGER.debug("Added %d utility meter sensors", len(utility_meter_sensors))


class DMXAddressSensor(CoordinatorEntity, SensorEntity):
    """Representation of the DMX Address Sensor."""
    
    _attr_state_class = SensorStateClass.MEASUREMENT
    
    def __init__(self, coordinator, device, unique_id, dmx_uid):
        """Initialize the DMX Address sensor."""
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
        """When entity is added to Home Assistant."""
        await super().async_added_to_hass()
        # Fetch DMX address on load-in
        await self._fetch_dmx_address()
    
    async def _fetch_dmx_address(self):
        """Fetch the DMX address from the API."""
        if not self.coordinator.config_entry:
            _LOGGER.warning(f"No config entry available for {self.name}")
            return
            
        ip_address = self.coordinator.config_entry.data.get("address")
        ola_port = self.coordinator.config_entry.data.get("ola_port", 9090)
        
        if not ip_address:
            _LOGGER.warning(f"No IP address available for {self.name}")
            return
            
        # Default universe is 1
        universe = 1
        
        address = await async_get_dmx_address(ip_address, ola_port, universe, self._dmx_uid)
        if address is not None:
            self._dmx_address = address
            self.async_write_ha_state()
            _LOGGER.info(f"Updated DMX address for {self.name}: {address}")
        else:
            _LOGGER.warning(f"Failed to fetch DMX address for {self.name}")
    
    @property
    def native_value(self):
        """Return the DMX address."""
        return self._dmx_address
    
    @property
    def icon(self):
        """Return the icon."""
        return "mdi:identifier"
    
    @property
    def available(self):
        """Return if sensor is available."""
        # The sensor is available if we have a DMX address
        return self._dmx_address is not None


class EnergyDeviceSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Savant Energy Sensor."""

    def __init__(self, coordinator, device, sensor_type, unique_id, dmx_uid):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device = device
        self._sensor_type = sensor_type
        self._attr_name = f"{device['name']} {sensor_type.capitalize()}"
        self._attr_unique_id = unique_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device["uid"]))},
            name=device["name"],
            serial_number=dmx_uid,  # Set DMX UID as the serial number
            manufacturer=MANUFACTURER,
            model=get_device_model(device.get("capacity", 0)),  # Determine model
        )
        self._attr_native_unit_of_measurement = self._get_unit_of_measurement(
            sensor_type
        )
        self._dmx_uid = dmx_uid  # Ensure DMX UID is stored

    def _get_unit_of_measurement(self, sensor_type: str) -> str | None:
        """Return the unit of measurement for the sensor type."""
        match sensor_type:
            case "voltage":
                return "V"
            case "power":
                return "W"  # This is correct - power should be in W
            case _:
                return None

    @property
    def state_class(self) -> str | None:
        """Return the state class of the sensor."""
        match self._sensor_type:
            case "power":
                return "measurement"  # Power is a measurement
            case "voltage":
                return "measurement"
            case _:
                return "measurement"

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        snapshot_data = self.coordinator.data.get("snapshot_data", {})
        if snapshot_data and "presentDemands" in snapshot_data:
            for device in snapshot_data["presentDemands"]:
                if device["uid"] == self._device["uid"]:
                    # Get value based on sensor type
                    value = device.get(self._sensor_type)
                    if self._sensor_type == "power" and isinstance(value, (int, float)):
                        return int(value * 1000)  # Convert kW to W
                    return value
        return None

    @property
    def icon(self) -> str:
        """Return the icon for the sensor."""
        match self._sensor_type:
            case "voltage":
                return "mdi:lightning-bolt-outline"
            case "power":
                return "mdi:gauge"
            case _:
                return "mdi:gauge"

    @property
    def available(self) -> bool:
        """Return True if the entity is available."""
        snapshot_data = self.coordinator.data.get("snapshot_data", {})
        if not snapshot_data or "presentDemands" not in snapshot_data:
            return False

        # Check if this specific device exists in the coordinator data
        for device in snapshot_data["presentDemands"]:
            if device["uid"] == self._device["uid"]:
                # For relay status (percentCommanded), check if the value exists
                if (
                    self._sensor_type == "percentCommanded"
                    and "percentCommanded" not in device
                ):
                    return False
                # For other sensor types, check if the value exists
                elif (
                    self._sensor_type != "percentCommanded"
                    and self._sensor_type not in device
                ):
                    return False
                return True

        return False

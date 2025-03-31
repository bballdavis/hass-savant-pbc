"""Sensor platform for Savant Energy."""

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .models import get_device_model
from .utility_meter_sensor import EnhancedUtilityMeterSensor

_LOGGER = logging.getLogger(__name__)


def calculate_dmx_uid(uid: str) -> str:
    """Calculate the DMX UID based on the device UID."""
    base_uid = uid.split(".")[0]
    base_uid = f"{base_uid[:4]}:{base_uid[4:]}"  # Ensure proper formatting
    if uid.endswith(".1"):
        last_char = base_uid[-1]
        if last_char == "9":
            base_uid = f"{base_uid[:-1]}A"  # Convert 9 to A
        else:
            base_uid = (
                f"{base_uid[:-1]}{chr(ord(last_char) + 1)}"  # Increment last character
            )
    # _LOGGER.debug("Generated DMX UID: %s for device UID: %s", base_uid, uid)
    return base_uid


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Savant Energy sensor entities."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities = []
    power_sensors = []  # Keep track of power sensors for utility meter creation

    if (
        coordinator.data
        and isinstance(coordinator.data, dict)
        and "presentDemands" in coordinator.data
    ):
        demands_str = str(coordinator.data["presentDemands"])
        _LOGGER.debug(
            "Processing presentDemands: %.50s... (total length: %d)",
            demands_str,
            len(demands_str),
        )
        for device in coordinator.data["presentDemands"]:
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
            entities.append(
                EnergyDeviceSensor(
                    coordinator,
                    device,
                    "channel",
                    f"SavantEnergy_{uid}_channel",
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
        self._channel = device.get("channel")  # Add channel information

    def _get_unit_of_measurement(self, sensor_type: str) -> str | None:
        """Return the unit of measurement for the sensor type."""
        match sensor_type:
            case "voltage":
                return "V"
            case "power":
                return "W"  # This is correct - power should be in W
            case "channel":
                return None
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
            case "channel":
                return None
            case _:
                return "measurement"

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        if self.coordinator.data and "presentDemands" in self.coordinator.data:
            for device in self.coordinator.data["presentDemands"]:
                if device["uid"] == self._device["uid"]:
                    value = device.get(self._sensor_type)
                    if self._sensor_type == "power" and isinstance(value, (int, float)):
                        return int(value * 1000)  # Convert kW to W
                    if self._sensor_type == "channel" and isinstance(value, int):
                        return value
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
            case "channel":
                return "mdi:tune-variant"
            case _:
                return "mdi:gauge"

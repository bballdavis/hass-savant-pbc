"""Sensor platform for Savant Energy."""

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .utility_meter_sensor import (
    UtilityMeterSensor,
    RESET_DAILY,  # Add RESET_DAILY
    RESET_MONTHLY,
    RESET_YEARLY,
)

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
    _LOGGER.debug("Generated DMX UID: %s for device UID: %s", base_uid, uid)
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

    # After entities are added, create utility meter sensors using the actual entity_ids
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

        _LOGGER.debug(
            "Creating utility meters for %s with source entity: %s",
            device_name,
            power_sensor.entity_id,
        )

        # Daily meter (replacing hourly meter)
        utility_meter_sensors.append(
            UtilityMeterSensor(
                hass,
                power_sensor.entity_id,
                f"{device_name} Energy - Day",
                f"SavantEnergy_{uid}_daily_energy",
                device_info,
                RESET_DAILY,
            )
        )

        # Monthly meter
        utility_meter_sensors.append(
            UtilityMeterSensor(
                hass,
                power_sensor.entity_id,
                f"{device_name} Energy - Month",
                f"SavantEnergy_{uid}_monthly_energy",
                device_info,
                RESET_MONTHLY,
            )
        )

        # Yearly meter
        utility_meter_sensors.append(
            UtilityMeterSensor(
                hass,
                power_sensor.entity_id,
                f"{device_name} Energy - YTD",
                f"SavantEnergy_{uid}_yearly_energy",
                device_info,
                RESET_YEARLY,
            )
        )

    if utility_meter_sensors:
        async_add_entities(utility_meter_sensors)
        _LOGGER.debug("Added %d utility meter sensors", len(utility_meter_sensors))


def get_device_model(capacity: float) -> str:
    """Determine the device model based on capacity."""
    match capacity:
        case 2.4:
            return "Dual 20A Relay"
        case 7.2:
            return "30A Relay"
        case 14.4:
            return "60A Relay"
        case _:
            return "Unknown Model"


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
        self._attr_state_class = "measurement"  # Adjust as needed
        self._dmx_uid = dmx_uid  # Ensure DMX UID is stored
        self._channel = device.get("channel")  # Add channel information

    def _get_unit_of_measurement(self, sensor_type: str) -> str | None:
        """Return the unit of measurement for the sensor type."""
        match sensor_type:
            case "voltage":
                return "V"
            case "power":
                return "W"
            case "channel":
                return None
            case _:
                return None

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
                return "mdi:meter-electric-outline"
            case "channel":
                return "mdi:tune-variant"
            case _:
                return "mdi:gauge"
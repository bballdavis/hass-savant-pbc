"""Sensor platform for Energy Snapshot."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import logging

from .const import DOMAIN

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
    """Set up Energy Snapshot sensor entities."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities = []
    if (
        coordinator.data
        and isinstance(coordinator.data, dict)
        and "presentDemands" in coordinator.data
    ):
        _LOGGER.debug(
            "Processing presentDemands: %s", coordinator.data["presentDemands"]
        )
        for device in coordinator.data["presentDemands"]:
            uid = device["uid"]
            dmx_uid = calculate_dmx_uid(uid)
            _LOGGER.debug(
                "Creating sensors for device: %s with DMX UID: %s", device, dmx_uid
            )
            entities.append(
                EnergyDeviceSensor(
                    coordinator, device, "voltage", f"SavantEnergy_{uid}_voltage", dmx_uid
                )
            )
            entities.append(
                EnergyDeviceSensor(
                    coordinator, device, "power", f"SavantEnergy_{uid}_power", dmx_uid
                )
            )
# entities.append(
            #    EnergyDeviceSensor(
            #        coordinator, device, "channel", f"SavantEnergy_{uid}_channel"
            #    )
            # )
            entities.append(
                EnergyDeviceBinarySensor(
                    coordinator, device, f"SavantEnergy_{uid}_relay_status", dmx_uid
                )
            )
    else:
        _LOGGER.debug("No presentDemands data found in coordinator")

    async_add_entities(entities)
    _LOGGER.debug("Added %d sensor entities", len(entities))


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
    """Representation of an Energy Snapshot Sensor."""

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
            manufacturer="Savant",
            model=get_device_model(device.get("capacity", 0)),  # Determine model
        )
        self._attr_native_unit_of_measurement = self._get_unit_of_measurement(
            sensor_type
        )
        self._attr_state_class = "measurement"  # Adjust as needed
        self._dmx_uid = calculate_dmx_uid(
            device["uid"]
        )  # Ensure DMX UID is calculated correctly

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


class EnergyDeviceBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of an Energy Snapshot Binary Sensor."""

    def __init__(self, coordinator, device, unique_id, dmx_uid):
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._device = device
        self._attr_name = f"{device['name']} Relay Status"
        self._attr_unique_id = unique_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device["uid"]))},
            name=device["name"],
            serial_number=dmx_uid,  # Set DMX UID as the serial number
            manufacturer="Savant",
            model=get_device_model(device.get("capacity", 0)),  # Determine model
        )

    @property
    def is_on(self) -> bool | None:
        """Return true if the relay status is on."""
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
        return (
            self.coordinator.data is not None
            and "presentDemands" in self.coordinator.data
        )

    @property
    def icon(self) -> str:
        """Return the icon for the binary sensor."""
        return "mdi:toggle-switch-outline"

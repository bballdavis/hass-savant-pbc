"""Sensor platform for Energy Snapshot."""

from datetime import datetime, timedelta
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Energy Snapshot sensor entities."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities = []
    if (
        coordinator.data
        and isinstance(coordinator.data, dict)
        and "presentDemands" in coordinator.data
    ):
        for device in coordinator.data["presentDemands"]:
            uid = device["uid"]
            capacity = device.get("capacity", 0)
            entities.append(
                EnergyDeviceSensor(
                    coordinator,
                    device,
                    "voltage",
                    f"SavantEnergy_{uid}_voltage",
                    capacity,
                )
            )
            entities.append(
                EnergyDeviceBinarySensor(
                    coordinator,
                    device,
                    "percentCommanded",
                    f"SavantEnergy_{uid}_relay_status",
                    capacity,
                )
            )
            entities.append(
                EnergyDeviceSensor(
                    coordinator, device, "power", f"SavantEnergy_{uid}_power", capacity
                )
            )
            entities.append(
                EnergyDeviceSensor(
                    coordinator,
                    device,
                    "channel",
                    f"SavantEnergy_{uid}_channel",
                    capacity,
                )
            )
            entities.append(
                EnergyDeviceCumulativeSensor(
                    coordinator,
                    device,
                    "power",
                    f"SavantEnergy_{uid}_ytd_energy",
                    capacity,
                    "YTD",
                )
            )
            entities.append(
                EnergyDeviceCumulativeSensor(
                    coordinator,
                    device,
                    "power",
                    f"SavantEnergy_{uid}_month_energy",
                    capacity,
                    "month",
                )
            )
            entities.append(
                EnergyDeviceCumulativeSensor(
                    coordinator,
                    device,
                    "power",
                    f"SavantEnergy_{uid}_day_energy",
                    capacity,
                    "day",
                )
            )

    async_add_entities(entities)


class EnergyDeviceSensor(CoordinatorEntity, SensorEntity):
    """Representation of an Energy Snapshot Sensor."""

    def __init__(self, coordinator, device, sensor_type, unique_id, capacity):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device = device
        self._sensor_type = sensor_type
        self._attr_name = f"{device['name']} {sensor_type.capitalize()}"
        self._attr_unique_id = unique_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device["uid"]))},
            name=device["name"],
            manufacturer="Savant",
            model=self._get_model_from_capacity(capacity),
        )
        self._attr_native_unit_of_measurement = self._get_unit_of_measurement(
            sensor_type
        )
        self._attr_state_class = "measurement"  # Adjust as needed

    def _get_model_from_capacity(self, capacity: float) -> str:
        """Return the model based on the capacity."""
        if capacity == 2.4:
            return "Dual 20A Relay"
        elif capacity == 7.2:
            return "30A Relay"
        elif capacity == 14.4:
            return "60A Relay"
        return "Unknown Model"

    def _get_unit_of_measurement(self, sensor_type: str) -> str | None:
        """Return the unit of measurement for the sensor type."""
        match sensor_type:
            case "voltage":
                return "V"
            case "percentCommanded":
                return "%"
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

    def __init__(self, coordinator, device, sensor_type, unique_id, capacity):
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._device = device
        self._sensor_type = sensor_type
        self._attr_name = f"{device['name']} Relay Status"
        self._attr_unique_id = unique_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device["uid"]))},
            name=device["name"],
            manufacturer="Savant",
            model=self._get_model_from_capacity(capacity),
        )

    def _get_model_from_capacity(self, capacity: float) -> str:
        """Return the model based on the capacity."""
        if capacity == 2.4:
            return "Dual 20A Relay"
        elif capacity == 7.2:
            return "30A Relay"
        elif capacity == 14.4:
            return "60A Relay"
        return "Unknown Model"

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if self.coordinator.data and "presentDemands" in self.coordinator.data:
            for device in self.coordinator.data["presentDemands"]:
                if device["uid"] == self._device["uid"]:
                    value = device.get(self._sensor_type)
                    if isinstance(value, int):
                        return value == 100
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


class EnergyDeviceCumulativeSensor(CoordinatorEntity, SensorEntity):
    """Representation of a cumulative energy sensor."""

    def __init__(self, coordinator, device, sensor_type, unique_id, capacity, period):
        """Initialize the cumulative sensor."""
        super().__init__(coordinator)
        self._device = device
        self._sensor_type = sensor_type
        self._attr_name = f"{device['name']} {period} Energy"
        self._attr_unique_id = unique_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device["uid"]))},
            name=device["name"],
            manufacturer="Savant",
            model=self._get_model_from_capacity(capacity),
        )
        self._attr_native_unit_of_measurement = "Wh"
        self._attr_state_class = "total_increasing"
        self._period = period
        self._last_reset = self._get_last_reset()
        self._cumulative_energy = 0

    def _get_model_from_capacity(self, capacity: float) -> str:
        """Return the model based on the capacity."""
        if capacity == 2.4:
            return "Dual 20A Relay"
        elif capacity == 7.2:
            return "30A Relay"
        elif capacity == 14.4:
            return "60A Relay"
        return "Unknown Model"

    def _get_last_reset(self) -> datetime:
        """Return the last reset time based on the period."""
        now = datetime.now()
        match self._period:
            case "YTD":
                return datetime(now.year, 1, 1)
            case "month":
                return datetime(now.year, now.month, 1)
            case "day":
                return datetime(now.year, now.month, now.day)
            case _:
                return now

    @property
    def native_value(self) -> int | None:
        """Return the cumulative energy value."""
        if self.coordinator.data and "presentDemands" in self.coordinator.data:
            for device in self.coordinator.data["presentDemands"]:
                if device["uid"] == self._device["uid"]:
                    power = device.get(self._sensor_type)
                    if isinstance(power, (int, float)):
                        elapsed_time = (
                            datetime.now() - self._last_reset
                        ).total_seconds() / 3600
                        self._cumulative_energy += int(
                            power * elapsed_time * 1000
                        )  # Convert kW to Wh
                        self._last_reset = datetime.now()
                        return self._cumulative_energy
        return None

    @property
    def icon(self) -> str:
        """Return the icon for the cumulative sensor."""
        return "mdi:chart-line"

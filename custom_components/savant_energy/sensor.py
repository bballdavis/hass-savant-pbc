"""Sensor platform for Savant Energy."""

import logging

from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, MANUFACTURER
from .models import get_device_model
from .energy_stats_sensor import EnergyStatsSensor
from .energy_device_sensor import EnergyDeviceSensor
from .dmx_address_sensor import DMXAddressSensor
from .utils import calculate_dmx_uid

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
        energy_stats_sensors = []
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
            
            # Predictable entity_id for the power sensor
            power_entity_id = f"sensor.savantenergy_{uid}_power"
            energy_stats_sensors.append(
                EnergyStatsSensor(
                    hass,
                    power_entity_id,
                    "Energy",
                    f"SavantEnergy_{uid}_energy",
                    device_info,
                )
            )
            
        # Add all entities at once
        async_add_entities(entities + energy_stats_sensors)
        _LOGGER.debug("Added %d sensor entities (including energy stats sensors)", len(entities + energy_stats_sensors))
        
        return True
    else:
        _LOGGER.debug("No presentDemands data found in coordinator")

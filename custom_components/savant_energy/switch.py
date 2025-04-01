"""Switch platform for Savant Energy."""

import logging
import time
import math

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_SWITCH_COOLDOWN, DEFAULT_SWITCH_COOLDOWN, MANUFACTURER
from .models import get_device_model  # Import from models.py instead of sensor.py

_LOGGER = logging.getLogger(__name__)

_last_command_time = 0.0


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    """Set up Savant Energy switch entities."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    # Get cooldown setting from config
    cooldown = config_entry.options.get(
        CONF_SWITCH_COOLDOWN,
        config_entry.data.get(CONF_SWITCH_COOLDOWN, DEFAULT_SWITCH_COOLDOWN),
    )

    entities = []
    if (
        coordinator.data
        and isinstance(coordinator.data, dict)
        and "presentDemands" in coordinator.data
    ):
        for device in coordinator.data["presentDemands"]:
            entities.append(EnergyDeviceSwitch(hass, coordinator, device, cooldown))

    async_add_entities(entities)


class EnergyDeviceSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a Savant Energy Switch."""

    def __init__(self, hass: HomeAssistant, coordinator, device, cooldown: int):
        """Initialize the switch."""
        super().__init__(coordinator)
        self._hass = hass
        self._device = device
        self._cooldown = cooldown
        self._attr_name = f"{device['name']} Switch"
        self._attr_unique_id = f"{DOMAIN}_{device['uid']}_switch"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device["uid"]))},
            name=device["name"],
            manufacturer=MANUFACTURER,
            model=get_device_model(
                device.get("capacity", 0)
            ),  # Use the model lookup function
        )
        self._attr_is_on = self._get_percent_commanded_state()
        self._last_commanded_state = self._attr_is_on
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    def _get_percent_commanded_state(self) -> bool | None:
        """Get the state of the switch based on percentCommanded, or None if unknown."""
        if self.coordinator.data and "presentDemands" in self.coordinator.data:
            for device in self.coordinator.data["presentDemands"]:
                if device["uid"] == self._device["uid"]:
                    if "percentCommanded" in device:
                        return device["percentCommanded"] == 100
        return None

    @property
    def available(self) -> bool:
        """Return True if the entity is available."""
        # First check if coordinator data is available
        if not self.coordinator.data or "presentDemands" not in self.coordinator.data:
            return False

        # Then check if we can get a valid relay state
        relay_state = self._get_percent_commanded_state()
        if relay_state is None:
            return False

        return True

    @property
    def is_on(self) -> bool:
        """Return the state of the switch."""
        return self._attr_is_on if self._attr_is_on is not None else False

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        global _last_command_time
        now = time.monotonic()

        # Check cooldown
        if now - _last_command_time < self._cooldown:
            time_left = math.ceil(self._cooldown - (now - _last_command_time))
            _LOGGER.debug("Cooldown active, ignoring turn_on command")

            # Use persistent_notification.create service which is always available
            await self._hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "message": f"Action for {self._device['name']} was delayed. Please wait {time_left} seconds before trying again.",
                    "title": "Switch Action Delayed",
                    "notification_id": f"{DOMAIN}_cooldown_{self._device['uid']}",
                },
            )
            return

        if not self.is_on:
            _last_command_time = now  # Set cooldown timer only when actually proceeding

            channel_values = []
            for dev in self.coordinator.data["presentDemands"]:
                if dev["uid"] == self._device["uid"]:
                    channel_values.append("255")  # Set this device to on
                else:
                    # Default to 255 (on) if percentCommanded is not available
                    channel_values.append(
                        "255" if dev.get("percentCommanded", 100) == 100 else "0"
                    )

            formatted_string = f'curl -X POST -d "u=1&d={",".join(channel_values)}" http://192.168.1.108:9090/set_dmx'
            _LOGGER.debug("Formatted string: %s", formatted_string)

            # Add the actual API call to turn the switch on
            self._attr_is_on = True
            self._last_commanded_state = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        global _last_command_time
        now = time.monotonic()

        # Check cooldown
        if now - _last_command_time < self._cooldown:
            time_left = math.ceil(self._cooldown - (now - _last_command_time))
            _LOGGER.debug("Cooldown active, ignoring turn_off command")

            # Use persistent_notification.create service which is always available
            await self._hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "message": f"Action for {self._device['name']} was delayed. Please wait {time_left} seconds before trying again.",
                    "title": "Switch Action Delayed",
                    "notification_id": f"{DOMAIN}_cooldown_{self._device['uid']}",
                },
            )
            return

        if self.is_on:
            _last_command_time = now  # Set cooldown timer only when actually proceeding

            channel_values = []
            for dev in self.coordinator.data["presentDemands"]:
                if dev["uid"] == self._device["uid"]:
                    channel_values.append("0")  # Set this device to off
                else:
                    # Default to 255 (on) if percentCommanded is not available
                    channel_values.append(
                        "255" if dev.get("percentCommanded", 100) == 100 else "0"
                    )

            formatted_string = f'curl -X POST -d "u=1&d={",".join(channel_values)}" http://192.168.1.108:9090/set_dmx'
            _LOGGER.debug("Formatted string: %s", formatted_string)

            # Add the actual API call to turn the switch off
            self._attr_is_on = False
            self._last_commanded_state = False
            self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        new_state = self._get_percent_commanded_state()

        # Only process state changes
        if new_state != self._last_commanded_state:
            # Check if cooldown is active
            now = time.monotonic()
            if now - _last_command_time < self._cooldown:
                # Cooldown active, reject the state change
                time_left = math.ceil(self._cooldown - (now - _last_command_time))
                _LOGGER.debug(
                    "Cooldown active, rejecting state change from coordinator for %s. %d seconds left",
                    self._device["name"],
                    time_left,
                )

                # Keep our current state instead of accepting the change
                # This will effectively reject the state change
                self._attr_is_on = self._last_commanded_state
                self.async_write_ha_state()
            else:
                # No cooldown, accept the state change
                self._attr_is_on = new_state
                self._last_commanded_state = new_state
                self.async_write_ha_state()

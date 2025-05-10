"""Switch platform for Savant Energy."""

import logging
import time
import math

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_SWITCH_COOLDOWN, DEFAULT_SWITCH_COOLDOWN, MANUFACTURER, DEFAULT_OLA_PORT, CONF_DMX_TESTING_MODE
from .models import get_device_model
from .utils import calculate_dmx_uid, async_set_dmx_values, async_get_dmx_address

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
    snapshot_data = coordinator.data.get("snapshot_data", {})
    if (
        snapshot_data
        and isinstance(snapshot_data, dict)
        and "presentDemands" in snapshot_data
    ):
        for device in snapshot_data["presentDemands"]:
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
        self._attr_name = f"{device['name']} Breaker"
        self._attr_unique_id = f"{DOMAIN}_{device['uid']}_breaker"
        self._dmx_uid = calculate_dmx_uid(device["uid"])
        self._dmx_address = None  # Will be fetched before sending commands
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device["uid"]))},
            name=device["name"],
            manufacturer=MANUFACTURER,
            model=get_device_model(
                device.get("capacity", 0)
            ),  # Use the model lookup function
            serial_number=self._dmx_uid,  # Add DMX UID as serial number
        )
        self._attr_is_on = self._get_relay_status_state()
        self._last_commanded_state = self._attr_is_on
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    def _get_relay_status_state(self) -> bool | None:
        """Get the state of the switch based on the relay status sensor, or None if unknown."""
        device_name = self._device['name']
        
        # Look for binary sensor with Relay Status in the name for this device
        for binary_sensor in self._hass.states.async_all("binary_sensor"):
            if (binary_sensor.attributes.get("friendly_name") and 
                f"{device_name} Relay Status" == binary_sensor.attributes.get("friendly_name")):
                if binary_sensor.state.lower() == "on":
                    return True
                elif binary_sensor.state.lower() == "off":
                    return False
                # If state is not "on" or "off", it's unknown
                break
        
        return None

    async def _get_dmx_address_from_sensor(self) -> int | None:
        """Try to get the DMX address from the sensor entity."""
        # Construct the sensor entity_id
        dmx_address_entity_id = f"sensor.{self._device['name'].lower().replace(' ', '_')}_dmx_address"
        # Try more variations if the simple approach doesn't work
        alternative_entity_id = f"sensor.savant_energy_{self._device['uid']}_dmx_address"
        
        # Check if sensor exists in Home Assistant's state machine
        state = self._hass.states.get(dmx_address_entity_id)
        if not state or state.state in ('unknown', 'unavailable'):
            # Try alternative entity_id
            state = self._hass.states.get(alternative_entity_id)
            
        if state and state.state not in ('unknown', 'unavailable'):
            try:
                return int(state.state)
            except (ValueError, TypeError):
                _LOGGER.warning(f"Invalid DMX address in sensor {state.entity_id}: {state.state}")
                
        return None    

    async def _fetch_dmx_address(self) -> int | None:
        """Fetch DMX address from sensor only."""
        # Only get from sensor
        address = await self._get_dmx_address_from_sensor()
        if address is not None:
            return address
            
        _LOGGER.warning(f"No DMX address found in sensor for {self.name}")
        return None

    async def _get_all_device_dmx_states(self, target_dmx_address=None, target_value=None):
        """Build a dict of {dmx_address: value} for all devices using only DMX Address and Relay Status sensors."""
        dmx_states = {}
        max_address = 0

        # Get all DMX address sensors
        dmx_address_entities = [entity for entity in self._hass.states.async_all("sensor") if entity.entity_id.endswith("_dmx_address")]

        for dmx_address_entity in dmx_address_entities:
            # Skip if the DMX address is not a valid number
            if dmx_address_entity.state in ("unknown", "unavailable") or not dmx_address_entity.state:
                continue
            try:
                dmx_address = int(dmx_address_entity.state)
            except (ValueError, TypeError):
                _LOGGER.warning(f"Invalid DMX address in sensor {dmx_address_entity.entity_id}: {dmx_address_entity.state}")
                continue

            # Find the corresponding relay status sensor from binary_sensor domain
            # Extract device name from the DMX address sensor
            entity_id = dmx_address_entity.entity_id
            device_name = None
            
            # Try to extract device name from sensor entity attributes
            sensor_state = self._hass.states.get(entity_id)
            if sensor_state and sensor_state.attributes.get("friendly_name"):
                # Remove " DMX Address" from the friendly name
                device_name = sensor_state.attributes.get("friendly_name").replace(" DMX Address", "")
            
            if not device_name:
                # Fallback: try to extract from entity_id
                entity_name = entity_id.split(".", 1)[1].replace("_dmx_address", "")
                # Convert underscores to spaces and title case
                device_name = entity_name.replace("_", " ").title()
            
            # Look for a binary sensor with "Relay Status" in the name for this device
            relay_found = False
            for binary_sensor in self._hass.states.async_all("binary_sensor"):
                if binary_sensor.attributes.get("friendly_name") and f"{device_name} Relay Status" == binary_sensor.attributes.get("friendly_name"):
                    relay_status_state = binary_sensor
                    relay_found = True
                    break
            
            # Default to ON (255) if relay status is not found or unknown
            value = "255"
            if relay_found and relay_status_state.state not in ("unknown", "unavailable"):
                if relay_status_state.state.lower() == "on":
                    value = "255"
                elif relay_status_state.state.lower() == "off":
                    value = "0"
                _LOGGER.debug(f"Found relay status for {device_name}: {relay_status_state.state} (using value {value})")
            else:
                _LOGGER.debug(f"No relay status found for {device_name}, defaulting to ON")

            dmx_states[dmx_address] = value
            if dmx_address > max_address:
                max_address = dmx_address

        # If a target address/value is provided (for the switch being toggled), override it
        if target_dmx_address:
            dmx_states[target_dmx_address] = target_value
            if target_dmx_address > max_address:
                max_address = target_dmx_address

        return dmx_states, max_address

    async def _send_full_dmx_command(self, target_dmx_address, target_value):
        """Send a DMX command with the full state of all addresses."""
        # Build the full DMX state array
        dmx_states, max_address = await self._get_all_device_dmx_states(target_dmx_address, target_value)
        
        ip_address = self.coordinator.config_entry.data.get("address")
        ola_port = self.coordinator.config_entry.data.get("ola_port", DEFAULT_OLA_PORT)
        
        # Get DMX testing mode from config
        dmx_testing_mode = self.coordinator.config_entry.options.get(
            CONF_DMX_TESTING_MODE,
            self.coordinator.config_entry.data.get(CONF_DMX_TESTING_MODE, False)
        )
        
        # Pass the testing mode parameter to the utility function
        success = await async_set_dmx_values(ip_address, dmx_states, ola_port, dmx_testing_mode)
        if not success:
            _LOGGER.error(f"Failed to send DMX command for {self.name} at address {target_dmx_address}")
            
        return success

    @property
    def available(self) -> bool:
        """Return True if the entity is available."""
        # First check if coordinator data is available
        snapshot_data = self.coordinator.data.get("snapshot_data", {})
        if not snapshot_data or "presentDemands" not in snapshot_data:
            return False

        # Then check if we can get a valid relay state
        relay_state = self._get_relay_status_state()
        if relay_state is None:
            return False

        return True

    @property
    def is_on(self) -> bool:
        """Return the state of the switch based on the relay status sensor."""
        # Return the stored state if we have one
        if self._attr_is_on is not None:
            return self._attr_is_on

        # Try to find the relay status sensor for this device
        device_name = self._device['name']
        
        # Look for binary sensor with Relay Status in the name for this device
        for binary_sensor in self._hass.states.async_all("binary_sensor"):
            if (binary_sensor.attributes.get("friendly_name") and 
                f"{device_name} Relay Status" == binary_sensor.attributes.get("friendly_name")):
                if binary_sensor.state.lower() == "on":
                    return True
                elif binary_sensor.state.lower() == "off":
                    return False
        
        # Fall back to off if we can't find the relay status
        return False

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        global _last_command_time
        now = time.monotonic()
        if now - _last_command_time < self._cooldown:
            time_left = math.ceil(self._cooldown - (now - _last_command_time))
            _LOGGER.debug("Cooldown active, ignoring turn_on command")
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
            _last_command_time = now
            dmx_address = await self._fetch_dmx_address()
            if dmx_address is None:
                _LOGGER.warning(f"Cannot turn on {self.name}: DMX address unknown")
                return
            _LOGGER.info(f"Turning ON {self.name} at DMX address {dmx_address}")
            await self._send_full_dmx_command(dmx_address, "255")
            self._attr_is_on = True
            self._last_commanded_state = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        global _last_command_time
        now = time.monotonic()
        if now - _last_command_time < self._cooldown:
            time_left = math.ceil(self._cooldown - (now - _last_command_time))
            _LOGGER.debug("Cooldown active, ignoring turn_off command")
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
            _last_command_time = now
            dmx_address = await self._fetch_dmx_address()
            if dmx_address is None:
                _LOGGER.warning(f"Cannot turn off {self.name}: DMX address unknown")
                return
            _LOGGER.info(f"Turning OFF {self.name} at DMX address {dmx_address}")
            await self._send_full_dmx_command(dmx_address, "0")
            self._attr_is_on = False
            self._last_commanded_state = False
            self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Look for binary sensor with Relay Status in name for this device
        device_name = self._device['name']
        new_state = None
        
        for binary_sensor in self._hass.states.async_all("binary_sensor"):
            if (binary_sensor.attributes.get("friendly_name") and 
                f"{device_name} Relay Status" == binary_sensor.attributes.get("friendly_name")):
                new_state = binary_sensor.state.lower() == "on"
                break
        
        # Only update if we found a relay status and it's different from our current state
        if new_state is not None and new_state != self._last_commanded_state:
            self._attr_is_on = new_state
            self._last_commanded_state = new_state
            self.async_write_ha_state()

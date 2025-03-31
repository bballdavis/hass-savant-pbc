"""Utility meter sensor implementation for Savant Energy."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MANUFACTURER

_LOGGER = logging.getLogger(__name__)

# Constants for reset periods
RESET_DAILY = "daily"
RESET_MONTHLY = "monthly"
RESET_YEARLY = "yearly"


class EnhancedUtilityMeterSensor(RestoreEntity):
    """Energy meter sensor with daily, monthly, and yearly usage (primary) attributes."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        source_entity: str,
        name: str,
        unique_id: str,
        device_info: DeviceInfo,
    ):
        """Initialize the utility meter sensor."""
        self.hass = hass
        self._source_entity = source_entity
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._attr_device_info = device_info

        # Initialize all counters to zero
        self._yearly_usage = 0.0
        self._attr_native_value = 0.0  # Explicitly set native_value
        self._daily_usage = 0.0
        self._monthly_usage = 0.0

        self._last_reset = dt_util.utcnow()
        self._last_power = None
        self._last_update = None

        # Register state listeners
        self._remove_listeners = []

    async def async_added_to_hass(self):
        """Handle entity which will be added."""
        _LOGGER.debug("Setting up energy meter %s", self.name)
        await super().async_added_to_hass()

        # Restore previous state if available
        last_state = await self.async_get_last_state()
        if last_state is not None:
            # Restore the main yearly usage from the state value
            try:
                self._yearly_usage = (
                    float(last_state.state)
                    if last_state.state not in (None, "unknown", "unavailable")
                    else 0.0
                )
                self._attr_native_value = (
                    self._yearly_usage
                )  # Set native_value directly
            except (ValueError, TypeError):
                self._yearly_usage = 0.0
                self._attr_native_value = 0.0

            # Restore attributes if available
            if "daily_usage_kwh" in last_state.attributes:
                try:
                    self._daily_usage = float(last_state.attributes["daily_usage_kwh"])
                except (ValueError, TypeError):
                    self._daily_usage = 0.0
            elif "daily_usage" in last_state.attributes:
                try:
                    self._daily_usage = float(last_state.attributes["daily_usage"])
                except (ValueError, TypeError):
                    self._daily_usage = 0.0

            if "monthly_usage_kwh" in last_state.attributes:
                try:
                    self._monthly_usage = float(
                        last_state.attributes["monthly_usage_kwh"]
                    )
                except (ValueError, TypeError):
                    self._monthly_usage = 0.0
            elif "monthly_usage" in last_state.attributes:
                try:
                    self._monthly_usage = float(last_state.attributes["monthly_usage"])
                except (ValueError, TypeError):
                    self._monthly_usage = 0.0

            if "last_reset" in last_state.attributes:
                try:
                    self._last_reset = dt_util.parse_datetime(
                        last_state.attributes["last_reset"]
                    )
                except (ValueError, TypeError):
                    self._last_reset = dt_util.utcnow()

        current_state = self.hass.states.get(self._source_entity)
        if not last_state and (
            current_state is None or current_state.state in ("unknown", "unavailable")
        ):
            # If there's no previous sensor state and source entity is unknown,
            # explicitly set the yearly usage to avoid "unknown" display
            self._yearly_usage = 0.0
            self._attr_native_value = 0.0  # Set native_value directly
            self.async_write_ha_state()

        # Track the source entity
        @callback
        def async_source_state_changed(entity_id, old_state, new_state):
            """Handle power changes."""
            if not new_state or new_state.state in (None, "unknown", "unavailable"):
                return

            # Parse the power values
            try:
                if not old_state or old_state.state in (None, "unknown", "unavailable"):
                    old_power = 0
                else:
                    old_power = float(old_state.state)
                new_power = float(new_state.state)
            except (ValueError, TypeError):
                _LOGGER.warning("Could not parse power values for %s", self.name)
                return

            # Calculate energy
            if self._last_update is not None:
                now = dt_util.utcnow()
                time_diff = (now - self._last_update).total_seconds() / 3600
                avg_power = (old_power + new_power) / 2
                energy_kwh = avg_power * time_diff / 1000
                _LOGGER.debug(
                    "%s: Power avg=%.1f W × %.4f h = %.5f kWh",
                    self.name,
                    avg_power,
                    time_diff,
                    energy_kwh,
                )

                self._yearly_usage += energy_kwh
                self._daily_usage += energy_kwh
                self._monthly_usage += energy_kwh
                self._attr_native_value = round(
                    self._yearly_usage, 1
                )  # Changed from 3 to 1
                self.async_write_ha_state()

            self._last_power = new_power
            self._last_update = dt_util.utcnow()

        # Track time for resetting periods
        @callback
        def async_reset_daily(now):
            """Reset daily usage at midnight."""
            _LOGGER.debug("Resetting daily energy usage for %s", self.name)
            self._daily_usage = 0.0
            self.async_write_ha_state()

            # Schedule next reset at midnight
            next_midnight = dt_util.start_of_local_day(
                dt_util.now() + timedelta(days=1)
            )
            self._remove_listeners.append(
                async_track_point_in_time(self.hass, async_reset_daily, next_midnight)
            )

        @callback
        def async_reset_monthly(now):
            """Reset monthly usage at the first day of month."""
            _LOGGER.debug("Resetting monthly energy usage for %s", self.name)
            self._monthly_usage = 0.0
            self.async_write_ha_state()

            # Schedule next reset for the first day of next month
            today = dt_util.now().replace(day=1)
            next_month = (
                today.replace(month=today.month + 1)
                if today.month < 12
                else today.replace(year=today.year + 1, month=1)
            )
            next_reset = dt_util.start_of_local_day(next_month)
            self._remove_listeners.append(
                async_track_point_in_time(self.hass, async_reset_monthly, next_reset)
            )

        @callback
        def async_reset_yearly(now):
            """Reset the yearly usage at the beginning of the year."""
            _LOGGER.debug("Resetting yearly energy usage for %s", self.name)
            self._yearly_usage = 0.0
            self._attr_native_value = 0.0  # Reset native_value directly
            self._daily_usage = 0.0
            self._monthly_usage = 0.0
            self._last_reset = dt_util.utcnow()
            self.async_write_ha_state()

            # Schedule next reset for January 1st of next year
            today = dt_util.now()
            next_year = today.replace(year=today.year + 1, month=1, day=1)
            next_reset = dt_util.start_of_local_day(next_year)

            self._remove_listeners.append(
                async_track_point_in_time(self.hass, async_reset_yearly, next_reset)
            )

        # Set up entity state tracking
        self._remove_listeners.append(
            self.hass.helpers.event.async_track_state_change(
                self._source_entity, async_source_state_changed
            )
        )

        # Schedule initial resets
        now = dt_util.now()
        # Next daily reset (midnight)
        next_midnight = dt_util.start_of_local_day(now + timedelta(days=1))
        self._remove_listeners.append(
            async_track_point_in_time(self.hass, async_reset_daily, next_midnight)
        )
        # Next monthly reset (1st of month)
        next_month = (
            now.replace(day=1, month=now.month + 1)
            if now.month < 12
            else now.replace(year=now.year + 1, month=1, day=1)
        )
        next_month_reset = dt_util.start_of_local_day(next_month)
        self._remove_listeners.append(
            async_track_point_in_time(self.hass, async_reset_monthly, next_month_reset)
        )
        # Next yearly reset (January 1st)
        next_year = now.replace(year=now.year + 1, month=1, day=1)
        next_year_reset = dt_util.start_of_local_day(next_year)
        self._remove_listeners.append(
            async_track_point_in_time(self.hass, async_reset_yearly, next_year_reset)
        )

        # Initialize with current state
        current_state = self.hass.states.get(self._source_entity)
        if current_state is not None:
            async_source_state_changed(self._source_entity, None, current_state)

        # Make sure we write the current state to avoid "unknown" display
        self._attr_native_value = round(
            self._yearly_usage,
            1,  # Changed from 3 to 1
        )  # Set explicitly before writing
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self):
        """Handle entity removal."""
        # Remove listeners
        for remove_listener in self._remove_listeners:
            remove_listener()
        self._remove_listeners = []

    @property
    def native_value(self) -> float:
        """Return the yearly energy usage in kWh."""
        return round(self._yearly_usage or 0.0, 1)  # Changed from 3 to 1

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return entity specific state attributes."""
        # Follow standard Home Assistant attribute naming (no _kwh suffix)
        return {
            "daily_usage": round(self._daily_usage, 1),  # Changed from 3 to 1
            "monthly_usage": round(self._monthly_usage, 1),  # Changed from 3 to 1
            "yearly_usage": round(self._yearly_usage, 1),  # Changed from 3 to 1
            "last_reset": self._last_reset.isoformat(),
        }

    @property
    def state(self):
        """Return the state of the entity."""
        return round(self._yearly_usage, 1)  # Changed from 3 to 1

    @property
    def available(self) -> bool:
        """Return True if the sensor is available."""
        # Always return True to make sure the sensor shows up
        return True

    @property
    def icon(self) -> str:
        """Return the icon for the utility meter sensor."""
        return "mdi:meter-electric-outline"

    @property
    def unit_of_measurement(self) -> str:
        """Return the unit of measurement."""
        return UnitOfEnergy.KILO_WATT_HOUR

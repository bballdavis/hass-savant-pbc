"""Utility meter sensor implementation for Savant Energy."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict
from decimal import Decimal, ROUND_HALF_UP

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
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


class EnhancedUtilityMeterSensor(RestoreEntity, SensorEntity):
    """Energy meter sensor with daily, monthly, yearly, and lifetime usage attributes."""

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
        self._lifetime_usage = 0.0  # Never resets
        self._yearly_usage = 0.0
        self._monthly_usage = 0.0
        self._daily_usage = 0.0

        self._attr_native_value = 0.0  # Explicitly set native_value

        self._last_reset = dt_util.utcnow()  # For legacy compatibility
        self._last_yearly_reset = dt_util.now().replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        self._last_monthly_reset = dt_util.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        self._last_daily_reset = dt_util.start_of_local_day(dt_util.now())

        self._last_power = None
        self._last_update = None

        # Register state listeners
        self._remove_listeners = []

    async def async_added_to_hass(self):
        """Handle entity which will be added."""
        await super().async_added_to_hass()

        # Restore previous state if available
        last_state = await self.async_get_last_state()
        if last_state is not None:
            # Restore the main lifetime usage from the state value
            try:
                self._lifetime_usage = (
                    float(last_state.state)
                    if last_state.state not in (None, "unknown", "unavailable")
                    else 0.0
                )
                self._attr_native_value = self._lifetime_usage
            except (ValueError, TypeError):
                self._lifetime_usage = 0.0
                self._attr_native_value = 0.0

            # Restore attributes if available
            if "daily_usage" in last_state.attributes:
                try:
                    self._daily_usage = float(last_state.attributes["daily_usage"])
                except (ValueError, TypeError):
                    self._daily_usage = 0.0

            if "monthly_usage" in last_state.attributes:
                try:
                    self._monthly_usage = float(last_state.attributes["monthly_usage"])
                except (ValueError, TypeError):
                    self._monthly_usage = 0.0

            if "yearly_usage" in last_state.attributes:
                try:
                    self._yearly_usage = float(last_state.attributes["yearly_usage"])
                except (ValueError, TypeError):
                    self._yearly_usage = 0.0

            # Restore last reset datetimes robustly
            now = dt_util.now()
            today = dt_util.start_of_local_day(now)
            first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            first_of_year = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

            if "last_daily_reset" in last_state.attributes:
                try:
                    self._last_daily_reset = dt_util.parse_datetime(last_state.attributes["last_daily_reset"])
                except Exception:
                    self._last_daily_reset = today
            else:
                self._last_daily_reset = today

            if "last_monthly_reset" in last_state.attributes:
                try:
                    self._last_monthly_reset = dt_util.parse_datetime(last_state.attributes["last_monthly_reset"])
                except Exception:
                    self._last_monthly_reset = first_of_month
            else:
                self._last_monthly_reset = first_of_month

            if "last_yearly_reset" in last_state.attributes:
                try:
                    self._last_yearly_reset = dt_util.parse_datetime(last_state.attributes["last_yearly_reset"])
                except Exception:
                    self._last_yearly_reset = first_of_year
            else:
                self._last_yearly_reset = first_of_year

            # Only reset usage if the period has actually changed
            if self._last_daily_reset is None or self._last_daily_reset < today:
                self._daily_usage = 0.0
                self._last_daily_reset = today
            if self._last_monthly_reset is None or self._last_monthly_reset < first_of_month:
                self._monthly_usage = 0.0
                self._last_monthly_reset = first_of_month
            if self._last_yearly_reset is None or self._last_yearly_reset < first_of_year:
                self._yearly_usage = 0.0
                self._last_yearly_reset = first_of_year

        current_state = self.hass.states.get(self._source_entity)
        if not last_state and (
            current_state is None or current_state.state in ("unknown", "unavailable")
        ):
            # If there's no previous sensor state and source entity is unknown,
            # explicitly set the lifetime usage to avoid "unknown" display
            self._lifetime_usage = 0.0
            self._attr_native_value = 0.0
            self.async_write_ha_state()

        # After restoring state, check and correct reset dates/values if the period has actually expired
        now = dt_util.now()
        today = dt_util.start_of_local_day(now)
        if self._last_daily_reset is None or self._last_daily_reset < today:
            self._daily_usage = 0.0
            self._last_daily_reset = today
        first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if self._last_monthly_reset is None or self._last_monthly_reset < first_of_month:
            self._monthly_usage = 0.0
            self._last_monthly_reset = first_of_month
        first_of_year = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        if self._last_yearly_reset is None or self._last_yearly_reset < first_of_year:
            self._yearly_usage = 0.0
            self._last_yearly_reset = first_of_year
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

                # Don't allow negative energy values
                if energy_kwh < 0:
                    _LOGGER.warning("Negative energy calculated (%f kWh) - ignoring", energy_kwh)
                    energy_kwh = 0

                # Log current measurements and accumulation for debugging
                _LOGGER.debug(
                    "%s: Power: %.2fW, Time: %.4f hours, Energy: %.6f kWh, "
                    "Daily: %.4f → %.4f, Monthly: %.4f → %.4f",
                    self.name, new_power, time_diff, energy_kwh, 
                    self._daily_usage, self._daily_usage + energy_kwh,
                    self._monthly_usage, self._monthly_usage + energy_kwh
                )

                self._lifetime_usage += energy_kwh

                # For yearly, monthly, and daily, always check if we need to reset first
                # before accumulating new energy values
                now_local = dt_util.now()
                today = dt_util.start_of_local_day(now_local)
                first_of_month = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                first_of_year = now_local.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

                # Check for period changes and reset if needed
                if self._last_yearly_reset is None or self._last_yearly_reset < first_of_year:
                    _LOGGER.info("%s: Yearly period changed, resetting yearly usage", self.name)
                    self._yearly_usage = energy_kwh  # Start fresh with current energy
                    self._last_yearly_reset = first_of_year
                else:
                    self._yearly_usage += energy_kwh
                
                if self._last_monthly_reset is None or self._last_monthly_reset < first_of_month:
                    _LOGGER.info("%s: Monthly period changed, resetting monthly usage", self.name)
                    self._monthly_usage = energy_kwh  # Start fresh with current energy
                    self._last_monthly_reset = first_of_month
                else:
                    self._monthly_usage += energy_kwh
                
                if self._last_daily_reset is None or self._last_daily_reset < today:
                    _LOGGER.info("%s: Daily period changed, resetting daily usage", self.name)
                    self._daily_usage = energy_kwh  # Start fresh with current energy
                    self._last_daily_reset = today
                else:
                    self._daily_usage += energy_kwh

                self._attr_native_value = round(self._lifetime_usage, 1)
                
                # Log a summary of current values at INFO level periodically
                if self._lifetime_usage % 1.0 < energy_kwh:  # Log approximately every kWh
                    _LOGGER.info(
                        "%s: Current usage - Daily: %.4f kWh, Monthly: %.4f kWh, "
                        "Yearly: %.4f kWh, Lifetime: %.4f kWh",
                        self.name, self._daily_usage, self._monthly_usage, 
                        self._yearly_usage, self._lifetime_usage
                    )
                
                self.async_write_ha_state()

            self._last_power = new_power
            self._last_update = dt_util.utcnow()

        # Track time for resetting periods
        @callback
        def async_reset_daily(now):
            """Reset daily usage at midnight."""
            _LOGGER.debug("Resetting daily energy usage for %s", self.name)
            self._daily_usage = 0.0
            self._last_daily_reset = dt_util.start_of_local_day(now)
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
            self._last_monthly_reset = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
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
            self._last_yearly_reset = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
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
        self._attr_native_value = round(self._lifetime_usage, 1)
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self):
        """Handle entity removal."""
        # Remove listeners
        for remove_listener in self._remove_listeners:
            remove_listener()
        self._remove_listeners = []

    @property
    def native_value(self) -> float:
        """Return the lifetime energy usage in kWh."""
        return round(self._lifetime_usage or 0.0, 1)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return entity specific state attributes with consistent precision and up-to-date reset dates."""
        # All usage values rounded to one decimal place for consistency
        return {
            "daily_usage": round(self._daily_usage or 0.0, 1),
            "monthly_usage": round(self._monthly_usage or 0.0, 1),
            "yearly_usage": round(self._yearly_usage or 0.0, 1),
            "lifetime_usage": round(self._lifetime_usage or 0.0, 1),
            "last_daily_reset": self._last_daily_reset.isoformat() if self._last_daily_reset else None,
            "last_monthly_reset": self._last_monthly_reset.isoformat() if self._last_monthly_reset else None,
            "last_yearly_reset": self._last_yearly_reset.isoformat() if self._last_yearly_reset else None,
        }

    @property
    def state(self):
        """Return the state of the entity."""
        return round(self._lifetime_usage, 1)

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

"""Power Usage Statistics Sensor for Savant Energy.
This sensor tracks power consumption over time and converts it to energy (kWh)."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Callable, List
import decimal
from decimal import Decimal

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_point_in_time,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MANUFACTURER

_LOGGER = logging.getLogger(__name__)

# Configure decimal precision for energy calculations
decimal.getcontext().prec = 15  # Increased precision

# Constants for reset periods
PERIOD_DAILY = "daily"
PERIOD_MONTHLY = "monthly"
PERIOD_YEARLY = "yearly"
PERIOD_LIFETIME = "lifetime"

ATTR_DAILY_USAGE = "daily_usage"
ATTR_MONTHLY_USAGE = "monthly_usage"
ATTR_YEARLY_USAGE = "yearly_usage"
ATTR_LAST_DAILY_RESET = "last_daily_reset"
ATTR_LAST_MONTHLY_RESET = "last_monthly_reset"
ATTR_LAST_YEARLY_RESET = "last_yearly_reset"


class EnergyStatsSensor(RestoreEntity, SensorEntity):
    """Power usage statistics sensor with daily, monthly, yearly and lifetime energy tracking."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_has_entity_name = True
    _attr_should_poll = False  # We update based on source entity changes and time

    def __init__(
        self,
        hass: HomeAssistant,
        source_entity_id: str,
        name: str,
        unique_id: str,
        device_info: DeviceInfo,
    ):
        """Initialize the energy statistics sensor."""
        self.hass = hass
        self._source_entity_id = source_entity_id
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._attr_device_info = device_info
        # Initialize energy values with proper decimal precision
        self._energy: Dict[str, Decimal] = {
            PERIOD_DAILY: Decimal("0.0"),
            PERIOD_MONTHLY: Decimal("0.0"),
            PERIOD_YEARLY: Decimal("0.0"),
            PERIOD_LIFETIME: Decimal("0.0"),
        }
        _LOGGER.debug(
            "%s: Initialized energy values - daily: %.1f kWh, monthly: %.1f kWh, yearly: %.1f kWh, lifetime: %.1f kWh",
            unique_id,
            float(self._energy[PERIOD_DAILY]),
            float(self._energy[PERIOD_MONTHLY]),
            float(self._energy[PERIOD_YEARLY]),
            float(self._energy[PERIOD_LIFETIME])
        )
        
        self._last_power_state: Optional[float] = None
        self._last_update_time: Optional[datetime] = None
        
        now = dt_util.now()        
        self._last_reset: Dict[str, Optional[datetime]] = {
            PERIOD_DAILY: dt_util.start_of_local_day(now),
            PERIOD_MONTHLY: now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
            PERIOD_YEARLY: now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0),
            PERIOD_LIFETIME: None,  # Lifetime does not reset
        }
        
        # Set the native value with 1 decimal place precision
        self._attr_native_value = round(float(self._energy[PERIOD_LIFETIME]), 1)
        self._listeners: List[Callable[[], None]] = []

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        # Try to restore previous state
        if state := await self.async_get_last_state():
            try:
                await self._async_restore_state(state)
            except Exception as ex:
                _LOGGER.error("%s: Error restoring state: %s", self.entity_id, ex)
        else:
            _LOGGER.debug("%s: No previous state found, initializing", self.entity_id)
        # Set up tracking and reset schedules
        self._setup_source_tracking()
        self._setup_periodic_resets()
        # Check for missed resets (important after HA restart)
        await self._check_and_perform_missed_resets()

    async def _async_restore_state(self, last_state: State) -> None:
        """Restore previous energy state."""
        _LOGGER.debug("%s: Restoring state from %s", self.entity_id, last_state)
        # Restore lifetime energy value (main state value)
        if last_state.state not in (None, "unknown", "unavailable"):            
            try:
                self._energy[PERIOD_LIFETIME] = Decimal(str(last_state.state))
                self._attr_native_value = round(float(self._energy[PERIOD_LIFETIME]), 1)  # Round to 1 decimal place
                _LOGGER.debug("%s: Restored lifetime value to %.2f kWh", 
                             self.entity_id, float(self._energy[PERIOD_LIFETIME]))
            except (ValueError, decimal.InvalidOperation):
                _LOGGER.warning("%s: Could not restore lifetime state from '%s'", 
                                self.entity_id, last_state.state)
        # Restore attributes (period-specific energy values and reset times)
        attributes = last_state.attributes
        _LOGGER.debug("%s: Attributes to restore: %s", self.entity_id, attributes)
        for period in [PERIOD_DAILY, PERIOD_MONTHLY, PERIOD_YEARLY]:
            # Restore energy usage for this period
            usage_attr = f"{period}_usage"
            if usage_attr in attributes:
                try:
                    self._energy[period] = Decimal(str(attributes[usage_attr]))
                    _LOGGER.debug("%s: Restored %s to %.2f kWh", 
                                 self.entity_id, period, float(self._energy[period]))
                except (ValueError, decimal.InvalidOperation):
                    _LOGGER.warning("%s: Could not restore %s from '%s'", 
                                    self.entity_id, usage_attr, attributes[usage_attr])
            else:
                _LOGGER.debug("%s: No %s attribute found in state", self.entity_id, usage_attr)
            # Restore last reset time for this period
            reset_attr = f"last_{period}_reset"
            if reset_attr in attributes and attributes[reset_attr]:
                try:
                    parsed_date = dt_util.parse_datetime(str(attributes[reset_attr]))
                    if parsed_date:
                        self._last_reset[period] = dt_util.as_local(parsed_date)
                        _LOGGER.debug("%s: Restored %s to %s", 
                                     self.entity_id, reset_attr, self._last_reset[period])
                except Exception:
                    _LOGGER.warning("%s: Could not parse %s timestamp", 
                                    self.entity_id, reset_attr)
        _LOGGER.debug("%s: Restored state: energy=%s, last_reset=%s", 
                      self.entity_id, self._energy, self._last_reset)

    def _setup_source_tracking(self) -> None:
        """Set up tracking of the source power sensor."""
        # Track state changes of the power sensor
        self._listeners.append(
            async_track_state_change_event(
                self.hass, [self._source_entity_id], self._async_source_state_changed
            )
        )
        
        # Also get the initial state if available
        if state := self.hass.states.get(self._source_entity_id):
            self._update_from_source_state(state)

    @callback
    def _async_source_state_changed(self, event) -> None:
        """Handle source sensor state changes."""
        if not event.data.get("new_state"):
            return
            
        new_state = event.data["new_state"]
        self._update_from_source_state(new_state)
    
    def _update_from_source_state(self, state: State) -> None:
        """Process new state value from source sensor."""
        if state.state in (None, "unknown", "unavailable"):
            return
            
        try:
            current_power = float(state.state)  # Power in watts
            current_time = dt_util.utcnow()  # Use UTC for calculations
            
            # Skip if this is the first reading (need two points for integration)
            if self._last_power_state is None or self._last_update_time is None:
                self._last_power_state = current_power
                self._last_update_time = current_time
                return
                
            # Calculate time delta in seconds
            time_delta_seconds = (current_time - self._last_update_time).total_seconds()
            
            # Skip calculation if time hasn't advanced or went backwards
            if time_delta_seconds <= 0:
                _LOGGER.debug("%s: Time delta is invalid (%s seconds), skipping", 
                              self.entity_id, time_delta_seconds)
                self._last_power_state = current_power
                self._last_update_time = current_time
                return
                
            # Convert seconds to hours for energy calculation
            time_delta_hours = Decimal(str(time_delta_seconds)) / Decimal("3600.0")
              # Calculate energy using trapezoidal rule: (P1 + P2)/2 * T
            # Power is in watts, so result is in watt-hours (Wh)
            avg_power = (Decimal(str(self._last_power_state)) + Decimal(str(current_power))) / Decimal("2.0")
            energy_wh = avg_power * time_delta_hours
            
            # Log input values for energy calculation
            _LOGGER.debug(
                "%s: Calculating energy - last_power: %.2f W, current_power: %.2f W, time_delta: %.4f hours", 
                self.entity_id, self._last_power_state, current_power, float(time_delta_hours)
            )
            
            # Convert Wh to kWh for storage and display
            energy_kwh = energy_wh / Decimal("1000.0")
            _LOGGER.debug("%s: Calculated energy: %.4f kWh", self.entity_id, float(energy_kwh))
            
            # Skip if calculated energy is negative (could happen with production meters)
            # For this implementation, we assume we're only tracking consumption
            if energy_kwh < 0:
                _LOGGER.debug("%s: Negative energy calculated (%s kWh), skipping", 
                             self.entity_id, energy_kwh)
                self._last_power_state = current_power
                self._last_update_time = current_time
                return
                  # Update all energy counters
            for period in self._energy:
                self._energy[period] += energy_kwh
            
            # Log the current energy values for debugging
            _LOGGER.debug(
                "%s: Updated energy values - daily: %.2f kWh, monthly: %.2f kWh, yearly: %.2f kWh, lifetime: %.2f kWh", 
                self.entity_id,
                float(self._energy[PERIOD_DAILY]),
                float(self._energy[PERIOD_MONTHLY]),
                float(self._energy[PERIOD_YEARLY]),
                float(self._energy[PERIOD_LIFETIME])
            )
                  
            # Update entity state (lifetime value)
            self._attr_native_value = round(float(self._energy[PERIOD_LIFETIME]), 1)  # Round to 1 decimal place
            
            # Store current values for next update
            self._last_power_state = current_power
            self._last_update_time = current_time
            
            self.async_write_ha_state()
            
        except (ValueError, TypeError, decimal.InvalidOperation) as ex:
            _LOGGER.error("%s: Error calculating energy: %s", self.entity_id, ex)

    def _setup_periodic_resets(self) -> None:
        """Set up the periodic reset schedules for daily, monthly, yearly."""
        # Daily reset - schedule for midnight each day
        next_midnight = dt_util.start_of_local_day() + timedelta(days=1)
        self._listeners.append(
            async_track_point_in_time(
                self.hass, self._async_reset_daily, next_midnight
            )
        )
        
        # Monthly reset - schedule for midnight on the first day of next month
        now = dt_util.now()
        if now.month == 12:
            next_month = now.replace(year=now.year+1, month=1, day=1)
        else:
            next_month = now.replace(month=now.month+1, day=1)
        next_month = next_month.replace(hour=0, minute=0, second=0, microsecond=0)
        self._listeners.append(
            async_track_point_in_time(
                self.hass, self._async_reset_monthly, next_month
            )
        )
        
        # Yearly reset - schedule for midnight on January 1st
        next_year = now.replace(year=now.year+1, month=1, day=1, 
                                hour=0, minute=0, second=0, microsecond=0)
        self._listeners.append(
            async_track_point_in_time(
                self.hass, self._async_reset_yearly, next_year
            )
        )    @callback
    def _async_reset_daily(self, _now: Optional[datetime] = None) -> None:
        """Reset daily stats and schedule next reset."""
        old_value = float(self._energy[PERIOD_DAILY])
        self._energy[PERIOD_DAILY] = Decimal("0.0")
        self._last_reset[PERIOD_DAILY] = dt_util.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        
        _LOGGER.debug("%s: Reset daily energy stats from %.2f kWh to 0.0", self.entity_id, old_value)
        self.async_write_ha_state()
        
        # Schedule next daily reset
        next_midnight = dt_util.start_of_local_day() + timedelta(days=1)
        self._listeners.append(
            async_track_point_in_time(
                self.hass, self._async_reset_daily, next_midnight
            )
        )    @callback
    def _async_reset_monthly(self, _now: Optional[datetime] = None) -> None:
        """Reset monthly stats and schedule next reset."""
        old_value = float(self._energy[PERIOD_MONTHLY])
        self._energy[PERIOD_MONTHLY] = Decimal("0.0")
        now = dt_util.now()
        self._last_reset[PERIOD_MONTHLY] = now.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        
        _LOGGER.debug("%s: Reset monthly energy stats from %.2f kWh to 0.0", self.entity_id, old_value)
        self.async_write_ha_state()
        
        # Schedule next monthly reset
        now = dt_util.now()
        if now.month == 12:
            next_month = now.replace(year=now.year+1, month=1, day=1)
        else:
            next_month = now.replace(month=now.month+1, day=1)
        next_month = next_month.replace(hour=0, minute=0, second=0, microsecond=0)
        self._listeners.append(
            async_track_point_in_time(
                self.hass, self._async_reset_monthly, next_month
            )
        )

    @callback
    def _async_reset_yearly(self, _now: Optional[datetime] = None) -> None:
        """Reset yearly stats and schedule next reset."""
        self._energy[PERIOD_YEARLY] = Decimal("0.0")
        now = dt_util.now()
        self._last_reset[PERIOD_YEARLY] = now.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
        
        _LOGGER.debug("%s: Reset yearly energy stats", self.entity_id)
        self.async_write_ha_state()
        
        # Schedule next yearly reset
        next_year = dt_util.now().replace(year=now.year+1, month=1, day=1,
                                         hour=0, minute=0, second=0, microsecond=0)
        self._listeners.append(
            async_track_point_in_time(
                self.hass, self._async_reset_yearly, next_year
            )
        )

    async def _check_and_perform_missed_resets(self) -> None:
        """Check if any resets were missed while HA was down."""
        now = dt_util.now()
        
        # Check daily reset
        today_start = dt_util.start_of_local_day(now)
        if (self._last_reset[PERIOD_DAILY] is None or 
                self._last_reset[PERIOD_DAILY] < today_start):
            _LOGGER.debug("%s: Missed daily reset detected, resetting daily stats", self.entity_id)
            self._energy[PERIOD_DAILY] = Decimal("0.0")
            self._last_reset[PERIOD_DAILY] = today_start
        
        # Check monthly reset
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if (self._last_reset[PERIOD_MONTHLY] is None or 
                self._last_reset[PERIOD_MONTHLY] < month_start):
            _LOGGER.debug("%s: Missed monthly reset detected, resetting monthly stats", self.entity_id)
            self._energy[PERIOD_MONTHLY] = Decimal("0.0")
            self._last_reset[PERIOD_MONTHLY] = month_start
        
        # Check yearly reset
        year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        if (self._last_reset[PERIOD_YEARLY] is None or 
                self._last_reset[PERIOD_YEARLY] < year_start):
            _LOGGER.debug("%s: Missed yearly reset detected, resetting yearly stats", self.entity_id)
            self._energy[PERIOD_YEARLY] = Decimal("0.0")
            self._last_reset[PERIOD_YEARLY] = year_start
              # Write state if any resets were performed
        self.async_write_ha_state()
        
    async def async_will_remove_from_hass(self) -> None:
        """Remove event listeners when entity is removed."""
        for unsubscribe_callback in self._listeners:
            unsubscribe_callback()
        self._listeners = []    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return the state attributes."""
        daily_usage = round(float(self._energy[PERIOD_DAILY]), 1)
        monthly_usage = round(float(self._energy[PERIOD_MONTHLY]), 1)
        yearly_usage = round(float(self._energy[PERIOD_YEARLY]), 1)
        
        # Log attribute values for debugging
        _LOGGER.debug(
            "%s: Returning attributes - daily: %.1f, monthly: %.1f, yearly: %.1f", 
            self.entity_id, daily_usage, monthly_usage, yearly_usage
        )
        
        return {
            ATTR_DAILY_USAGE: daily_usage,
            ATTR_MONTHLY_USAGE: monthly_usage,
            ATTR_YEARLY_USAGE: yearly_usage,
            ATTR_LAST_DAILY_RESET: self._last_reset[PERIOD_DAILY].isoformat() 
                if self._last_reset[PERIOD_DAILY] else None,
            ATTR_LAST_MONTHLY_RESET: self._last_reset[PERIOD_MONTHLY].isoformat() 
                if self._last_reset[PERIOD_MONTHLY] else None,
            ATTR_LAST_YEARLY_RESET: self._last_reset[PERIOD_YEARLY].isoformat()
                if self._last_reset[PERIOD_YEARLY] else None,
        }
    
    @property
    def icon(self) -> str:
        """Return the icon to use for the entity."""
        return "mdi:lightning-bolt"
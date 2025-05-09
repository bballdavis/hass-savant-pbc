"""Utility meter sensor implementation for Savant Energy."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Callable
import decimal
from decimal import Decimal, getcontext

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
getcontext().prec = 15  # Increased precision

# Constants for reset periods
PERIOD_DAILY = "daily"
PERIOD_MONTHLY = "monthly"
PERIOD_YEARLY = "yearly"
PERIOD_LIFETIME = "lifetime"


class EnhancedUtilityMeterSensor(RestoreEntity, SensorEntity):
    """Energy meter sensor with lifetime tracking and daily, monthly, yearly attributes."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_has_entity_name = True
    _attr_should_poll = False # We update based on source entity changes and time

    def __init__(
        self,
        hass: HomeAssistant,
        source_entity_id: str,
        name: str,
        unique_id: str,
        device_info: DeviceInfo,
    ):
        """Initialize the energy meter sensor."""
        self.hass = hass
        self._source_entity_id = source_entity_id
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._attr_device_info = device_info

        self._energy: Dict[str, Decimal] = {
            PERIOD_DAILY: Decimal("0.0"),
            PERIOD_MONTHLY: Decimal("0.0"),
            PERIOD_YEARLY: Decimal("0.0"),
            PERIOD_LIFETIME: Decimal("0.0"),
        }
        
        self._last_power_state: Optional[float] = None
        self._last_update_time: Optional[datetime] = None
        
        now = dt_util.now()
        self._last_reset: Dict[str, Optional[datetime]] = {
            PERIOD_DAILY: dt_util.start_of_local_day(now),
            PERIOD_MONTHLY: now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
            PERIOD_YEARLY: now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0),
            PERIOD_LIFETIME: None, # Lifetime does not reset in this context
        }

        self._attr_native_value = float(self._energy[PERIOD_LIFETIME])
        self._listeners: list[Callable] = []

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        
        if state := await self.async_get_last_state():
            await self._async_restore_state(state)
        else:
            _LOGGER.debug("%s: No previous state found, initializing", self.entity_id)

        self._setup_source_tracking()
        self._setup_periodic_resets()
        
        # Perform initial check for resets that might have been missed if HA was down
        self._check_and_perform_missed_resets()
        
        self._update_state() # Write initial/restored state

    async def _async_restore_state(self, last_state: State) -> None:
        """Restore previous energy state."""
        _LOGGER.debug("%s: Restoring state", self.entity_id)
        try:
            if last_state.state not in (None, "unknown", "unavailable"):
                self._energy[PERIOD_LIFETIME] = Decimal(str(last_state.state))
            
            attributes = last_state.attributes
            for period in [PERIOD_DAILY, PERIOD_MONTHLY, PERIOD_YEARLY]:
                usage_attr = f"{period}_usage"
                reset_attr = f"last_{period}_reset"

                if usage_attr in attributes:
                    try:
                        self._energy[period] = Decimal(str(attributes[usage_attr]))
                    except (ValueError, TypeError, decimal.InvalidOperation) as e:
                        _LOGGER.warning("%s: Could not restore %s energy from value '%s': %s", 
                                        self.entity_id, period, attributes[usage_attr], e)
                
                if reset_attr in attributes and attributes[reset_attr]:
                    try:
                        parsed_date = dt_util.parse_datetime(str(attributes[reset_attr]))
                        if parsed_date:
                             # Ensure it's timezone-aware, matching what dt_util.start_of_local_day provides
                            self._last_reset[period] = dt_util.as_local(parsed_date)
                    except Exception as e:
                        _LOGGER.warning("%s: Could not parse %s date '%s', using default: %s", 
                                        self.entity_id, reset_attr, attributes[reset_attr], e)
            
            _LOGGER.debug("%s: Restored energy: %s", self.entity_id, self._energy)
            _LOGGER.debug("%s: Restored last_reset: %s", self.entity_id, self._last_reset)

        except Exception as ex:
            _LOGGER.error("%s: Error restoring energy state: %s", self.entity_id, ex)

    def _check_and_perform_missed_resets(self) -> None:
        """Check and perform resets for periods that might have elapsed while HA was offline."""
        now = dt_util.now()
        
        # Daily
        today_start = dt_util.start_of_local_day(now)
        if self._last_reset[PERIOD_DAILY] and self._last_reset[PERIOD_DAILY] < today_start:
            _LOGGER.info("%s: Daily period elapsed since last run. Resetting daily energy.", self.entity_id)
            self._energy[PERIOD_DAILY] = Decimal("0.0")
            self._last_reset[PERIOD_DAILY] = today_start

        # Monthly
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if self._last_reset[PERIOD_MONTHLY] and self._last_reset[PERIOD_MONTHLY] < month_start:
            _LOGGER.info("%s: Monthly period elapsed since last run. Resetting monthly energy.", self.entity_id)
            self._energy[PERIOD_MONTHLY] = Decimal("0.0")
            self._last_reset[PERIOD_MONTHLY] = month_start

        # Yearly
        year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        if self._last_reset[PERIOD_YEARLY] and self._last_reset[PERIOD_YEARLY] < year_start:
            _LOGGER.info("%s: Yearly period elapsed since last run. Resetting yearly energy.", self.entity_id)
            self._energy[PERIOD_YEARLY] = Decimal("0.0")
            self._last_reset[PERIOD_YEARLY] = year_start
        
        self._update_state()
    def _setup_source_tracking(self) -> None:
        """Set up tracking of the source power sensor."""
        
        @callback
        def async_source_state_changed(event) -> None:
            """Handle power sensor state changes."""
            new_state: Optional[State] = event.data.get("new_state")
            
            if not new_state or new_state.state in (None, "unknown", "unavailable"):
                _LOGGER.debug("%s: Source sensor new_state is invalid: %s", self.entity_id, new_state.state if new_state else "None")
                return

            try:
                current_power = float(new_state.state)
                current_time = dt_util.utcnow() # Use UTC for calculations

                if self._last_power_state is not None and self._last_update_time is not None:
                    time_delta_seconds = (current_time - self._last_update_time).total_seconds()
                    
                    if time_delta_seconds <= 0: # Time hasn't advanced or went backwards
                        _LOGGER.debug("%s: Time delta is zero or negative (%s s), skipping calculation.", self.entity_id, time_delta_seconds)
                        # Still update last known state if power changed, to avoid stale data on next valid update
                        self._last_power_state = current_power
                        self._last_update_time = current_time
                        return

                    # Warn if time delta is excessively large (e.g., > 1 hour), could indicate HA restart or sensor issues
                    if time_delta_seconds > 3600 * 2: # More than 2 hours
                        _LOGGER.warning(
                            "%s: Time difference too large (%.2f hours). This might lead to inaccurate energy calculation. "
                            "Last update: %s, Current update: %s, Last Power: %s W, Current Power: %s W",
                            self.entity_id, time_delta_seconds / 3600,
                            self._last_update_time, current_time,
                            self._last_power_state, current_power
                        )
                        # To prevent a massive jump, we might skip this one calculation or cap it.
                        # For now, we'll proceed but the warning is important.

                    time_delta_hours = Decimal(str(time_delta_seconds)) / Decimal("3600.0")
                    
                    # Trapezoidal rule for integration: (P1 + P2)/2 * T
                    avg_power = (Decimal(str(self._last_power_state)) + Decimal(str(current_power))) / Decimal("2.0")
                    energy_increment_kwh = (avg_power * time_delta_hours) / Decimal("1000.0")
                    
                    if energy_increment_kwh < Decimal("0.0"):
                        _LOGGER.warning("%s: Negative energy increment calculated (%s kWh). Ignoring.", self.entity_id, energy_increment_kwh)
                        energy_increment_kwh = Decimal("0.0")
                    
                    if energy_increment_kwh > Decimal("0.0"):
                        _LOGGER.debug(
                            "%s: Calculated energy increment: %s kWh (Power: %sW -> %sW, Time Diff: %.2fs)",
                            self.entity_id, energy_increment_kwh, self._last_power_state, current_power, time_delta_seconds
                        )
                        self._energy[PERIOD_LIFETIME] += energy_increment_kwh
                        self._energy[PERIOD_DAILY] += energy_increment_kwh
                        self._energy[PERIOD_MONTHLY] += energy_increment_kwh
                        self._energy[PERIOD_YEARLY] += energy_increment_kwh
                        self._update_state()
                    else:
                        _LOGGER.debug("%s: Zero energy increment, no update to counters.", self.entity_id)

                self._last_power_state = current_power
                self._last_update_time = current_time
                
            except (ValueError, TypeError) as ex:
                _LOGGER.warning("%s: Error calculating energy from power value '%s': %s", self.entity_id, new_state.state, ex)
            except Exception as ex:
                _LOGGER.error("%s: Unexpected error in async_source_state_changed: %s", self.entity_id, ex, exc_info=True)

        # Initialize with current state if available
        current_source_state = self.hass.states.get(self._source_entity_id)
        if current_source_state and current_source_state.state not in ("unknown", "unavailable", None):
            try:
                self._last_power_state = float(current_source_state.state)
                self._last_update_time = dt_util.utcnow()
                _LOGGER.debug("%s: Initialized with power: %s W at %s", self.entity_id, self._last_power_state, self._last_update_time)
            except (ValueError, TypeError):
                _LOGGER.warning("%s: Could not parse initial power value: %s", self.entity_id, current_source_state.state)
        
        self._listeners.append(
            async_track_state_change_event(
                self.hass, [self._source_entity_id], async_source_state_changed
            )
        )

    def _setup_periodic_resets(self) -> None:
        """Set up periodic reset points for daily, monthly, and yearly counters."""
        
        @callback
        def _async_reset_daily(now_utc: datetime) -> None:
            _LOGGER.info("%s: Resetting daily energy counter.", self.entity_id)
            self._energy[PERIOD_DAILY] = Decimal("0.0")
            self._last_reset[PERIOD_DAILY] = dt_util.start_of_local_day(dt_util.as_local(now_utc))
            self._update_state()

        @callback
        def _async_reset_monthly(now_utc: datetime) -> None:
            _LOGGER.info("%s: Resetting monthly energy counter.", self.entity_id)
            self._energy[PERIOD_MONTHLY] = Decimal("0.0")
            local_now = dt_util.as_local(now_utc)
            self._last_reset[PERIOD_MONTHLY] = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            self._update_state()

        @callback
        def _async_reset_yearly(now_utc: datetime) -> None:
            _LOGGER.info("%s: Resetting yearly energy counter.", self.entity_id)
            self._energy[PERIOD_YEARLY] = Decimal("0.0")
            local_now = dt_util.as_local(now_utc)
            self._last_reset[PERIOD_YEARLY] = local_now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            self._update_state()

        # Schedule future resets
        # It's important to calculate the *next* reset time from the current time.
        now = dt_util.now() # Current local time
        next_daily_reset = dt_util.start_of_local_day(now) + timedelta(days=1)
        self._listeners.append(async_track_point_in_time(self.hass, _async_reset_daily, next_daily_reset))
        _LOGGER.debug("%s: Scheduled next daily reset at %s", self.entity_id, next_daily_reset)

        current_month = now.month
        current_year = now.year
        if current_month == 12:
            next_monthly_reset_date = now.replace(year=current_year + 1, month=1, day=1)
        else:
            next_monthly_reset_date = now.replace(month=current_month + 1, day=1)
        next_monthly_reset = dt_util.start_of_local_day(next_monthly_reset_date)
        self._listeners.append(async_track_point_in_time(self.hass, _async_reset_monthly, next_monthly_reset))
        _LOGGER.debug("%s: Scheduled next monthly reset at %s", self.entity_id, next_monthly_reset)
        
        next_yearly_reset_date = now.replace(year=current_year + 1, month=1, day=1)
        next_yearly_reset = dt_util.start_of_local_day(next_yearly_reset_date)
        self._listeners.append(async_track_point_in_time(self.hass, _async_reset_yearly, next_yearly_reset))
        _LOGGER.debug("%s: Scheduled next yearly reset at %s", self.entity_id, next_yearly_reset)

    def _update_state(self) -> None:
        """Update entity state with current energy values."""
        self._attr_native_value = round(float(self._energy[PERIOD_LIFETIME]), 4) # Keep good precision
        if self.hass and self.entity_id: # Ensure entity is added
             _LOGGER.debug("%s: Updating state. Native: %s, Attrs: %s", self.entity_id, self._attr_native_value, self.extra_state_attributes)
             self.async_write_ha_state()
        else:
            _LOGGER.debug("%s: Hass or entity_id not available yet for state update.", self._attr_name)


    async def async_will_remove_from_hass(self) -> None:
        """Handle entity removal."""
        _LOGGER.debug("%s: Removing entity and listeners.", self.entity_id)
        for remove_listener in self._listeners:
            remove_listener()
        self._listeners = []

    @property
    def native_value(self) -> float:
        """Return the lifetime energy usage in kWh."""
        return round(float(self._energy[PERIOD_LIFETIME]), 4)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return entity specific state attributes."""
        attrs = {
            # Round to a reasonable number of decimal places for display
            "daily_usage": round(float(self._energy[PERIOD_DAILY]), 3),
            "monthly_usage": round(float(self._energy[PERIOD_MONTHLY]), 3),
            "yearly_usage": round(float(self._energy[PERIOD_YEARLY]), 3),
            "lifetime_usage": round(float(self._energy[PERIOD_LIFETIME]), 3),
        }
        for period_name in [PERIOD_DAILY, PERIOD_MONTHLY, PERIOD_YEARLY]:
            if self._last_reset[period_name]:
                attrs[f"last_{period_name}_reset"] = self._last_reset[period_name].isoformat() # type: ignore[union-attr]
            else:
                attrs[f"last_{period_name}_reset"] = None
        
        attrs["source_entity_id"] = self._source_entity_id
        return attrs

    @property
    def icon(self) -> str:
        """Return the icon for the utility meter sensor."""
        return "mdi:meter-electric-outline"

    @property
    def last_reset(self) -> Optional[datetime]:
        """Return the time when the sensor was last reset (None for total_increasing)."""
        return None # As per HA docs for state_class TOTAL_INCREASING

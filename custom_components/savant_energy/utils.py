"""Utility functions for Savant Energy integration."""

import logging
import asyncio
import subprocess
import json
from datetime import datetime, timedelta
import aiohttp
from typing import List, Dict, Any, Optional, Final, Tuple, Union

from .const import DEFAULT_OLA_PORT

_LOGGER = logging.getLogger(__name__)

# DMX API constants
DMX_ON_VALUE: Final = 255
DMX_OFF_VALUE: Final = 0
DMX_CACHE_SECONDS: Final = 5  # Cache DMX status for 5 seconds
DMX_API_TIMEOUT: Final = 30  # Time in seconds to consider API down

# Track API statistics
_dmx_api_stats = {
    "request_count": 0,
    "failure_count": 0,
    "last_successful_call": None,
    "success_rate": 100.0
}

# Class variables to track DMX API status across all instances
_last_successful_api_call: Optional[datetime] = None
_api_failure_count: int = 0
_api_request_count: int = 0

# Log the utility module loading
_LOGGER.warning("Savant Energy utils module loaded")


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
    return base_uid


async def async_get_all_dmx_status(ip_address: str, channels: List[int], ola_port: int = DEFAULT_OLA_PORT) -> Dict[int, bool]:
    """Get DMX status for specified channels in one batch.
    
    Args:
        ip_address: IP address of the OLA server
        channels: List of DMX channels to check
        ola_port: OLA server port
        
    Returns:
        Dictionary mapping channel numbers to boolean status (True = on, False = off)
    """
    global _last_successful_api_call, _api_failure_count, _api_request_count
    
    if not channels or len(channels) == 0:
        _LOGGER.warning("Channels parameter is required but was empty - nothing to check")
        return {}
    
    # Convert all channels to integers to ensure proper handling
    int_channels = []
    for ch in channels:
        try:
            int_channels.append(int(ch))
        except (ValueError, TypeError):
            _LOGGER.warning(f"Skipping invalid channel: {ch}")

    if not ip_address or not ola_port:
        _LOGGER.debug("Missing IP address or OLA port for DMX request")
        return {}
    
    url = f"http://{ip_address}:{ola_port}/get_dmx?u=1"
    #_LOGGER.warning(f"Making DMX request to: {url}")
    
    dmx_status_dict = {}  # Maps channel -> status
    
    try:
        _api_request_count += 1
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                #_LOGGER.debug(f"Got response with status: {response.status}")
                if response.status == 200:
                    data = await response.text()
                    
                    try:
                        # Parse JSON response - DMX data will always be in a "dmx" field
                        json_data = json.loads(data)
                        if "dmx" in json_data:
                            dmx_values = json_data["dmx"]
                            
                            # Map channel to status - channels in DMX start at 1, but array is 0-indexed
                            for channel in int_channels:
                                if 0 <= channel-1 < len(dmx_values):  # Adjust index by -1
                                    channel_value = dmx_values[channel-1]
                                    dmx_status = channel_value != DMX_OFF_VALUE
                                    dmx_status_dict[channel] = dmx_status
                                else:
                                    _LOGGER.warning(f"Channel {channel} is out of range (max: {len(dmx_values)})")
                            
                            _last_successful_api_call = datetime.now()
                        else:
                            _LOGGER.error(f"Expected 'dmx' key not found in JSON response: {json_data}")
                            _api_failure_count += 1
                            
                    except json.JSONDecodeError as e:
                        _LOGGER.error(f"Error parsing JSON response: {e}, data: '{data}'")
                        _api_failure_count += 1
                else:
                    _LOGGER.debug(f"DMX request failed with status {response.status}, response: {await response.text()}")
                    _api_failure_count += 1
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        _LOGGER.debug(f"Network error making DMX request: {type(err).__name__}: {err}")
        _api_failure_count += 1
    except Exception as err:
        _LOGGER.debug(f"Unexpected error in DMX request: {type(err).__name__}: {err}")
        _api_failure_count += 1
    
    return dmx_status_dict


async def async_get_dmx_status(ip_address: str, channel: int, ola_port: int = DEFAULT_OLA_PORT) -> Optional[bool]:
    """Get DMX status for a specific channel."""
    global _last_successful_api_call, _api_failure_count, _api_request_count
    
    _LOGGER.debug(f"DMX STATUS REQUEST - Channel: {channel}, IP: {ip_address}, Port: {ola_port}")
    
    if not ip_address or not ola_port:
        _LOGGER.debug("Missing IP address or OLA port for DMX request")
        return None
    
    url = f"http://{ip_address}:{ola_port}/get_dmx?u=1"
    
    try:
        _api_request_count += 1
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                _LOGGER.debug(f"Got response with status: {response.status}")
                if response.status == 200:
                    data = await response.text()
                    try:
                        # Parse JSON response
                        json_data = json.loads(data)
                        if "dmx" in json_data:
                            dmx_values = json_data["dmx"]
                            
                            # DMX channels start at 1, but array is 0-indexed
                            if 0 <= channel-1 < len(dmx_values):
                                value = dmx_values[channel-1]  # Adjust index by -1
                                dmx_status = value != DMX_OFF_VALUE
                                _last_successful_api_call = datetime.now()
                                return dmx_status
                            else:
                                _LOGGER.warning(f"Channel {channel} is out of range (max: {len(dmx_values)})")
                        else:
                            _LOGGER.error(f"Expected 'dmx' key not found in JSON response: {json_data}")
                    except json.JSONDecodeError as e:
                        _LOGGER.debug(f"Invalid JSON response format: '{data}' - Error: {e}")
                        _api_failure_count += 1
                else:
                    _LOGGER.debug(f"DMX request failed with status {response.status}, response: {await response.text()}")
                    _api_failure_count += 1
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        _LOGGER.debug(f"Network error making DMX request: {type(err).__name__}: {err}")
        _api_failure_count += 1
    except Exception as err:
        _LOGGER.debug(f"Unexpected error in DMX request: {type(err).__name__}: {err}")
        _api_failure_count += 1
    
    return None


async def async_set_dmx_values(ip_address: str, channel_values: Dict[int, str], ola_port: int = 9090) -> bool:
    """Set DMX values for channels.
    
    Args:
        ip_address: IP address of the OLA server
        channel_values: Dictionary mapping channel numbers (starting at 1) to values
        ola_port: Port for the OLA server
    
    Returns:
        True if successful, False otherwise
    """
    global _dmx_api_stats
    _dmx_api_stats["request_count"] += 1
    
    try:
        # Find the maximum channel number to determine array size
        max_channel = max(channel_values.keys()) if channel_values else 0
        
        # Create array of values where index position corresponds to channel-1
        # (since DMX channels start at 1, but array indices start at 0)
        value_array = ["0"] * max_channel
        
        # Set values in the array according to channel mapping
        for channel, value in channel_values.items():
            if 1 <= channel <= max_channel:
                value_array[channel-1] = value
        
        # Format the data parameter as simple comma-separated values
        data_param = ",".join(value_array)
        
        # Build the curl command with properly formatted parameters
        cmd = f'curl -X POST -d "u=1&d={data_param}" http://{ip_address}:{ola_port}/set_dmx'
        
        # Log the curl command prominently so it's visible in the logs
        _LOGGER.warning(f"CURL COMMAND: {cmd}")  # Use warning level for better visibility
        
        # Execute the curl command
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            _LOGGER.error(f"Error setting DMX values: {stderr.decode()}")
            _dmx_api_stats["failure_count"] += 1
            _dmx_api_stats["success_rate"] = ((_dmx_api_stats["request_count"] - _dmx_api_stats["failure_count"]) / 
                                             _dmx_api_stats["request_count"]) * 100.0
            return False
            
        # Log the response
        _LOGGER.info(f"DMX command response: {stdout.decode()}")
        _dmx_api_stats["last_successful_call"] = datetime.now()
        _dmx_api_stats["success_rate"] = ((_dmx_api_stats["request_count"] - _dmx_api_stats["failure_count"]) / 
                                         _dmx_api_stats["request_count"]) * 100.0
        return True
        
    except Exception as e:
        _LOGGER.error(f"Failed to set DMX values: {str(e)}")
        _dmx_api_stats["failure_count"] += 1
        _dmx_api_stats["success_rate"] = ((_dmx_api_stats["request_count"] - _dmx_api_stats["failure_count"]) / 
                                         _dmx_api_stats["request_count"]) * 100.0
        return False


def is_dmx_api_available() -> bool:
    """Check if the DMX API is currently available."""
    global _last_successful_api_call
    
    if _last_successful_api_call is None:
        return True
        
    time_since_last_success = datetime.now() - _last_successful_api_call
    return time_since_last_success.total_seconds() < DMX_API_TIMEOUT


def get_dmx_api_stats() -> Dict[str, Any]:
    """Return current DMX API statistics."""
    return _dmx_api_stats
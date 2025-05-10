"""Utility functions for Savant Energy integration.
Provides DMX, API, and helper routines for the integration.
All utility functions are now documented for clarity and open source maintainability.
"""

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
DMX_ADDRESS_CACHE_SECONDS: Final = 3600  # Cache DMX address for 1 hour

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

# DMX address cache to minimize API calls
_dmx_address_cache = {}  # Maps DMX UID -> {"address": int, "timestamp": datetime}


def calculate_dmx_uid(uid: str) -> str:
    """
    Calculate the DMX UID based on the device UID, incrementing as hex if needed.
    Args:
        uid: Device UID string
    Returns:
        DMX UID string in the format XXXX:YYYYYY
    """
    base_uid = uid.split(".")[0]
    base_uid = f"{base_uid[:4]}:{base_uid[4:]}"
    if uid.endswith(".1"):
        prefix = base_uid[:-2]
        last_two = base_uid[-2:]
        try:
            incremented = f"{int(last_two, 16) + 1:02X}"
        except Exception:
            incremented = last_two
        base_uid = prefix + incremented
    return base_uid


async def async_get_dmx_address(ip_address: str, ola_port: int, universe: int, dmx_uid: str) -> Optional[int]:
    """
    Get DMX address for a device using the RDM API.
    Args:
        ip_address: IP address of the OLA server
        ola_port: OLA server port
        universe: DMX universe ID (usually 1)
        dmx_uid: The DMX UID of the device
    Returns:
        The DMX address as an integer or None if not found
    """
    global _dmx_address_cache
    
    cache_key = f"{dmx_uid}"
    now = datetime.now()
    
    # Check cache for existing DMX address
    if cache_key in _dmx_address_cache:
        cache_entry = _dmx_address_cache[cache_key]
        if (now - cache_entry["timestamp"]).total_seconds() < DMX_ADDRESS_CACHE_SECONDS:
            _LOGGER.debug(f"Using cached DMX address {cache_entry['address']} for device {dmx_uid}")
            return cache_entry["address"]
    
    if not ip_address or not ola_port:
        _LOGGER.warning("Missing IP address or OLA port for DMX address request")
        return None
    
    url = f"http://{ip_address}:{ola_port}/json/rdm/uid_info?id={universe}&uid={dmx_uid}"
    _LOGGER.debug(f"Fetching DMX address from: {url}")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    text_response = await response.text()
                    _LOGGER.debug(f"RDM raw text response: {text_response}")
                    
                    try:
                        data = json.loads(text_response)
                        _LOGGER.debug(f"RDM parsed JSON response: {data}")
                        
                        if "address" in data:
                            address = int(data["address"])
                            _dmx_address_cache[cache_key] = {
                                "address": address,
                                "timestamp": now
                            }
                            return address
                        else:
                            _LOGGER.warning(f"No 'address' field in RDM response: {data}")
                    except json.JSONDecodeError as json_err:
                        _LOGGER.warning(f"Failed to parse JSON from response: {json_err}. Text: {text_response}")
                else:
                    _LOGGER.warning(f"Failed to get DMX address, status: {response.status}, response: {await response.text()}")
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        _LOGGER.warning(f"Network error fetching DMX address: {type(err).__name__}: {err}")
    except json.JSONDecodeError as err:
        _LOGGER.warning(f"Invalid JSON in DMX address response: {err}")
    except Exception as err:
        _LOGGER.warning(f"Unexpected error fetching DMX address: {type(err).__name__}: {err}")
    
    return None


async def async_get_all_dmx_status(ip_address: str, channels: List[int], ola_port: int = DEFAULT_OLA_PORT) -> Dict[int, bool]:
    """
    Get DMX status for specified channels in one batch.
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
    
    dmx_status_dict = {}
    
    try:
        _api_request_count += 1
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.text()
                    
                    try:
                        json_data = json.loads(data)
                        if "dmx" in json_data:
                            dmx_values = json_data["dmx"]
                            
                            for channel in int_channels:
                                if 0 <= channel-1 < len(dmx_values):
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
    """
    Get DMX status for a specific channel.
    Args:
        ip_address: IP address of the OLA server
        channel: DMX channel number
        ola_port: OLA server port
    Returns:
        Boolean status (True = on, False = off) or None if unavailable
    """
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
                        json_data = json.loads(data)
                        if "dmx" in json_data:
                            dmx_values = json_data["dmx"]
                            
                            if 0 <= channel-1 < len(dmx_values):
                                value = dmx_values[channel-1]
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


async def _execute_curl_command(cmd: str) -> tuple[int, str, str]:
    """
    Execute the given curl command asynchronously.
    Args:
        cmd: Curl command string
    Returns:
        Tuple containing (returncode, stdout, stderr)
    """
    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    return process.returncode, stdout.decode(), stderr.decode()


async def async_set_dmx_values(ip_address: str, channel_values: Dict[int, str], ola_port: int = 9090, testing_mode: bool = False) -> bool:
    """
    Set DMX values for channels.
    Args:
        ip_address: IP address of the OLA server
        channel_values: Dictionary mapping channel numbers (starting at 1) to values
        ola_port: Port for the OLA server
        testing_mode: If True, only log the command without executing it
    Returns:
        True if successful, False otherwise
    """
    global _dmx_api_stats
    _dmx_api_stats["request_count"] += 1
    
    try:
        max_channel = max(channel_values.keys()) if channel_values else 0
        
        value_array = ["0"] * max_channel
        
        for channel, value in channel_values.items():
            if 1 <= channel <= max_channel:
                if str(value) == "255" or str(value).lower() == "on" or str(value) == "1":
                    value_array[channel-1] = "255"
                else:
                    value_array[channel-1] = "0"
        
        data_param = ",".join(value_array)
        
        cmd = f'curl -X POST -d "u=1&d={data_param}" http://{ip_address}:{ola_port}/set_dmx'
        
        log_level = logging.INFO if testing_mode else logging.DEBUG
        _LOGGER.log(log_level, f"DMX COMMAND {'(TESTING MODE - NOT SENT)' if testing_mode else '(sending)'}: {cmd}")
        
        if testing_mode:
            _dmx_api_stats["last_successful_call"] = datetime.now()
            _dmx_api_stats["success_rate"] = ((_dmx_api_stats["request_count"] - _dmx_api_stats["failure_count"]) / 
                                            _dmx_api_stats["request_count"]) * 100.0
            return True
        
        returncode, stdout, stderr = await _execute_curl_command(cmd)
        if returncode != 0:
            _LOGGER.error(f"Error setting DMX values: {stderr}")
            _dmx_api_stats["failure_count"] += 1
            _dmx_api_stats["success_rate"] = ((_dmx_api_stats["request_count"] - _dmx_api_stats["failure_count"]) / 
                                            _dmx_api_stats["request_count"]) * 100.0
            return False
        _LOGGER.info(f"DMX command response: {stdout}")

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
    """
    Check if the DMX API is currently available.
    Returns:
        True if the API is available, False otherwise
    """
    global _last_successful_api_call
    
    if _last_successful_api_call is None:
        return True
        
    time_since_last_success = datetime.now() - _last_successful_api_call
    return time_since_last_success.total_seconds() < DMX_API_TIMEOUT


def get_dmx_api_stats() -> Dict[str, Any]:
    """
    Return current DMX API statistics.
    Returns:
        Dictionary containing API statistics
    """
    return _dmx_api_stats
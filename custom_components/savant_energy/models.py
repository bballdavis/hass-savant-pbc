"""Models and device information functions for Savant Energy."""

from typing import Union

def get_device_model(capacity: Union[int, float, None]) -> str:
    """Determine device model based on capacity."""
    if capacity is None:
        return "Unknown"
    
    match capacity:
        case 2.4:
            return "Dual 20A Relay"
        case 7.2:
            return "30A Relay"
        case 14.4:
            return "60A Relay"
        case _:
            return "Unknown Model"

"""
Models and device information functions for Savant Energy.
Provides helpers for device model identification based on relay capacity.
All functions are now documented for clarity and open source maintainability.
"""

from typing import Union

def get_device_model(capacity: Union[int, float, None]) -> str:
    """
    Determine device model based on relay capacity.
    Args:
        capacity: The relay's capacity in kW (float or int)
    Returns:
        A string describing the device model.
    """
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

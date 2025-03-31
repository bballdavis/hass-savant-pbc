"""Models for the Savant Energy integration."""


def get_device_model(capacity: float) -> str:
    """Determine the device model based on capacity."""
    match capacity:
        case 2.4:
            return "Dual 20A Relay"
        case 7.2:
            return "30A Relay"
        case 14.4:
            return "60A Relay"
        case _:
            return "Unknown Model"

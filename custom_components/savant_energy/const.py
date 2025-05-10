"""Constants for the Savant Energy integration.
Defines all configuration keys, defaults, and branding info used throughout the integration.
All constants are now documented for clarity and open source maintainability.
"""

# Domain name for the integration
DOMAIN = "savant_energy"

# List of Home Assistant platforms supported by this integration
PLATFORMS = ["sensor", "binary_sensor", "switch", "button"]

# Configuration keys
CONF_ADDRESS = "address"  # IP address of Savant controller
CONF_PORT = "port"        # Port for energy snapshot data
CONF_OLA_PORT = "ola_port"  # Port for OLA/DMX API
CONF_SCAN_INTERVAL = "scan_interval"  # Polling interval (seconds)
CONF_SWITCH_COOLDOWN = "switch_cooldown"  # Minimum seconds between relay toggles
CONF_DMX_TESTING_MODE = "dmx_testing_mode"  # Enable advanced DMX testing mode

# Default values
DEFAULT_SWITCH_COOLDOWN = 30  # Default cooldown of 30 seconds
DEFAULT_PORT = 2000           # Default Savant energy port
DEFAULT_OLA_PORT = 9090       # Default OLA/DMX API port

# Manufacturer branding
MANUFACTURER = "Savant"

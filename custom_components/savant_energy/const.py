"""Constants for the Savant Energy integration."""

DOMAIN = "savant_energy"
PLATFORMS = ["sensor", "binary_sensor", "switch", "button"]  # Added button to platforms

CONF_ADDRESS = "address"
CONF_PORT = "port"
CONF_OLA_PORT = "ola_port"

CONF_SCAN_INTERVAL = "scan_interval"
CONF_SWITCH_COOLDOWN = "switch_cooldown"
DEFAULT_SWITCH_COOLDOWN = 30  # Default cooldown of 30 seconds
DEFAULT_PORT = 2000
DEFAULT_OLA_PORT = 9090

# Used for branding
MANUFACTURER = "Savant"

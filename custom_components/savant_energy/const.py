"""Constants for the Savant Energy integration."""

DOMAIN = "savant_energy"
PLATFORMS = ["sensor", "binary_sensor", "switch"]

CONF_ADDRESS = "address"
CONF_PORT = "port"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_SWITCH_COOLDOWN = "switch_cooldown"
DEFAULT_SWITCH_COOLDOWN = 30  # Default cooldown of 30 seconds

# Used for branding
MANUFACTURER = "Savant"

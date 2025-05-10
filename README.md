# Savant Energy Home Assistant Integration

Welcome to the **Savant Energy** integration for Home Assistant! This project brings Savant relay and energy monitoring devices into your smart home, providing real-time power, voltage, relay control, and more—all with a beautiful, open-source touch.

## 🚀 Features
- **Automatic device discovery** from your Savant system
- **Power and voltage sensors** for each relay
- **Relay (breaker) switch control** with configurable cooldown
- **Binary sensors** for relay status
- **Button entities** for diagnostics and control
- **DMX address sensors** for advanced users

## 🛠️ Installation (via HACS)
1. **Add the repository to HACS**:
   - In Home Assistant, go to **HACS > Integrations > Custom repositories**.
   - Add your fork or this repo's URL: `https://github.com/bballdavis/hass-savant-pbc`.
   - Set category to **Integration**.
2. **Install the integration**:
   - Search for **Savant Energy** in HACS and click **Install**.
3. **Restart Home Assistant** to load the integration.
4. **Add the integration**:
   - Go to **Settings > Devices & Services > Add Integration**.
   - Search for **Savant Energy** and follow the prompts (enter your Savant controller's IP, port, and OLA port if needed).

## ⚡ How to Use
Once installed and configured, the integration will automatically create entities for each Savant relay device it discovers. Here’s what you’ll see:

### Entity Breakdown
- **Power Sensor (`sensor.<device>_power`)**: Shows the real-time power usage (Watts) for each relay.
- **Voltage Sensor (`sensor.<device>_voltage`)**: Displays the current voltage (Volts) for each relay.
- **Breaker Switch (`switch.<device>_breaker`)**: Lets you turn the relay on/off. Includes a configurable cooldown (default: 30 seconds) to prevent rapid toggling and protect your hardware.
- **Relay Status Binary Sensor (`binary_sensor.<device>_relay_status`)**: Indicates if the relay is currently ON or OFF.
- **DMX Address Sensor (`sensor.<device>_dmx_address`)**: (Advanced) Shows the DMX address assigned to the relay.
- **Diagnostic Buttons**:
  - **All Loads On**: Instantly turns on all relays.
  - **API Command Log**: Logs a sample DMX API command for troubleshooting.
  - **API Stats**: Shows DMX API health and statistics.

## 📝 Configuration Options
- **IP Address**: The address of your Savant controller.
- **Port**: The port for energy snapshot data (default: 2000).
- **OLA Port**: The port for DMX/OLA API (default: 9090).
- **Scan Interval**: How often to poll for new data (default: 15s).
- **Breaker Cooldown**: Minimum seconds between relay toggles (default: 30s).
- **DMX Testing Mode**: Enable for advanced DMX testing (optional).

## 🧑‍💻 Contributing
We love contributions! Please:
- Open issues for bugs or feature requests
- Submit pull requests with clear descriptions
- Follow the code style and add docstrings/comments

## 📚 File Structure
- `__init__.py`: Integration setup and coordinator logic
- `sensor.py`, `power_device_sensor.py`: Power/voltage sensors
- `switch.py`: Relay (breaker) switch logic
- `binary_sensor.py`: Relay status sensors
- `button.py`: Diagnostic and control buttons
- `dmx_address_sensor.py`: DMX address sensors
- `utils.py`: Utility functions (DMX, API, etc.)
- `snapshot_data.py`: Fetches energy snapshot from Savant
- `models.py`: Device model helpers
- `const.py`: Constants

## 🏷️ License
This project is licensed under the GNU GPL v3. See `LICENSE` for details.

---

**Enjoy your smarter, more open Savant system!**

For help, visit the [GitHub repo](https://github.com/bballdavis/hass-savant-pbc) or open an issue.

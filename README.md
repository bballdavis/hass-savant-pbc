# Savant Energy Home Assistant Integration

Welcome to the **Savant Energy** integration for Home Assistant! This project brings Savant relay and energy monitoring devices into your smart home, providing real-time power, voltage, relay control, and more—all with a beautiful, open-source touch.

## 🚀 Features
- **Automatic device discovery** from your Savant system
- **Power and voltage sensors** for each relay
- **Relay (breaker) switch control** with configurable cooldown
- **Relay Binary sensors** for relay status
- **All Loads On Button** to quickly turn all loads on
- **DMX address sensors** for controlling individual breakers
- **Custom Lovelace card** for managing energy scenes

## 🛠️ Installation (via HACS)
1. **Add the repository to HACS**:
   - In Home Assistant, go to **HACS > Integrations > Custom repositories**.
   - Add your fork or this repo's URL: `https://github.com/bballdavis/HASS-Savant-Energy`.
   - Set category to **Integration**.
2. **Install the integration**:
   - Search for **Savant Energy** in HACS and click **Install**.
3. **Restart Home Assistant** to load the integration.
4. **Add the integration**:
   - Go to **Settings > Devices & Services > Add Integration**.
   - Search for **Savant Energy** and follow the prompts.
   - Add you Panel Controller Bridge's (PCB) IP address.
   - The port defaults should work, but you can change it if needed.

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

## 📱 Savant Energy Scenes Card

### Using the Card
The integration includes a custom Lovelace card for managing Savant Energy scenes. To use it:

1. Edit any dashboard
2. Click "Add Card"
3. Choose "Manual" at the bottom
4. Enter the following YAML:
```yaml
type: custom:savant-energy-scenes-card
```

### Card Features
- Create, edit, and delete Savant Energy scenes
- Control which relays are active in each scene
- Simple and intuitive interface for managing scenes

### Troubleshooting the Card
If the card doesn't load with an error like "Custom element doesn't exist: savant-energy-scenes-card":

1. Verify the integration is properly set up
2. Check that the JS file exists in `/config/www/savant-energy-scenes-card.js`
3. Verify resource registration: Settings > Dashboards > Resources
4. If needed, add the resource manually: `/local/savant-energy-scenes-card.js` with type `module`
5. Clear your browser cache and reload Home Assistant

## 📝 Configuration Options
- **IP Address**: The address of your Savant controller.
- **Port**: The port for energy snapshot data (default: 2000).
- **OLA Port**: The port for DMX/OLA API (default: 9090).
- **Scan Interval**: How often to poll for new data (default: 15s).
- **Breaker Cooldown**: Minimum seconds between relay toggles (default: 30s).
- **DMX Testing Mode**: Enable for advanced DMX testing (optional). This mode is a testing mode for viewing the DMX command to be sent without actually sending it (console only).

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

For help, visit the [GitHub repo](https://github.com/bballdavis/HASS-Savant-Energy) or open an issue.

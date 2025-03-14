# custom_components/energy_snapshot/snapshot_data.py
import socket
import base64
import json
import logging

_LOGGER = logging.getLogger(__name__)

def get_current_energy_snapshot(address, port):
    """Retrieves the current energy snapshot."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((address, port))
            data = s.recv(100000)

        if not data:
            _LOGGER.error("No data received")
            return None

        _LOGGER.error(f"Data received: {data[:100]}... (length: {len(data)})")

        data_str = data.decode('utf-8')
        _LOGGER.error(f"Data string: {data_str[:100]}... (length: {len(data_str)})")

        if "\n" in data_str:
            data_str = data_str.split("\n", 1)[1]

        if data_str.startswith("SET_ENERGY="):
            data_str = data_str[len("SET_ENERGY="):]

        _LOGGER.error(f"Processed data string: {data_str[:100]}... (length: {len(data_str)})")

        try:
            decoded_string = base64.b64decode(data_str).decode('utf-8')
            _LOGGER.error(f"Decoded string: {decoded_string[:100]}... (length: {len(decoded_string)})")
        except (base64.binascii.Error) as e:
            _LOGGER.error(f"Decode Error: {e}, Data Length: {len(data_str)}")
            return None
        try:
            json_data = json.loads(decoded_string)
            return json_data
        except (json.JSONDecodeError) as e:
            _LOGGER.error(f"JSON Error: {e}, JSON: {decoded_string}")
            return None

    except socket.error as e:
        _LOGGER.error(f"Socket Error: {e}")
        return None
    except Exception as e:
        _LOGGER.error(f"Unexpected Error: {e}")
        return None
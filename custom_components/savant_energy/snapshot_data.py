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
            data = b""
            set_energy_found = False
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
                if data.count(b"\n") >= 2:
                    break

        if not data:
            return None

        data_str = data.decode("utf-8")

        # Extract the value of SET_ENERGY
        if "SET_ENERGY=" in data_str:
            data_str = data_str.split("SET_ENERGY=", 1)[1]

        # Strip off everything after the newline that follows SET_ENERGY
        if "\n" in data_str:
            data_str = data_str.split("\n", 1)[0]

        _LOGGER.debug(f"Data after decode length: {len(data_str)})")

        if "\n" in data_str:
            data_str = data_str.split("\n", 1)[1]

        if data_str.startswith("SET_ENERGY="):
            data_str = data_str[len("SET_ENERGY=") :]

        _LOGGER.debug(
            f"Processed data string: {data_str[:100]}... (length: {len(data_str)})"
        )

        try:
            decoded_string = base64.b64decode(data_str).decode("utf-8")
            _LOGGER.debug(
                f"Decoded string: {decoded_string[:100]}... (length: {len(decoded_string)})"
            )
        except base64.binascii.Error as e:
            _LOGGER.error(f"Decode Error: {e}, Data Length: {len(data_str)}")
            return None
        try:
            json_data = json.loads(decoded_string)
            return json_data
        except json.JSONDecodeError as e:
            _LOGGER.error(f"JSON Error: {e}, JSON: {decoded_string}")
            return None

    except socket.error as e:
        _LOGGER.error(f"Socket Error: {e}")
        return None
    except Exception as e:
        _LOGGER.error(f"Unexpected Error: {e}")
        return None

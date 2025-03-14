import socket
import base64
import json
import logging

def get_current_energy_snapshot(address, port):
    """Retrieves the current energy snapshot."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((address, port))
            data = s.recv(20000)

        if not data:
            return None

        data_str = data.decode('utf-8')

        if "\n" in data_str:
            data_str = data_str.split("\n", 1)[1]

        if data_str.startswith("SET_ENERGY="):
            data_str = data_str[len("SET_ENERGY="):]

        try:
            decoded_string = base64.b64decode(data_str).decode('utf-8')
            json_data = json.loads(decoded_string)
            return json_data
        except (base64.binascii.Error, json.JSONDecodeError) as e:
            print(f"Decode/JSON Error: {e}, Data Length: {len(data_str)}")
            return None

    except socket.error as e:
        print(f"Socket Error: {e}")
        return None
    except Exception as e:
        print(f"Unexpected Error: {e}")
        return None

# Example usage
if __name__ == "__main__":
    address = "192.168.1.108"  # Replace with the actual address
    port = 2000  # Replace with the actual port
    snapshot = get_current_energy_snapshot(address, port)
    if snapshot:
        with open("output.json", "w") as outfile:
            json.dump(snapshot, outfile, indent=4)
        print("Energy Snapshot saved to output.json")
    else:
        print("Failed to retrieve energy snapshot.")
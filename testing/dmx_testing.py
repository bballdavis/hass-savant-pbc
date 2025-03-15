import ola.ClientWrapper as ola

def set_dmx_value(universe, channel, value):
    """Sets a DMX value to either 0 or 255 (representing 0% or 100%).

    Args:
        universe: The DMX universe (integer).
        channel: The DMX channel (integer).
        value: 0 for off (0%), 1 for on (100%).
    """

    if value not in [0, 1]:
        raise ValueError("Value must be 0 or 1.")

    data = ola.DmxData(512)  # Create a DmxData object (512 channels)
    dmx_value = 255 if value == 1 else 0  # 255 for 100%, 0 for 0%
    data.SetChannel(channel - 1, dmx_value) #channel indexing begins at 0 in OLA

    def send_dmx():
        client.SendDmx(universe, data, lambda state: None)  # Send the DMX data

    client = ola.ClientWrapper()
    client.Run(send_dmx)

# Example usage:
universe_number = 1  # Replace with your universe number
channel_number = 2  # Replace with your channel number
on_off = 1  # 1 for on, 0 for off

set_dmx_value(universe_number, channel_number, on_off)

# Example to turn off the same channel:
on_off = 0;
#set_dmx_value(universe_number, channel_number, on_off)

#Example to turn on channel 5 of universe 0
#set_dmx_value(0,5,1)
import usb.core
import usb.util

# Find the USB device
dev = usb.core.find(idVendor=0x1a86, idProduct=0x7523)

# Make sure the device was found
if dev is None:
    raise ValueError("Device not found")

# Set the active configuration
dev.set_configuration()

# Interface 0, Bulk IN endpoint 0x82 (make sure this is correct for your device)
endpoint = 0x82

# Loop to continuously read data
while True:

    raw_data = dev.read(endpoint, 7)
    db_value = (raw_data[1] * 256 + raw_data[2])/10 
    # Print the dB value directly
    print(db_value)
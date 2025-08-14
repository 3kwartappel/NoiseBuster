import usb.core
import usb.util

# Find device
dev = usb.core.find(idVendor=0x16C0, idProduct=0x05DC)

if dev is None:
    print("Device not found")
else:
    print("Device found:", dev)

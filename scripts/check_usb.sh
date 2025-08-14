#!/usr/bin/env bash
# Small helper script moved from pythontest.py to scripts/
# Usage: ./scripts/check_usb.sh

python - <<'PY'
import usb.core

dev = usb.core.find(idVendor=0x16c0, idProduct=0x05dc)
if dev is None:
    print("Device not found")
else:
    print("Device found:", dev)
PY

# Optional: a handy system watch command for debugging (uncomment to use)
# watch -n 10 "echo -n \$(date '+%F %T')' | CPU: '; top -bn1 | grep 'Cpu(s)' | awk '{print 100 - \$8 \"%\"}'; free -m | awk '/Mem:/ {printf \" | Mem Used: %dMB | Mem Free: %dMB\", \$3, \$4}'; df -h / | awk 'END {printf \" | Disk Used: %s\", \$5}'; vcgencmd measure_temp | sed 's/temp=/ | Temp: /'"

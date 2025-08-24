#!/bin/bash

# Usage: ./run_pi.sh [duration_seconds]
# If duration_seconds is provided and >0, it will be passed to noisebuster.py as
# --test-duration <duration_seconds>. If omitted or 0, noisebuster.py runs normally.

DURATION=${1:-0}

if [ "$DURATION" -gt 0 ] 2>/dev/null; then
  REMOTE_CMD="cd code/NoiseBuster; source env/bin/activate; python -m src.noisebuster --test-duration $DURATION; bash"
else
  REMOTE_CMD="cd code/NoiseBuster; source env/bin/activate; python -m src.noisebuster; bash"
fi

ssh -t pi@192.168.0.112 "$REMOTE_CMD"

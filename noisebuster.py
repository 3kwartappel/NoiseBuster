#!/usr/bin/env python3
# NoiseBuster - created by Raphaël Vael (Main Dev)
# License: CC BY-NC 4.0
import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
import traceback
import socket
from queue import Queue
import schedule

# Only use libcamera-vid for video recording
try:
    from dotenv import load_dotenv
except Exception:
    # dotenv not available in all environments; make load_dotenv a no-op
    def load_dotenv():
        return None


from video_recording import start_video_buffer, stop_video_buffer
from video_recording import trigger_event_recording as vr_trigger


def load_config(config_path):
    with open(config_path, "r") as config_file:
        config = json.load(config_file)
    return config


config = None
try:
    config = load_config("config.json")
    load_dotenv()
    influx_token = os.getenv("INFLUXDB_TOKEN")
    if influx_token:
        config["INFLUXDB_CONFIG"]["token"] = influx_token
except json.JSONDecodeError as e:
    print(f"Error parsing config.json: {e}")
    sys.exit(1)
except FileNotFoundError as e:
    print(f"Configuration file not found: {e}")
    sys.exit(1)

# Now actually import them
import usb.core
import usb.util


def record_video_libcamera(filename, duration=5, resolution="1024x768", framerate=10):
    """Simple one-off recording (kept for fallback)."""
    width, height = resolution.split("x")
    cmd = [
        "libcamera-vid",
        "-t",
        str(duration * 1000),
        "-o",
        filename,
        "--width",
        width,
        "--height",
        height,
        "--framerate",
        str(framerate),
        "-n",
        "--inline",
    ]
    try:
        subprocess.run(cmd, check=True)
        logger.info(f"Video recorded: {filename}")
    except Exception as e:
        logger.error(f"libcamera-vid failed: {e}")


def trigger_video_recording(noise_level, config):
    """Proxy to video_recording module trigger."""
    if not VIDEO_CONFIG.get("enabled"):
        return False
    return vr_trigger(
        noise_level=noise_level, video_config=config.get("VIDEO_CONFIG", {})
    )


# We'll keep optional modules as None if not installed or not enabled
InfluxDBClient = None
SYNCHRONOUS = None
cv2 = None
np = None
write_api = None
failed_writes_queue = Queue()
global_picam2 = None


# Load config from config.json
def load_config(config_path):
    with open(config_path, "r") as config_file:
        config = json.load(config_file)
    return config


# (config already loaded earlier)

# Extract main sections of the config
INFLUXDB_CONFIG = config.get("INFLUXDB_CONFIG", {})
CAMERA_CONFIG = config.get("CAMERA_CONFIG", {})
IMAGE_STORAGE_CONFIG = config.get("IMAGE_STORAGE_CONFIG", {})
DEVICE_AND_NOISE_MONITORING_CONFIG = config.get(
    "DEVICE_AND_NOISE_MONITORING_CONFIG", {}
)
TIMEZONE_CONFIG = config.get("TIMEZONE_CONFIG", {})
VIDEO_CONFIG = config.get("VIDEO_CONFIG", {})

# removed inline buffer helpers; using video_recording module


# Retrieve USB device IDs from the config
usb_vendor_id_str = DEVICE_AND_NOISE_MONITORING_CONFIG.get("usb_vendor_id", "")
usb_product_id_str = DEVICE_AND_NOISE_MONITORING_CONFIG.get("usb_product_id", "")

usb_vendor_id_int = int(usb_vendor_id_str, 16) if usb_vendor_id_str else None
usb_product_id_int = int(usb_product_id_str, 16) if usb_product_id_str else None


####################################
# LOGGING CONFIGURATION
####################################
class ColoredFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[37m",  # White
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[41m",  # Red background
    }
    RESET = "\033[0m"

    def format(self, record):
        # Do not mutate record.msg (other handlers may rely on it).
        color = self.COLORS.get(record.levelname, self.RESET)
        formatted = super().format(record)
        return f"{color}{formatted}{self.RESET}"


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Console handler
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
console_formatter = ColoredFormatter("%(asctime)s - %(levelname)s - %(message)s")
ch.setFormatter(console_formatter)
logger.addHandler(ch)

# File handler: only add if LOCAL_LOGGING is enabled in config
if config.get("LOCAL_LOGGING", True):
    # Use a rotating file handler to avoid truncating logs and keep recent history.
    fh = RotatingFileHandler("noisebuster.log", maxBytes=5_000_000, backupCount=3)
    fh.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    fh.setFormatter(file_formatter)
    logger.addHandler(fh)
    logger.info("Detailed logs are saved in 'noisebuster.log'.")
else:
    logger.info("Local logging has been disabled in config.json.")


####################################
# LOAD USB IDs
####################################
def load_usb_ids(usb_ids_path):
    usb_ids = []
    try:
        with open(usb_ids_path, "r") as usb_ids_file:
            for line in usb_ids_file:
                # remove comments
                line_content, sep, comment = line.partition("#")
                line_content = line_content.strip()
                if not line_content:
                    continue
                parts = line_content.split(",")
                if len(parts) >= 2:
                    vendor_id_str, product_id_str = parts[0], parts[1]
                    model = comment.strip() if comment else "Unknown model"
                    vendor_id = int(vendor_id_str, 16)
                    product_id = int(product_id_str, 16)
                    usb_ids.append((vendor_id, product_id, model))
                else:
                    logger.warning(f"Incorrect format in USB IDs file: {line.strip()}")
    except FileNotFoundError:
        logger.warning(
            f"USB IDs file '{usb_ids_path}' not found. Automatic detection may fail."
        )
    return usb_ids


usb_ids = load_usb_ids("usb_ids")


####################################
# IMPORT OPTIONAL MODULES
####################################
def import_optional_modules():
    global InfluxDBClient, SYNCHRONOUS, cv2, np
    missing_optional_modules = []

    # Influx
    if INFLUXDB_CONFIG.get("enabled"):
        try:
            from influxdb_client import InfluxDBClient as InfluxDBClientImported
            from influxdb_client.client.write_api import (
                SYNCHRONOUS as SYNCHRONOUS_IMPORTED,
            )

            InfluxDBClient = InfluxDBClientImported
            SYNCHRONOUS = SYNCHRONOUS_IMPORTED
        except ImportError:
            logger.error("InfluxDB client library not installed ('influxdb-client').")
            missing_optional_modules.append("influxdb_client")

    # Camera
    if CAMERA_CONFIG.get("use_ip_camera") or CAMERA_CONFIG.get("use_pi_camera"):
        try:
            import cv2 as cv2_imported
            import numpy as np_imported

            cv2 = cv2_imported
            np = np_imported
        except ImportError:
            logger.error(
                "OpenCV or numpy not installed. Please install 'opencv-python' + 'numpy'."
            )
            missing_optional_modules.append("opencv-python, numpy")
    # Pi Camera
    if CAMERA_CONFIG.get("use_pi_camera"):
        try:
            # Use importlib to test availability without creating unused symbols
            import importlib

            importlib.import_module("picamera2")
        except ImportError:
            logger.error("Pi camera library 'picamera2' not installed.")
            missing_optional_modules.append("picamera2")

    return missing_optional_modules


missing_optional_modules = import_optional_modules()


####################################
# CONFIGURATION VALIDATION
####################################
def check_configuration():
    logger.info("Checking configuration...")

    # InfluxDB
    if INFLUXDB_CONFIG.get("enabled"):
        influxdb_missing = []
        required_fields = ["host", "port", "token", "org", "bucket", "realtime_bucket"]
        for field in required_fields:
            if not INFLUXDB_CONFIG.get(field) or str(
                INFLUXDB_CONFIG.get(field)
            ).startswith("<YOUR_"):
                influxdb_missing.append(field)
        bucket_name = INFLUXDB_CONFIG.get("bucket", "")
        realtime_bucket_name = INFLUXDB_CONFIG.get("realtime_bucket", "")
        if bucket_name != "noise_buster":
            logger.error("InfluxDB 'bucket' must be 'noise_buster'.")
            influxdb_missing.append("bucket")
        if realtime_bucket_name != "noise_buster_realtime":
            logger.error("InfluxDB 'realtime_bucket' must be 'noise_buster_realtime'.")
            influxdb_missing.append("realtime_bucket")
        if influxdb_missing:
            logger.error(
                f"InfluxDB is missing or misconfigured: {', '.join(influxdb_missing)}. Disabling."
            )
            INFLUXDB_CONFIG["enabled"] = False
        else:
            logger.info("InfluxDB is enabled and properly configured.")
    else:
        logger.info("InfluxDB is disabled.")

    # Camera
    if CAMERA_CONFIG.get("use_ip_camera"):
        needed_fields = ["ip_camera_url", "ip_camera_protocol"]
        missing = [f for f in needed_fields if not CAMERA_CONFIG.get(f)]
        if missing:
            logger.error(f"IP Camera missing: {', '.join(missing)}. Disabling.")
            CAMERA_CONFIG["use_ip_camera"] = False
        else:
            logger.info("IP camera is enabled.")
    else:
        logger.info("IP camera is disabled.")

    # Pi Camera
    if CAMERA_CONFIG.get("use_pi_camera"):
        logger.info("Pi camera is enabled.")
    else:
        logger.info("Pi camera is disabled.")

    # Video configuration check
    if VIDEO_CONFIG.get("enabled"):
        if not VIDEO_CONFIG.get("fps"):
            VIDEO_CONFIG["fps"] = 10
        if not VIDEO_CONFIG.get("buffer_seconds"):
            VIDEO_CONFIG["buffer_seconds"] = 10
        if not VIDEO_CONFIG.get("resolution"):
            VIDEO_CONFIG["resolution"] = [640, 480]
        if not VIDEO_CONFIG.get("retention_hours"):
            VIDEO_CONFIG["retention_hours"] = 24

        logger.info(
            f"Video recording enabled: {VIDEO_CONFIG['fps']}fps, {VIDEO_CONFIG['buffer_seconds']}s buffer"
        )
    else:
        logger.info("Video recording is disabled.")

    # Device & Noise
    if not DEVICE_AND_NOISE_MONITORING_CONFIG.get("minimum_noise_level"):
        logger.error("No 'minimum_noise_level' in DEVICE_AND_NOISE_MONITORING_CONFIG.")
    else:
        logger.info(
            f"Minimum noise level: {DEVICE_AND_NOISE_MONITORING_CONFIG['minimum_noise_level']} dB."
        )


check_configuration()

####################################
# USB
####################################
device_detected = False


def detect_usb_device(verbose=True):
    global device_detected
    devs = usb.core.find(find_all=True)
    for dev in devs:
        dev_vendor_id = dev.idVendor
        dev_product_id = dev.idProduct

        # If config specifically sets vendor/product
        if usb_vendor_id_int and usb_product_id_int:
            if (
                dev_vendor_id == usb_vendor_id_int
                and dev_product_id == usb_product_id_int
            ):
                if verbose or not device_detected:
                    model = next(
                        (
                            name
                            for vid, pid, name in usb_ids
                            if vid == dev_vendor_id and pid == dev_product_id
                        ),
                        None,
                    )
                    if model:
                        logger.info(
                            f"Detected specified device: {model} (Vendor {hex(dev_vendor_id)}, Product {hex(dev_product_id)})"
                        )
                    else:
                        logger.info(
                            "User-defined USB sound device detected (not in usb_ids list)."
                        )
                device_detected = True
                return dev
        else:
            # If not specifically set, check the usb_ids file
            known = next(
                (
                    m
                    for m in usb_ids
                    if m[0] == dev_vendor_id and m[1] == dev_product_id
                ),
                None,
            )
            if known:
                if verbose or not device_detected:
                    logger.info(
                        f"{known[2]} sound meter detected (Vendor {hex(dev_vendor_id)}, Product {hex(dev_product_id)})"
                    )
                device_detected = True
                return dev
            else:
                if verbose and not device_detected:
                    logger.info(
                        f"Ignoring device: Vendor {hex(dev_vendor_id)}, Product {hex(dev_product_id)}"
                    )

    # No device found
    device_detected = False
    if usb_vendor_id_int and usb_product_id_int:
        logger.error("Specified USB device not found. Check config or cable.")
    else:
        logger.error("No known USB sound meter found. Possibly not connected?")
    return None


####################################
# CAMERA
####################################


def capture_image_fast(current_peak_dB, timestamp):
    """Disabled: Use libcamera-vid for video events."""
    logger.info("capture_image_fast is disabled. Use libcamera-vid for video events.")
    return


def delete_old_images():
    image_path = DEVICE_AND_NOISE_MONITORING_CONFIG.get("image_save_path", "./images")
    if not os.path.exists(image_path):
        os.makedirs(image_path)
        logger.info(f"Created image directory: {image_path}")

    current_time = datetime.now()
    retention_hours = DEVICE_AND_NOISE_MONITORING_CONFIG.get(
        "image_retention_hours", 24
    )
    for filename in os.listdir(image_path):
        filepath = os.path.join(image_path, filename)
        if os.path.isfile(filepath):
            file_creation_time = datetime.fromtimestamp(os.path.getctime(filepath))
            time_diff = current_time - file_creation_time
            if time_diff > timedelta(hours=retention_hours):
                os.remove(filepath)
                logger.info(f"Deleted old image: {filepath}")


####################################
# MAIN NOISE MONITOR
####################################
def update_noise_level():
    """Monitor noise from USB, record events, and publish/log them."""
    window_start_time = time.time()
    current_peak_dB = 0

    usb_dev = detect_usb_device(verbose=True)
    if not usb_dev:
        logger.error("No USB device found. Exiting.")
        sys.exit(1)
    logger.info("Noise monitoring on USB device.")

    last_above_threshold = False
    while True:
        current_time = time.time()
        if (current_time - window_start_time) >= DEVICE_AND_NOISE_MONITORING_CONFIG[
            "time_window_duration"
        ]:
            timestamp = datetime.utcnow()
            delete_old_images()
            logger.info(
                f"Time window elapsed. Current peak dB: {round(current_peak_dB, 1)}"
            )

            # Realtime data
            realtime_data = [
                {
                    "measurement": "noise_buster_events",
                    "tags": {"location": "noise_buster"},
                    "time": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "fields": {"noise_level": round(current_peak_dB, 1)},
                }
            ]

            logger.info(f"Current noise level: {round(current_peak_dB, 1)} dB")

            # Influx DB (realtime bucket)
            if INFLUXDB_CONFIG.get("enabled") and InfluxDBClient and write_api:
                try:
                    write_api.write(
                        bucket=INFLUXDB_CONFIG["realtime_bucket"], record=realtime_data
                    )
                    logger.info(
                        f"All noise levels written to realtime bucket: {round(current_peak_dB, 1)} dB"
                    )
                except Exception as e:
                    logger.error(f"Failed to write to InfluxDB: {str(e)}. Queueing.")
                    failed_writes_queue.put(
                        (INFLUXDB_CONFIG["realtime_bucket"], [realtime_data])
                    )

            # If above threshold
            above_threshold = (
                current_peak_dB
                >= DEVICE_AND_NOISE_MONITORING_CONFIG["minimum_noise_level"]
            )
            # Only trigger on rising edge
            if above_threshold and not last_above_threshold:
                main_data = {
                    "measurement": "noise_buster_events",
                    "tags": {"location": "noise_buster"},
                    "time": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "fields": {"noise_level": round(current_peak_dB, 1)},
                }

                logger.info(
                    f"Noise level exceeded threshold: {round(current_peak_dB, 1)} dB"
                )

                # Influx DB main bucket
                if INFLUXDB_CONFIG.get("enabled") and InfluxDBClient and write_api:
                    try:
                        write_api.write(
                            bucket=INFLUXDB_CONFIG["bucket"], record=main_data
                        )
                        logger.info(
                            f"High noise level data written to main bucket: {main_data}"
                        )
                    except Exception as e:
                        logger.error(
                            f"Failed to write main data to InfluxDB: {str(e)}. Queueing."
                        )
                        failed_writes_queue.put(
                            (INFLUXDB_CONFIG["bucket"], [main_data])
                        )

                # NEW: video recording (libcamera-vid)
                if VIDEO_CONFIG.get("enabled"):
                    try:
                        started = trigger_video_recording(
                            noise_level=round(current_peak_dB, 1), config=config
                        )
                        if started:
                            logger.info(
                                "Event recording started (pre/post window capture in progress)."
                            )
                        else:
                            logger.info(
                                "Event recording skipped (another in progress)."
                            )
                    except Exception:
                        logger.error(
                            "An unhandled exception occurred during video recording trigger:"
                        )
                        traceback.print_exc()
            last_above_threshold = above_threshold

            # reset
            window_start_time = current_time
            current_peak_dB = 0

        # Reading from device
        try:
            ret = usb_dev.ctrl_transfer(0xC0, 4, 0, 0, 200)
            dB = (ret[0] + ((ret[1] & 3) * 256)) * 0.1 + 30
            dB = round(dB, 1)
            if dB > current_peak_dB:
                current_peak_dB = dB
        except Exception as e:
            logger.error(f"Unexpected error reading from device: {str(e)}")
        time.sleep(0.1)


####################################
# SCHEDULING
####################################
def schedule_tasks():
    try:
        # Influx retries
        if INFLUXDB_CONFIG.get("enabled"):
            schedule.every(1).minutes.do(retry_failed_writes)
    except Exception as e:
        logger.error(f"Error scheduling tasks: {str(e)}")


def retry_failed_writes():
    if not (INFLUXDB_CONFIG.get("enabled") and InfluxDBClient and write_api):
        logger.debug("InfluxDB disabled or not configured; skipping retries.")
        return
    while not failed_writes_queue.empty():
        bucket, data = failed_writes_queue.get()
        try:
            write_api.write(bucket=bucket, record=data)
            logger.info(f"Retried write to InfluxDB bucket '{bucket}' successfully.")
        except Exception as e:
            logger.error(
                f"Failed to write to InfluxDB on retry: {str(e)}. Re-queueing."
            )
            failed_writes_queue.put((bucket, data))
            break


####################################
# STARTUP NOTIFICATIONS
####################################
def notify_on_start():
    hostname = socket.gethostname()
    local_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    usb_dev_check = detect_usb_device(verbose=False)
    usb_status = "USB sound meter detected" if usb_dev_check else "USB not detected"

    influxdb_url = (
        f"https://{INFLUXDB_CONFIG['host']}:{INFLUXDB_CONFIG['port']}"
        if INFLUXDB_CONFIG.get("enabled")
        else "N/A"
    )
    influxdb_status = "Connected" if InfluxDBClient else "Not connected"
    video_status = "Enabled" if VIDEO_CONFIG.get("enabled") else "Disabled"

    if VIDEO_CONFIG.get("enabled"):
        video_details = f" ({VIDEO_CONFIG.get('fps', 10)}fps, {VIDEO_CONFIG.get('buffer_seconds', 10)}s buffer)"
    else:
        video_details = ""

    message = (
        f"**Noise Buster Client Started**\n"
        f"Hostname: **{hostname}**\n"
        f"Status: **Client started successfully**\n"
        f"InfluxDB URL: **{influxdb_url}**\n"
        f"InfluxDB Connection: **{influxdb_status}**\n"
        f"USB Sound Meter: **{usb_status}**\n"
        f"Minimum Noise Level: **{DEVICE_AND_NOISE_MONITORING_CONFIG['minimum_noise_level']} dB**\n"
        f"Camera Usage: **{'IP Camera' if CAMERA_CONFIG.get('use_ip_camera') else 'None'}**\n"
        f"Video Recording: **{video_status}{video_details}**\n"
        f"Timezone: **UTC{TIMEZONE_CONFIG.get('timezone_offset', 0):+}**\n"
        f"Local Time: **{local_time}**\n"
    )
    # Log the startup message
    logger.info(message)


####################################
# CLEANUP PI CAMERA
####################################
def cleanup_pi_camera():
    """Clean up Pi camera resources on shutdown"""
    global global_picam2
    if "global_picam2" in globals() and global_picam2:
        try:
            global_picam2.stop()
            global_picam2.close()
            logger.info("Pi camera cleaned up successfully")
        except Exception as e:
            logger.warning(f"Error cleaning up Pi camera: {str(e)}")


####################################
# MAIN
####################################
def main():

    # Quick config checks
    dev_check = detect_usb_device(verbose=False)
    if not dev_check:
        logger.error("No USB sound meter found. Exiting.")
        sys.exit(1)
    logger.info("Starting Noise Monitoring on USB device.")

    # Start circular buffer recorder via video_recording module
    if VIDEO_CONFIG.get("enabled"):
        started = start_video_buffer(VIDEO_CONFIG)
        if not started:
            logger.error(
                "Video buffer failed to start; event videos will be unavailable."
            )

    # ...existing code...

    # Start noise monitoring in separate thread.
    noise_thread = threading.Thread(target=update_noise_level)
    noise_thread.daemon = True
    noise_thread.start()

    # Schedule tasks
    schedule_tasks()

    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Manual interruption by user.")
        if not VIDEO_CONFIG.get("enabled"):
            cleanup_pi_camera()  # Clean up on exit only if not using video
        else:
            stop_video_buffer()
        # No video buffer cleanup needed beyond stopping libcamera-vid


if __name__ == "__main__":
    main()

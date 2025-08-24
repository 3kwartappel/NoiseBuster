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
import usb.core
import argparse

# Only use libcamera-vid for video recording


from .video_recording import start_video_buffer, stop_video_buffer
from .video_recording import trigger_event_recording as vr_trigger

# Global stop event used to gracefully stop threads (useful for test mode)
stop_event = threading.Event()


from .config import config

# usb modules imported above


def trigger_video_recording(noise_level, video_config):
    """Proxy to video_recording module trigger."""
    if not video_config.get("enabled"):
        return False
    return vr_trigger(
        noise_level=noise_level, video_config=video_config
    )


# We'll keep optional modules as None if not installed or not enabled
InfluxDBClient = None
SYNCHRONOUS = None
cv2 = None
np = None
write_api = None
failed_writes_queue = Queue()
global_picam2 = None

# removed inline buffer helpers; using video_recording module


# Retrieve USB device IDs from the config
usb_vendor_id_str = config.device_and_noise.get("usb_vendor_id", "")
usb_product_id_str = config.device_and_noise.get("usb_product_id", "")

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

# Get the absolute path to the project's root directory
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# File handler: only add if LOCAL_LOGGING is enabled in config
if config.local_logging:
    # Use a rotating file handler to avoid truncating logs and keep recent history.
    log_file_path = os.path.join(project_root, "noisebuster.log")
    fh = RotatingFileHandler(log_file_path, maxBytes=5_000_000, backupCount=3)
    fh.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    fh.setFormatter(file_formatter)
    logger.addHandler(fh)
    logger.info(f"Detailed logs are saved in '{log_file_path}'.")
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


usb_ids = load_usb_ids(os.path.join(project_root, "usb_ids"))


####################################
# IMPORT OPTIONAL MODULES
####################################
def import_optional_modules():
    global InfluxDBClient, SYNCHRONOUS, cv2, np
    missing_optional_modules = []

    # Influx
    if config.influxdb.get("enabled"):
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
    if config.camera.get("use_ip_camera"):
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

    return missing_optional_modules


missing_optional_modules = import_optional_modules()


####################################
# CONFIGURATION VALIDATION
####################################
def check_configuration():
    logger.info("Checking configuration...")

    # InfluxDB
    if config.influxdb.get("enabled"):
        influxdb_missing = []
        required_fields = ["host", "port", "token", "org", "bucket", "realtime_bucket"]
        for field in required_fields:
            if not config.influxdb.get(field) or str(
                config.influxdb.get(field)
            ).startswith("<YOUR_"):
                influxdb_missing.append(field)
        bucket_name = config.influxdb.get("bucket", "")
        realtime_bucket_name = config.influxdb.get("realtime_bucket", "")
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
            config.influxdb["enabled"] = False
        else:
            logger.info("InfluxDB is enabled and properly configured.")
    else:
        logger.info("InfluxDB is disabled.")

    # Camera
    if config.camera.get("use_ip_camera"):
        needed_fields = ["ip_camera_url", "ip_camera_protocol"]
        missing = [f for f in needed_fields if not config.camera.get(f)]
        if missing:
            logger.error(f"IP Camera missing: {', '.join(missing)}. Disabling.")
            config.camera["use_ip_camera"] = False
        else:
            logger.info("IP camera is enabled.")
    else:
        logger.info("IP camera is disabled.")

    # Pi Camera
    if config.camera.get("use_pi_camera"):
        logger.info("Pi camera is enabled.")
    else:
        logger.info("Pi camera is disabled.")

    # Video configuration check
    if config.video.get("enabled"):
        if not config.video.get("fps"):
            config.video["fps"] = 10
        if not config.video.get("buffer_seconds"):
            config.video["buffer_seconds"] = 10
        if not config.video.get("resolution"):
            config.video["resolution"] = [640, 480]
        if not config.video.get("retention_hours"):
            config.video["retention_hours"] = 24

        logger.info(
            "Video recording enabled: %sfps, %ss buffer",
            config.video["fps"],
            config.video["buffer_seconds"],
        )
    else:
        logger.info("Video recording is disabled.")

    # Device & Noise
    if not config.device_and_noise.get("minimum_noise_level"):
        logger.error("No 'minimum_noise_level' in DEVICE_AND_NOISE_MONITORING_CONFIG.")
    else:
        logger.info(
            "Minimum noise level: %s dB.",
            config.device_and_noise["minimum_noise_level"],
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
                            "Detected specified device: %s (Vendor %s, Product %s)",
                            model,
                            hex(dev_vendor_id),
                            hex(dev_product_id),
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
                        "%s sound meter detected (Vendor %s, Product %s)",
                        known[2],
                        hex(dev_vendor_id),
                        hex(dev_product_id),
                    )
                device_detected = True
                return dev
            else:
                if verbose and not device_detected:
                    logger.info(
                        "Ignoring device: Vendor %s, Product %s",
                        hex(dev_vendor_id),
                        hex(dev_product_id),
                    )

    # No device found
    device_detected = False
    if usb_vendor_id_int and usb_product_id_int:
        logger.error("Specified USB device not found. Check config or cable.")
    else:
        logger.error("No known USB sound meter found. Possibly not connected?")
    return None


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
    while not stop_event.is_set():
        current_time = time.time()
        if (current_time - window_start_time) >= config.device_and_noise[
            "time_window_duration"
        ]:
            timestamp = datetime.utcnow()
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

            logger.info("Current noise level: %s dB", round(current_peak_dB, 1))

            # Influx DB (realtime bucket)
            if config.influxdb.get("enabled") and InfluxDBClient and write_api:
                try:
                    write_api.write(
                        bucket=config.influxdb["realtime_bucket"], record=realtime_data
                    )
                    logger.info(
                        "All noise levels written to realtime bucket: %s dB",
                        round(current_peak_dB, 1),
                    )
                except Exception as e:
                    logger.error(f"Failed to write to InfluxDB: {str(e)}. Queueing.")
                    failed_writes_queue.put(
                        (config.influxdb["realtime_bucket"], [realtime_data])
                    )

            # If above threshold
            above_threshold = (
                current_peak_dB
                >= config.device_and_noise["minimum_noise_level"]
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
                    "Noise level exceeded threshold: %s dB", round(current_peak_dB, 1)
                )

                # Influx DB main bucket
                if config.influxdb.get("enabled") and InfluxDBClient and write_api:
                    try:
                        write_api.write(
                            bucket=config.influxdb["bucket"], record=main_data
                        )
                        logger.info(
                            f"High noise level data written to main bucket: {main_data}"
                        )
                    except Exception as e:
                        logger.error(
                            f"Failed to write main data to InfluxDB: {str(e)}. Queueing."
                        )
                        failed_writes_queue.put(
                            (config.influxdb["bucket"], [main_data])
                        )

                # NEW: video recording (libcamera-vid)
                if config.video.get("enabled"):
                    try:
                        started = trigger_video_recording(
                            noise_level=round(current_peak_dB, 1), video_config=config.video
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
        if config.influxdb.get("enabled"):
            schedule.every(1).minutes.do(retry_failed_writes)
    except Exception as e:
        logger.error(f"Error scheduling tasks: {str(e)}")


def retry_failed_writes():
    if not (config.influxdb.get("enabled") and InfluxDBClient and write_api):
        logger.debug("InfluxDB disabled or not configured; skipping retries.")
        return
    while not failed_writes_queue.empty():
        bucket, data = failed_writes_queue.get()
        try:
            write_api.write(bucket=bucket, record=data)
            logger.info(f"Retried write to InfluxDB bucket '{bucket}' successfully.")
        except Exception as e:
            logger.error(
                "Failed to write to InfluxDB on retry: %s. Re-queueing.", str(e)
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

    if config.influxdb.get("enabled"):
        influxdb_url = "https://{host}:{port}".format(
            host=config.influxdb.get("host", ""), port=config.influxdb.get("port", "")
        )
    else:
        influxdb_url = "N/A"
    influxdb_status = "Connected" if InfluxDBClient else "Not connected"
    video_status = "Enabled" if config.video.get("enabled") else "Disabled"

    if config.video.get("enabled"):
        video_details = " (%sfps, %ss buffer)" % (
            config.video.get("fps", 10),
            config.video.get("buffer_seconds", 10),
        )
    else:
        video_details = ""

    message = (
        f"**Noise Buster Client Started**\n"
        f"Hostname: **{hostname}**\n"
        f"Status: **Client started successfully**\n"
        f"InfluxDB URL: **{influxdb_url}**\n"
        f"InfluxDB Connection: **{influxdb_status}**\n"
        f"USB Sound Meter: **{usb_status}**\n"
        f"Minimum Noise Level: **{config.device_and_noise['minimum_noise_level']} dB**\n"
        f"Camera Usage: **{'IP Camera' if config.camera.get('use_ip_camera') else 'None'}**\n"
        f"Video Recording: **{video_status}{video_details}**\n"
        f"Timezone: **UTC{config.timezone.get('timezone_offset', 0):+}**\n"
        f"Local Time: **{local_time}**\n"
    )
    # Log the startup message
    logger.info(message)


####################################
# CLEANUP PI CAMERA
####################################
def cleanup_pi_camera():
    """Clean up Pi camera resources on shutdown"""
    if "global_picam2" in globals() and globals().get("global_picam2"):
        try:
            globals().get("global_picam2").stop()
            globals().get("global_picam2").close()
            logger.info("Pi camera cleaned up successfully")
        except Exception as e:
            logger.warning(f"Error cleaning up Pi camera: {str(e)}")


####################################
# MAIN
####################################
def main():

    parser = argparse.ArgumentParser(description="NoiseBuster main runner")
    parser.add_argument(
        "--test-duration",
        type=int,
        default=0,
        help="Run for N seconds then exit (0 = run indefinitely)",
    )
    args = parser.parse_args()

    # Quick config checks
    dev_check = detect_usb_device(verbose=False)
    if not dev_check:
        logger.error("No USB sound meter found. Exiting.")
        sys.exit(1)
    logger.info("Starting Noise Monitoring on USB device.")

    # Start circular buffer recorder via video_recording module
    if config.video.get("enabled"):
        started = start_video_buffer(config.video)
        if not started:
            logger.error(
                "Video buffer failed to start; event videos will be unavailable."
            )

    # Start noise monitoring in separate thread.
    noise_thread = threading.Thread(target=update_noise_level)
    noise_thread.daemon = True
    noise_thread.start()

    # Schedule tasks
    schedule_tasks()

    # If test duration set, we'll exit after that many seconds.
    start_time = time.time()
    try:
        while not stop_event.is_set():
            schedule.run_pending()
            time.sleep(1)
            if (
                args.test_duration > 0
                and (time.time() - start_time) >= args.test_duration
            ):
                logger.info(
                    "Test duration elapsed (%s seconds). Shutting down.",
                    args.test_duration,
                )
                break
    except KeyboardInterrupt:
        logger.info("Manual interruption by user.")
    finally:
        # Signal threads to stop
        stop_event.set()
        # Cleanup resources
        if not config.video.get("enabled"):
            cleanup_pi_camera()
        else:
            stop_video_buffer()
        # Join threads (with timeout)
        noise_thread.join(timeout=5)


if __name__ == "__main__":
    main()

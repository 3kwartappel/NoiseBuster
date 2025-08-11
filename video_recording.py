#!/usr/bin/env python3
# Video Recording Implementation for NoiseBuster (libcamera-vid segment buffer)

import logging
import threading
import time
import os
import subprocess
from datetime import datetime

logger = logging.getLogger(__name__)

# Globals for buffer management
_buffer_dir = os.path.join(os.getcwd(), "videos", "buffer")
_video_dir = os.path.join(os.getcwd(), "videos")
_proc = None
_record_lock = threading.Lock()


def start_video_buffer(video_config: dict) -> bool:
    """Start background libcamera-vid writing 1s .h264 segments with inline SPS/PPS.

    Returns True if started, False otherwise.
    """
    global _proc
    try:
        if not video_config.get("enabled"):
            logger.info("Video buffer disabled by config.")
            return False
        os.makedirs(_buffer_dir, exist_ok=True)
        os.makedirs(_video_dir, exist_ok=True)
        fps = int(video_config.get("fps", 10))
        width, height = video_config.get("resolution", [1024, 768])
        pattern = os.path.join(_buffer_dir, "seg_%010d.h264")
        cmd = [
            "libcamera-vid",
            "-t", "0",
            "-o", pattern,
            "--segment", "1",
            "--width", str(width),
            "--height", str(height),
            "--framerate", str(fps),
            "--inline",
            "-n",
        ]
        # Stop any previous instance
        if _proc and _proc.poll() is None:
            _proc.terminate()
            _proc.wait(timeout=2)
        _proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info("libcamera-vid segment buffer started (1s segments).")
        return True
    except Exception as e:
        logger.error(f"Failed to start video buffer: {e}")
        return False


def stop_video_buffer():
    global _proc
    try:
        if _proc and _proc.poll() is None:
            _proc.terminate()
            _proc.wait(timeout=3)
            logger.info("libcamera-vid segment buffer stopped.")
    except Exception as e:
        logger.warning(f"Error stopping video buffer: {e}")
    finally:
        _proc = None


def _list_segments():
    if not os.path.isdir(_buffer_dir):
        return []
    items = []
    for name in os.listdir(_buffer_dir):
        if name.startswith("seg_") and name.endswith(".h264"):
            p = os.path.join(_buffer_dir, name)
            try:
                items.append((p, os.path.getmtime(p)))
            except FileNotFoundError:
                continue
    items.sort(key=lambda x: x[1])
    return items


def _cleanup_old_segments(buffer_seconds: int):
    keep_seconds = max(10, int(buffer_seconds) * 2)
    now = time.time()
    for p, mt in _list_segments():
        if now - mt > keep_seconds:
            try:
                os.remove(p)
            except Exception:
                pass


def trigger_event_recording(noise_level: float, temperature, weather_description: str, precipitation, video_config: dict) -> bool:
    """Concatenate .h264 segments around the event time into a single .h264 file.

    - Includes pre_event_seconds before and post_event_seconds after the trigger.
    - Skips if another recording is in progress.
    """
    if not video_config.get("enabled"):
        return False

    # Atomic non-blocking acquire to avoid race between concurrent triggers
    if not _record_lock.acquire(blocking=False):
        logger.info("A video recording is already in progress; skipping this trigger.")
        return False

    pre_s = int(video_config.get("pre_event_seconds", 5))
    post_s = int(video_config.get("post_event_seconds", 5))
    buffer_s = int(video_config.get("buffer_seconds", 10))
    if buffer_s < pre_s:
        logger.warning(f"VIDEO_CONFIG.buffer_seconds ({buffer_s}) is shorter than pre_event_seconds ({pre_s}). Increase buffer for better pre-roll.")

    event_ts = datetime.now()
    final_name = f"video_{event_ts.strftime('%Y-%m-%d_%H-%M-%S')}_{noise_level}dB.h264"
    final_path = os.path.join(_video_dir, final_name)

    def _worker():
        try:
            # Wait post window so all future segments are flushed
            time.sleep(max(0, post_s))
            start_t = event_ts.timestamp() - pre_s - 1  # small margin
            end_t = event_ts.timestamp() + post_s + 1
            segs = _list_segments()
            chosen = [p for p, mt in segs if start_t <= mt <= end_t]
            chosen.sort(key=lambda p: os.path.getmtime(p))

            if not chosen:
                logger.error("No segments available for the requested event window; not saving video.")
                return

            with open(final_path, "wb") as out_f:
                for seg in chosen:
                    try:
                        with open(seg, "rb") as in_f:
                            out_f.write(in_f.read())
                    except Exception as e:
                        logger.warning(f"Failed to append segment {os.path.basename(seg)}: {e}")

            if os.path.exists(final_path) and os.path.getsize(final_path) > 0:
                logger.info(f"Saved event video: {final_path}")
            else:
                logger.error("Final .h264 file is missing or empty after concatenation.")
        finally:
            try:
                _cleanup_old_segments(buffer_s)
            except Exception:
                pass
            _record_lock.release()

    logger.info(f"Event recording started (pre={pre_s}s, post={post_s}s, noise={noise_level}dB)")
    threading.Thread(target=_worker, daemon=True).start()
    return True

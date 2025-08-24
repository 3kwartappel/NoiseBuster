#!/usr/bin/env python3
# Video Recording Implementation for NoiseBuster (libcamera-vid segment buffer)

import logging
import os
import subprocess
import threading
import time
from datetime import datetime
import shutil

logger = logging.getLogger(__name__)

# Get the absolute path to the project's root directory
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Globals for buffer management
_buffer_dir = os.path.join(project_root, "videos", "buffer")
_video_dir = os.path.join(project_root, "videos")
_proc = None
_record_lock = threading.Lock()


def is_tool(name):
    """Check whether `name` is on PATH and marked as executable."""
    return shutil.which(name) is not None


def start_video_buffer(video_config: dict) -> bool:
    """Start background libcamera-vid writing 1s .h264 segments with inline SPS/PPS.

    Returns True if started, False otherwise.
    """
    global _proc
    try:
        if not video_config.get("enabled"):
            logger.info("Video buffer disabled by config.")
            return False

        if not is_tool("rpicam-vid"):
            logger.error("rpicam-vid command not found. Please ensure it is installed and in your PATH.")
            return False

        os.makedirs(_buffer_dir, exist_ok=True)
        os.makedirs(_video_dir, exist_ok=True)
        fps = int(video_config.get("fps", 10))
        width, height = video_config.get("resolution", [1024, 768])
        pattern = os.path.join(_buffer_dir, "seg_%010d.h264")
        cmd = [
            "rpicam-vid",
            "-t",
            "0",
            "-o",
            pattern,
            "--segment",
            "1",
            "--width",
            str(width),
            "--height",
            str(height),
            "--framerate",
            str(fps),
            "--inline",
            "-n",
        ]
        if video_config.get("audio", {}).get("enabled"):
            cmd.extend(["--listen", "--audio-codec", "aac"])
        # Stop any previous instance
        if _proc and _proc.poll() is None:
            _proc.terminate()
            _proc.wait(timeout=2)
        _proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        logger.info("rpicam-vid segment buffer started (1s segments).")
        return True
    except FileNotFoundError:
        logger.error("Failed to start video buffer: libcamera-vid command not found.")
        return False
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
        if name.startswith("seg_") and (name.endswith(".h264") or name.endswith(".mp4")):
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


def trigger_event_recording(noise_level: float, video_config: dict) -> bool:
    """Concatenate .h264 segments around the event time into a single .h264 file.

    - Includes pre_event_seconds before and post_event_seconds after the trigger.
    - Skips if another recording is in progress.
    """
    if not video_config.get("enabled"):
        return False

    if not is_tool("ffmpeg"):
        logger.error("ffmpeg command not found. Please ensure it is installed and in your PATH.")
        return False

    # Atomic non-blocking acquire to avoid race between concurrent triggers
    if not _record_lock.acquire(blocking=False):
        logger.info("A video recording is already in progress; skipping this trigger.")
        return False

    pre_s = int(video_config.get("pre_event_seconds", 5))
    post_s = int(video_config.get("post_event_seconds", 5))
    buffer_s = int(video_config.get("buffer_seconds", 10))
    if buffer_s < pre_s:
        logger.warning(
            "VIDEO_CONFIG.buffer_seconds (%s) is shorter than pre_event_seconds (%s). "
            "Increase buffer for better pre-roll.",
            buffer_s,
            pre_s,
        )

    event_ts = datetime.now()
    final_name = f"video_{event_ts.strftime('%Y-%m-%d_%H-%M-%S')}_{noise_level}dB.mp4"
    final_path = os.path.join(_video_dir, final_name)

    def _worker():
        try:
            # Wait for the post-event window to ensure all segments are written
            time.sleep(post_s)
            start_t = event_ts.timestamp() - pre_s - 2  # 2s grace period
            end_t = event_ts.timestamp() + post_s + 2 # 2s grace period
            
            segs = _list_segments()
            
            chosen = [p for p, mt in segs if start_t <= mt <= end_t]
            chosen.sort(key=lambda p: os.path.getmtime(p))

            if not chosen:
                logger.error(
                    "No segments available for the requested event window; not saving video."
                )
                return

            # Create a temporary file with the list of segments to concatenate
            list_file_path = os.path.join(_buffer_dir, "concat_list.txt")
            with open(list_file_path, "w") as f:
                for seg in chosen:
                    f.write(f"file '{seg}'\n")

            # Use ffmpeg to concatenate the segments
            ffmpeg_cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                list_file_path,
                "-c",
                "copy",
                final_path,
            ]
            subprocess.run(ffmpeg_cmd, check=True, capture_output=True, text=True)
            os.remove(list_file_path)

            if os.path.exists(final_path) and os.path.getsize(final_path) > 0:
                logger.info(f"Saved event video: {final_path}")
                if video_config.get("embed_decibel_reading"):
                    embed_text_path = os.path.join(project_root, "scripts", "embed_text.py")
                    processed_path = final_path.replace(".mp4", "_processed.mp4")
                    subprocess.run([
                        "python",
                        embed_text_path,
                        final_path,
                        processed_path,
                        f"{noise_level} dB"
                    ])
                    os.remove(final_path)
                    os.rename(processed_path, final_path)
            else:
                logger.error(
                    "Final .mp4 file is missing or empty after concatenation."
                )
        except FileNotFoundError:
            logger.error("ffmpeg command not found. Please ensure it is installed and in your PATH.")
        except subprocess.CalledProcessError as e:
            logger.error(f"ffmpeg command failed: {e.stderr}")
        finally:
            _record_lock.release()
            try:
                _cleanup_old_segments(buffer_s)
            except Exception:
                pass

    logger.info(
        "Event recording started (pre=%ss, post=%ss, noise=%sdB)",
        pre_s,
        post_s,
        noise_level,
    )
    threading.Thread(target=_worker, daemon=True).start()
    return True

#!/usr/bin/env python3
# Video Recording Implementation for NoiseBuster
# This module implements a robust circular buffer using deque and cv2.VideoWriter.

import logging
# THIS IS A NEW FILE - VERSION 4 - IF YOU SEE THIS, THE SCRIPT IS UPDATED
# Use logger instance for all logging
logger = logging.getLogger(__name__)
logger.critical("SUCCESS: Running video_recording.py version 4 (cv2.VideoWriter method)")

import threading
import time
import os
import cv2
import numpy as np
from collections import deque
from datetime import datetime
import traceback

try:
    from picamera2 import Picamera2
    PICAMERA2_IMPORTED = True
except ImportError:
    PICAMERA2_IMPORTED = False
    logger.error("picamera2 library not found. Video recording will be disabled.")

class CircularVideoBuffer:
    """A robust circular buffer for video frames using deque and OpenCV."""

    def __init__(self, fps=10, buffer_seconds=10, resolution=(640, 480)):
        if not PICAMERA2_IMPORTED:
            raise ImportError("picamera2 library is required for video recording.")

        self.fps = fps
        self.resolution = resolution
        self.max_frames = int(fps * buffer_seconds)
        self.frame_buffer = deque(maxlen=self.max_frames)
        self.picam2 = None
        self.capture_thread = None
        self.should_stop = threading.Event()
        self.is_recording_event = False
        self.recording_event_lock = threading.Lock()
        logger.info(f"Circular video buffer initialized: {fps}fps, {buffer_seconds}s buffer, {resolution} resolution")

    def start(self):
        """Initializes and starts the camera capture thread."""
        try:
            self.picam2 = Picamera2()
            video_config = self.picam2.create_video_configuration(
                main={"size": self.resolution, "format": "RGB888"},
                controls={"FrameRate": self.fps}
            )
            self.picam2.configure(video_config)
            self.picam2.start()
            time.sleep(2) # Allow camera to warm up (could be configurable)
            logger.info("Pi camera initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Pi camera: {e}")
            logger.debug(traceback.format_exc())
            return False

        self.should_stop.clear()
        self.capture_thread = threading.Thread(target=self._capture_loop)
        self.capture_thread.daemon = True
        self.capture_thread.start()
        logger.info("Started continuous video capture thread.")
        return True

    def _capture_loop(self):
        """The main loop for capturing frames and adding them to the buffer."""
        logger.info("Capture loop started.")
        frame_interval = 1.0 / self.fps
        while not self.should_stop.is_set():
            start_time = time.time()
            try:
                frame = self.picam2.capture_array()
                if frame is not None:
                    # picamera2 captures in RGB, convert to BGR for OpenCV
                    frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                    self.frame_buffer.append(frame_bgr)
                else:
                    logger.warning("Captured a null frame from camera.")
                # Sleep to maintain FPS
                elapsed = time.time() - start_time
                sleep_time = frame_interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
            except Exception as e:
                logger.error(f"Error in capture loop: {e}")
                logger.debug(traceback.format_exc())
                # If the camera timed out, try to restart it.
                if "Camera frontend has timed out" in str(e):
                    logger.warning("Camera timeout detected. Attempting to restart camera...")
                    try:
                        self.picam2.stop()
                        self.picam2.start()
                        logger.info("Camera restarted successfully.")
                    except Exception as restart_e:
                        logger.error(f"Failed to restart camera: {restart_e}")
                time.sleep(1) # Wait a second before retrying

    def trigger_event_recording(self, noise_level, temperature=None, weather_description="", precipitation=0.0, post_event_seconds=5):
        """Triggers the recording of the current buffer plus post-event frames."""
        with self.recording_event_lock:
            if self.is_recording_event:
                logger.warning("Event recording already in progress, skipping.")
                return
            self.is_recording_event = True

        recording_thread = threading.Thread(
            target=self._record_event,
            args=(noise_level, temperature, weather_description, precipitation, post_event_seconds)
        )
        recording_thread.daemon = True
        recording_thread.start()

    def _record_event(self, noise_level, temperature, weather_description, precipitation, post_event_seconds):
        """Handles the actual video file creation."""
        logger.info("Starting event recording process...")
        final_filepath = ""
        video_writer = None
        all_frames = []

        try:
            # 1. Immediately grab all frames (pre and post)
            # This minimizes the time spent blocking other recordings.
            pre_event_frames = list(self.frame_buffer)
            all_frames.extend(pre_event_frames)

            post_event_frame_count = int(self.fps * post_event_seconds)
            frames_recorded = 0
            while frames_recorded < post_event_frame_count:
                frame = self.picam2.capture_array()
                if frame is not None:
                    frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                    all_frames.append(frame_bgr)
                    frames_recorded += 1
                # A small sleep is still needed to not overwhelm the camera
                time.sleep(1 / self.fps)

            logger.info(f"Collected {len(pre_event_frames)} pre-event and {frames_recorded} post-event frames.")

            # 2. Now, write the collected frames to a file.
            video_save_path = os.path.join(os.getcwd(), "videos")
            if not os.path.exists(video_save_path):
                os.makedirs(video_save_path)

            event_timestamp = datetime.now()
            formatted_time = event_timestamp.strftime("%Y-%m-%d_%H-%M-%S")
            weather_info = f"{weather_description.replace(' ', '_')}_{temperature}C" if weather_description else "no_weather"
            filename = f"video_{formatted_time}_{weather_info}_{noise_level}dB.mp4"
            final_filepath = os.path.join(video_save_path, filename)

            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            video_writer = cv2.VideoWriter(final_filepath, fourcc, self.fps, self.resolution)

            if not video_writer.isOpened():
                logger.error(f"Failed to open video writer for {final_filepath}")
                # The finally block will still run to reset the flag
                return

            logger.info(f"Writing {len(all_frames)} total frames to {final_filepath}...")
            for frame in all_frames:
                CircularVideoBuffer._add_overlay_to_frame(frame, event_timestamp, noise_level, temperature, weather_description, precipitation)
                video_writer.write(frame)
            logger.info("Finished writing frames.")

        except Exception as e:
            logger.error(f"Exception during video file creation: {e}")
            logger.debug(traceback.format_exc())
        finally:
            if video_writer:
                video_writer.release()
                logger.info("Video writer released.")

            if os.path.exists(final_filepath) and os.path.getsize(final_filepath) > 0:
                logger.info(f"Event video saved successfully: {final_filepath}")
                self._cleanup_videos(video_save_path, keep_latest=final_filepath)
            else:
                logger.error(f"Video file was not created or is empty: {final_filepath}")

            # This is the most critical part: ensuring the flag is always reset.
            with self.recording_event_lock:
                self.is_recording_event = False
                logger.info("Event recording finished, flag reset.")

    @staticmethod
    def _add_overlay_to_frame(frame, timestamp, noise_level, temperature, weather_description, precipitation):
        """Adds text overlay directly to the frame."""
        formatted_time = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        text_lines = [f"Time: {formatted_time}", f"Noise: {noise_level} dB"]
        if temperature is not None:
            text_lines.append(f"Temp: {temperature}C")
        if weather_description:
            text_lines.append(f"Weather: {weather_description}")
        if precipitation > 0:
            text_lines.append(f"Rain: {precipitation}mm")
        y_position = 30
        for line in text_lines:
            cv2.putText(frame, line, (10, y_position), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
            cv2.putText(frame, line, (10, y_position), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
            y_position += 25

    def _cleanup_videos(self, path, keep_latest):
        logger.info(f"Cleaning up old videos, keeping {os.path.basename(keep_latest)}")
        try:
            for filename in os.listdir(path):
                filepath = os.path.join(path, filename)
                if filename.endswith('.mp4') and filepath != keep_latest:
                    os.remove(filepath)
                    logger.info(f"Removed old video: {filename}")
        except Exception as e:
            logger.error(f"Error during video cleanup: {e}")

    def stop(self):
        logger.info("Stopping video capture...")
        self.should_stop.set()
        if self.capture_thread:
            self.capture_thread.join(timeout=2)
        if self.picam2:
            try:
                self.picam2.stop()
            except Exception as e:
                logger.warning(f"Error stopping camera: {e}")
            try:
                self.picam2.close()
            except Exception as e:
                logger.warning(f"Error closing camera: {e}")
        logger.info("Video capture system stopped.")

# --- Integration functions for your main NoiseBuster script ---

def initialize_video_system(config):
    video_config = config.get("VIDEO_CONFIG", {})
    if not video_config.get("enabled", False):
        logger.info("Video recording is disabled in config.")
        return None
    
    if not PICAMERA2_IMPORTED:
        logger.error("Cannot initialize video system because picamera2 library is not installed.")
        return None

    try:
        fps = video_config.get("fps", 10)
        buffer_seconds = video_config.get("buffer_seconds", 10)
        resolution = tuple(video_config.get("resolution", [640, 480]))
        
        video_buffer = CircularVideoBuffer(fps=fps, buffer_seconds=buffer_seconds, resolution=resolution)
        
        if video_buffer.start():
            return video_buffer
        else:
            logger.error("CircularVideoBuffer failed to start.")
            return None
    except Exception as e:
        logger.error(f"An error occurred during video system initialization: {e}")
        logger.debug(traceback.format_exc())
        return None

def trigger_video_recording(video_buffer, noise_level, temperature, weather_description, precipitation, config):
    if video_buffer:
        video_config = config.get("VIDEO_CONFIG", {})
        post_event_seconds = video_config.get("post_event_seconds", 5)
        video_buffer.trigger_event_recording(
            noise_level=noise_level,
            temperature=temperature, 
            weather_description=weather_description,
            precipitation=precipitation,
            post_event_seconds=post_event_seconds
        )

def cleanup_video_system(video_buffer):
    if video_buffer:
        video_buffer.stop()

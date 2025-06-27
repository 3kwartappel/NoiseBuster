#!/usr/bin/env python3
# Video Recording Implementation for NoiseBuster
# This module implements circular buffer video recording for Pi Camera

import threading
import time
import os
import cv2
import numpy as np
from collections import deque
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class CircularVideoBuffer:
    """Circular buffer for video frames with Pi Camera support"""
    
    def __init__(self, fps=10, buffer_seconds=10, resolution=(640, 480)):
        self.fps = fps
        self.buffer_seconds = buffer_seconds
        self.resolution = resolution
        self.max_frames = fps * buffer_seconds
        
        # Circular buffer for frames
        self.frame_buffer = deque(maxlen=self.max_frames)
        self.timestamp_buffer = deque(maxlen=self.max_frames)
        
        # Threading
        self.buffer_lock = threading.Lock()
        self.recording_thread = None
        self.capture_thread = None
        self.should_stop = threading.Event()
        self.is_recording_event = False
        
        # Pi Camera
        self.picam2 = None
        self.camera_lock = threading.Lock()
        
        logger.info(f"Circular video buffer initialized: {fps}fps, {buffer_seconds}s buffer, {resolution} resolution")
    
    def initialize_camera(self):
        """Initialize Pi camera for video capture"""
        try:
            from picamera2 import Picamera2
            
            self.picam2 = Picamera2()
            
            # Configure for video capture
            video_config = self.picam2.create_video_configuration()
            video_config["main"]["size"] = self.resolution
            video_config["main"]["format"] = "RGB888"  # RGB format for easier processing
            video_config["buffer_count"] = 4  # Reduce buffer count for lower latency
            
            self.picam2.configure(video_config)
            self.picam2.start()
            
            # Give camera time to settle
            time.sleep(2)
            
            logger.info(f"Pi camera initialized for video: {self.resolution} @ {self.fps}fps")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize Pi camera for video: {str(e)}")
            return False
    
    def start_continuous_capture(self):
        """Start continuous frame capture in background thread"""
        if self.capture_thread and self.capture_thread.is_alive():
            logger.warning("Capture thread already running")
            return
        
        if not self.initialize_camera():
            logger.error("Cannot start capture - camera initialization failed")
            return
        
        self.should_stop.clear()
        self.capture_thread = threading.Thread(target=self._continuous_capture_loop)
        self.capture_thread.daemon = True
        self.capture_thread.start()
        
        logger.info("Started continuous video capture")
    
    def _continuous_capture_loop(self):
        """Continuous capture loop for circular buffer with auto-recovery"""
        frame_interval = 1.0 / self.fps
        last_capture_time = 0

        while not self.should_stop.is_set():
            current_time = time.time()

            # Maintain target FPS
            if current_time - last_capture_time < frame_interval:
                time.sleep(0.01)
                continue

            try:
                # Capture frame from Pi camera
                with self.camera_lock:
                    if self.picam2:
                        frame = self.picam2.capture_array()
                        if frame is not None:
                            # Convert RGB to BGR for OpenCV compatibility
                            if len(frame.shape) == 3 and frame.shape[2] == 3:
                                frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                            else:
                                frame_bgr = frame
                            # Add to circular buffer
                            with self.buffer_lock:
                                self.frame_buffer.append(frame_bgr.copy())
                                self.timestamp_buffer.append(current_time)
                            last_capture_time = current_time
                        else:
                            logger.warning("Captured frame is None.")
                    else:
                        logger.warning("Pi camera object is None in capture loop.")
            except Exception as e:
                logger.error(f"Error capturing frame: {str(e)}")
                # Attempt to reinitialize the camera after a short delay
                logger.info("Attempting to reinitialize Pi camera after error...")
                with self.camera_lock:
                    try:
                        if self.picam2:
                            self.picam2.stop()
                            self.picam2.close()
                    except Exception:
                        pass
                    self.picam2 = None
                    time.sleep(2)
                    self.initialize_camera()
                time.sleep(1)
    
    def trigger_event_recording(self, noise_level, temperature=None, weather_description="", precipitation=0.0, post_event_seconds=5):
        """Trigger recording of event (pre-buffer + post-event)"""
        if self.is_recording_event:
            logger.warning("Event recording already in progress, skipping")
            return
        
        self.is_recording_event = True
        
        # Start recording in separate thread
        recording_thread = threading.Thread(
            target=self._record_event,
            args=(noise_level, temperature, weather_description, precipitation, post_event_seconds)
        )
        recording_thread.daemon = True
        recording_thread.start()
    
    def _record_event(self, noise_level, temperature, weather_description, precipitation, post_event_seconds):
        """Record event video (pre-buffer + post-event duration)"""
        video_writer = None
        filepath = ""
        pre_event_frames_len = 0
        frames_recorded = 0
        try:
            event_timestamp = datetime.now()
            
            # Create filename
            formatted_time = event_timestamp.strftime("%Y-%m-%d_%H-%M-%S")
            weather_info = f"{weather_description.replace(' ', '_')}_{temperature}C" if weather_description else "no_weather"
            filename = f"video_{formatted_time}_{weather_info}_{noise_level}dB.mp4"
            
            # Create video save path
            video_save_path = os.path.join(os.getcwd(), "videos")
            if not os.path.exists(video_save_path):
                os.makedirs(video_save_path)
                logger.info(f"Created video directory: {video_save_path}")
            
            filepath = os.path.join(video_save_path, filename)
            
            # Get current buffer frames (pre-event)
            with self.buffer_lock:
                pre_event_frames = list(self.frame_buffer)
            pre_event_frames_len = len(pre_event_frames)
            
            logger.info(f"Starting event recording: {pre_event_frames_len} pre-event frames, {post_event_seconds}s post-event")
            
            # Initialize video writer
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            video_writer = cv2.VideoWriter(filepath, fourcc, self.fps, self.resolution)
            
            if not video_writer.isOpened():
                logger.error(f"Failed to open video writer for {filepath}")
                return
            
            # Write pre-event frames
            for frame in pre_event_frames:
                if frame is not None:
                    display_frame = self._add_overlay_to_frame(
                        frame.copy(), event_timestamp, noise_level, temperature, weather_description, precipitation
                    )
                    video_writer.write(display_frame)
            
            # Record post-event frames
            post_event_frame_count = int(self.fps * post_event_seconds)
            
            start_time = time.time()
            while frames_recorded < post_event_frame_count and not self.should_stop.is_set():
                try:
                    with self.camera_lock:
                        if self.picam2:
                            frame = self.picam2.capture_array()
                            if frame is not None:
                                if len(frame.shape) == 3 and frame.shape[2] == 3:
                                    frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                                else:
                                    frame_bgr = frame
                                display_frame = self._add_overlay_to_frame(
                                    frame_bgr.copy(), event_timestamp, noise_level, temperature, weather_description, precipitation
                                )
                                video_writer.write(display_frame)
                                frames_recorded += 1
                    
                    elapsed = time.time() - start_time
                    expected_time = frames_recorded / self.fps
                    if elapsed < expected_time:
                        time.sleep(expected_time - elapsed)
                        
                except Exception as e:
                    logger.error(f"Error recording post-event frame: {str(e)}")
                    time.sleep(1.0 / self.fps)
                    
        except Exception as e:
            logger.error(f"Error during event recording: {str(e)}")
            logger.debug("Full traceback:", exc_info=True)
        finally:
            if video_writer and video_writer.isOpened():
                video_writer.release()
                if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                    logger.info(f"Event video saved successfully: {filepath}")
                    logger.info(f"Video stats: {pre_event_frames_len} pre-event + {frames_recorded} post-event frames")
                else:
                    logger.error(f"Video file was not created or is empty: {filepath}")
            self.is_recording_event = False
    
    def _add_overlay_to_frame(self, frame, timestamp, noise_level, temperature, weather_description, precipitation):
        """Add text overlay to video frame"""
        try:
            formatted_time = timestamp.strftime("%Y-%m-%d %H:%M:%S")
            
            text_lines = [
                f"Time: {formatted_time}",
                f"Noise: {noise_level} dB",
            ]
            
            if temperature is not None:
                text_lines.append(f"Temp: {temperature}C")
            if weather_description:
                text_lines.append(f"Weather: {weather_description}")
            if precipitation > 0:
                text_lines.append(f"Rain: {precipitation}mm")
            
            # Add text with better visibility
            y_position = 30
            for line in text_lines:
                # Black outline
                cv2.putText(frame, line, (10, y_position), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
                # White text
                cv2.putText(frame, line, (10, y_position), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
                y_position += 25
            
            return frame
            
        except Exception as e:
            logger.error(f"Error adding overlay to frame: {str(e)}")
            return frame
    
    def cleanup_old_videos(self, retention_hours=24):
        """Clean up old video files"""
        video_path = os.path.join(os.getcwd(), "videos")
        if not os.path.exists(video_path):
            return
        
        try:
            current_time = datetime.now()
            for filename in os.listdir(video_path):
                if filename.endswith('.mp4'):
                    filepath = os.path.join(video_path, filename)
                    if os.path.isfile(filepath):
                        file_creation_time = datetime.fromtimestamp(os.path.getctime(filepath))
                        time_diff = current_time - file_creation_time
                        if time_diff.total_seconds() > (retention_hours * 3600):
                            os.remove(filepath)
                            logger.info(f"Deleted old video: {filename}")
        except Exception as e:
            logger.error(f"Error cleaning up old videos: {str(e)}")
    
    def stop_capture(self):
        """Stop continuous capture and cleanup"""
        logger.info("Stopping video capture...")
        
        self.should_stop.set()
        
        # Wait for capture thread to finish
        if self.capture_thread and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=5)
        
        # Cleanup camera
        with self.camera_lock:
            if self.picam2:
                try:
                    self.picam2.stop()
                    self.picam2.close()
                    logger.info("Pi camera stopped and closed")
                except Exception as e:
                    logger.warning(f"Error stopping camera: {str(e)}")
                finally:
                    self.picam2 = None
        
        logger.info("Video capture stopped")
    
    def get_latest_frame(self):
        """Return the latest frame from the buffer, or None if empty."""
        with self.buffer_lock:
            if self.frame_buffer:
                return self.frame_buffer[-1].copy()
            else:
                return None


# Integration functions for your main NoiseBuster script

def initialize_video_system(config):
    """Initialize the video recording system"""
    video_config = config.get("VIDEO_CONFIG", {})
    
    if not video_config.get("enabled", False):
        return None
    
    fps = video_config.get("fps", 10)
    buffer_seconds = video_config.get("buffer_seconds", 10)
    resolution = tuple(video_config.get("resolution", [640, 480]))
    
    video_buffer = CircularVideoBuffer(fps=fps, buffer_seconds=buffer_seconds, resolution=resolution)
    
    # Start continuous capture
    video_buffer.start_continuous_capture()
    
    return video_buffer

def trigger_video_recording(video_buffer, noise_level, temperature, weather_description, precipitation, config):
    """Trigger video recording for noise event"""
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
    """Cleanup video system on shutdown"""
    if video_buffer:
        video_buffer.stop_capture()


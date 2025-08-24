
import json
import os
import sys

class Config:
    def __init__(self, config_path=os.path.join(os.path.dirname(__file__), "..", "config.json")):
        try:
            with open(config_path, "r") as config_file:
                self.config = json.load(config_file)
        except json.JSONDecodeError as e:
            print(f"Error parsing config.json: {e}")
            sys.exit(1)
        except FileNotFoundError as e:
            print(f"Configuration file not found: {e}")
            sys.exit(1)

        self._extract_configs()

    def _extract_configs(self):
        self.influxdb = self.config.get("INFLUXDB_CONFIG", {})
        self.camera = self.config.get("CAMERA_CONFIG", {})
        self.image_storage = self.config.get("IMAGE_STORAGE_CONFIG", {})
        self.device_and_noise = self.config.get("DEVICE_AND_NOISE_MONITORING_CONFIG", {})
        self.timezone = self.config.get("TIMEZONE_CONFIG", {})
        self.video = self.config.get("VIDEO_CONFIG", {})
        self.local_logging = self.config.get("LOCAL_LOGGING", True)

    def get(self, key, default=None):
        return self.config.get(key, default)

config = Config()

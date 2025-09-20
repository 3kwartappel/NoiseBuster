# NoiseBuster: oise Monitoring

NoiseBuster is a Python application for real-time noise monitoring using a USB sound meter. It integrates with InfluxDB for data storage, Grafana for visualization, and supports various optional features like video recording, weather data correlation, and notifications. This document provides a comprehensive guide for setting up, configuring, and running NoiseBuster.

## 1. Project Overview

NoiseBuster is designed for continuous noise level monitoring. When noise exceeds a configurable threshold, it can trigger events such as video recording and send notifications. It's a versatile tool for monitoring environmental noise from sources like traffic, construction, or events.

### 1.1. Features

*   **Real-time Noise Monitoring:** Captures and logs decibel levels from a USB sound meter.
*   **Data Storage & Visualization:** Stores time-series data in InfluxDB, which can be visualized with Grafana.
*   **Event-based Video Recording:** Automatically records video clips (with pre- and post-event buffering) when noise levels exceed a defined threshold.
*   **Optional Integrations:**
    *   MQTT for home automation.
    *   OpenWeatherMap for weather data correlation.
    *   Telraam for traffic data.
    *   Discord and Pushover for notifications.
*   **Cross-Platform:** Can be run on Linux (including Raspberry Pi), Windows (via WSL), and in Docker containers.

## 2. Getting Started

### 2.1. Hardware Requirements

*   **Core:**
    *   A Linux-based system (e.g., Raspberry Pi, Ubuntu server) or a Windows machine with WSL.
    *   A USB-connected sound level meter. The application can auto-detect many models, or you can specify the vendor and product ID in the configuration.
*   **Optional:**
    *   A Raspberry Pi Camera or an IP camera for video recording.

### 2.2. Software Prerequisites

*   Python 3.6+
*   `git`
*   `ffmpeg` (for video recording)
*   `rpicam-vid` (for video recording on Raspberry Pi)

## 3. Setup and Installation

### 3.1. Linux (including Raspberry Pi)

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/3kwartappel/NoiseBuster.git
    cd NoiseBuster
    ```

2.  **Create and activate a Python virtual environment:**
    ```bash
    python3 -m venv env
    source env/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    *(For non-Raspberry Pi systems, you may need to use `requirements_no_pi.txt`)*

4.  **Set USB Device Permissions (once off) - already done:**
    Create a `udev` rule to ensure the application can access the USB sound meter.
    First, find your device's vendor and product ID:
    ```bash
    lsusb
    ```
    Then, create a rule file:
    ```bash
    sudo nano /etc/udev/rules.d/99-usb-soundmeter.rules
    ```
    Add the following line, replacing the `idVendor` and `idProduct` with your device's IDs:
    ```
    SUBSYSTEM=="usb", ATTR{idVendor}=="16c0", ATTR{idProduct}=="05dc", MODE="0666"
    ```
    Reload the `udev` rules:
    ```bash
    sudo udevadm control --reload
    sudo udevadm trigger
    ```

<!-- ### 3.2. Windows (via WSL)

1.  **Install prerequisites in your WSL terminal:**
    ```bash
    sudo apt-get update && sudo apt-get install -y python3-pip python3-venv git
    ```

2.  **Clone the repository and set up the environment:**
    ```bash
    git clone https://github.com/3kwartappel/NoiseBuster.git
    cd NoiseBuster
    python3 -m venv .wsl_venv
    source .wsl_venv/bin/activate
    pip install -r requirements_no_pi.txt
    ``` -->

<!-- ### 3.3. Docker

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/3kwartappel/NoiseBuster.git
    cd NoiseBuster
    ```

2.  **Build the Docker image:**
    ```bash
    docker build -t noisebuster .
    ```

3.  **Run the Docker container:**
    You'll need to pass the USB device to the container.
    ```bash
    docker run -d --name noisebuster --device=/dev/bus/usb:/dev/bus/usb noisebuster
    ``` -->

## 4. Configuration

All configuration is done in the `config.json` file.

*   **`INFLUXDB_CONFIG`**: Enable and configure InfluxDB connection details.
*   **`CAMERA_CONFIG`**: Enable and configure either a Pi camera or an IP camera.
*   **`VIDEO_CONFIG`**: Enable and configure video recording settings like FPS, buffer size, and retention.
*   **`DEVICE_AND_NOISE_MONITORING_CONFIG`**: Set the minimum noise level to trigger events, and optionally specify the USB device vendor/product IDs if auto-detect fails.
*   Other sections for optional integrations.

## 5. Running NoiseBuster

### 5.1. Direct Execution

After setup and configuration, you can run the application directly:

```bash
python -m src.noisebuster
```

You can also run it for a specific duration for testing:

```bash
python -m src.noisebuster --test-duration 30
```

<!-- ### 5.2. Running as a Service (Linux)

To run NoiseBuster automatically on boot, you can set up a `systemd` service.

1.  **Create a startup script (`start_noisebuster.sh`):**
    ```bash
    #!/bin/bash
    cd /path/to/NoiseBuster
    source env/bin/activate
    python -m src.noisebuster
    ```
    Make it executable: `chmod +x start_noisebuster.sh`

2.  **Create a systemd service file (`/etc/systemd/system/noisebuster.service`):**
    ```ini
    [Unit]
    Description=NoiseBuster Service
    After=network.target

    [Service]
    User=your_user
    WorkingDirectory=/path/to/NoiseBuster
    ExecStart=/path/to/NoiseBuster/start_noisebuster.sh
    Restart=always

    [Install]
    WantedBy=multi-user.target
    ```

3.  **Enable and start the service:**
    ```bash
    sudo systemctl daemon-reload
    sudo systemctl enable noisebuster.service
    sudo systemctl start noisebuster.service
    ``` -->

## 6. Development and Testing

### 6.1. AI Development Guidelines

The following always needs to be adhered before pushing code.

*   **Create Tests:** New features should be accompanied by tests.
*   **Secret-Scanning:** Ensure no sensitive information is committed.
*   **Model Agnostic:** Workflows and prompts should be compatible with various AI models.

### 6.2. Code Formatting

This project uses `black` for code formatting and `flake8` for linting.

```bash
# Format with Black. run this locally before pushing.
black .

# Run Flake8. run this locally before pushing.
flake8 .
```

### 6.3. Running Tests

Install test dependencies and run `pytest`:

```bash
pip install pytest pytest-mock
pytest
```

## 7. Project Tasks (TODO)

*   Fix remaining unit tests.
*   Address security flaws identified by GitHub.
*   Develop a method for testing in CI/CD without physical hardware (e.g., using preset video/audio for analysis).

from unittest.mock import patch, MagicMock
from ..noisebuster import main as noisebuster_main


@patch("src.noisebuster.detect_usb_device")
@patch("src.video_recording.start_video_buffer")
@patch("src.noisebuster.vr_trigger")
def test_integration_mock_noise_event(
    mock_vr_trigger,
    mock_start_video_buffer,
    mock_detect_usb_device,
    monkeypatch,
):
    # Mock the USB device
    mock_usb_device = MagicMock()
    mock_detect_usb_device.return_value = mock_usb_device

    # Mock the video buffer
    mock_start_video_buffer.return_value = True

    # Simulate a noise event by patching the ctrl_transfer method
    def mock_ctrl_transfer(*args, **kwargs):
        # Return a high noise level to trigger an event
        return [44, 1]

    mock_usb_device.ctrl_transfer.side_effect = mock_ctrl_transfer

    # Run the main function in a separate thread
    import threading

    # Use a test-specific config
    with patch("src.noisebuster.config") as mock_config:
        mock_config.influxdb = {"enabled": False}
        mock_config.camera = {"use_ip_camera": False, "use_pi_camera": False}
        mock_config.video = {
            "enabled": True,
            "fps": 10,
            "buffer_seconds": 10,
            "pre_event_seconds": 5,
            "post_event_seconds": 5,
            "resolution": [640, 480],
            "retention_hours": 1,
        }
        mock_config.device_and_noise = {
            "minimum_noise_level": 50,
            "time_window_duration": 1,
        }
        mock_config.timezone = {}

        # Use monkeypatch to control the test duration
        monkeypatch.setattr("sys.argv", ["noisebuster.py", "--test-duration", "5"])

        main_thread = threading.Thread(target=noisebuster_main)
        main_thread.start()
        main_thread.join()

    # Check if the trigger_event_recording function was called
    mock_vr_trigger.assert_called()

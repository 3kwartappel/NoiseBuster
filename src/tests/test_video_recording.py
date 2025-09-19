import os
import subprocess
import time
from datetime import datetime
from unittest.mock import patch, mock_open
from ..video_recording import (
    _list_segments,
    _cleanup_old_segments,
    trigger_event_recording,
    _process_event_recording,
)


def test_list_segments():
    dummy_dir = "dummy_buffer"
    with patch("src.video_recording._buffer_dir", dummy_dir):
        with patch("os.path.isdir", return_value=True):
            with patch(
                "os.listdir", return_value=["seg_1.h264", "seg_2.h264", "not_a_segment"]
            ):
                with patch("os.path.getmtime", return_value=time.time()):
                    segments = _list_segments()
                    assert len(segments) == 2
                    assert segments[0][0] == os.path.join(dummy_dir, "seg_1.h264")
                    assert segments[1][0] == os.path.join(dummy_dir, "seg_2.h264")


def test_cleanup_old_segments():
    dummy_dir = "dummy_buffer"
    old_file = os.path.join(dummy_dir, "old.h264")
    new_file = os.path.join(dummy_dir, "new.h264")
    with patch("src.video_recording._buffer_dir", dummy_dir):
        with patch(
            "src.video_recording._list_segments",
            return_value=[(old_file, time.time() - 10), (new_file, time.time())],
        ):
            with patch("os.remove") as mock_remove:
                _cleanup_old_segments(1)
                mock_remove.assert_called_once_with(old_file)




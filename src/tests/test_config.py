import pytest
from unittest.mock import patch, mock_open
from ..config import Config
import json
import sys

def test_config_file_not_found():
    with patch("builtins.open", side_effect=FileNotFoundError):
        with pytest.raises(SystemExit) as e:
            Config()
        assert e.type == SystemExit
        assert e.value.code == 1

def test_config_invalid_json():
    with patch("builtins.open", mock_open(read_data="invalid json")):
        with pytest.raises(SystemExit) as e:
            Config()
        assert e.type == SystemExit
        assert e.value.code == 1

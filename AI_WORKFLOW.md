# AI Development Workflow

This guide documents the automated developer workflow for the AI agent to run quick checks and remote tests of NoiseBuster.

FYI - some file are gitignored. always make sure that is kept in mind when listing files. 

## Environment Setup

Before running checks, ensure the development environment is correctly configured.

0. check that the background service is stopped (only needed to do this at the beginning)
```bash
sudo systemctl stop noisebuster.service
```

1.  **Recreate the Virtual Environment (if necessary).** If `pip` is broken or dependencies are corrupt, start fresh:
    ```bash
    rm -rf env && python3 -m venv env
    ```

2.  **Activate the Virtual Environment.**
    ```bash
    source env/bin/activate
    ```

3.  **Install System Dependencies.** These are required for some Python packages.
    ```bash
    sudo apt-get update && sudo apt-get install -y python3-libcamera libcap-dev
    ```

4.  **Install Python Dependencies.**
    ```bash
    pip install -r requirements.txt
    ```

5.  **Install Development Tools.**
    ```bash
    pip install black flake8
    ```

## Quick Checklist

1.  **Make code changes locally.** After making changes, always test them using the steps below.

2.  **Activate the local Python environment.**
    ```bash
    source env/bin/activate
    ```

3.  **Compile the Python code.** something like this
    ```bash
    python3 -m py_compile xxx.py
    ```

4.  **Test the code on the Raspberry Pi.** Run a timed test of NoiseBuster (minimum 20 seconds).
    ```bash
    python noisebuster.py --test-duration 20
    ```

5.  **Inspect logs and behavior on the Pi and fix any issues.**

6.  **Repeat the process until all checks pass.**

## Code Quality

Periodically, run Black (formatter) and Flake8 (linter) locally.

```bash
black .
flake8 .
```

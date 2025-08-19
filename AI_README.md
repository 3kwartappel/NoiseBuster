# AI / Copilot workflow

Purpose

This short guide documents the automated developer workflow used by the Copilot AI agent to run quick checks and remote tests of NoiseBuster.

Quick checklist

- [ ] Make code changes locally
- [ ] Activate local virtualenv and run `black` and `flake8`
- [ ] SSH to the Pi and run a timed test of NoiseBuster (minium 30s example)
- [ ] Inspect logs / behavior on the Pi and fix issues
- [ ] Repeat until green

Commands (run from the project root on WSL)

Activate the WSL venv by opening a terminal:

```bash
source .wsl_venv/bin/activate
```

Run Black (format) and Flake8 (lint):

```bash
black .
flake8 .
```

Run a quick 30s remote test on the Pi (example):

```bash
# direct ssh command
ssh -t pi@192.168.0.112 "cd code/NoiseBuster; source env/bin/activate; python noisebuster.py --test-duration 30"

# OR use the helper script (passes duration to remote)
./run_pi.sh 30
```

Notes / tips

- Always run `black` and `flake8` locally before pushing changes or initiating a remote test. That avoids trivial style regressions and reveals obvious errors.
- Use `./run_pi.sh <seconds>` to pass different test durations (0 or omitted runs indefinitely).
- Check `noisebuster.log` on the Pi for detailed logs after a run.

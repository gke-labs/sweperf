# SWE-bench Trajectory Image Generator

This toolkit pulls execution logs (trajectories) from SWE-agent runs against SWE-bench and generates a replayable Docker image for each case. The resulting images use a pseudo-terminal (PTY) to visually simulate the agent typing and executing commands in real-time, exactly as they occurred in the original SWE-bench environment.

## Prerequisites

1. Python 3 and `pip` installed.
2. Docker daemon running (if you plan to use `--build`).
3. Install the dependencies via:
   ```bash
   pip3 install -r requirements.txt
   ```

## Getting the Trajectories

The SWE-bench team has migrated their execution logs to a public AWS S3 bucket. You must first download the trajectories for the run you wish to process. You can do this by using the official download script from the `swe-bench/experiments` repository:

```bash
git clone https://github.com/swe-bench/experiments.git
cd experiments
pip3 install boto3 requests urllib3 tqdm
python3 -m analysis.download_logs evaluation/verified/20251120_livesweagent_gemini-3-pro-preview
```

## How It Works

1. **`generate.py`** is the main orchestrator script. It scans a directory of `.traj.json` trajectory files, extracts all of the terminal commands executed by the agent (supporting both standard SWE-agent `action` payloads and `gemini-3-pro-preview` markdown blocks), and writes them to a `{instance_id}_trace.json` file.
2. It then generates a `{instance_id}.Dockerfile` that inherits from the official `swebench/sweb.eval.x86_64.{instance_id}` base image.
3. **`replay.py`** is copied into the Docker image as the entrypoint. It utilizes `pexpect` to spawn a bash pseudo-terminal, simulating keystrokes and executing the trace with realistic visual delays.

## Usage

You can run `generate.py` directly against the downloaded trajectories directory:

```bash
sudo python3 generate.py \
    --local-trajs-dir ../experiments/evaluation/verified/20251120_livesweagent_gemini-3-pro-preview/trajs/ \
    --build
```

*(Note: `sudo` is usually required for the `--build` flag so that the Python script can communicate with the local Docker daemon socket).*

### Flags

- `--local-trajs-dir`: Path to the local directory containing the downloaded `.traj.json` files (can contain nested subdirectories, as the script crawls it recursively).
- `--build`: If specified, the script will automatically invoke `docker build` to create the final `swe-agent-replay:{instance_id}` image.
- `--limit <N>`: Limit the number of trajectories processed (useful for testing, e.g., `--limit 1`).
- `--test`: Generates a dummy `test.Dockerfile` based on `ubuntu:22.04` and replays a mock `test_trace.json` instead of pulling large SWE-bench images.

## Testing a Generated Image

Once an image is built, you can run it interactively to watch the agent's trajectory replay in the terminal:

```bash
sudo docker run -it --rm swe-agent-replay:<instance_id>
```
*(Example: `sudo docker run -it --rm swe-agent-replay:pydata__xarray-4356`)*

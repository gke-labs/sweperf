# SWE-bench Trajectory Image Generator

This toolkit pulls execution logs (trajectories) from SWE-agent runs against SWE-bench and generates a replayable Docker image for each case. The resulting images use a pseudo-terminal (PTY) to visually simulate the agent typing and executing commands in real-time, exactly as they occurred in the original SWE-bench environment.

## Prerequisites

1. Python 3 and `pip` installed.
2. Docker daemon running (if you plan to use `--build`).
3. Install the dependencies via:
   ```bash
   pip3 install -r requirements.txt
   ```

## How It Works

1. **`generate.py`** is the main orchestrator script. When run, it will automatically clone the `swe-bench/experiments` repo, download the S3 trajectory logs for the specified run name (falling back to `--local-trajs-dir` if provided), and extract all of the terminal commands executed by the agent (supporting both standard SWE-agent `action` payloads and `gemini-3-pro-preview` markdown blocks), writing them to a `{instance_id}_trace.json` file.
2. It then generates a `{instance_id}.Dockerfile` that inherits from the official `swebench/sweb.eval.x86_64.{instance_id}` base image.
3. **`replay.py`** is copied into the Docker image as the entrypoint. It utilizes `pexpect` to spawn a bash pseudo-terminal, simulating keystrokes and executing the trace with realistic visual delays.

## Usage

You can run `generate.py` directly, and it will automatically download the default evaluation trajectories (`20251120_livesweagent_gemini-3-pro-preview`):

```bash
sudo python3 generate.py --build
```

*(Note: `sudo` is usually required for the `--build` flag so that the Python script can communicate with the local Docker daemon socket).*

### Flags

- `--local-trajs-dir`: Path to the local directory containing the downloaded `.traj.json` files (can contain nested subdirectories, as the script crawls it recursively). If omitted, the script downloads them automatically.
  - `--build`: If specified, the script will automatically invoke `docker build` to create the final `sweperf:{instance_id}` image.
- `--push`: Automatically pushes the built images to a remote registry (requires `--build`).
- `--image-prefix`: Prefix for the docker image tag. For example, if you set `--image-prefix my-registry/my-repo/`, the image will be tagged as `my-registry/my-repo/<run_name>:{instance_id}`.
- `--limit <N>`: Limit the number of trajectories processed (useful for testing, e.g., `--limit 1`).
- `--test`: Generates a dummy `test.Dockerfile` based on `ubuntu:22.04` and replays a mock `test_trace.json` instead of pulling large SWE-bench images.

## Testing a Generated Image

Once an image is built, you can run it interactively to watch the agent's trajectory replay in the terminal:

```bash
sudo docker run -it --rm sweperf:<instance_id>
```
*(Example: `sudo docker run -it --rm sweperf:pydata__xarray-4356`)*

### Wait for Claim Mode

To simulate use in a warm pool (e.g., Kubernetes Agent Sandbox), you can start the container in a paused state until it receives a claim signal. By setting the `WAIT_FOR_CLAIM_FILE` environment variable to a file path, the script will loop indefinitely until that file exists and contains `agents.x-k8s.io/sandbox-id`.

```bash
sudo docker run -it --rm -e WAIT_FOR_CLAIM_FILE=/tmp/claim.txt sweperf:<instance_id>
```
*(The execution will pause until you inject the signal: `echo "agents.x-k8s.io/sandbox-id" > /tmp/claim.txt` into the container)*

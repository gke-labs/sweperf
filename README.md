# SWE-perf

SWE-perf is a Kubernetes-based load testing and benchmarking framework designed to evaluate infrastructure performance under the heavy, bursty load of autonomous coding agents (such as SWE-agent).

## Architecture

*   **High-Density GKE Cluster**: The test cluster is automatically configured with a high-density footprint (`--default-max-pods-per-node=256`). This allows us to massively stress the Kubernetes scheduler and evaluate high-concurrency pod churn without hitting standard secondary IP allocation limits.
*   **Agent Sandbox**: We leverage [kubernetes-sigs/agent-sandbox](https://github.com/kubernetes-sigs/agent-sandbox) to safely execute untrusted agent actions inside isolated pods.
*   **Log-Normal Replay Engine (`replay.py`)**: A python script that lives inside a Kubernetes ConfigMap and is mounted directly into the benchmark pods. It takes a pre-recorded agent trajectory, simulates character-by-character shell typing, and synthesizes highly realistic LLM latency (think time) using a log-normal distribution.
*   **Stateless Submitter (`benchmark/submitter.sh`)**: A robust, lightweight bash controller that queries the Kubernetes API and maintains a strict concurrent pod limit over a user-defined time window, automatically backfilling pods as they complete.
*   **Metrics Collector**: A parallel background process that records `kubectl top nodes` throughout the benchmark and automatically processes Average, Max, and P90 CPU and RAM statistics upon completion.

## Usage

### 1. Environment Setup

The `sweperf` script automates the entire provisioning process across two subcommands.

First, create the GKE cluster and install the agent-sandbox:
```bash
./sweperf create-cluster <PROJECT_ID> <REGION> <CLUSTER_NAME> <REPO_NAME>
```

Next, generate the SWE-bench docker images, push them to the registry, and prepull them onto the nodes to prevent cold-start skew:
```bash
./sweperf generate-images <PROJECT_ID> <REGION> <REPO_NAME> [IMAGE_LIMIT]
```

### 2. Running a Benchmark

The easiest way to execute a test is via the `run-benchmark` subcommand, which automatically spins up the submitter alongside the metrics collector.

```bash
./sweperf run-benchmark <DURATION_SECONDS> <CONCURRENCY>

# Example (20 minutes with 512 active pods):
# ./sweperf run-benchmark 1200 512
```

### 3. Modifying Agent Latency (Extreme Churn Testing)

By default, the `replay.py` script natively emulates realistic LLM latency averaging ~15.6s of sleep between executed bash commands (derived from real-world agent trajectories).

If you want to evaluate maximum cluster churn without being bottlenecked by simulated LLM think time, you can override the distribution to floor out at a fixed `0.5s` delay. Edit `benchmark/pod_template.yaml` and add the following environment variable to the container spec:

```yaml
env:
- name: LLM_LATENCY_MU
  value: "-5"
```

## Testing

To run the local unit tests that verify the `replay.py` execution within a dummy Docker container using `pexpect`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pytest pexpect
pytest tests/test_replay.py
```

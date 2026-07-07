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

The `setup.sh` script automates the entire provisioning process: it creates the GKE cluster, provisions the Artifact Registry, generates the SWE-bench docker images, pushes them, deploys the agent-sandbox controller, and prepulls the images onto the nodes to prevent cold-start skew during the benchmark.

```bash
./setup.sh <PROJECT_ID> <REGION> <CLUSTER_NAME> <REPO_NAME> [IMAGE_LIMIT]

# Example:
# ./setup.sh my-gcp-project us-central1 my-cluster swe-perf-repo 10
```

### 2. Running a Benchmark

The easiest way to execute a test is via the wrapper script, which automatically spins up the submitter alongside the metrics collector.

```bash
./run_benchmark_with_metrics.sh
```

*Note: You can easily adjust the `DURATION` (seconds) and `CONCURRENCY` (target active pods) variables at the top of the `run_benchmark_with_metrics.sh` script.*

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

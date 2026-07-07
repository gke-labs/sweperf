# SWE-perf

SWE-perf generates Docker containers that run SWE-bench derived workloads to emulate the behavior of autonomous coding agents (like SWE-agent). It also provides an optional Kubernetes-based benchmarking framework to evaluate infrastructure performance under the heavy, bursty load of these agents.

## Core Feature: Workload Image Generation

The most critical component of SWE-perf is the image generation engine. It creates standalone Docker images that perfectly replicate an autonomous agent interacting with a codebase. 

Instead of running an expensive LLM in the loop, the generated containers use a **Log-Normal Replay Engine** (`benchmark/replay.py`). This engine:
1. Takes a pre-recorded agent trajectory (commands run during a SWE-bench task).
2. Simulates character-by-character shell typing using `pexpect` against a bash session.
3. Synthesizes highly realistic LLM latency (think time) between commands using a log-normal distribution derived from real-world agent trajectories (averaging ~15.6s).

These standalone containers can be deployed in any environment to simulate realistic AI agent workloads without requiring an actual LLM backend or API keys.

### Usage: Generating Images

To generate the SWE-bench docker images, push them to a registry, and optionally pre-pull them onto nodes:

```bash
./sweperf generate-images <PROJECT_ID> <REGION> <REPO_NAME> [IMAGE_LIMIT]
```
*Note: This utilizes the `generate-images/generate.py` script under the hood to build images with the injected replay engine and trajectory traces.*

---

## Optional: Cluster Infrastructure & Benchmarking

While the generated images can be used anywhere, SWE-perf also includes scripts to provision a high-density GKE cluster and run structured load tests.

### 1. Environment Setup

Create a GKE cluster with a high-density footprint (`--default-max-pods-per-node=256`) and install the [agent-sandbox](https://github.com/kubernetes-sigs/agent-sandbox) to safely execute untrusted actions inside isolated pods:

```bash
./sweperf create-cluster <PROJECT_ID> <REGION> <CLUSTER_NAME> <REPO_NAME>
```

### 2. Running a Benchmark

The `run-benchmark` subcommand spins up a stateless submitter alongside a metrics collector. The submitter queries the Kubernetes API and maintains a strict concurrent pod limit over a user-defined time window, automatically backfilling pods as they complete.

```bash
./sweperf run-benchmark <DURATION_SECONDS> <CONCURRENCY>

# Example (20 minutes with 512 active pods):
# ./sweperf run-benchmark 1200 512
```

### 3. Modifying Agent Latency (Extreme Churn Testing)

If you want to evaluate maximum cluster churn without being bottlenecked by simulated LLM think time, you can override the distribution to floor out at a fixed `0.5s` delay. Edit `benchmark/pod_template.yaml` and add the following environment variable to the container spec:

```yaml
env:
- name: LLM_LATENCY_MU
  value: "-5"
```

## Testing

To run the local unit tests that verify the `replay.py` execution within a dummy Docker container using `pexpect`:

```bash
python3 -m unittest discover -s tests
```

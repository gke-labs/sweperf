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
./sweperf generate-images --project <PROJECT_ID> --region <REGION> --repo <REPO_NAME> [--limit <LIMIT>] [--run <RUN_NAME>]
```

**Options:**
* `--project`: Your Google Cloud project ID.
* `--region`: The Google Cloud region (e.g., `us-central1`).
* `--repo`: The name of the Artifact Registry repository to push images to.
* `--limit`: (Optional) The maximum number of images to generate (default: 0 for all).
* `--run`: (Optional) The SWE-bench experiment run name to pull trajectories from.

*Note: By default, it uses trajectories from `20251120_livesweagent_gemini-3-pro-preview`. You can specify a different run from the SWE-bench experiments repository using the `--run` flag.*
*This utilizes the `generate-images/generate.py` script under the hood to build images with the injected replay engine and trajectory traces.*

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

If you want to evaluate maximum cluster churn without being bottlenecked by simulated LLM think time, or if you want to test different latency profiles, you can override the distribution parameters. The timing is completely parameterizable via environment variables in the container spec. 

Edit `benchmark/pod_template.yaml` and add the following environment variables (these are the defaults):

```yaml
env:
- name: LLM_LATENCY_MU
  value: "2.0414"
- name: LLM_LATENCY_SIGMA
  value: "0.8674"
- name: LLM_LATENCY_MIN
  value: "0.5"
```

To floor out the latency for extreme churn testing (e.g. constant 0.5s delay), you can set `LLM_LATENCY_MU` to a large negative number like `"-5"`, or explicitly set `LLM_LATENCY_MIN` and a negative `LLM_LATENCY_MU`.

## Testing

To run the local unit tests that verify the `replay.py` execution within a dummy Docker container using `pexpect`:

```bash
python3 -m unittest discover -s tests
```

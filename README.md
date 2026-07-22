# SWE-perf

SWE-perf provides a suite of standalone Docker containers (including a unified On-Demand Runner) that emulate the behavior of autonomous coding agents (like SWE-agent or OpenHands). This suite allows teams to evaluate infrastructure performance under the heavy, bursty load of AI agents, without actually needing to run an expensive LLM in the loop.

## Table of Contents
- [Architecture & On-Demand Runner](#architecture--on-demand-runner)
- [Cluster Infrastructure & Caching](#cluster-infrastructure--caching)
- [Benchmarking](#benchmarking)
- [Image Properties & Usage](#image-properties--usage)
- [The Pre-baked Image Suite](#the-pre-baked-image-suite)
- [Building / Regenerating Images (Advanced)](#building--regenerating-images-advanced)
- [Testing](#testing)

## Architecture & On-Demand Runner

Instead of hitting an OpenAI or Gemini API, the containers use an embedded **Log-Normal Replay Engine**. This engine:
1. Takes a pre-recorded agent trajectory (commands run during a SWE-bench task).
2. Simulates character-by-character shell typing using `pexpect` against a bash session.
3. Synthesizes realistic LLM latency (think time) between commands using a log-normal distribution derived from real-world agent trajectories (averaging ~15.6s).

**The On-Demand Runner**
The **On-Demand Runner** (`sweperf:universal`) is a single, unified Docker image. When an On-Demand Pod starts, it dynamically uses pre-extracted setup scripts to fetch dependencies, builds the SWE-bench environment for the specific task at runtime, and executes the simulated trajectory.

---

## Cluster Infrastructure & Caching

SWE-perf includes scripts to provision a high-density GKE cluster, set up package caches, and run structured load tests.

### 1. Environment Setup

Create a GKE cluster with a high-density footprint (`--default-max-pods-per-node=256`). This command will also automatically provision an Artifact Registry repository and synchronize the SWE-perf image suite into it (used for the pre-baked image suite):

```bash
./sweperf create-cluster <PROJECT_ID> <REGION> <CLUSTER_NAME> <REPO_NAME>
```

### 2. Artifact Registry Caches (Crucial for On-Demand Run)

Since the On-Demand Runner dynamically builds the environment for each task at runtime, it relies heavily on fetching dependencies (like `pip install`). To avoid getting rate-limited or bogged down by network latency during high-density tests, deploy a PyPI proxy cache in Artifact Registry:

```bash
./sweperf create-caches <PROJECT_ID> <REGION> <PYPI_REPO>
```

---

## Benchmarking

With the cluster and caches set up, you can run realistic load tests.

**Choosing a Benchmark:**
- **On-Demand Benchmark** simulates a normal agentic workload where the agent operates on arbitrary repositories on the fly (it does not know the repository or environment beforehand and must build it at runtime).
- **Pre-baked Benchmark** simulates a Reinforcement Learning (RL) workload where the environment is thoroughly known, cached, and pre-baked (because an RL agent repeatedly interacts with the same known repository during training).

### On-Demand Benchmark

The `run-universal` subcommand spins up a stateless submitter alongside a metrics collector. It queries the Kubernetes API and maintains a strict concurrent pod limit over a user-defined time window using the On-Demand Runner.

```bash
./sweperf run-universal <DURATION_SECONDS> <CONCURRENCY> [PYPI_CACHE_URL]

# Example (20 minutes with 512 active pods, utilizing the PyPI cache):
# ./sweperf run-universal 1200 512 us-central1-python.pkg.dev/my-project/my-pypi-cache
```

### Pre-baked Benchmark (Pre-built Images)

If you are using the pre-baked suite of 500+ pre-built isolated images (one per task), you should pre-pull images to avoid network throttling:
```bash
./sweperf prepull-images
```
Then run the older submitter script:
```bash
./sweperf run-benchmark <DURATION_SECONDS> <CONCURRENCY>
```

---

## Image Properties & Usage

There are several useful dials baked into the container.

### Modifying Agent Latency (Extreme Churn Testing)

If you want to evaluate maximum cluster churn without being bottlenecked by simulated LLM think time, you can override the timing distribution (defaults shown):

```yaml
env:
- name: LLM_LATENCY_MU
  value: "2.0414"
- name: LLM_LATENCY_SIGMA
  value: "0.8674"
- name: LLM_LATENCY_MIN
  value: "0.5"
```
To floor out the latency (e.g. constant 0.5s delay), set `LLM_LATENCY_MU` to a negative number like `"-5"`.

### Wait for Claim (Agent Sandbox Integration)

To integrate seamlessly with [Agent Sandbox's warm pools](https://github.com/kubernetes-sigs/agent-sandbox), the replay engine can block execution until the Pod is assigned. Set `WAIT_FOR_CLAIM_FILE` to a path containing downward API labels (e.g., `/etc/podinfo/labels`). The engine waits for the `agents.x-k8s.io/sandbox-id` label.

### Wait for Start Port (Network Blocking)

Set the `WAIT_FOR_START_PORT` (e.g., `8080`) to have the pod pause until it receives an HTTP GET on `/start`. Useful for synchronizing a massive start across hundreds of pre-warmed pods.

---

## The Pre-baked Image Suite

If you want to use the pre-baked suite of 500+ distinct images:

```bash
# 1. Trigger the server-to-server copy into your destination Artifact Registry
./sweperf copy-images us-central1-docker.pkg.dev/<YOUR_PROJECT>/<YOUR_REPO_NAME>

# 2. Generate your local image index to point to your freshly-copied repo
./sweperf generate-image-list us-central1-docker.pkg.dev/<YOUR_PROJECT>/<YOUR_REPO_NAME>
```

---

## Building / Regenerating Images (Advanced)

If you make edits to the replay engine, you will need to re-generate the images.

### Building On-Demand Images

1. **Base SWE-bench Image:**
   Build the generic base environment (`sweb.base.x86_64:latest`):
   ```bash
   ./sweperf build-sweb-base
   ```
2. **On-Demand Image:**
   Iterate over tasks, extract setup bash scripts, and build the single On-Demand Docker image (`sweperf:universal`):
   ```bash
   ./sweperf generate-universal [--image-prefix <PREFIX>]
   ```

### Building Pre-baked Isolated Images (Per-Task)
```bash
./sweperf generate-images --project <PROJECT_ID> --region <REGION> --repo <REPO_NAME> [--limit <LIMIT>] [--run <RUN_NAME>]
```

---

## Testing

To run the local unit tests that verify the `replay.py` execution within a dummy Docker container using `pexpect`:

```bash
python3 -m unittest discover -s tests
```

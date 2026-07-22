# SWE-perf

SWE-perf provides a suite of standalone Docker containers that emulate the behavior of autonomous coding agents (like SWE-agent or OpenHands). This suite allows teams to evaluate infrastructure performance under the heavy, bursty load of AI agents, without actually needing to run an expensive LLM in the loop.

## Table of Contents
- [The Image Suite](#the-image-suite)
- [Getting the Images](#-getting-the-images)
- [Image Properties & Usage](#image-properties--usage)
- [Building / Regenerating Images (Advanced)](#building--regenerating-images-advanced)
- [Cluster Infrastructure & Benchmarking](#optional-cluster-infrastructure--benchmarking)
- [Testing](#testing)

## The Image Suite

The core value of SWE-perf is the container suite itself. Instead of hitting an OpenAI or Gemini API, the containers use an embedded **Log-Normal Replay Engine**. This engine:
1. Takes a pre-recorded agent trajectory (commands run during a SWE-bench task).
2. Simulates character-by-character shell typing using `pexpect` against a bash session.
3. Synthesizes realistic LLM latency (think time) between commands using a log-normal distribution derived from real-world agent trajectories (averaging ~15.6s).

**Two Operation Modes:**
- **On-Demand Runner (Singleton Image):** A single, unified Docker image (`sweperf:universal`). When it starts, it dynamically uses pre-extracted setup scripts to fetch dependencies and builds the SWE-bench environment for the specific task at runtime. This simulates a normal agentic workload where the agent operates on arbitrary repositories on the fly.
- **Pre-baked Images:** A suite of 500+ separate images (one for each SWE-bench task). This simulates a Reinforcement Learning (RL) workload where the environment is thoroughly known, cached, and pre-baked (because an RL agent repeatedly interacts with the same known repository during training).

These standalone containers can be deployed in any environment to simulate realistic AI agent workloads natively.

---

## 🚀 Getting the Images

If you want to use the pre-built, production-ready SWE-perf image suite within your own Google Cloud projects, **you do not need to generate them yourself.** Instead, synchronize a copy of the official repository directly into your own Artifact Registry. This syncs over both the singleton On-Demand image and the Pre-baked suite.

The most efficient way to achieve this is via a server-to-server copy using `gcrane` (a Google-maintained CLI for container registries). This bypasses downloading hundreds of gigabytes locally and takes only seconds to copy all images natively.

```bash
# 1. Authenticate to Google Cloud
gcloud auth login
gcloud auth configure-docker us-central1-docker.pkg.dev

# 2. Trigger the server-to-server copy into your destination Artifact Registry
./sweperf copy-images \
  us-central1-docker.pkg.dev/<YOUR_PROJECT>/<YOUR_REPO_NAME>

# 3. Generate your local image index to point to your freshly-copied repo
./sweperf generate-image-list \
  us-central1-docker.pkg.dev/<YOUR_PROJECT>/<YOUR_REPO_NAME>
```

By explicitly copying the images into your own project and generating the local manifests, your GKE clusters and VMs gain native, frictionless access without having to navigate cross-project IAM restrictions or service account key sharing.

Here is an example Pod spec using the singleton On-Demand image:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: sweperf-agent-test
spec:
  containers:
  - name: agent
    # Replace with your project and repo
    image: us-central1-docker.pkg.dev/<YOUR_PROJECT>/<YOUR_REPO_NAME>/sweperf:universal
  restartPolicy: Never
```

---

## Image Properties & Usage

Once you have access to the images, you can deploy them directly. There are several useful dials baked into the container.

### Modifying Agent Latency (Extreme Churn Testing)

If you want to evaluate maximum cluster churn without being bottlenecked by simulated LLM think time, or if you want to test different latency profiles, you can override the distribution parameters. The timing is parameterizable via environment variables when running the container (these are the defaults):

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

### Wait for Claim (Agent Sandbox Integration)

To use the generated images seamlessly with [Agent Sandbox's warm pools](https://github.com/kubernetes-sigs/agent-sandbox), the replay engine can be configured to block execution until the Pod is formally claimed and assigned to a user.

Set the `WAIT_FOR_CLAIM_FILE` environment variable to a file path containing the downward API labels (e.g. `/etc/podinfo/labels`). The replay script will loop indefinitely until it finds the `agents.x-k8s.io/sandbox-id` label inside that file, which is the platform signal injected by Agent Sandbox upon a successful claim.

Example for a pod spec:
```yaml
env:
- name: WAIT_FOR_CLAIM_FILE
  value: "/etc/podinfo/labels"
volumeMounts:
- name: podinfo
  mountPath: /etc/podinfo
volumes:
- name: podinfo
  downwardAPI:
    items:
    - path: "labels"
      fieldRef:
        fieldPath: metadata.labels
```

---

### Wait for Start Port (Network Blocking)

If you are not using Agent Sandbox but still want to deploy pods in a "warm" paused state until explicitly triggered, you can use the `WAIT_FOR_START_PORT` mode. This is useful for load testing where you want to spin up pods and have them all start running the agent trajectory simultaneously via a broadcast signal.

Setting the `WAIT_FOR_START_PORT` environment variable to a port number will cause the container to stand up a simple TCP server and pause execution until it receives the string `start` (or an HTTP GET request to `/start`) on that port.

Example for a pod spec:
```yaml
env:
- name: WAIT_FOR_START_PORT
  value: "8080"
```
To trigger the replay engine once the pod is running:
```bash
curl -X GET http://<pod-ip>:8080/start
```

---

## Building / Regenerating Images (Advanced)

If you have made edits to the replay engine or script injector, you will need to re-generate the image suite from scratch.

### 1. Building the On-Demand Singleton Image

First, build the generic base environment (`sweb.base.x86_64:latest`):
```bash
./sweperf build-sweb-base
```

Then extract setup bash scripts, and build the single On-Demand Docker image (`sweperf:universal`):
```bash
./sweperf generate-universal [--image-prefix <PREFIX>]
```

### 2. Building Pre-baked Isolated Images (Per-Task)
To generate the legacy 500+ Docker images, push them to a registry, and optionally pre-pull them onto nodes:

```bash
./sweperf generate-images --project <PROJECT_ID> --region <REGION> --repo <REPO_NAME> [--limit <LIMIT>] [--run <RUN_NAME>]
```

---

## Optional: Cluster Infrastructure & Benchmarking

While the generated images can be used anywhere, SWE-perf also includes scripts to provision a high-density GKE cluster, set up caches, and run structured load tests for both On-Demand and Pre-baked workloads.

### 1. Environment Setup

Create a GKE cluster with a high-density footprint (`--default-max-pods-per-node=256`). This command will also automatically provision an Artifact Registry repository and synchronize the SWE-perf image suite into it.

```bash
./sweperf create-cluster <PROJECT_ID> <REGION> <CLUSTER_NAME> <REPO_NAME>
```

### 2. Artifact Registry Caches (Crucial for On-Demand Run)

Since the On-Demand Runner dynamically builds the environment for each task at runtime, it relies heavily on fetching dependencies (like `pip install`). To avoid getting rate-limited or bogged down by network latency during high-density tests, deploy a PyPI proxy cache:

```bash
./sweperf create-caches <PROJECT_ID> <REGION> <PYPI_REPO>
```

### 3. Pre-pull Test Images (Crucial for Pre-baked Run)

To avoid network throttling and excessive disk I/O when spinning up hundreds of distinct pods simultaneously, cache the pre-baked test images onto your nodes beforehand:

```bash
./sweperf prepull-images
```

### 4. Running a Benchmark

The submitter commands spin up a stateless submitter alongside a metrics collector. It queries the Kubernetes API and maintains a strict concurrent pod limit over a user-defined time window, automatically backfilling pods as they complete.

**On-Demand Benchmark**
```bash
./sweperf run-universal <DURATION_SECONDS> <CONCURRENCY> [PYPI_CACHE_URL]

# Example (20 minutes with 512 active pods, utilizing the PyPI cache):
# ./sweperf run-universal 1200 512 us-central1-python.pkg.dev/my-project/my-pypi-cache
```

**Pre-baked Benchmark**
```bash
./sweperf run-benchmark <DURATION_SECONDS> <CONCURRENCY>
```

---

## Testing

To run the local unit tests that verify the `replay.py` execution within a dummy Docker container using `pexpect`:

```bash
python3 -m unittest discover -s tests
```

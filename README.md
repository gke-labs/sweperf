# SWE-perf

SWE-perf generates Docker containers that run SWE-bench derived workloads to emulate the behavior of autonomous coding agents (like SWE-agent). It also provides an optional Kubernetes-based benchmarking framework to evaluate infrastructure performance under the heavy, bursty load of these agents.

## Core Feature: Workload Image Generation

The most critical component of SWE-perf is the image generation engine. It creates standalone Docker images that perfectly replicate an autonomous agent interacting with a codebase. 

Instead of running an expensive LLM in the loop, the generated containers use a **Log-Normal Replay Engine** (`benchmark/replay.py`). This engine:
1. Takes a pre-recorded agent trajectory (commands run during a SWE-bench task).
2. Simulates character-by-character shell typing using `pexpect` against a bash session.
3. Synthesizes highly realistic LLM latency (think time) between commands using a log-normal distribution derived from real-world agent trajectories (averaging ~15.6s).

These standalone containers can be deployed in any environment to simulate realistic AI agent workloads without requiring an actual LLM backend or API keys.

---

## 🚀 Getting the Images

If you want to use the pre-built, production-ready SWE-perf image suite within your own Google Cloud projects, **you do not need to generate them yourself.** Instead, synchronize a copy of the official repository directly into your own Artifact Registry. 

The most efficient way to achieve this is via a purely server-to-server copy using `gcrane` (a Google-maintained CLI for container registries). This bypasses downloading hundreds of gigabytes locally and takes only seconds to copy all 500+ images natively.

```bash
# 1. Install gcrane if you do not have it
go install github.com/google/go-containerregistry/cmd/gcrane@latest

# 2. Authenticate to Google Cloud
gcloud auth login
gcloud auth configure-docker us-central1-docker.pkg.dev

# 3. Trigger the server-to-server copy into your destination Artifact Registry
gcrane cp -r \
  us-central1-docker.pkg.dev/bsalmon-gke-dev/sweperf \
  us-central1-docker.pkg.dev/<YOUR_PROJECT>/<YOUR_REPO_NAME>
```

By explicitly copying the images into your own project, your GKE clusters and VMs gain native, frictionless access without having to navigate cross-project IAM restrictions or service account key sharing.

---

## Image Properties & Usage

Once you have access to the images, you can deploy them directly. There are several useful dials baked into the container.

### Modifying Agent Latency (Extreme Churn Testing)

If you want to evaluate maximum cluster churn without being bottlenecked by simulated LLM think time, or if you want to test different latency profiles, you can override the distribution parameters. The timing is completely parameterizable via environment variables when running the container (these are the defaults):

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

If you are not using Agent Sandbox but still want to deploy pods in a "warm" paused state until explicitly triggered, you can use the `WAIT_FOR_START_PORT` mode. This is useful for load testing where you want to spin up 500 pods and have them all start running the agent trajectory simultaneously via a broadcast signal.

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

**Trajectory Source**  
The image generator automatically downloads agent trajectories from the official [SWE-bench/experiments](https://github.com/swe-bench/experiments) repository. This repository hosts public traces of various LLMs and agents (like SWE-agent or OpenHands) attempting to solve SWE-bench issues. SWE-perf extracts the raw bash commands from these JSON traces and bakes them directly into the generated Docker images.

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

## Testing

To run the local unit tests that verify the `replay.py` execution within a dummy Docker container using `pexpect`:

```bash
python3 -m unittest discover -s tests
```

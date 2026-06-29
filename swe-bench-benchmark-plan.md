# Plan: Integrating SWE-bench Workload with ClusterLoader2

## 1. Background & Motivation

Currently, the `agent-sandbox` load tests (via ClusterLoader2 in `dev/load-test/agent-sandbox-load-test.yaml`) only measure the creation latency of raw `Sandbox` resources.

However, the `agent-sandbox-rl` SWE-bench orchestration relies on the **v1beta1 extensions**:
1. **`SandboxTemplate`**: Defines the base Sandbox configuration for a SWE-bench task image.
2. **`SandboxWarmPool`**: Maintains a pre-warmed set of Sandboxes based on the template.
3. **`SandboxClaim`**: Claims an existing, running Sandbox from the warm pool to achieve sub-second startup times.

To accurately load-test the SWE-bench workflow, we need to model this specific resource churn in ClusterLoader2 (CL2).

## 2. Integration Plan (Custom Python Benchmark)

Since ClusterLoader2 cannot natively measure execution commands sent over the SDK, we will build a custom Python benchmark using the `k8s_agent_sandbox` asynchronous SDK. 

### Step 1: Pre-process the SWE-bench Data (GCS Tarball)
We will create a pre-processing script that extracts the heavy, task-specific data (like the Conda environment and Git repository) from the standard SWE-bench images.
It will package this data into an uncompressed `.tar` file and upload it to a GCS bucket. 

### Step 2: Create the Base Infrastructure
We will create two Kubernetes YAML templates to set up the environment before the benchmark runs:
- `swe-bench-template.yaml`: A single, generic `SandboxTemplate` using a lightweight base image (e.g., Python or Ubuntu) with basic tools like `curl` and `tar` installed.
- `swe-bench-warmpool.yaml`: A single `SandboxWarmPool` that provisions pre-warmed replicas of this generic template.

### Step 3: Write the Python Benchmark Script
We will create a dedicated asynchronous Python script (e.g., `test/benchmarks/swe_bench_load_test.py`) that uses the Python SDK (`k8s_agent_sandbox`) to perform the load test.

The script will use `asyncio` to execute `N` concurrent tasks. Each task will do the following:
1. **Claim:** Create a `SandboxClaim` targeting the generic warm pool and await its binding. Record the `Claim Latency`.
2. **Connect:** Establish a connection to the Sandbox.
3. **Download:** Use `handle.async_exec()` to run the GCS download and extraction command (e.g., `curl -s <url> | tar -xz`). Record the `Download Latency`.
4. **Execute (Optional):** Run a mock SWE-bench test command. Record the `Execution Latency`.
5. **Cleanup:** Delete the claim.

At the end of the run, the script will aggregate all recorded latencies (min, max, p50, p90, p99) and output a detailed performance report.

## 3. Next Steps

If this plan looks good, I can proceed with implementing these files:
1. Creating the three YAML object templates (`Template`, `WarmPool`, `Claim`).
2. Authoring the `swe-bench-load-test.yaml` CL2 configuration.
3. Adding a run script in `test-recipes/`.

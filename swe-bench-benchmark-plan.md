# Plan: Baseline SWE-bench Load Test with ClusterLoader2

## 1. Background & Motivation

We want to establish a baseline performance metric for raw Kubernetes Pod creation latency when running heterogeneous SWE-bench images. Before we test the `agent-sandbox` controller and its WarmPool capabilities, we need to know how fast standard GKE can spin up standard Pods.

The goal is to submit raw Pods against random SWE-bench images, keeping a fixed number "in flight" (concurrently running) at any given time, and measure the startup and execution latency using ClusterLoader2 (CL2).

## 2. Integration Plan (ClusterLoader2 Baseline)

### Step 1: Pre-pull the SWE-bench Images
We will use the `agent-sandbox-rl` prepull feature (via `prepull_images.py` / `sync_swe_bench_images.py`) to pre-copy the full SWE-bench images to the target Kubernetes nodes via a DaemonSet. This avoids cold-start network latency from skewing our baseline metrics.

### Step 2: Write the Closed-Loop Python Driver
ClusterLoader2 is primarily an open-loop load testing tool. To satisfy the requirement of "scaling up from 1 job until a few are pending and submitting immediately on completion," we will build a custom Python benchmark script (`baseline_benchmark.py`).

The script will use the native `kubernetes` Python client to implement a dynamic concurrency controller:
1. **Target Pending State**: We will maintain a rule: `if current_pending_jobs < TARGET_PENDING (e.g., 2), submit a new Job.`
2. **Slow Start & Scale Up**: 
   - At T=0, 0 jobs are pending, so it submits jobs until 2 are pending.
   - If the cluster has capacity, those 2 become `Running`. The pending count drops to 0. The script submits 2 more.
   - This naturally scales up the number of `Running` jobs until the cluster hits its maximum resource capacity (e.g., node CPU/RAM limits).
3. **Steady State**: Once the cluster is full, new jobs will stay `Pending`. The script stops submitting. As soon as a running Job completes, Kubernetes will schedule a pending one, dropping the pending count, which triggers the script to submit a replacement. This ensures perfect closed-loop utilization.

### Step 3: Random Image Selection
The script will fetch the list of SWE-bench instances (reusing the Hugging Face fetch logic from `sync_swe_bench_images.py`) and select a random pre-pulled image for each new Job. This ensures we baseline against heterogeneous images.

### Step 4: Measure & Report
The script will use the Kubernetes Watch API to record precise timestamps:
- `T0`: Job creation.
- `T1`: Pod enters `Running` state.
- `T2`: Job completes.

At the end of the run (e.g., after 50 jobs complete), it will output aggregated startup (`T1 - T0`) and execution (`T2 - T1`) latencies.

## 3. Next Steps

1. **Author the Generator Script:** Write the Python script to generate the batched CL2 configuration.
2. **Create the Base Pod Template:** Write a simple `raw-pod-template.yaml` that takes the `Image` as a template variable.
3. **Execute the Baseline:** Run the generated CL2 test against the GKE cluster and collect the baseline performance report.

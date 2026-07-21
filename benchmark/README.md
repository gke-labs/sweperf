# Benchmark Subsystem

This directory contains standalone execution shells and python daemon scripts designed to submit loads to Kubernetes testing clusters, track resource utilization continuously, and generate metrics reports.

### Overview of Resources

1. **`run_benchmark.sh`** (Master Wrapper)
   - Usage: `./run_benchmark.sh <mode: universal|legacy> <pod_template.yaml> <concurrency> <duration_seconds> <target_file> [extra_args...]`
   - **Recommended:** This acts as a unified entry point, effectively replacing the individual manual commands below. It spins up the `collector.py` and `node_watcher.py` monitoring daemons linearly before invoking the required worker shell, subsequently triggering `process_metrics.py` once execution halts. Data footprints are cleared cleanly between repeated calls.

2. **`submitter_universal.sh`** / **`submitter.sh`** (Stateless Load Injectors)
   - Periodically queries the Kubernetes API and maintains exactly `CONCURRENCY` number of active pods on the cluster, replacing pods dynamically as they finish, for the specified total `DURATION`.
   - `submitter_universal.sh` executes tests against standard generic base images using `INSTANCE_ID` configurations.
   - `submitter.sh` works over heavily baked independent image branches.

3. **`node_watcher.py` & `collector.py`** 
   - Non-blocking daemon scripts strictly tracing Node CPU / RAM load and active versus pending cluster pod states over the given run lengths.
   - Generates local cache telemetry to `node_metrics.txt`, `concurrency.txt`, and `pods.json`.

4. **`process_metrics.py`**
   - Automatically cross-references telemetry caching against timestamping footprints to produce final Markdown documents showing performance bounds (P50/P90), per-job execution times, and resource footprint estimations.

### Notes
Ensure the corresponding `pod_template*.yaml` configs accurately parameterize your `swe-bench` runtime arguments before orchestrating testing benchmarks en masse on any cluster setup!

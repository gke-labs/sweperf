import asyncio
import time
import argparse
import statistics
from k8s_agent_sandbox.async_sandbox_client import AsyncSandboxClient
from k8s_agent_sandbox.models import SandboxInClusterConnectionConfig

async def worker(client, pool_name, worker_id, tarball_url):
    print(f"Worker {worker_id}: Requesting claim from {pool_name}...")
    
    # 1. Measure claim latency
    t0 = time.time()
    sandbox = await client.create_sandbox(pool_name)
    claim_latency = time.time() - t0
    print(f"Worker {worker_id}: Claim bound in {claim_latency:.2f}s")
    
    # 2. Measure download latency
    # In a real run, this would be a real URL. For testing, it could be a small mock URL.
    # The command uses curl and pipes to tar into the /workspace volume created in the template.
    download_cmd = (
        "python3 -c 'import urllib.request, json, subprocess; "
        "req = urllib.request.Request(\"http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token\", headers={\"Metadata-Flavor\": \"Google\"}); "
        "token = json.loads(urllib.request.urlopen(req).read().decode())[\"access_token\"]; "
        f"req2 = urllib.request.Request(\"{tarball_url}\", headers={{\"Authorization\": f\"Bearer {{token}}\"}}); "
        "subprocess.Popen([\"tar\", \"-xz\", \"-C\", \"/workspace\"], stdin=urllib.request.urlopen(req2)).wait()'"
    )
    t1 = time.time()
    await sandbox.commands.run(download_cmd)
    download_latency = time.time() - t1
    print(f"Worker {worker_id}: Downloaded in {download_latency:.2f}s")
    
    # 3. Optional exec execution
    t2 = time.time()
    await sandbox.commands.run("echo 'mock swe-bench test execution'")
    exec_latency = time.time() - t2
    print(f"Worker {worker_id}: Executed in {exec_latency:.2f}s")
    
    return {
        "claim": claim_latency,
        "download": download_latency,
        "exec": exec_latency,
    }

async def main():
    parser = argparse.ArgumentParser(description="End-to-End SWE-bench Load Test Benchmark")
    parser.add_argument("--concurrency", type=int, default=10, help="Number of concurrent sandboxes to spawn")
    parser.add_argument("--pool-name", type=str, default="swe-bench-generic-pool", help="Name of the SandboxWarmPool to target")
    parser.add_argument("--tarball-url", type=str, required=True, help="URL to the GCS tarball (must be publicly accessible or signed)")
    args = parser.parse_args()
    
    # Note: Assumes running inside a Pod on the cluster. 
    # For local development against a kind cluster, SandboxGatewayConnectionConfig would be used.
    from k8s_agent_sandbox.models import SandboxLocalTunnelConnectionConfig
    config = SandboxLocalTunnelConnectionConfig(namespace="default")
    
    print(f"Starting load test with {args.concurrency} concurrent tasks...")
    t0 = time.time()
    
    async with AsyncSandboxClient(connection_config=config) as client:
        tasks = [
            worker(client, args.pool_name, i, args.tarball_url)
            for i in range(args.concurrency)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
    
    total_duration = time.time() - t0
    
    # Process results
    successes = []
    errors = []
    
    for r in results:
        if isinstance(r, Exception):
            errors.append(r)
        else:
            successes.append(r)
            
    print(f"\n--- LOAD TEST RESULTS ---")
    print(f"Total duration: {total_duration:.2f}s")
    print(f"Successful tasks: {len(successes)}")
    print(f"Failed tasks: {len(errors)}")
    
    if len(errors) > 0:
        print(f"\nErrors encountered: {errors[:3]} (truncated)")
        
    if successes:
        claim_times = [s["claim"] for s in successes]
        dl_times = [s["download"] for s in successes]
        exec_times = [s["exec"] for s in successes]
        
        print("\n--- LATENCY PERCENTILES ---")
        for name, metric in [("Claim", claim_times), ("Download", dl_times), ("Exec", exec_times)]:
            p50 = statistics.median(metric)
            p90 = statistics.quantiles(metric, n=10)[8] if len(metric) >= 10 else max(metric)
            p99 = statistics.quantiles(metric, n=100)[98] if len(metric) >= 100 else max(metric)
            print(f"{name} -> p50: {p50:.2f}s, p90: {p90:.2f}s, p99: {p99:.2f}s")

if __name__ == "__main__":
    asyncio.run(main())

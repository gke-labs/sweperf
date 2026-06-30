#!/usr/bin/env python3
import os
import sys
import urllib.request
import json
import logging
import argparse

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../agent-sandbox/examples/agent-sandbox-rl')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../agent-sandbox/clients/python/agentic-sandbox-client')))

try:
    from agent_sandbox_rl import SandboxFleet
except ImportError as e:
    print(f"Failed to import agent_sandbox_rl: {e}")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def fetch_swe_bench_lite_instances():
    """Fetch the list of SWE-bench Lite instance IDs from Hugging Face."""
    logging.info("Fetching SWE-bench Lite instances from Hugging Face...")
    instances = []
    offset = 0
    while True:
        url = f"https://datasets-server.huggingface.co/rows?dataset=princeton-nlp%2FSWE-bench_Lite&config=default&split=test&offset={offset}&length=100"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
                rows = data.get('rows', [])
                if not rows:
                    break
                for row in rows:
                    instances.append(row['row']['instance_id'])
                offset += len(rows)
        except Exception as e:
            logging.error(f"Failed to fetch dataset page at offset {offset}: {e}")
            break
    logging.info(f"Fetched {len(instances)} instances.")
    return instances

def prepull_batch(fleet, batch_images, batch_index):
    logging.info(f"Pre-pulling batch {batch_index} with {len(batch_images)} images...")
    tasks = [{"id": f"task-{i}", "image": img} for i, img in enumerate(batch_images)]
    
    # We must reset the plan between batches since we reuse the same fleet object,
    # or just create a new fleet. Creating a new fleet is safer to clear state.
    batch_fleet = SandboxFleet()
    batch_fleet.load_tasks(tasks)
    batch_fleet.plan()
    batch_fleet.prepull(wait=True)

def main():
    parser = argparse.ArgumentParser(description="Pre-pull SWE-bench images to Kubernetes nodes")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of instances to process (0 = all)")
    parser.add_argument("--batch-size", type=int, default=20, help="Number of images per DaemonSet (to avoid Pod limits)")
    
    args = parser.parse_args()
    
    # 1. Fetch Lite instances
    instances = fetch_swe_bench_lite_instances()
    if not instances:
        logging.error("No instances fetched. Exiting.")
        sys.exit(1)
        
    if args.limit > 0:
        instances = instances[:args.limit]
        logging.info(f"Limited processing to {args.limit} instances.")
        
    # 2. Form image names
    images = []
    for instance_id in instances:
        safe_id = instance_id.replace("__", "_1776_")
        images.append(f"swebench/sweb.eval.x86_64.{safe_id}:latest")
    
    # 3. Pre-pull in batches
    logging.info(f"Starting pre-pull for {len(images)} images in batches of {args.batch_size}...")
    fleet = SandboxFleet()
    
    for i in range(0, len(images), args.batch_size):
        batch = images[i:i + args.batch_size]
        prepull_batch(fleet, batch, (i // args.batch_size) + 1)
                
    logging.info(f"Finished pre-pulling all {len(images)} images.")

if __name__ == "__main__":
    main()

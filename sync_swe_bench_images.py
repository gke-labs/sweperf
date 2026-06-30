#!/usr/bin/env python3
import os
import sys
import subprocess
import concurrent.futures
import tempfile
import urllib.request
import json
import logging
import argparse

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def fetch_swe_bench_lite_instances():
    """Fetch the list of SWE-bench Lite instance IDs from Hugging Face."""
    logging.info("Fetching SWE-bench Lite instances from Hugging Face...")
    instances = []
    offset = 0
    while True:
        # The Hugging Face Datasets Server API paginates at 100 rows per request
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

def process_instance(instance_id, bucket_name, overwrite=False):
    """Pull, extract, tar, and upload a single SWE-bench instance image."""
    # Docker Hub images map double underscores to _1776_
    safe_id = instance_id.replace("__", "_1776_")
    image_name = f"swebench/sweb.eval.x86_64.{safe_id}:latest"
    tar_name = f"sweb.eval.x86_64.{safe_id}.tar.gz"
    bucket_url = f"gs://{bucket_name}/swebench/{tar_name}"
    
    # Check if it already exists in the bucket
    if not overwrite:
        check_cmd = ["gcloud", "storage", "ls", bucket_url]
        if subprocess.run(check_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            logging.info(f"[{instance_id}] Already exists in bucket, skipping.")
            return True

    logging.info(f"[{instance_id}] Processing image: {image_name}")
    
    # Run in a dedicated temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        # Pull the image
        pull_cmd = ["docker", "pull", image_name]
        res = subprocess.run(pull_cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logging.error(f"[{instance_id}] Failed to pull image {image_name}:\n{res.stderr}")
            return False
            
        # Create a container (do not start it)
        create_cmd = ["docker", "create", image_name]
        res = subprocess.run(create_cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logging.error(f"[{instance_id}] Failed to create container for {image_name}:\n{res.stderr}")
            return False
        container_id = res.stdout.strip()
        
        try:
            # Copy out directories
            logging.info(f"[{instance_id}] Extracting directories from container...")
            subprocess.run(["docker", "cp", f"{container_id}:/testbed", os.path.join(temp_dir, "testbed")], check=True)
            subprocess.run(["docker", "cp", f"{container_id}:/opt/miniconda3", os.path.join(temp_dir, "miniconda3")], check=True)
            
            # Tar them up
            logging.info(f"[{instance_id}] Compressing to tarball...")
            tar_path = os.path.join(temp_dir, tar_name)
            # Use gzip fast compression (-1) because disk/CPU bound is slower than GCS upload
            os.environ["GZIP"] = "-1" 
            tar_cmd = ["tar", "-czf", tar_path, "-C", temp_dir, "testbed", "miniconda3"]
            subprocess.run(tar_cmd, check=True)
            
            # Upload to GCS
            logging.info(f"[{instance_id}] Uploading to GCS...")
            upload_cmd = ["gcloud", "storage", "cp", tar_path, bucket_url]
            subprocess.run(upload_cmd, check=True)
            
            logging.info(f"[{instance_id}] Successfully uploaded to {bucket_url}")
        except subprocess.CalledProcessError as e:
            logging.error(f"[{instance_id}] Error during extract/compress/upload: {e}")
            return False
        finally:
            # Clean up container and image to prevent exhausting disk space
            subprocess.run(["docker", "rm", "-v", container_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["docker", "rmi", image_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
    return True

def main():
    parser = argparse.ArgumentParser(description="Synchronize SWE-bench images to GCS")
    parser.add_argument("bucket", help="GCS bucket name (e.g., my-bench-bucket)")
    parser.add_argument("--workers", type=int, default=8, help="Number of parallel workers (default: 8)")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing tarballs in GCS")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of instances to process (0 = all)")
    
    args = parser.parse_args()
    
    # 1. Fetch Lite instances
    instances = fetch_swe_bench_lite_instances()
    if not instances:
        logging.error("No instances fetched. Exiting.")
        sys.exit(1)
        
    if args.limit > 0:
        instances = instances[:args.limit]
        logging.info(f"Limited processing to {args.limit} instances.")
        
    # 2. Process concurrently
    logging.info(f"Starting parallel processing with {args.workers} workers...")
    
    success_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_id = {executor.submit(process_instance, iid, args.bucket, args.overwrite): iid for iid in instances}
        for future in concurrent.futures.as_completed(future_to_id):
            iid = future_to_id[future]
            try:
                success = future.result()
                if success:
                    success_count += 1
            except Exception as e:
                logging.error(f"[{iid}] Task threw exception: {e}")
                
    logging.info(f"Finished processing. Successful: {success_count}/{len(instances)}")

if __name__ == "__main__":
    main()

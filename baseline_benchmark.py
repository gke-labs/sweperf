#!/usr/bin/env python3
import time
import uuid
import random
import argparse
import logging
import urllib.request
import json
from collections import defaultdict
from kubernetes import client, config, watch

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def fetch_swe_bench_lite_images(limit=20):
    logging.info("Fetching SWE-bench Lite instance list from Hugging Face...")
    url = f"https://datasets-server.huggingface.co/rows?dataset=princeton-nlp%2FSWE-bench_Lite&config=default&split=test&offset=0&length={limit}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            rows = data.get('rows', [])
            instances = [row['row']['instance_id'] for row in rows]
            images = [f"swebench/sweb.eval.x86_64.{inst.replace('__', '_1776_')}:latest" for inst in instances]
            return images
    except Exception as e:
        logging.error(f"Failed to fetch images: {e}")
        return []

def create_pod_manifest(name, image):
    return client.V1Pod(
        api_version="v1",
        kind="Pod",
        metadata=client.V1ObjectMeta(
            name=name,
            labels={"app": "swe-bench-baseline"}
        ),
        spec=client.V1PodSpec(
            restart_policy="Never",
            containers=[
                client.V1Container(
                    name="swe-bench-test",
                    image=image,
                    # We just sleep to simulate execution without actually running eval.
                    # This measures purely the k8s overhead + pulling overhead.
                    command=["/bin/sh", "-c", "echo 'Simulating SWE-bench test...'; sleep 10"]
                )
            ]
        )
    )

def main():
    parser = argparse.ArgumentParser(description="Closed-Loop Baseline Benchmark")
    parser.add_argument("--target-pending", type=int, default=2, help="Number of pending pods to maintain")
    parser.add_argument("--total-pods", type=int, default=50, help="Total number of pods to execute before stopping")
    parser.add_argument("--namespace", type=str, default="default", help="Kubernetes namespace")
    args = parser.parse_args()

    config.load_kube_config()
    v1 = client.CoreV1Api()

    images = fetch_swe_bench_lite_images(limit=100)
    if not images:
        logging.error("No images available to run.")
        return

    logging.info(f"Target pending pods: {args.target_pending}")
    logging.info(f"Total pods to run: {args.total_pods}")

    pods_submitted = 0
    pods_completed = 0
    
    # State tracking
    pending_pods = set()
    running_pods = set()
    completed_pods = set()

    timestamps = {}  # pod_name -> {created, running, completed}

    def submit_new_pod():
        nonlocal pods_submitted
        if pods_submitted >= args.total_pods:
            return False
            
        pod_name = f"swe-bench-baseline-{uuid.uuid4().hex[:8]}"
        image = random.choice(images)
        manifest = create_pod_manifest(pod_name, image)
        
        logging.info(f"Submitting pod {pod_name} (image: {image})")
        timestamps[pod_name] = {"created": time.time()}
        
        try:
            v1.create_namespaced_pod(namespace=args.namespace, body=manifest)
            pods_submitted += 1
            return True
        except Exception as e:
            logging.error(f"Failed to submit pod {pod_name}: {e}")
            return False

    def check_and_fill_queue():
        # Submit new pods until we hit our target pending count
        while len(pending_pods) < args.target_pending and pods_submitted < args.total_pods:
            if not submit_new_pod():
                break

    # Initial submission
    check_and_fill_queue()

    # Watch loop
    w = watch.Watch()
    logging.info("Starting watch loop...")
    
    for event in w.stream(v1.list_namespaced_pod, namespace=args.namespace, label_selector="app=swe-bench-baseline"):
        pod = event['object']
        name = pod.metadata.name
        phase = pod.status.phase

        # Update our state sets
        if phase == "Pending":
            pending_pods.add(name)
            running_pods.discard(name)
        elif phase == "Running":
            if name in pending_pods:
                pending_pods.discard(name)
                timestamps[name]["running"] = time.time()
                logging.info(f"Pod {name} is Running. (Pending: {len(pending_pods)}, Running: {len(running_pods) + 1})")
            running_pods.add(name)
        elif phase in ["Succeeded", "Failed"]:
            if name not in completed_pods:
                pending_pods.discard(name)
                running_pods.discard(name)
                completed_pods.add(name)
                timestamps[name]["completed"] = time.time()
                pods_completed += 1
                logging.info(f"Pod {name} Completed ({pods_completed}/{args.total_pods}).")

        # After state update, check if we need to submit more to maintain the queue
        if pods_completed >= args.total_pods:
            logging.info("Reached total target completions.")
            w.stop()
            break
            
        check_and_fill_queue()

    # Report results
    logging.info("\n--- Benchmark Results ---")
    startup_times = []
    execution_times = []
    
    for name, times in timestamps.items():
        if "running" in times and "created" in times:
            startup_times.append(times["running"] - times["created"])
        if "completed" in times and "running" in times:
            execution_times.append(times["completed"] - times["running"])

    if startup_times:
        startup_times.sort()
        p50_start = startup_times[int(len(startup_times)*0.5)]
        p90_start = startup_times[int(len(startup_times)*0.9)]
        logging.info(f"Startup Latency (T1-T0): p50 = {p50_start:.2f}s, p90 = {p90_start:.2f}s")
    
    if execution_times:
        execution_times.sort()
        p50_exec = execution_times[int(len(execution_times)*0.5)]
        logging.info(f"Execution Latency (T2-T1): p50 = {p50_exec:.2f}s")
        
    # Cleanup
    logging.info("Cleaning up benchmark pods...")
    try:
        v1.delete_collection_namespaced_pod(
            namespace=args.namespace,
            label_selector="app=swe-bench-baseline"
        )
        logging.info("Cleanup successful.")
    except Exception as e:
        logging.error(f"Cleanup failed: {e}")

if __name__ == "__main__":
    main()

import json
import subprocess
import time
import sys

def is_pod_oom(pod):
    status = pod.get("status", {})
    if status.get("reason") == "OOMKilled":
        return True
    
    container_statuses = (
        status.get("containerStatuses", []) +
        status.get("initContainerStatuses", []) +
        status.get("ephemeralContainerStatuses", [])
    )
    for c_status in container_statuses:
        state_term = c_status.get("state", {}).get("terminated", {})
        last_term = c_status.get("lastState", {}).get("terminated", {})
        state_wait = c_status.get("state", {}).get("waiting", {})
        
        if (state_term.get("reason") == "OOMKilled" or state_term.get("exitCode") == 137 or
            last_term.get("reason") == "OOMKilled" or last_term.get("exitCode") == 137 or
            state_wait.get("reason") == "OOMKilled"):
            return True
            
    message = status.get("message", "")
    if message and "OOMKilled" in message:
        return True

    return False

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 collector.py <duration_seconds>")
        sys.exit(1)
        
    duration = int(sys.argv[1])
    start_time = time.time()
    
    # Store all pods we've seen keyed by their UID
    seen_pods = {}
    
    while time.time() - start_time < duration + 30: # run a bit longer to catch the tail
        try:
            result = subprocess.run(["kubectl", "get", "pods", "-l", "app=swebench", "-o", "json"], capture_output=True, text=True)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                running = 0
                pending = 0
                ooms = 0
                for pod in data.get("items", []):
                    pod_uid = pod["metadata"]["uid"]
                    seen_pods[pod_uid] = pod
                    phase = pod.get("status", {}).get("phase")
                    if phase == "Running":
                        running += 1
                    elif phase == "Pending":
                        pending += 1
                    
                    if is_pod_oom(pod):
                        ooms += 1

                with open("concurrency.txt", "a") as f_conc:
                    f_conc.write(f"{time.time()} {pending} {running} {ooms}\n")
        except Exception as e:
            pass
            
        # Write merged state to pods.json
        with open("pods.json", "w") as f:
            json.dump({
                "apiVersion": "v1",
                "kind": "List",
                "items": list(seen_pods.values())
            }, f)
            
        time.sleep(30)
        
if __name__ == "__main__":
    main()

import subprocess
import time
import sys

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 pod_watcher.py <duration_seconds>")
        sys.exit(1)
        
    duration = int(sys.argv[1])
    end_time = time.time() + duration
    
    print("Pod Watcher started.")
    with open('pod_metrics.txt', 'w') as f:
        while time.time() < end_time:
            timestamp = int(time.time())
            
            top_proc = subprocess.run(['kubectl', 'top', 'pods', '-l', 'app=swebench', '--no-headers'], capture_output=True, text=True)
            if top_proc.returncode == 0:
                for line in top_proc.stdout.strip().split('\n'):
                    parts = line.split()
                    if len(parts) >= 3:
                        pod_name = parts[0]
                        cpu = parts[1]
                        ram = parts[2]
                        f.write(f"{timestamp} {pod_name} {cpu} {ram}\n")
                f.flush()
            
            time.sleep(10)

if __name__ == "__main__":
    main()

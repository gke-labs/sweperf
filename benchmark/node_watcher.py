# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import subprocess
import time
import sys

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 node_watcher.py <duration_seconds>")
        sys.exit(1)
        
    duration = int(sys.argv[1])
    end_time = time.time() + duration
    
    print("Locked Node Watcher started.")
    with open('node_metrics.txt', 'w') as f:
        while time.time() < end_time:
            timestamp = int(time.time())
            
            # 1. Fetch live node memory / CPU telemetry
            top_proc = subprocess.run(['kubectl', 'top', 'nodes', '--no-headers'], capture_output=True, text=True)
            if top_proc.returncode != 0:
                time.sleep(10)
                continue
                
            node_stats = {}
            for line in top_proc.stdout.strip().split('\n'):
                parts = line.split()
                if len(parts) >= 4:
                    node_name = parts[0]
                    # Format natively returned by top: NAME CPU(cores) CPU% MEMORY(bytes) MEMORY%
                    cpu = parts[1]
                    ram = parts[3]
                    node_stats[node_name] = {'cpu': cpu, 'ram': ram, 'pods': 0}
            
            # 2. Fetch exactly how many pods are ACTIVELY 'Running' pinned specifically to these individual nodes
            pods_proc = subprocess.run(
                ['kubectl', 'get', 'pods', '-l', 'app=swebench', '--field-selector=status.phase=Running', 
                 '-o', 'custom-columns=NODE:.spec.nodeName', '--no-headers'], 
                capture_output=True, text=True
            )
            
            if pods_proc.returncode == 0:
                lines = pods_proc.stdout.strip().split('\n')
                for node_name in lines:
                    node_name = node_name.strip()
                    if node_name in node_stats:
                        node_stats[node_name]['pods'] += 1
            
            # 3. Write structurally aligned telemetry: TIMESTAMP NODE CPU RAM PODS
            for node_name, stats in node_stats.items():
                f.write(f"{timestamp} {node_name} {stats['cpu']} {stats['ram']} {stats['pods']}\n")
            f.flush()
            
            time.sleep(10)

if __name__ == "__main__":
    main()

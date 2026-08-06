import subprocess
import time
import sys
import json

def fetch_node_conditions():
    proc = subprocess.run(['kubectl', 'get', 'nodes', '-o', 'json'], capture_output=True, text=True)
    if proc.returncode != 0:
        return {}
    try:
        data = json.loads(proc.stdout)
    except Exception:
        return {}
    
    conditions_map = {}
    for item in data.get('items', []):
        node_name = item.get('metadata', {}).get('name')
        if not node_name:
            continue
        ready = "Unknown"
        mem_pressure = "False"
        disk_pressure = "False"
        pid_pressure = "False"
        
        conds = item.get('status', {}).get('conditions', [])
        for c in conds:
            c_type = c.get('type')
            c_status = c.get('status')
            if c_type == 'Ready':
                ready = c_status
            elif c_type == 'MemoryPressure':
                mem_pressure = c_status
            elif c_type == 'DiskPressure':
                disk_pressure = c_status
            elif c_type == 'PIDPressure':
                pid_pressure = c_status
                
        conditions_map[node_name] = {
            'ready': ready,
            'memory_pressure': mem_pressure,
            'disk_pressure': disk_pressure,
            'pid_pressure': pid_pressure
        }
    return conditions_map

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 node_watcher.py <duration_seconds>")
        sys.exit(1)
        
    duration = int(sys.argv[1])
    end_time = time.time() + duration
    
    print("Locked Node Watcher started.")
    with open('node_metrics.txt', 'w') as f_metrics, open('node_health.txt', 'w') as f_health:
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
                f_metrics.write(f"{timestamp} {node_name} {stats['cpu']} {stats['ram']} {stats['pods']}\n")
            f_metrics.flush()

            # 4. Fetch and log node health & pressure conditions
            node_conds = fetch_node_conditions()
            for node_name, cond in node_conds.items():
                f_health.write(f"{timestamp} {node_name} {cond['ready']} {cond['memory_pressure']} {cond['disk_pressure']} {cond['pid_pressure']}\n")
            f_health.flush()
            
            time.sleep(10)

if __name__ == "__main__":
    main()


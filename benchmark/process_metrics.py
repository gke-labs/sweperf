import collections
import math
import sys

def parse_metrics(lines):
    data = collections.defaultdict(lambda: {'cpu': [], 'ram': []})
    for line in lines:
        parts = line.strip().split()
        if len(parts) >= 5:
            node = parts[0]
            cpu_str = parts[1]
            if cpu_str.endswith('m'):
                cpu = int(cpu_str[:-1])
            else:
                try:
                    cpu = int(cpu_str) * 1000
                except:
                    continue

            ram_str = parts[3]
            if ram_str.endswith('Mi'):
                ram = int(ram_str[:-2])
            elif ram_str.endswith('Gi'):
                ram = int(ram_str[:-2]) * 1024
            else:
                try:
                    ram = int(ram_str) / (1024*1024)
                except:
                    continue

            data[node]['cpu'].append(cpu)
            data[node]['ram'].append(ram)
    return data

def percentile(N, percent, key=lambda x:x):
    if not N:
        return None
    k = (len(N)-1) * percent
    f = int(k)
    c = math.ceil(k)
    if f == c:
        return key(N[int(k)])
    d0 = key(N[int(f)]) * (c-k)
    d1 = key(N[int(c)]) * (k-f)
    return d0+d1

def process_metrics(data):
    report = []
    report.append("### Node Resource Usage Report")
    report.append("")
    for node, metrics in data.items():
        cpus = sorted(metrics['cpu'])
        rams = sorted(metrics['ram'])
        if not cpus:
            continue
        
        cpu_avg = sum(cpus) / len(cpus)
        cpu_max = cpus[-1]
        cpu_p90 = percentile(cpus, 0.90)
        
        ram_avg = sum(rams) / len(rams)
        ram_max = rams[-1]
        ram_p90 = percentile(rams, 0.90)
        
        report.append(f"**Node:** `{node}`")
        report.append(f"- **CPU (millicores):** Avg: {cpu_avg:.1f}, Max: {cpu_max}, P90: {cpu_p90:.1f}")
        report.append(f"- **RAM (MiB):**        Avg: {ram_avg:.1f}, Max: {ram_max}, P90: {ram_p90:.1f}")
        report.append("")
    return "\n".join(report)

if __name__ == "__main__":
    try:
        with open('node_metrics.txt', 'r') as f:
            lines = f.readlines()
            data = parse_metrics(lines)
            print(process_metrics(data))
    except FileNotFoundError:
        print("node_metrics.txt not found.")
        sys.exit(1)

import collections
import math
import sys
import json
from datetime import datetime

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

def parse_job_metrics(file_path):
    metrics = {
        'lengths': [],
        'pending_times': [],
        'earliest_start': None,
        'latest_end': None,
        'succeeded': 0,
        'failed': 0,
        'oom_killed': 0,
        'other_errors': 0,
    }
    try:
        with open(file_path, 'r') as f:
            pods_data = json.load(f)
            for item in pods_data.get('items', []):
                # parse creationTimestamp
                metadata = item.get('metadata', {})
                creation_time_str = metadata.get('creationTimestamp')
                creation_time = None
                if creation_time_str:
                    try:
                        creation_time = datetime.strptime(creation_time_str, "%Y-%m-%dT%H:%M:%SZ")
                    except ValueError:
                        pass

                status = item.get('status', {})
                start_time_str = status.get('startTime')
                if not start_time_str:
                    continue
                try:
                    start_time = datetime.strptime(start_time_str, "%Y-%m-%dT%H:%M:%SZ")
                except ValueError:
                    continue
                    
                if creation_time and start_time >= creation_time:
                    pending = (start_time - creation_time).total_seconds()
                    metrics['pending_times'].append(pending)
                
                finished_at = None
                exit_code = None
                reason = None
                for c_status in status.get('containerStatuses', []):
                    term = c_status.get('state', {}).get('terminated', {})
                    if term.get('finishedAt'):
                        finished_at_str = term['finishedAt']
                        try:
                            finished_at = datetime.strptime(finished_at_str, "%Y-%m-%dT%H:%M:%SZ")
                        except (ValueError, TypeError):
                            pass
                        exit_code = term.get('exitCode')
                        reason = term.get('reason')
                        break
                
                if not metrics['earliest_start'] or start_time < metrics['earliest_start']:
                    metrics['earliest_start'] = start_time

                if finished_at:
                    job_len = (finished_at - start_time).total_seconds()
                    if job_len >= 0:
                        metrics['lengths'].append(job_len)
                    if not metrics['latest_end'] or finished_at > metrics['latest_end']:
                        metrics['latest_end'] = finished_at
                        
                    if exit_code == 0:
                        metrics['succeeded'] += 1
                    else:
                        metrics['failed'] += 1
                        if reason == 'OOMKilled':
                            metrics['oom_killed'] += 1
                        else:
                            metrics['other_errors'] += 1
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    
    return metrics

def process_job_metrics(metrics):
    lengths = metrics['lengths']
    earliest_start = metrics['earliest_start']
    latest_end = metrics['latest_end']
    
    report = []
    report.append("### Job Performance & Health Report")
    report.append("")
    
    if not lengths and not metrics['pending_times']:
        report.append("No job data found.")
        report.append("")
        return "\n".join(report)

    if lengths:
        lengths_sorted = sorted(lengths)
        avg_len = sum(lengths_sorted) / len(lengths_sorted)
        max_len = lengths_sorted[-1]
        p90_len = percentile(lengths_sorted, 0.90)

        report.append(f"- **Completed Jobs:** {len(lengths)} (Succeeded: {metrics['succeeded']}, Failed: {metrics['failed']})")
        if metrics['failed'] > 0:
            report.append(f"  - **Failures:** OOMKilled: {metrics['oom_killed']}, Other Errors: {metrics['other_errors']}")
            
        report.append(f"- **Job Length (s):** Avg: {avg_len:.1f}, Max: {max_len:.1f}, P90: {p90_len:.1f}")

        if earliest_start and latest_end and latest_end > earliest_start:
            total_duration = (latest_end - earliest_start).total_seconds()
            throughput_min = (len(lengths) / total_duration) * 60
            report.append(f"- **Throughput:**     {throughput_min:.2f} jobs/minute")
            
    if metrics['pending_times']:
        pending_sorted = sorted(metrics['pending_times'])
        avg_pend = sum(pending_sorted) / len(pending_sorted)
        max_pend = pending_sorted[-1]
        p90_pend = percentile(pending_sorted, 0.90)
        report.append(f"- **Time-to-Start (s):** Avg: {avg_pend:.1f}, Max: {max_pend:.1f}, P90: {p90_pend:.1f}")
    
    report.append("")
    return "\n".join(report)

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
    report_parts = []
    try:
        with open('node_metrics.txt', 'r') as f:
            lines = f.readlines()
            data = parse_metrics(lines)
            report_parts.append(process_metrics(data))
    except FileNotFoundError:
        print("node_metrics.txt not found.")
        sys.exit(1)
        
    metrics = parse_job_metrics('pods.json')
    if metrics['lengths'] or metrics['pending_times']:
        report_parts.append(process_job_metrics(metrics))
        
    print("\n".join(report_parts))

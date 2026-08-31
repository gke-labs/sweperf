import collections
import math
import sys
import json
import os
from datetime import datetime, timezone

def parse_metrics(lines):
    data = collections.defaultdict(lambda: {'cpu': [], 'ram': [], 'per_job_cpu': [], 'per_job_ram': []})
    for line in lines:
        parts = line.strip().split()
        # New Strict Aligned Format: TIMESTAMP NODE CPU RAM PODS
        if len(parts) == 5:
            timestamp = parts[0]
            node = parts[1]
            cpu_str = parts[2]
            ram_str = parts[3]
            try:
                pods = int(parts[4])
            except ValueError:
                continue

            if cpu_str.endswith('m'):
                cpu = int(cpu_str[:-1])
            else:
                try:
                    cpu = int(cpu_str) * 1000
                except:
                    continue

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
            
            # Instantly calculate purely aligned slices!
            if pods > 0:
                data[node]['per_job_cpu'].append(cpu / pods)
                data[node]['per_job_ram'].append(ram / pods)
                if 'history' not in data[node]:
                    data[node]['history'] = []
                try:
                    ts_val = int(timestamp)
                except ValueError:
                    try:
                        ts_val = int(datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())
                    except Exception:
                        ts_val = 0
                data[node]['history'].append((ts_val, cpu / pods, ram / pods))
                
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

def parse_job_metrics(file_path, node_data=None):
    metrics = {
        'lengths': [],
        'pending_times': [],
        'earliest_start': None,
        'latest_end': None,
        'succeeded': 0,
        'failed': 0,
        'oom_killed': 0,
        'other_errors': 0,
        'by_job_group': collections.defaultdict(lambda: {'succeeded': 0, 'failed': 0, 'lengths': [], 'cpu': [], 'ram': []}),
        'by_job_type': collections.defaultdict(lambda: {'succeeded': 0, 'failed': 0, 'lengths': [], 'cpu': [], 'ram': []})
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

                node_name = item.get('spec', {}).get('nodeName')
                job_type = "unknown"
                containers = item.get('spec', {}).get('containers', [])
                if containers:
                    c = containers[0]
                    for env in c.get('env', []):
                        if env.get('name') == 'INSTANCE_ID':
                            job_type = env.get('value')
                            break
                    if job_type == "unknown":
                        image = c.get('image', '')
                        if ':' in image:
                            job_type = image.split(':')[-1]
                # Fallback purely to repo prefix if it's long
                job_group = job_type.split("__")[0] if "__" in job_type else job_type

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
                        metrics['by_job_group'][job_group]['lengths'].append(job_len)
                        metrics['by_job_type'][job_type]['lengths'].append(job_len)
                        
                        if node_data and node_name and node_name in node_data and 'history' in node_data[node_name]:
                            st_ts = start_time.replace(tzinfo=timezone.utc).timestamp()
                            end_ts = finished_at.replace(tzinfo=timezone.utc).timestamp()
                            for ts, c_cpu, c_ram in node_data[node_name]['history']:
                                if st_ts <= ts <= end_ts:
                                    metrics['by_job_group'][job_group]['cpu'].append(c_cpu)
                                    metrics['by_job_group'][job_group]['ram'].append(c_ram)
                                    metrics['by_job_type'][job_type]['cpu'].append(c_cpu)
                                    metrics['by_job_type'][job_type]['ram'].append(c_ram)
                    if not metrics['latest_end'] or finished_at > metrics['latest_end']:
                        metrics['latest_end'] = finished_at
                        
                    if exit_code == 0:
                        metrics['succeeded'] += 1
                        metrics['by_job_group'][job_group]['succeeded'] += 1
                        metrics['by_job_type'][job_type]['succeeded'] += 1
                    else:
                        metrics['failed'] += 1
                        metrics['by_job_group'][job_group]['failed'] += 1
                        metrics['by_job_type'][job_type]['failed'] += 1
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
            
        by_group = metrics.get('by_job_group', {})
        if by_group:
            report.append("")
            report.append("#### Job Statistics by Repository Group")
            report.append("")
            report.append("| Repository Group | Total | Succeeded | Failed | Avg Time (s) | Max Time (s) | Avg CPU (m) | Avg RAM (MiB) |")
            report.append("|---|---|---|---|---|---|---|---|")
            for t_name, t_metrics in sorted(by_group.items()):
                t_total = len(t_metrics['lengths']) + (t_metrics['succeeded'] + t_metrics['failed'] - len(t_metrics['lengths']))
                t_total = max(t_total, t_metrics['succeeded'] + t_metrics['failed'])
                if t_total == 0:
                    continue
                t_avg = sum(t_metrics['lengths']) / max(1, len(t_metrics['lengths']))
                t_max = max(t_metrics['lengths']) if t_metrics['lengths'] else 0
                c_cpu = sum(t_metrics['cpu']) / max(1, len(t_metrics['cpu'])) if t_metrics['cpu'] else 0
                c_ram = sum(t_metrics['ram']) / max(1, len(t_metrics['ram'])) if t_metrics['ram'] else 0
                report.append(f"| `{t_name}` | {t_total} | {t_metrics['succeeded']} | {t_metrics['failed']} | {t_avg:.1f} | {t_max:.1f} | {c_cpu:.1f} | {c_ram:.1f} |")
            report.append("")
            
        by_type = metrics.get('by_job_type', {})
        if by_type:
            report.append("")
            report.append("#### Job Statistics by Specific Test Case")
            report.append("")
            report.append("| Test Case (Instance ID) | Total | Succeeded | Failed | Avg Time (s) | Max Time (s) | Avg CPU (m) | Avg RAM (MiB) |")
            report.append("|---|---|---|---|---|---|---|---|")
            for t_name, t_metrics in sorted(by_type.items()):
                t_total = len(t_metrics['lengths']) + (t_metrics['succeeded'] + t_metrics['failed'] - len(t_metrics['lengths']))
                t_total = max(t_total, t_metrics['succeeded'] + t_metrics['failed'])
                if t_total == 0:
                    continue
                t_avg = sum(t_metrics['lengths']) / max(1, len(t_metrics['lengths']))
                t_max = max(t_metrics['lengths']) if t_metrics['lengths'] else 0
                c_cpu = sum(t_metrics['cpu']) / max(1, len(t_metrics['cpu'])) if t_metrics['cpu'] else 0
                c_ram = sum(t_metrics['ram']) / max(1, len(t_metrics['ram'])) if t_metrics['ram'] else 0
                report.append(f"| `{t_name}` | {t_total} | {t_metrics['succeeded']} | {t_metrics['failed']} | {t_avg:.1f} | {t_max:.1f} | {c_cpu:.1f} | {c_ram:.1f} |")
            report.append("")
            
    if metrics['pending_times']:
        pending_sorted = sorted(metrics['pending_times'])
        avg_pend = sum(pending_sorted) / len(pending_sorted)
        max_pend = pending_sorted[-1]
        p90_pend = percentile(pending_sorted, 0.90)
        report.append(f"- **Time-to-Start (s):** Avg: {avg_pend:.1f}, Max: {max_pend:.1f}, P90: {p90_pend:.1f}")
        
    if os.path.exists('concurrency.txt'):
        running_pts = []
        pending_pts = []
        with open('concurrency.txt', 'r') as cf:
            for c_line in cf:
                parts = c_line.strip().split()
                if len(parts) >= 3:
                    pending_pts.append(int(parts[1]))
                    running_pts.append(int(parts[2]))
        
        if running_pts:
            r_avg = sum(running_pts) / len(running_pts)
            p_avg = sum(pending_pts) / len(pending_pts)
            report.append("")
            report.append(f"- **Outstanding Queue (Pending):** Avg: {p_avg:.1f}, Peak: {max(pending_pts)}")
            report.append(f"- **Active In-Flight (Running):** Avg: {r_avg:.1f}, Peak: {max(running_pts)}")
    
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
    node_data = None
    try:
        with open('node_metrics.txt', 'r') as f:
            lines = f.readlines()
            node_data = parse_metrics(lines)
            report_parts.append(process_metrics(node_data))
    except FileNotFoundError:
        print("node_metrics.txt not found.")
        sys.exit(1)
        
    metrics = parse_job_metrics('pods.json', node_data=node_data)
    if metrics['lengths'] or metrics['pending_times']:
        report_parts.append(process_job_metrics(metrics))

    # Add Per-Job Math using Aligned Telemetry
    if node_data:
        avg_cpu_per_job = 0
        avg_ram_per_job = 0
        total_slices = 0
        
        for node, n_metrics in node_data.items():
            if n_metrics.get('per_job_cpu'):
                avg_cpu_per_job += sum(n_metrics['per_job_cpu'])
                avg_ram_per_job += sum(n_metrics['per_job_ram'])
                total_slices += len(n_metrics['per_job_cpu'])
                
        if total_slices > 0:
            avg_cpu_per_job /= total_slices
            avg_ram_per_job /= total_slices
            
            heuristics_report = [
                "### Per-Job Footprint (Cost Heuristics)",
                "",
                f"- **Avg CPU per job:** {avg_cpu_per_job:.1f} millicores (Calculated via Aligned Point-in-Time Slice Arrays)",
                f"- **Avg RAM per job:** {avg_ram_per_job:.1f} MiB (Includes native node OS caching)",
                ""
            ]
            report_parts.append("\n".join(heuristics_report))
        
    print("\n".join(report_parts))

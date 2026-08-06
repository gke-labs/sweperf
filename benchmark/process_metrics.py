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
        'by_job_group': collections.defaultdict(lambda: {'succeeded': 0, 'failed': 0, 'oom_killed': 0, 'lengths': [], 'cpu': [], 'ram': []}),
        'by_job_type': collections.defaultdict(lambda: {'succeeded': 0, 'failed': 0, 'oom_killed': 0, 'lengths': [], 'cpu': [], 'ram': []})
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
                start_time = None
                if start_time_str:
                    try:
                        start_time = datetime.strptime(start_time_str, "%Y-%m-%dT%H:%M:%SZ")
                    except ValueError:
                        pass
                    
                if creation_time and start_time and start_time >= creation_time:
                    pending = (start_time - creation_time).total_seconds()
                    metrics['pending_times'].append(pending)
                
                finished_at = None
                exit_code = None
                reason = None
                is_oom = False

                container_statuses = (
                    status.get('containerStatuses', []) +
                    status.get('initContainerStatuses', []) +
                    status.get('ephemeralContainerStatuses', [])
                )
                for c_status in container_statuses:
                    state_term = c_status.get('state', {}).get('terminated', {})
                    last_term = c_status.get('lastState', {}).get('terminated', {})
                    state_wait = c_status.get('state', {}).get('waiting', {})

                    term = state_term if state_term else last_term
                    if term:
                        if term.get('finishedAt') and not finished_at:
                            finished_at_str = term['finishedAt']
                            try:
                                finished_at = datetime.strptime(finished_at_str, "%Y-%m-%dT%H:%M:%SZ")
                            except (ValueError, TypeError):
                                pass
                        if term.get('exitCode') is not None and exit_code is None:
                            exit_code = term.get('exitCode')
                        if term.get('reason') and not reason:
                            reason = term.get('reason')

                    if (state_term.get('reason') == 'OOMKilled' or state_term.get('exitCode') == 137 or
                        last_term.get('reason') == 'OOMKilled' or last_term.get('exitCode') == 137 or
                        state_wait.get('reason') == 'OOMKilled'):
                        is_oom = True

                if status.get('reason') == 'OOMKilled' or reason == 'OOMKilled' or exit_code == 137:
                    is_oom = True
                
                if start_time and (not metrics['earliest_start'] or start_time < metrics['earliest_start']):
                    metrics['earliest_start'] = start_time

                if finished_at and start_time:
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
                        
                if is_oom:
                    metrics['failed'] += 1
                    metrics['oom_killed'] += 1
                    metrics['by_job_group'][job_group]['failed'] += 1
                    metrics['by_job_group'][job_group]['oom_killed'] += 1
                    metrics['by_job_type'][job_type]['failed'] += 1
                    metrics['by_job_type'][job_type]['oom_killed'] += 1
                elif exit_code == 0:
                    metrics['succeeded'] += 1
                    metrics['by_job_group'][job_group]['succeeded'] += 1
                    metrics['by_job_type'][job_type]['succeeded'] += 1
                elif exit_code is not None or status.get('phase') == 'Failed':
                    metrics['failed'] += 1
                    metrics['other_errors'] += 1
                    metrics['by_job_group'][job_group]['failed'] += 1
                    metrics['by_job_type'][job_type]['failed'] += 1
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
    
    total_completed = metrics['succeeded'] + metrics['failed']
    if total_completed == 0 and not lengths and not metrics['pending_times']:
        report.append("No job data found.")
        report.append("")
        return "\n".join(report)

    if lengths or total_completed > 0:
        count_completed = max(len(lengths), total_completed)
        report.append(f"- **Completed Jobs:** {count_completed} (Succeeded: {metrics['succeeded']}, Failed: {metrics['failed']})")
        if metrics['failed'] > 0:
            report.append(f"  - **Failures:** OOMKilled: {metrics['oom_killed']}, Other Errors: {metrics['other_errors']}")
        else:
            report.append(f"  - **OOMKilled Pods:** {metrics['oom_killed']}")

        if lengths:
            lengths_sorted = sorted(lengths)
            avg_len = sum(lengths_sorted) / len(lengths_sorted)
            max_len = lengths_sorted[-1]
            p90_len = percentile(lengths_sorted, 0.90)
            report.append(f"- **Job Length (s):** Avg: {avg_len:.1f}, Max: {max_len:.1f}, P90: {p90_len:.1f}")

        if earliest_start and latest_end and latest_end > earliest_start and lengths:
            total_duration = (latest_end - earliest_start).total_seconds()
            throughput_min = (len(lengths) / total_duration) * 60
            report.append(f"- **Throughput:**     {throughput_min:.2f} jobs/minute")
            
        by_group = metrics.get('by_job_group', {})
        if by_group:
            report.append("")
            report.append("#### Job Statistics by Repository Group")
            report.append("")
            report.append("| Repository Group | Total | Succeeded | Failed | OOMKilled | Avg Time (s) | Max Time (s) | Avg CPU (m) | Peak CPU (m) | P90 CPU (m) | Avg RAM (MiB) | Peak RAM (MiB) | P90 RAM (MiB) |")
            report.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
            for t_name, t_metrics in sorted(by_group.items()):
                t_total = len(t_metrics['lengths']) + (t_metrics['succeeded'] + t_metrics['failed'] - len(t_metrics['lengths']))
                t_total = max(t_total, t_metrics['succeeded'] + t_metrics['failed'])
                if t_total == 0:
                    continue
                t_avg = sum(t_metrics['lengths']) / max(1, len(t_metrics['lengths']))
                t_max = max(t_metrics['lengths']) if t_metrics['lengths'] else 0
                
                cpus_s = sorted(t_metrics['cpu']) if t_metrics['cpu'] else []
                c_cpu_avg = sum(cpus_s) / max(1, len(cpus_s)) if cpus_s else 0
                c_cpu_max = cpus_s[-1] if cpus_s else 0
                c_cpu_p90 = percentile(cpus_s, 0.90) if cpus_s else 0
                
                rams_s = sorted(t_metrics['ram']) if t_metrics['ram'] else []
                c_ram_avg = sum(rams_s) / max(1, len(rams_s)) if rams_s else 0
                c_ram_max = rams_s[-1] if rams_s else 0
                c_ram_p90 = percentile(rams_s, 0.90) if rams_s else 0
                
                oom_cnt = t_metrics.get('oom_killed', 0)
                report.append(f"| `{t_name}` | {t_total} | {t_metrics['succeeded']} | {t_metrics['failed']} | {oom_cnt} | {t_avg:.1f} | {t_max:.1f} | {c_cpu_avg:.1f} | {c_cpu_max:.1f} | {c_cpu_p90:.1f} | {c_ram_avg:.1f} | {c_ram_max:.1f} | {c_ram_p90:.1f} |")
            report.append("")
            
        by_type = metrics.get('by_job_type', {})
        if by_type:
            report.append("")
            report.append("#### Job Statistics by Specific Test Case")
            report.append("")
            report.append("| Test Case (Instance ID) | Total | Succeeded | Failed | OOMKilled | Avg Time (s) | Max Time (s) | Avg CPU (m) | Peak CPU (m) | P90 CPU (m) | Avg RAM (MiB) | Peak RAM (MiB) | P90 RAM (MiB) |")
            report.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
            for t_name, t_metrics in sorted(by_type.items()):
                t_total = len(t_metrics['lengths']) + (t_metrics['succeeded'] + t_metrics['failed'] - len(t_metrics['lengths']))
                t_total = max(t_total, t_metrics['succeeded'] + t_metrics['failed'])
                if t_total == 0:
                    continue
                t_avg = sum(t_metrics['lengths']) / max(1, len(t_metrics['lengths']))
                t_max = max(t_metrics['lengths']) if t_metrics['lengths'] else 0
                
                cpus_s = sorted(t_metrics['cpu']) if t_metrics['cpu'] else []
                c_cpu_avg = sum(cpus_s) / max(1, len(cpus_s)) if cpus_s else 0
                c_cpu_max = cpus_s[-1] if cpus_s else 0
                c_cpu_p90 = percentile(cpus_s, 0.90) if cpus_s else 0
                
                rams_s = sorted(t_metrics['ram']) if t_metrics['ram'] else []
                c_ram_avg = sum(rams_s) / max(1, len(rams_s)) if rams_s else 0
                c_ram_max = rams_s[-1] if rams_s else 0
                c_ram_p90 = percentile(rams_s, 0.90) if rams_s else 0
                
                oom_cnt = t_metrics.get('oom_killed', 0)
                report.append(f"| `{t_name}` | {t_total} | {t_metrics['succeeded']} | {t_metrics['failed']} | {oom_cnt} | {t_avg:.1f} | {t_max:.1f} | {c_cpu_avg:.1f} | {c_cpu_max:.1f} | {c_cpu_p90:.1f} | {c_ram_avg:.1f} | {c_ram_max:.1f} | {c_ram_p90:.1f} |")
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
        oom_pts = []
        with open('concurrency.txt', 'r') as cf:
            for c_line in cf:
                parts = c_line.strip().split()
                if len(parts) >= 3:
                    try:
                        pending_pts.append(int(parts[1]))
                        running_pts.append(int(parts[2]))
                    except ValueError:
                        pass
                if len(parts) >= 4:
                    try:
                        oom_pts.append(int(parts[3]))
                    except ValueError:
                        pass
        
        if running_pts:
            r_avg = sum(running_pts) / len(running_pts)
            p_avg = sum(pending_pts) / len(pending_pts)
            report.append("")
            report.append(f"- **Outstanding Queue (Pending):** Avg: {p_avg:.1f}, Peak: {max(pending_pts)}")
            report.append(f"- **Active In-Flight (Running):** Avg: {r_avg:.1f}, Peak: {max(running_pts)}")
            if oom_pts:
                report.append(f"- **Active OOM Pods:** Peak: {max(oom_pts)}")
    
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

def process_node_health(file_path):
    if not os.path.exists(file_path):
        return ""
    
    node_records = collections.defaultdict(list)
    try:
        with open(file_path, 'r') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 6:
                    try:
                        ts = int(parts[0])
                        node = parts[1]
                        ready = parts[2]
                        mem = parts[3]
                        disk = parts[4]
                        pid = parts[5]
                        node_records[node].append((ts, ready, mem, disk, pid))
                    except ValueError:
                        pass
    except Exception:
        return ""
    
    if not node_records:
        return ""

    node_stats = {}
    nodes_under_pressure_count = 0

    for node, records in sorted(node_records.items()):
        records.sort(key=lambda x: x[0])
        total_unhealthy_time = 0
        mem_pressure_time = 0
        disk_pressure_time = 0
        pid_pressure_time = 0
        not_ready_time = 0
        
        for i in range(len(records)):
            ts, ready, mem, disk, pid = records[i]
            if i < len(records) - 1:
                duration = records[i+1][0] - ts
            else:
                duration = 10
            
            duration = max(1, min(duration, 60))

            is_mem = (mem.lower() == 'true')
            is_disk = (disk.lower() == 'true')
            is_pid = (pid.lower() == 'true')
            is_not_ready = (ready.lower() != 'true')

            if is_mem:
                mem_pressure_time += duration
            if is_disk:
                disk_pressure_time += duration
            if is_pid:
                pid_pressure_time += duration
            if is_not_ready:
                not_ready_time += duration

            if is_mem or is_disk or is_pid or is_not_ready:
                total_unhealthy_time += duration

        if total_unhealthy_time > 0:
            nodes_under_pressure_count += 1

        node_stats[node] = {
            'total_unhealthy': total_unhealthy_time,
            'mem_pressure': mem_pressure_time,
            'disk_pressure': disk_pressure_time,
            'pid_pressure': pid_pressure_time,
            'not_ready': not_ready_time
        }

    report = []
    report.append("### Node Health & Resource Pressure Report")
    report.append("")
    report.append(f"- **Total Nodes Monitored:** {len(node_stats)}")
    report.append(f"- **Nodes Experiencing Resource Pressure / Unhealthiness:** {nodes_under_pressure_count}")
    report.append("")

    if nodes_under_pressure_count > 0:
        report.append("| Node | Ready (NotReady/Unavailable) | Memory Pressure | Disk Pressure | PID Pressure | Total Duration Under Pressure / Unhealthy |")
        report.append("|---|---|---|---|---|---|")
        for node, stats in sorted(node_stats.items()):
            if stats['total_unhealthy'] > 0:
                nr_str = f"{stats['not_ready']}s"
                mem_str = f"{stats['mem_pressure']}s"
                disk_str = f"{stats['disk_pressure']}s"
                pid_str = f"{stats['pid_pressure']}s"
                tot_s = stats['total_unhealthy']
                tot_str = f"{tot_s}s ({tot_s // 60}m {tot_s % 60}s)"
                report.append(f"| `{node}` | {nr_str} | {mem_str} | {disk_str} | {pid_str} | {tot_str} |")
    else:
        report.append("All nodes remained Healthy & Ready with no resource pressure throughout the run.")
    
    report.append("")
    return "\n".join(report)

if __name__ == "__main__":
    report_parts = []
    node_data = None
    timestamps = []
    try:
        with open('node_metrics.txt', 'r') as f:
            lines = f.readlines()
            for line in lines:
                parts = line.strip().split()
                if parts:
                    try:
                        ts = int(parts[0])
                        timestamps.append(ts)
                    except ValueError:
                        try:
                            ts = int(datetime.strptime(parts[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())
                            timestamps.append(ts)
                        except Exception:
                            pass
            node_data = parse_metrics(lines)
            if timestamps:
                start_ts = min(timestamps)
                end_ts = max(timestamps)
                start_dt = datetime.fromtimestamp(start_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
                end_dt = datetime.fromtimestamp(end_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
                duration = end_ts - start_ts
                timing_report = [
                    "### Run Timing",
                    "",
                    f"- **Start Time:** {start_dt}",
                    f"- **End Time:**   {end_dt}",
                    f"- **Duration:**   {duration} seconds ({duration // 60}m {duration % 60}s)",
                    ""
                ]
                report_parts.append("\n".join(timing_report))
            report_parts.append(process_metrics(node_data))
            health_report = process_node_health('node_health.txt')
            if health_report:
                report_parts.append(health_report)
    except FileNotFoundError:
        print("node_metrics.txt not found.")
        sys.exit(1)
        
    metrics = parse_job_metrics('pods.json', node_data=node_data)
    if metrics['lengths'] or metrics['pending_times']:
        report_parts.append(process_job_metrics(metrics))

    # Add Per-Job Math using Aligned Telemetry
    if node_data:
        all_cpu_slices = []
        all_ram_slices = []
        
        for node, n_metrics in node_data.items():
            if n_metrics.get('per_job_cpu'):
                all_cpu_slices.extend(n_metrics['per_job_cpu'])
                all_ram_slices.extend(n_metrics['per_job_ram'])
                
        if all_cpu_slices and all_ram_slices:
            cpu_sorted = sorted(all_cpu_slices)
            ram_sorted = sorted(all_ram_slices)
            
            avg_cpu = sum(cpu_sorted) / len(cpu_sorted)
            p90_cpu = percentile(cpu_sorted, 0.90)
            peak_cpu = cpu_sorted[-1]
            
            avg_ram = sum(ram_sorted) / len(ram_sorted)
            p90_ram = percentile(ram_sorted, 0.90)
            peak_ram = ram_sorted[-1]
            
            heuristics_report = [
                "### Per-Job Footprint (Cost Heuristics)",
                "",
                f"- **CPU per job (millicores):** Avg: {avg_cpu:.1f}, Peak: {peak_cpu:.1f}, P90: {p90_cpu:.1f} (Calculated via Aligned Point-in-Time Slice Arrays)",
                f"- **RAM per job (MiB):**        Avg: {avg_ram:.1f}, Peak: {peak_ram:.1f}, P90: {p90_ram:.1f} (Includes native node OS caching)",
                ""
            ]
            report_parts.append("\n".join(heuristics_report))
        
    print("\n".join(report_parts))

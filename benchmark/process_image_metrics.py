import json
import collections

def percentile(N, percent):
    if not N: return 0
    import math
    k = (len(N)-1) * percent
    f = int(k)
    c = math.ceil(k)
    if f == c: return N[int(k)]
    d0 = N[int(f)] * (c-k)
    d1 = N[int(c)] * (k-f)
    return d0+d1

def parse():
    mets = collections.defaultdict(lambda: {'cpu': [], 'ram': []})
    try:
        with open('pod_metrics.txt') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 4:
                    pod = parts[1]
                    cpu_str = parts[2]
                    ram_str = parts[3]
                    
                    if cpu_str.endswith('m'): cpu = int(cpu_str[:-1])
                    else:
                        try: cpu = int(cpu_str) * 1000
                        except: continue
                        
                    if ram_str.endswith('Mi'): ram = int(ram_str[:-2])
                    elif ram_str.endswith('Gi'): ram = int(ram_str[:-2]) * 1024
                    elif ram_str.endswith('Ki'): ram = int(ram_str[:-2]) / 1024
                    else: 
                        try: ram = float(ram_str)/(1024*1024)
                        except: continue

                    mets[pod]['cpu'].append(cpu)
                    mets[pod]['ram'].append(ram)
    except Exception:
        pass
                
    image_data = collections.defaultdict(lambda: {'cpu': [], 'ram': [], 'lengths': [], 'completed': 0})
    try:
        with open('pods.json') as f:
            pods = json.load(f)
    except Exception:
        pods = {}
    
    for item in pods.get('items', []):
        name = item['metadata']['name']
        containers = item.get('spec', {}).get('containers', [])
        if not containers: continue
        image = containers[0].get('image', '')
        
        if ':' in image:
            tag = image.split(':')[-1]
            case_name = tag
        else:
            case_name = 'unknown'

        status = item.get('status', {})
        start = status.get('startTime')
        
        import datetime
        finished_at = None
        if start:
            try: start_t = datetime.datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ")
            except: start_t = None
            if start_t:
                for c_status in status.get('containerStatuses', []):
                    term = c_status.get('state', {}).get('terminated', {})
                    if term.get('finishedAt'):
                        try: finished_at = datetime.datetime.strptime(term['finishedAt'], "%Y-%m-%dT%H:%M:%SZ")
                        except: pass
                        break

                if finished_at:
                    job_len = (finished_at - start_t).total_seconds()
                    image_data[case_name]['lengths'].append(job_len)
                    image_data[case_name]['completed'] += 1
            
        if name in mets:
            image_data[case_name]['cpu'].extend(mets[name]['cpu'])
            image_data[case_name]['ram'].extend(mets[name]['ram'])
            
    # MD Output
    print("### SWE-Bench Image Benchmark Results (Per Case)")
    print("")
    print("| Image Base | Completed Jobs | Avg Len (s) | P90 Len (s) | Max Len (s) | Avg CPU (m) | Max CPU (m) | Avg RAM (MiB) | Max RAM (MiB) |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    
    # CSV Output
    with open('report.csv', 'w') as csvf:
        csvf.write("Image Base,Completed Jobs,Avg Len (s),P90 Len (s),Max Len (s),Avg CPU (m),Max CPU (m),Avg RAM (MiB),Max RAM (MiB)\n")

        for t, d in sorted(image_data.items(), key=lambda x: -(max(x[1]['ram']) if x[1]['ram'] else 0)):
            completed = d['completed']
            lens = sorted(d['lengths'])
            cpus = sorted(d['cpu'])
            rams = sorted(d['ram'])
            
            if completed == 0 and not rams:
                continue
                
            avg_len = sum(lens)/len(lens) if lens else 0
            p90_len = percentile(lens, 0.90) if lens else 0
            max_len = max(lens) if lens else 0
            
            avg_cpu = sum(cpus)/len(cpus) if cpus else 0
            max_cpu = max(cpus) if cpus else 0
            
            avg_ram = sum(rams)/len(rams) if rams else 0
            max_ram = max(rams) if rams else 0
            
            print(f"| `{t}` | {completed} | {avg_len:.1f} | {p90_len:.1f} | {max_len:.1f} | {avg_cpu:.1f} | {max_cpu:.0f} | {avg_ram:.1f} | {max_ram:.1f} |")
            csvf.write(f"{t},{completed},{avg_len:.1f},{p90_len:.1f},{max_len:.1f},{avg_cpu:.1f},{max_cpu:.0f},{avg_ram:.1f},{max_ram:.1f}\n")

if __name__ == "__main__":
    parse()

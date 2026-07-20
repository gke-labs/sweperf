import sys
import json
import time
import pexpect
import os
import random

def simulate_typing(command):
    sys.stdout.write("\033[92m$ ") # Green prompt
    for char in command:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(0.01)
    sys.stdout.write("\033[0m\n")
    sys.stdout.flush()

def main():
    if os.environ.get("WAIT_FOR_CLAIM_FILE"):
        claim_file = os.environ.get("WAIT_FOR_CLAIM_FILE")
        print(f"Waiting for claim signal in {claim_file}...")
        sys.stdout.flush()
        while True:
            if os.path.exists(claim_file):
                try:
                    with open(claim_file, 'r') as f:
                        if 'agents.x-k8s.io/sandbox-id' in f.read():
                            print("Claim signal received!")
                            sys.stdout.flush()
                            break
                except Exception:
                    pass
            time.sleep(1)

    if os.environ.get("WAIT_FOR_START_PORT"):
        import socket
        port = int(os.environ.get("WAIT_FOR_START_PORT"))
        print(f"Waiting for 'start' command on port {port}...")
        sys.stdout.flush()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('', port))
            s.listen()
            while True:
                try:
                    conn, addr = s.accept()
                    with conn:
                        data = conn.recv(1024)
                        text = data.decode('utf-8', errors='ignore').lower()
                        if 'start' in text:
                            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\nOK\n")
                            break
                        else:
                            conn.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                except Exception as e:
                    pass
        print("Start signal received via port!")
        sys.stdout.flush()

    if len(sys.argv) != 2:
        print("Usage: python3 replay.py <trace.json>")
        sys.exit(1)
        
    trace_file = sys.argv[1]
    if not os.path.exists(trace_file):
        print(f"Error: trace file {trace_file} not found.")
        sys.exit(1)
        
    if os.environ.get("DO_GIT_PULL") == "true":
        import subprocess
        print("Simulating agent load: Cloning repo...")
        sys.stdout.flush()
        try:
            # Extract git repo URL from SWEPERF_TRAJECTORY_SOURCE env var
            # Example: .../trajs/sympy__sympy-14248/sympy__sympy-14248.traj.json
            traj_source = os.environ.get("SWEPERF_TRAJECTORY_SOURCE", "")
            if traj_source:
                instance_id = traj_source.split('/')[-1].replace(".traj.json", "")
                owner, rest = instance_id.split("__")
                repo = rest.rsplit("-", 1)[0]
                repo_url = f"https://github.com/{owner}/{repo}.git"
            else:
                raise Exception("Missing SWEPERF_TRAJECTORY_SOURCE")
            
            commit_sha = subprocess.check_output(['git', '-C', '/testbed', 'rev-parse', 'HEAD'], text=True).strip()
            print(f"Cloning {repo_url} at {commit_sha} to /tmp/agent_workspace...")
            sys.stdout.flush()
            subprocess.run(['git', 'clone', repo_url, '/tmp/agent_workspace'], check=True)
            subprocess.run(['git', '-C', '/tmp/agent_workspace', 'fetch', 'origin', commit_sha], check=False)
            subprocess.run(['git', '-C', '/tmp/agent_workspace', 'checkout', commit_sha], check=False)
            print("Simulating agent load: Installing cloned tree into isolated venv...")
            sys.stdout.flush()
            subprocess.run(['python3', '-m', 'venv', '/tmp/dummy_venv'], check=False)
            subprocess.run(['/tmp/dummy_venv/bin/pip', 'install', '-e', '/tmp/agent_workspace'], check=False)
            print("Clone and install complete.")
            sys.stdout.flush()
        except Exception as e:
            print(f"Failed to clone repo for load simulation: {e}")
            sys.stdout.flush()
            
    with open(trace_file, 'r') as f:
        commands = json.load(f)
        
    print(f"Loaded {len(commands)} commands to replay.")
    
    env = os.environ.copy()
    env['PAGER'] = 'cat'
    env['GIT_PAGER'] = 'cat'
    child = pexpect.spawn('bash --norc --noprofile', encoding='utf-8', timeout=None, env=env)
    
    # Disable terminal echo so we don't see the command twice
    child.sendline('stty -echo')
    
    unique_prompt = 'REPLAY_DONE_PROMPT_12345>'
    child.sendline(f"PS1='{unique_prompt}'")
    child.expect(unique_prompt)
    
    # Clear anything left in the buffer
    _ = child.before
    
    success_count = 0
    failure_count = 0
    
    for cmd in commands:
        if isinstance(cmd, dict):
            command = cmd.get("command", "")
            sleep_time = cmd.get("sleep", None)
        else:
            command = cmd
            sleep_time = None
            
        if sleep_time is None:
            # Synthesize LLM latency timing based on log-normal distribution
            # Derived from analyzing Antigravity LLM interaction logs across 23 real-world complex coding tasks.
            # Median: 6.00s, P90: 12.00s, Avg: 15.65s, Max: 169s
            mu = float(os.environ.get("LLM_LATENCY_MU", "2.0414"))
            sigma = float(os.environ.get("LLM_LATENCY_SIGMA", "0.8674"))
            min_latency = float(os.environ.get("LLM_LATENCY_MIN", "0.5"))
            sleep_time = max(min_latency, random.lognormvariate(mu, sigma))
            

        if not command.strip():
            continue
            
        simulate_typing(command)
        
        for line in command.splitlines():
            child.sendline(line)
            time.sleep(0.01)

        child.expect(unique_prompt)
        
        # Since echo is off, child.before is strictly the command's output
        clean_output = child.before
            
        # Clean trailing newlines before the prompt
        if clean_output.endswith('\r\n'):
            clean_output = clean_output[:-2]
            
        if clean_output.strip():
            sys.stdout.write(clean_output + "\n")
        sys.stdout.flush()
        print("") # new line for breathing room

        # Check exit code
        child.sendline("echo $?")
        child.expect(unique_prompt)
        exit_output = child.before.strip()
        try:
            # The output should just be the number since echo is off
            # But just in case, we'll take the last word
            code = int(exit_output.split()[-1])
            if code == 0:
                success_count += 1
            else:
                failure_count += 1
        except Exception:
            failure_count += 1
            pass
            
        time.sleep(sleep_time)
        
    print(f"\n\033[96m--- Replay Complete ---\033[0m")
    stats_msg = f"[REPLAY_STATS] Successes: {success_count}, Failures: {failure_count}"
    print(stats_msg)
    
    try:
        with open('/dev/termination-log', 'w') as f:
            f.write(stats_msg)
    except Exception:
        pass

if __name__ == "__main__":
    main()

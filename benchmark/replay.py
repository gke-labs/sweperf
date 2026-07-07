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
    if len(sys.argv) != 2:
        print("Usage: python3 replay.py <trace.json>")
        sys.exit(1)
        
    trace_file = sys.argv[1]
    if not os.path.exists(trace_file):
        print(f"Error: trace file {trace_file} not found.")
        sys.exit(1)
        
    with open(trace_file, 'r') as f:
        commands = json.load(f)
        
    print(f"Loaded {len(commands)} commands to replay.")
    
    child = pexpect.spawn('bash --norc --noprofile', encoding='utf-8', timeout=None)
    
    # Disable terminal echo so we don't see the command twice
    child.sendline('stty -echo')
    
    unique_prompt = 'REPLAY_DONE_PROMPT_12345>'
    child.sendline(f"PS1='{unique_prompt}'")
    child.expect(unique_prompt)
    
    # Clear anything left in the buffer
    _ = child.before
    
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
        
        child.sendline(command)
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
        
        time.sleep(sleep_time)
        
    print("\n\033[96m--- Replay Complete ---\033[0m")

if __name__ == "__main__":
    main()

import sys
import json
import time
import pexpect
import random

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 replay.py <trace.json>")
        sys.exit(1)
        
    with open(sys.argv[1], 'r') as f:
        commands = json.load(f)
        
    print(f"Loaded {len(commands)} commands to replay.")
    
    # Start a bash session
    child = pexpect.spawn('bash --norc --noprofile', encoding='utf-8', timeout=None)
    
    # Set a unique prompt to reliably detect when commands finish
    unique_prompt = 'REPLAY_DONE_PROMPT>'
    child.sendline(f"PS1='{unique_prompt}'")
    child.expect(unique_prompt)
    
    timings = []
    start_total = time.time()
    
    for cmd in commands:
        # Simulate agent "thinking" time before the next command
        time.sleep(random.uniform(2.0, 5.0))
        
        start_time = time.time()
        child.sendline(cmd)
        
        # Wait for the prompt to return (indicating command completion)
        child.expect(unique_prompt)
        end_time = time.time()
        
        output = child.before.strip()
        elapsed = end_time - start_time
        timings.append({
            "command": cmd,
            "elapsed_seconds": elapsed,
            "output_length": len(output)
        })
        print(f"Executed: {cmd[:50]}{'...' if len(cmd) > 50 else ''} | Time: {elapsed:.3f}s")
        
    end_total = time.time()
    
    metrics = {
        "total_elapsed_seconds": end_total - start_total,
        "commands": timings
    }
    
    with open("replay_metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)
        
    print(f"Replay complete in {metrics['total_elapsed_seconds']:.3f}s. Metrics saved to replay_metrics.json.")

if __name__ == "__main__":
    main()

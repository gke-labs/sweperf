import os
import sys
import json
import subprocess
import glob
from pathlib import Path

def run_sweagent(task_id: str):
    print(f"========== 1. Running SWE-agent for {task_id} ==========")
    env = os.environ.copy()
    
    cmd = [
        sys.executable, "-m", "sweagent.run",
        "--model_name", "gemini/gemini-1.5-pro-latest",
        "--data_path", "princeton-nlp/SWE-bench_Verified",
        "--instance_filter", task_id,
        "--config_file", "config/default.yaml",
        "--per_instance_cost_limit", "3.00"
    ]
    
    swe_agent_dir = os.environ.get("SWE_AGENT_DIR", "/usr/local/google/home/bsalmon/git/SWE-agent")
    
    print(f"Executing: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=swe_agent_dir, env=env, check=True)
    print("SWE-agent run complete.")
    
def extract_trace(task_id: str) -> str:
    print(f"========== 2. Extracting Trace for {task_id} ==========")
    swe_agent_dir = Path(os.environ.get("SWE_AGENT_DIR", "/usr/local/google/home/bsalmon/git/SWE-agent"))
    
    search_pattern = str(swe_agent_dir / "trajectories" / "**" / f"{task_id}.json")
    traj_files = glob.glob(search_pattern, recursive=True)
    
    if not traj_files:
        raise FileNotFoundError(f"No trajectory found for {task_id} in {search_pattern}")
        
    latest_traj = max(traj_files, key=os.path.getmtime)
    print(f"Found trajectory: {latest_traj}")
    
    with open(latest_traj, 'r') as f:
        traj_data = json.load(f)
        
    commands = []
    
    for step in traj_data.get("trajectory", []):
        action = step.get("action", "")
        if action and not action.startswith("submit"):
            commands.append(action.strip())
            
    trace_out = f"{task_id}_trace.json"
    with open(trace_out, 'w') as f:
        json.dump(commands, f, indent=2)
        
    print(f"Extracted {len(commands)} commands to {trace_out}")
    return trace_out

def bake_image(task_id: str, trace_file: str):
    print(f"========== 3. Baking Replay Image for {task_id} ==========")
    
    replay_script = "replay.py"
    if not os.path.exists(replay_script):
        raise FileNotFoundError(f"{replay_script} not found in current directory.")
        
    base_image = f"sweb.env.x86_64.{task_id}:latest"
    
    dockerfile_content = f"""
FROM {base_image}
COPY {replay_script} /replay.py
COPY {trace_file} /trace.json
RUN apt-get update && apt-get install -y python3-pip && pip3 install pexpect
ENTRYPOINT ["python3", "/replay.py", "/trace.json"]
"""
    
    dockerfile_path = f"Dockerfile.{task_id}"
    with open(dockerfile_path, "w") as f:
        f.write(dockerfile_content.strip())
        
    new_image_tag = f"swe-bench-replay:{task_id}"
    print(f"Building Docker image: {new_image_tag} from {base_image}...")
    
    build_cmd = ["docker", "build", "-t", new_image_tag, "-f", dockerfile_path, "."]
    subprocess.run(build_cmd, check=True)
    
    print(f"Successfully built {new_image_tag}!")

def main():
    if len(sys.argv) != 2:
        print("Usage: python pipeline.py <task_id>")
        sys.exit(1)
        
    task_id = sys.argv[1]
    run_sweagent(task_id)
    trace_file = extract_trace(task_id)
    bake_image(task_id, trace_file)

if __name__ == "__main__":
    main()

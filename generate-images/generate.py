import os
import sys
import json
import urllib.request
import argparse
import subprocess
import time

def get_github_tree():
    """Fetch the full tree of swe-bench/experiments main branch."""
    url = "https://api.github.com/repos/swe-bench/experiments/git/trees/main?recursive=1"
    req = urllib.request.Request(url)
    # Add token if available in env to avoid rate limits
    if "GITHUB_TOKEN" in os.environ:
        req.add_header("Authorization", f"token {os.environ['GITHUB_TOKEN']}")
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            return data.get("tree", [])
    except Exception as e:
        print(f"Error fetching GitHub tree: {e}")
        return []

def extract_commands(traj_data):
    """
    Attempt to extract a list of bash commands from a trajectory JSON.
    Handles multiple common agent trajectory formats.
    """
    commands = []
    
    # Format 1: standard SWE-agent (info -> history)
    if "info" in traj_data and "history" in traj_data["info"]:
        for step in traj_data["info"]["history"]:
            if "action" in step and isinstance(step["action"], str):
                cmd = step["action"].strip()
                if cmd:
                    commands.append(cmd)
            elif "action_dict" in step:
                action_dict = step["action_dict"]
                if action_dict and "command" in action_dict:
                    cmd = action_dict["command"].strip()
                    if cmd:
                        commands.append(cmd)
                        
    # Format 2: messages array (e.g. gemini-3-pro-preview / mini-swe-agent-1)
    if "messages" in traj_data:
        import re
        for msg in traj_data["messages"]:
            if msg.get("role") == "assistant" and "content" in msg and msg["content"]:
                blocks = re.findall(r'```bash\n(.*?)\n```', msg["content"], re.DOTALL)
                for block in blocks:
                    cmd = block.strip()
                    if cmd:
                        commands.append(cmd)

    # Format 3: OpenHands style trajectory
    traj_list = traj_data.get("trajectory", traj_data.get("history", []))
    if traj_list:
        for item in traj_list:
            if "action" in item and item["action"] in ["run", "run_command", "execute"]:
                args = item.get("args", {})
                if isinstance(args, dict) and "command" in args:
                    commands.append(args["command"])
                elif isinstance(args, str):
                    commands.append(args)
            if "tool_calls" in item:
                for tc in item["tool_calls"]:
                    if tc.get("function", {}).get("name") in ["execute_bash", "run_bash"]:
                        args = tc["function"].get("arguments", "{}")
                        try:
                            parsed_args = json.loads(args)
                            if "command" in parsed_args:
                                commands.append(parsed_args["command"])
                        except:
                            pass
            if "command" in item and isinstance(item["command"], str):
                commands.append(item["command"])
                
    # Format 4: simple string list
    if isinstance(traj_data, list) and all(isinstance(x, str) for x in traj_data):
        commands = traj_data
        
    return commands

def process_instance(instance_id, url_or_path, build=False):
    """Download trajectory, generate trace and Dockerfile, and optionally build."""
    safe_id = instance_id.replace("__", "_1776_")
    base_image = f"swebench/sweb.eval.x86_64.{safe_id}:latest"
    
    print(f"\nProcessing {instance_id}...")
    
    # Fetch or read trajectory JSON
    try:
        if url_or_path.startswith("http://") or url_or_path.startswith("https://"):
            req = urllib.request.Request(url_or_path)
            if "GITHUB_TOKEN" in os.environ:
                req.add_header("Authorization", f"token {os.environ['GITHUB_TOKEN']}")
            with urllib.request.urlopen(req) as response:
                traj_data = json.loads(response.read().decode())
        else:
            with open(url_or_path, "r") as f:
                traj_data = json.load(f)
    except Exception as e:
        print(f"  Failed to read trajectory for {instance_id} from {url_or_path}: {e}")
        return False
        
    # 2. Extract commands
    commands = extract_commands(traj_data)
    if not commands:
        print(f"Warning: Could not extract any commands from {instance_id} trajectory. It might use an unsupported format.")
        # We will write empty trace anyway, maybe it just has no commands
        
    trace_filename = f"{instance_id}_trace.json"
    with open(trace_filename, "w") as f:
        json.dump(commands, f, indent=2)
    print(f"Saved {len(commands)} commands to {trace_filename}")
    
    # 3. Generate Dockerfile
    dockerfile_content = f"""FROM {base_image}
# Ensure python3 and pexpect are installed (sometimes SWE-bench images have python but no pexpect)
RUN if command -v pip &> /dev/null; then pip install pexpect; else apt-get update && apt-get install -y python3-pexpect; fi
COPY replay.py /replay.py
COPY {trace_filename} /trace.json
ENTRYPOINT ["python3", "/replay.py", "/trace.json"]
"""
    dockerfile_name = f"{instance_id}.Dockerfile"
    with open(dockerfile_name, "w") as f:
        f.write(dockerfile_content)
    print(f"Generated {dockerfile_name}")
    
    # 4. Build image (optional)
    if build:
        image_tag = f"swe-agent-replay:{instance_id}"
        print(f"Building Docker image {image_tag}...")
        cmd = ["docker", "build", "-t", image_tag, "-f", dockerfile_name, "."]
        try:
            subprocess.run(cmd, check=True)
            print(f"Successfully built {image_tag}")
        except subprocess.CalledProcessError as e:
            print(f"Failed to build {image_tag}: {e}")
            return False
            
    return True

def main():
    parser = argparse.ArgumentParser(description="Generate replay Docker images for SWE-bench cases.")
    parser.add_argument("--run", type=str, default="20251120_livesweagent_gemini-3-pro-preview", help="Run name in SWE-bench experiments")
    parser.add_argument("--limit", type=int, default=0, help="Max number of cases to process (0 = all)")
    parser.add_argument("--build", action="store_true", help="Actually run docker build (requires docker daemon)")
    parser.add_argument("--test", action="store_true", help="Run in test mode using local test_trace.json")
    parser.add_argument("--local-trajs-dir", type=str, help="Path to local trajs directory (bypasses GitHub download)")
    args = parser.parse_args()
    
    # Remove proxy env vars to ensure direct internet access works
    for k in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
        if k in os.environ:
            del os.environ[k]
            
    if args.test:
        print("Running in test mode...")
        trace_filename = "test_trace.json"
        if not os.path.exists(trace_filename):
            print(f"Error: {trace_filename} not found.")
            sys.exit(1)
        base_image = "ubuntu:22.04" # Use ubuntu for simple test to avoid pulling massive swebench images
        dockerfile_content = f"FROM {base_image}\nRUN apt-get update && apt-get install -y python3 python3-pexpect\nCOPY replay.py /replay.py\nCOPY {trace_filename} /trace.json\nENTRYPOINT [\"python3\", \"/replay.py\", \"/trace.json\"]\n"
        dockerfile_name = "test.Dockerfile"
        with open(dockerfile_name, "w") as f:
            f.write(dockerfile_content)
        print(f"Generated {dockerfile_name}")
        
        if args.build:
            image_tag = "swe-agent-replay:test"
            print(f"Building Docker image {image_tag}...")
            subprocess.run(["docker", "build", "-t", image_tag, "-f", dockerfile_name, "."], check=True)
            print(f"Successfully built {image_tag}")
            print("\nTo test it, run: docker run -it --rm swe-agent-replay:test")
        sys.exit(0)

    traj_files = []
    
    if args.local_trajs_dir:
        print(f"Reading local trajectories from {args.local_trajs_dir}...")
        if not os.path.isdir(args.local_trajs_dir):
            print(f"Error: Directory {args.local_trajs_dir} not found.")
            sys.exit(1)
        for root, dirs, files in os.walk(args.local_trajs_dir):
            for fname in files:
                if fname.endswith(".json"):
                    instance_id = fname.replace(".traj.json", "").replace(".json", "")
                    traj_files.append((instance_id, os.path.join(root, fname)))
    else:
        print("Fetching repository tree...")
        tree = get_github_tree()
        if not tree:
            print("Failed to get tree.")
            sys.exit(1)
            
        # Look for trajectory files in the specified run
        for item in tree:
            path = item["path"]
            if args.run in path and "/trajs/" in path and path.endswith(".json"):
                instance_id = path.split("/")[-1].replace(".json", "")
                raw_url = f"https://raw.githubusercontent.com/swe-bench/experiments/main/{path}"
                traj_files.append((instance_id, raw_url))
                
    if not traj_files:
        print(f"No trajectory files found.")
        sys.exit(1)
        
    print(f"Found {len(traj_files)} cases for {args.run}.")
    
    if args.limit > 0:
        traj_files = traj_files[:args.limit]
        print(f"Limiting to {args.limit} cases.")
        
    success_count = 0
    for instance_id, url in traj_files:
        if process_instance(instance_id, url, build=args.build):
            success_count += 1
            
    print(f"\nFinished. Successfully processed {success_count}/{len(traj_files)} cases.")

if __name__ == "__main__":
    main()

import os
import sys
import json
import urllib.request
import argparse
import subprocess
import time
import concurrent.futures



def gen_setup_script(instance_id, repo, base_commit, env_commit, python_version, pre_install, install, pip_packages, reqs_paths):
    cmds = ["#!/bin/bash", "set -e", "source /home/swe-bench/miniconda3/etc/profile.d/conda.sh || true"]
    cmds.append(f"git clone https://github.com/{repo} /testbed")
    cmds.append("cd /testbed")
    if env_commit and str(env_commit) != "None" and env_commit != base_commit:
        cmds.append(f"git checkout {env_commit}")
    else:
        cmds.append(f"git checkout {base_commit}")
    cmds.append(f"conda tos accept || true && conda create -n testbed python={python_version} -y")

    cmds.append("conda activate testbed")
    cmds.append("rm -rf $CONDA_PREFIX/compiler_compat/ld 2>/dev/null || true")
    cmds.append("python3 -m pip install --upgrade pip 'setuptools<69.0.0' wheel")
    cmds.append("python3 -m pip install flit_core pybind11 setuptools_scm extension_helpers")
    if "scikit-learn" in repo.lower() or "astropy" in repo.lower():
        cmds.append("python3 -m pip install 'cython>=0.29.36,<3.0' extension_helpers")
    if pre_install:
        if isinstance(pre_install, list):
            cmds.extend(pre_install)
        else:
            cmds.append(pre_install)

    if reqs_paths:
        for idx in range(len(reqs_paths)):
            cmds.append(f'''
if [ -f "{reqs_paths[idx]}" ]; then
    python -m pip install -r {reqs_paths[idx]}
fi
            '''.strip())

    if pip_packages:
        if isinstance(pip_packages, list):
            cmds.append(f"python -m pip install {' '.join(pip_packages)}")
        else:
            cmds.append(f"python -m pip install {pip_packages}")

    cmds.append("python3 -m pip install --no-build-isolation -e /testbed")
    if env_commit and str(env_commit) != "None" and env_commit != base_commit:
        cmds.append(f"git checkout {base_commit}")
    return "\n".join(cmds) + "\n"

def process_universal_instance(instance_id, url_or_path, dataset_indexed, swe_metadata):
    import urllib.request
    print(f"\nProcessing {instance_id} for universal runner...")
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
        print(f"  Failed: {e}")
        return False
        
    commands = extract_commands(traj_data)
    trace_filename = f"traces/{instance_id}_trace.json"
    with open(trace_filename, "w") as f:
        json.dump(commands, f, indent=2)
        
    if instance_id not in dataset_indexed:
        print(f"Warning: {instance_id} not found in dataset!")
        return False
        
    row = dataset_indexed[instance_id]
    repo = row['repo']
    version = row['version']
    
    spec = swe_metadata['specs'].get(repo, {}).get(version, {})
    
    python_ver = spec.get('python', "3.10")
        
    script = gen_setup_script(
        instance_id, repo, row['base_commit'], row['environment_setup_commit'],
        python_ver, spec.get('pre_install'), spec.get('install'),
        spec.get('pip_packages'), swe_metadata['reqs_paths'].get(repo)
    )
    
    with open(f"setups/setup_{instance_id}.sh", "w") as f:
        f.write(script)
    os.chmod(f"setups/setup_{instance_id}.sh", 0o755)
    return True

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
    
    # Format 4: simple string list
    if isinstance(traj_data, list) and all(isinstance(x, str) for x in traj_data):
        return traj_data

    if isinstance(traj_data, dict):
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

        # Format 3a: OpenHands style trajectory
        traj_list = traj_data.get("trajectory", traj_data.get("history", []))
    else:
        traj_list = traj_data if isinstance(traj_data, list) else []

    if traj_list:
        for item in traj_list:
            if isinstance(item, dict):
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
                    
    return commands

def process_instance(instance_id, url_or_path, build=False, push=False, image_prefix=""):
    """Download trajectory, generate trace and Dockerfile, and optionally build and push."""
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
LABEL "sweperf.base_image"="{base_image}"
LABEL "sweperf.trajectory_source"="{url_or_path}"
ENV SWEPERF_BASE_IMAGE="{base_image}"
ENV SWEPERF_TRAJECTORY_SOURCE="{url_or_path}"
RUN echo '{{"base_image": "{base_image}", "trajectory_source": "{url_or_path}"}}' > /sweperf_metadata.json
# Ensure python3 and pexpect are installed (sometimes SWE-bench images have python but no pexpect)
RUN if command -v pip &> /dev/null; then pip install pexpect; else apt-get update && apt-get install -y python3-pexpect; fi
COPY generate-images/replay.py /replay.py
COPY {trace_filename} /trace.json
ENTRYPOINT ["python3", "/replay.py", "/trace.json"]
"""
    dockerfile_name = f"{instance_id}.Dockerfile"
    with open(dockerfile_name, "w") as f:
        f.write(dockerfile_content)
    print(f"Generated {dockerfile_name}")
    
    # 4. Build image (optional)
    if build:
        tag_name = f"{image_prefix.rstrip('/')}:{instance_id}" if image_prefix else f"sweperf:{instance_id}"
        print(f"Building Docker image {tag_name}...")
        cmd = ["docker", "build", "--no-cache", "--rm", "--force-rm", "-t", tag_name, "-f", dockerfile_name, "."]
        try:
            env = os.environ.copy()
            env["DOCKER_BUILDKIT"] = "0" # Disable BuildKit to prevent it from pinning base images in cache
            subprocess.run(cmd, env=env, check=True)
            print(f"Successfully built {tag_name}")
        except subprocess.CalledProcessError as e:
            print(f"Failed to build {tag_name}: {e}")
            return False
            
        if push:
            print(f"Pushing Docker image {tag_name}...")
            try:
                subprocess.run(["docker", "push", tag_name], check=True)
                print(f"Successfully pushed {tag_name}")
            except subprocess.CalledProcessError as e:
                print(f"Failed to push {tag_name}: {e}")
                return False

        print(f"Cleaning up {tag_name} and base images to save disk space...")
        subprocess.run(["docker", "rmi", "-f", tag_name], check=False)
        subprocess.run(["docker", "rmi", "-f", base_image], check=False)
        subprocess.run(["docker", "image", "prune", "-f"], check=False)
        
    # if os.path.exists(trace_filename):
    #     os.remove(trace_filename)
    # if os.path.exists(dockerfile_name):
    #     os.remove(dockerfile_name)
        
    return True

def main():
    parser = argparse.ArgumentParser(description="Generate replay Docker images for SWE-bench cases.")
    parser.add_argument("--run", type=str, default="20251120_livesweagent_gemini-3-pro-preview", help="Run name in SWE-bench experiments")
    parser.add_argument("--limit", type=int, default=0, help="Max number of cases to process (0 = all)")
    parser.add_argument("--workers", type=int, default=8, help="Number of parallel workers for building images")
    parser.add_argument("--build", action="store_true", help="Actually run docker build (requires docker daemon)")
    parser.add_argument("--push", action="store_true", help="Push the built images to a remote registry (requires --build)")
    parser.add_argument("--image-prefix", type=str, default="", help="Prefix for the docker image tag (e.g. 'us-central1-docker.pkg.dev/my-project/repo/')")
    parser.add_argument("--test", action="store_true", help="Run in test mode using local test_trace.json")
    parser.add_argument("--universal", action="store_true", help="Generate single universal base image")
    parser.add_argument("--local-trajs-dir", type=str, help="Path to local trajs directory (bypasses GitHub download)")
    parser.add_argument("--output-list", type=str, help="File to write the list of successfully built/pushed image tags to")
    parser.add_argument("--output-yaml", type=str, help="Output YAML file for CL2 template overrides")
    args = parser.parse_args()
    
    if args.push and not args.build:
        print("Error: --push requires --build")
        sys.exit(1)
    
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
        dockerfile_content = f"FROM {base_image}\nLABEL \"sweperf.base_image\"=\"{base_image}\"\nLABEL \"sweperf.trajectory_source\"=\"test_trace.json\"\nENV SWEPERF_BASE_IMAGE=\"{base_image}\"\nENV SWEPERF_TRAJECTORY_SOURCE=\"test_trace.json\"\nRUN echo '{{\"base_image\": \"{base_image}\", \"trajectory_source\": \"test_trace.json\"}}' > /sweperf_metadata.json\nRUN apt-get update && apt-get install -y python3 python3-pexpect\nCOPY generate-images/replay.py /replay.py\nCOPY {trace_filename} /trace.json\nENTRYPOINT [\"python3\", \"/replay.py\", \"/trace.json\"]\n"
        dockerfile_name = "test.Dockerfile"
        with open(dockerfile_name, "w") as f:
            f.write(dockerfile_content)
        print(f"Generated {dockerfile_name}")
        
        if args.build:
            image_tag = f"{args.image_prefix.rstrip('/')}:test" if args.image_prefix else "sweperf:test"
            print(f"Building Docker image {image_tag}...")
            subprocess.run(["docker", "build", "-t", image_tag, "-f", dockerfile_name, "."], check=True)
            print(f"Successfully built {image_tag}")
            print(f"\nTo test it, run: docker run -it --rm {image_tag}")
        sys.exit(0)


    if args.universal:
        print("Running in universal mode...")
        os.makedirs("setups", exist_ok=True)
        os.makedirs("traces", exist_ok=True)
        with open("generated_instances.txt", "w") as f:
            pass
        from datasets import load_dataset
        ds = load_dataset('princeton-nlp/SWE-bench_Verified', split='test')
        dataset_indexed = {r['instance_id']: r for r in ds}
        
        try:
            from swebench.harness.constants.python import (
                MAP_REPO_VERSION_TO_SPECS_PY,
                MAP_REPO_TO_REQS_PATHS,
                MAP_REPO_TO_ENV_YML_PATHS
            )
            swe_metadata = {
                'specs': MAP_REPO_VERSION_TO_SPECS_PY,
                'reqs_paths': MAP_REPO_TO_REQS_PATHS,
                'env_yml_paths': MAP_REPO_TO_ENV_YML_PATHS
            }
        except ImportError as e:
            print(f"Warning: Failed to import swebench specs: {e}")
            swe_metadata = {'specs': {}, 'reqs_paths': {}, 'env_yml_paths': {}}

    traj_files = []
    
    if not args.local_trajs_dir:
        print(f"No --local-trajs-dir provided. Downloading trajectories for {args.run} from S3 via swe-bench/experiments repo...")
        repo_dir = "swe-bench-experiments-repo"
        if not os.path.exists(repo_dir):
            print("Cloning swe-bench/experiments repository...")
            subprocess.run(["git", "clone", "https://github.com/swe-bench/experiments.git", repo_dir], check=True)
        
        # Ensure dependencies are installed
        print("Ensuring dependencies for download_logs are installed...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-i", "https://pypi.org/simple", "boto3", "requests", "urllib3", "tqdm"], check=True)
        
        eval_path = f"evaluation/verified/{args.run}"
        marker_file = os.path.join(repo_dir, eval_path, ".download_success")
        
        if os.path.exists(marker_file):
            print(f"Trajectories for {eval_path} already downloaded. Skipping.")
        else:
            print(f"Running download_logs for {eval_path}...")
            try:
                subprocess.run([sys.executable, "-m", "analysis.download_logs", eval_path, "--skip_existing"], cwd=repo_dir, check=True)
                with open(marker_file, "w") as f:
                    f.write("done\n")
            except subprocess.CalledProcessError:
                print(f"Failed to download verified split. Trying lite split...")
                eval_path = f"evaluation/lite/{args.run}"
                marker_file = os.path.join(repo_dir, eval_path, ".download_success")
                if os.path.exists(marker_file):
                    print(f"Trajectories for {eval_path} already downloaded. Skipping.")
                else:
                    subprocess.run([sys.executable, "-m", "analysis.download_logs", eval_path, "--skip_existing"], cwd=repo_dir, check=True)
                    with open(marker_file, "w") as f:
                        f.write("done\n")
            
        args.local_trajs_dir = os.path.join(repo_dir, eval_path, "trajs")
        
    print(f"Reading local trajectories from {args.local_trajs_dir}...")
    if not os.path.isdir(args.local_trajs_dir):
        print(f"Error: Directory {args.local_trajs_dir} not found.")
        sys.exit(1)
        
    for root, dirs, files in os.walk(args.local_trajs_dir):
        for fname in files:
            if fname.endswith(".json"):
                instance_id = fname.replace(".traj.json", "").replace(".json", "")
                traj_files.append((instance_id, os.path.join(root, fname)))
                
    if not traj_files:
        print(f"No trajectory files found.")
        sys.exit(1)
        
    print(f"Found {len(traj_files)} cases for {args.run}.")
    
    if args.limit > 0:
        traj_files = traj_files[:args.limit]
        print(f"Limiting to {args.limit} cases.")
        
    success_count = 0
    successful_tags = []
    
    if args.image_prefix:
        args.image_prefix = args.image_prefix.rstrip('/') + "/sweperf"

    print(f"Starting parallel processing with {args.workers} workers...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        if args.universal:
            future_to_instance = {
                executor.submit(process_universal_instance, instance_id, url, dataset_indexed, swe_metadata): instance_id
                for instance_id, url in traj_files
            }
        else:
            future_to_instance = {
                executor.submit(process_instance, instance_id, url, build=args.build, push=args.push, image_prefix=args.image_prefix): instance_id
                for instance_id, url in traj_files
            }
        
        for future in concurrent.futures.as_completed(future_to_instance):
            instance_id = future_to_instance[future]
            try:
                if future.result():
                    success_count += 1
                    successful_tags.append(f"{args.image_prefix.rstrip('/')}:{instance_id}" if args.image_prefix else f"sweperf:{instance_id}")
                    if args.universal:
                        with open('generated_instances.txt', 'a') as gf:
                            gf.write(instance_id + '\n')
            except Exception as e:
                print(f"Error processing {instance_id}: {e}")
            

    if args.universal:
        print("Traces and setups generated. Using checked-in generate-images/Dockerfile.universal.")

    if args.output_list and successful_tags:
        with open(args.output_list, "w") as f:
            for tag in successful_tags:
                f.write(f"{tag}\n")
        print(f"Wrote {len(successful_tags)} tags to {args.output_list}")
            
    if args.output_yaml and successful_tags:
        with open(args.output_yaml, "w") as f:
            f.write("SWE_BENCH_IMAGES:\n")
            for tag in successful_tags:
                f.write(f"  - \"{tag}\"\n")
        print(f"Wrote {len(successful_tags)} tags to {args.output_yaml} in CL2 override format")
            
    print(f"\nFinished. Successfully processed {success_count}/{len(traj_files)} cases.")

if __name__ == "__main__":
    main()

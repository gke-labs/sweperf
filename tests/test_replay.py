import os
import json
import shutil
import tempfile
import subprocess
import unittest

class TestReplayScript(unittest.TestCase):
    def test_replay_script_execution(self):
        # We need the path to the real replay script
        # Assuming this test runs from the root of the repo or from tests/
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        replay_script_src = os.path.join(repo_root, 'generate-images', 'replay.py')
        
        self.assertTrue(os.path.exists(replay_script_src), f"Replay script not found at {replay_script_src}")
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # 1. Create a fake trajectory
            trace = [
                "echo 'unique_test_string_12345'",
                "expr 10 + 25",
                "mkdir my_test_directory",
                "ls -l",
                "ls nonexistent_dir"
            ]
            
            trace_path = os.path.join(temp_dir, "trace.json")
            with open(trace_path, "w") as f:
                json.dump(trace, f)
                
            # 2. Copy the replay script to the build context
            replay_script_dest = os.path.join(temp_dir, "replay.py")
            shutil.copy(replay_script_src, replay_script_dest)
            
            # 3. Create a Dockerfile
            dockerfile_content = """
FROM python:3.9-slim
RUN pip install pexpect
COPY replay.py /replay.py
COPY trace.json /trace.json
# Use very negative MU so sleep is effectively 0.5s (the script's minimum)
ENV LLM_LATENCY_MU=-5
ENV LLM_LATENCY_SIGMA=0.1
ENTRYPOINT ["python3", "/replay.py", "/trace.json"]
"""
            dockerfile_path = os.path.join(temp_dir, "Dockerfile")
            with open(dockerfile_path, "w") as f:
                f.write(dockerfile_content)
                
            # 4. Build the Docker image
            image_name = "test-replay-image:latest"
            build_cmd = ["docker", "build", "-t", image_name, "."]
            print(f"Building docker image {image_name}...")
            build_result = subprocess.run(build_cmd, cwd=temp_dir, capture_output=True, text=True)
            self.assertEqual(build_result.returncode, 0, f"Docker build failed:\nSTDOUT:\n{build_result.stdout}\nSTDERR:\n{build_result.stderr}")
            
            # 5. Run the Docker container
            run_cmd = ["docker", "run", "--rm", image_name]
            print(f"Running docker container {image_name}...")
            run_result = subprocess.run(run_cmd, capture_output=True, text=True)
            self.assertEqual(run_result.returncode, 0, f"Docker run failed:\nSTDOUT:\n{run_result.stdout}\nSTDERR:\n{run_result.stderr}")
            
            # 6. Confirm that the appropriate commands were executed
            output = run_result.stdout
            
            self.assertIn("unique_test_string_12345", output, "Failed to find 'echo' output")
            self.assertIn("35", output, "Failed to find 'expr' output")
            self.assertIn("my_test_directory", output, "Failed to find 'mkdir'/'ls' output")
            
            # 7. Check the replay stats for successes and failures
            self.assertIn("[REPLAY_STATS] Successes: 4, Failures: 1", output, "Failed to find correct success/failure counts in output")
            
            # Cleanup
            print(f"Cleaning up docker image {image_name}...")
            subprocess.run(["docker", "rmi", image_name], capture_output=True)

    def test_replay_wait_for_claim(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        replay_script_src = os.path.join(repo_root, 'generate-images', 'replay.py')
        
        with tempfile.TemporaryDirectory() as temp_dir:
            trace = ["echo 'post_claim_execution_123'"]
            trace_path = os.path.join(temp_dir, "trace.json")
            with open(trace_path, "w") as f:
                json.dump(trace, f)
                
            replay_script_dest = os.path.join(temp_dir, "replay.py")
            shutil.copy(replay_script_src, replay_script_dest)
            
            dockerfile_content = """
FROM python:3.9-slim
RUN pip install pexpect
COPY replay.py /replay.py
COPY trace.json /trace.json
ENV LLM_LATENCY_MU=-5
ENV LLM_LATENCY_SIGMA=0.1
ENTRYPOINT ["python3", "/replay.py", "/trace.json"]
"""
            dockerfile_path = os.path.join(temp_dir, "Dockerfile")
            with open(dockerfile_path, "w") as f:
                f.write(dockerfile_content)
                
            image_name = "test-replay-claim-image:latest"
            subprocess.run(["docker", "build", "-t", image_name, "."], cwd=temp_dir, capture_output=True, check=True)
            
            import time
            run_cmd = ["docker", "run", "-d", "-e", "WAIT_FOR_CLAIM_FILE=/tmp/claim.txt", image_name]
            run_result = subprocess.run(run_cmd, capture_output=True, text=True, check=True)
            container_id = run_result.stdout.strip()
            
            try:
                time.sleep(2)
                logs_before = subprocess.run(["docker", "logs", container_id], capture_output=True, text=True).stdout
                self.assertNotIn("post_claim_execution_123", logs_before, "Should not execute before claim")
                self.assertIn("Waiting for claim signal in /tmp/claim.txt...", logs_before, "Should print waiting message")
                
                subprocess.run(["docker", "exec", container_id, "sh", "-c", "echo 'agents.x-k8s.io/sandbox-id' > /tmp/claim.txt"], check=True)
                
                time.sleep(3)
                logs_after = subprocess.run(["docker", "logs", container_id], capture_output=True, text=True).stdout
                self.assertIn("Claim signal received!", logs_after, "Should print claim received message")
                self.assertIn("post_claim_execution_123", logs_after, "Should execute after claim")
            finally:
                subprocess.run(["docker", "rm", "-f", container_id], capture_output=True)
                subprocess.run(["docker", "rmi", image_name], capture_output=True)

    def test_replay_wait_for_start_port(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        replay_script_src = os.path.join(repo_root, 'generate-images', 'replay.py')
        
        with tempfile.TemporaryDirectory() as temp_dir:
            trace = ["echo 'post_port_execution_123'"]
            trace_path = os.path.join(temp_dir, "trace.json")
            with open(trace_path, "w") as f:
                json.dump(trace, f)
                
            replay_script_dest = os.path.join(temp_dir, "replay.py")
            shutil.copy(replay_script_src, replay_script_dest)
            
            dockerfile_content = """
FROM python:3.9-slim
RUN apt-get update && apt-get install -y curl
RUN pip install pexpect
COPY replay.py /replay.py
COPY trace.json /trace.json
ENV LLM_LATENCY_MU=-5
ENV LLM_LATENCY_SIGMA=0.1
ENTRYPOINT ["python3", "/replay.py", "/trace.json"]
"""
            dockerfile_path = os.path.join(temp_dir, "Dockerfile")
            with open(dockerfile_path, "w") as f:
                f.write(dockerfile_content)
                
            image_name = "test-replay-port-image:latest"
            subprocess.run(["docker", "build", "-t", image_name, "."], cwd=temp_dir, capture_output=True, check=True)
            
            import time
            run_cmd = ["docker", "run", "-d", "-e", "WAIT_FOR_START_PORT=8080", image_name]
            run_result = subprocess.run(run_cmd, capture_output=True, text=True, check=True)
            container_id = run_result.stdout.strip()
            
            try:
                time.sleep(2)
                logs_before = subprocess.run(["docker", "logs", container_id], capture_output=True, text=True).stdout
                self.assertNotIn("post_port_execution_123", logs_before, "Should not execute before curl")
                self.assertIn("Waiting for 'start' command on port 8080...", logs_before, "Should print waiting message")
                
                subprocess.run(["docker", "exec", container_id, "curl", "-X", "GET", "http://localhost:8080/start"], check=True)
                
                time.sleep(3)
                logs_after = subprocess.run(["docker", "logs", container_id], capture_output=True, text=True).stdout
                self.assertIn("Start signal received via port!", logs_after, "Should print port received message")
                self.assertIn("post_port_execution_123", logs_after, "Should execute after port start")
            finally:
                subprocess.run(["docker", "rm", "-f", container_id], capture_output=True)
                subprocess.run(["docker", "rmi", image_name], capture_output=True)

    def test_replay_git_diff_no_pager(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        replay_script_src = os.path.join(repo_root, 'generate-images', 'replay.py')
        
        with tempfile.TemporaryDirectory() as temp_dir:
            trace = [
                "git config --global user.email 'test@test.com'",
                "git config --global user.name 'Test'",
                "git init",
                "for i in $(seq 1 100); do echo $i >> large_file.txt; done",
                "git add large_file.txt",
                "git commit -m 'init'",
                "echo 'new line' >> large_file.txt",
                "git diff",
                "echo 'SUCCESS_AFTER_DIFF'"
            ]
            trace_path = os.path.join(temp_dir, "trace.json")
            with open(trace_path, "w") as f:
                json.dump(trace, f)
                
            replay_script_dest = os.path.join(temp_dir, "replay.py")
            shutil.copy(replay_script_src, replay_script_dest)
            
            dockerfile_content = """
FROM python:3.9-slim
RUN apt-get update && apt-get install -y git
RUN pip install pexpect
COPY replay.py /replay.py
COPY trace.json /trace.json
ENV LLM_LATENCY_MU=-5
ENV LLM_LATENCY_SIGMA=0.1
ENV GIT_PAGER=cat
ENV PAGER=cat
ENTRYPOINT ["python3", "/replay.py", "/trace.json"]
"""
            dockerfile_path = os.path.join(temp_dir, "Dockerfile")
            with open(dockerfile_path, "w") as f:
                f.write(dockerfile_content)
                
            image_name = "test-replay-git-diff:latest"
            subprocess.run(["docker", "build", "-t", image_name, "."], cwd=temp_dir, capture_output=True, check=True)
            
            run_cmd = ["docker", "run", "--rm", image_name]
            # Use timeout just in case it hangs!
            run_result = subprocess.run(run_cmd, capture_output=True, text=True, timeout=60)
            
            output = run_result.stdout
            
            self.assertIn("SUCCESS_AFTER_DIFF", output, "Failed to complete diff! The pager likely hung the process.")
            
            subprocess.run(["docker", "rmi", image_name], capture_output=True)

if __name__ == '__main__':
    unittest.main()

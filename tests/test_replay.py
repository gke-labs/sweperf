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
                "ls -l"
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
            
            # Cleanup
            print(f"Cleaning up docker image {image_name}...")
            subprocess.run(["docker", "rmi", image_name], capture_output=True)

if __name__ == '__main__':
    unittest.main()

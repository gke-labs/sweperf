"""Unit and integration tests for SWE-perf asynchronous execution replay engine."""

import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

# Add generate-images directory to path for import
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(repo_root, "generate-images"))

import replay
from replay import GLOBAL_STATE, WorkloadServerHandler


# ---------------------------------------------------------------------------
# In-Memory Async HTTP Unit Tests
# ---------------------------------------------------------------------------
class TestSweperfAsyncExecutionServer(unittest.TestCase):
  """Fast, in-process unit tests validating REST endpoints and execution semantics."""

  def setUp(self) -> None:
    GLOBAL_STATE.__init__()
    self.temp_dir = tempfile.TemporaryDirectory()
    self.trace_file = os.path.join(self.temp_dir.name, "test_trace.json")

    self.sample_commands = [
        "echo 'step 1'",
        {"command": "echo 'step 2'", "sleep": 0.01},
        "echo 'step 3'",
        "echo 'step 4'",
        "echo 'step 5'",
    ]
    with open(self.trace_file, "w") as f:
      json.dump(self.sample_commands, f)

    os.environ["TRACE_PATH"] = self.trace_file
    os.environ["SWEPERF_DISABLE_INTERNAL_SLEEP"] = "1"
    GLOBAL_STATE.load_trace(self.trace_file)

    # Boot HTTP server on dynamic local port
    self.server = http.server.HTTPServer(("127.0.0.1", 0), WorkloadServerHandler)
    self.port = self.server.server_address[1]
    self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
    self.server_thread.start()

  def tearDown(self) -> None:
    self.server.shutdown()
    self.server.server_close()
    self.temp_dir.cleanup()
    for k in ["TRACE_PATH", "AGENT_TRACE_PATH", "SWEPERF_DISABLE_INTERNAL_SLEEP", "SWEPERF_LEGACY_TCP", "WAIT_FOR_START_PORT"]:
      os.environ.pop(k, None)

  def _post_execute(self, payload: dict) -> urllib.request.addinfourl:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{self.port}/execute",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return urllib.request.urlopen(req)

  def _get_status(self, job_id: str = None) -> urllib.request.addinfourl:
    url = f"http://127.0.0.1:{self.port}/status"
    if job_id:
      url += f"?job_id={job_id}"
    req = urllib.request.Request(url, method="GET")
    return urllib.request.urlopen(req)

  def _poll_until_finished(self, job_id: str, timeout_sec: float = 3.0) -> dict:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
      resp = self._get_status(job_id)
      body = json.loads(resp.read().decode("utf-8"))
      if body.get("status") in ("COMPLETED", "FAILED"):
        return body
      time.sleep(0.05)
    self.fail(f"Job {job_id} did not finish within {timeout_sec}s")

  def test_async_chunk_execution_and_status_polling(self) -> None:
    """Verifies POST /execute returns 202 Accepted and GET /status polls to COMPLETED."""
    resp = self._post_execute({"start_step": 1, "end_step": 2})
    self.assertEqual(resp.status, 202)
    body = json.loads(resp.read().decode("utf-8"))
    self.assertIn("job_id", body)
    self.assertEqual(body["status"], "ACCEPTED")

    final_stat = self._poll_until_finished(body["job_id"])
    self.assertEqual(final_stat["status"], "COMPLETED")
    self.assertEqual(GLOBAL_STATE.last_completed_step, 2)

    # Subsequent contiguous chunk: 3..5
    resp2 = self._post_execute({"start_step": 3, "end_step": 5})
    self.assertEqual(resp2.status, 202)
    final_stat2 = self._poll_until_finished(json.loads(resp2.read().decode("utf-8"))["job_id"])
    self.assertEqual(final_stat2["status"], "COMPLETED")
    self.assertEqual(GLOBAL_STATE.last_completed_step, 5)

  def test_full_trace_execution(self) -> None:
    """Verifies executing all trace steps (1..5) in a single request."""
    resp = self._post_execute({"start_step": 1, "end_step": 5})
    self.assertEqual(resp.status, 202)
    job_id = json.loads(resp.read().decode("utf-8"))["job_id"]

    final_stat = self._poll_until_finished(job_id)
    self.assertEqual(final_stat["status"], "COMPLETED")
    self.assertEqual(GLOBAL_STATE.last_completed_step, 5)

  def test_non_zero_exit_code_still_completes(self) -> None:
    """Verifies that non-zero return codes (e.g. repro test failure) complete with COMPLETED."""
    failing_test_trace = [
        "python3 -c 'import sys; sys.exit(1)'",
        "echo 'Step after failure'",
    ]
    with open(self.trace_file, "w") as f:
      json.dump(failing_test_trace, f)
    GLOBAL_STATE.load_trace(self.trace_file)

    resp = self._post_execute({"start_step": 1, "end_step": 2})
    self.assertEqual(resp.status, 202)
    job_id = json.loads(resp.read().decode("utf-8"))["job_id"]

    final_stat = self._poll_until_finished(job_id)
    self.assertEqual(final_stat["status"], "COMPLETED")
    self.assertEqual(GLOBAL_STATE.last_completed_step, 2)

  def test_reset_sequence_to_step_one_allowed(self) -> None:
    """Verifies that sending start_step: 1 is always allowed to reset a trajectory run."""
    resp1 = self._post_execute({"start_step": 1, "end_step": 3})
    self._poll_until_finished(json.loads(resp1.read().decode("utf-8"))["job_id"])
    self.assertEqual(GLOBAL_STATE.last_completed_step, 3)

    # Reset back to step 1
    resp2 = self._post_execute({"start_step": 1, "end_step": 2})
    self.assertEqual(resp2.status, 202)
    self._poll_until_finished(json.loads(resp2.read().decode("utf-8"))["job_id"])
    self.assertEqual(GLOBAL_STATE.last_completed_step, 2)

  def test_validation_errors_return_400(self) -> None:
    """Verifies invalid payloads, types, or boundary limits return HTTP 400."""
    invalid_cases = [
        ({}, "Missing both fields"),
        ({"start_step": 1}, "Missing end_step"),
        ({"start_step": "1", "end_step": 2}, "String types"),
        ({"start_step": True, "end_step": 2}, "Boolean types"),
        ({"start_step": 0, "end_step": 2}, "start_step < 1"),
        ({"start_step": 3, "end_step": 2}, "start_step > end_step"),
        ({"start_step": 1, "end_step": -1}, "end_step: -1 is invalid"),
        ({"start_step": 1, "end_step": 999}, "end_step > total_steps"),
    ]

    for payload, description in invalid_cases:
      with self.subTest(desc=description):
        try:
          self._post_execute(payload)
          self.fail(f"Expected HTTP 400 for case: {description}")
        except urllib.error.HTTPError as e:
          self.assertEqual(e.code, 400)

  def test_non_contiguous_sequence_returns_400(self) -> None:
    """Verifies jumping forward mid-trajectory returns HTTP 400."""
    resp = self._post_execute({"start_step": 1, "end_step": 2})
    self.assertEqual(resp.status, 202)
    self._poll_until_finished(json.loads(resp.read().decode("utf-8"))["job_id"])

    try:
      self._post_execute({"start_step": 4, "end_step": 5})
      self.fail("Expected HTTP 400 for non-contiguous step index")
    except urllib.error.HTTPError as e:
      self.assertEqual(e.code, 400)
      body = json.loads(e.read().decode("utf-8"))
      self.assertIn("Expected 3", body["error"])

  def test_concurrency_conflict_returns_409(self) -> None:
    """Verifies simultaneous POST /execute calls return HTTP 409 Conflict."""
    slow_trace = [
        "python3 -c 'import time; time.sleep(0.8)'",
        "echo 'done'",
    ]
    with open(self.trace_file, "w") as f:
      json.dump(slow_trace, f)
    GLOBAL_STATE.load_trace(self.trace_file)

    resp1 = self._post_execute({"start_step": 1, "end_step": 2})
    self.assertEqual(resp1.status, 202)

    try:
      self._post_execute({"start_step": 1, "end_step": 2})
      self.fail("Expected HTTP 409 Conflict")
    except urllib.error.HTTPError as e:
      self.assertEqual(e.code, 409)

  def test_unknown_job_id_returns_404(self) -> None:
    """Verifies querying GET /status with non-existent job_id returns HTTP 404."""
    try:
      self._get_status("unknown-uuid-0000")
      self.fail("Expected HTTP 404")
    except urllib.error.HTTPError as e:
      self.assertEqual(e.code, 404)

  def test_general_liveness_check(self) -> None:
    """Verifies GET /status without parameters returns pod liveness info."""
    resp = self._get_status()
    self.assertEqual(resp.status, 200)
    body = json.loads(resp.read().decode("utf-8"))
    self.assertEqual(body.get("status"), "UP")
    self.assertEqual(body.get("total_steps"), 5)

  def test_internal_sleep_behavior(self) -> None:
    """Verifies that SWEPERF_DISABLE_INTERNAL_SLEEP toggles think-time sleep."""
    # With sleep enabled: should take >= 0.2s
    os.environ["SWEPERF_DISABLE_INTERNAL_SLEEP"] = "0"
    trace = [{"command": "echo 'sleep step'", "sleep": 0.25}]
    with open(self.trace_file, "w") as f:
      json.dump(trace, f)
    GLOBAL_STATE.load_trace(self.trace_file)

    t0 = time.time()
    resp = self._post_execute({"start_step": 1, "end_step": 1})
    self._poll_until_finished(json.loads(resp.read().decode("utf-8"))["job_id"])
    elapsed_with_sleep = time.time() - t0
    self.assertGreaterEqual(elapsed_with_sleep, 0.2)

    # With sleep disabled: should execute quickly (< 0.15s)
    os.environ["SWEPERF_DISABLE_INTERNAL_SLEEP"] = "1"
    t0 = time.time()
    resp2 = self._post_execute({"start_step": 1, "end_step": 1})
    self._poll_until_finished(json.loads(resp2.read().decode("utf-8"))["job_id"])
    elapsed_no_sleep = time.time() - t0
    self.assertLess(elapsed_no_sleep, 0.15)

  def test_execution_duration_reported_and_excludes_sleep(self) -> None:
    """Verifies execution_duration_ms measures subprocess run and excludes time.sleep."""
    os.environ["SWEPERF_DISABLE_INTERNAL_SLEEP"] = "0"
    trace = [{"command": "python3 -c 'import time; time.sleep(0.1)'", "sleep": 0.4}]
    with open(self.trace_file, "w") as f:
      json.dump(trace, f)
    GLOBAL_STATE.load_trace(self.trace_file)

    t0 = time.time()
    resp = self._post_execute({"start_step": 1, "end_step": 1})
    self.assertEqual(resp.status, 202)
    job_id = json.loads(resp.read().decode("utf-8"))["job_id"]

    final_stat = self._poll_until_finished(job_id, timeout_sec=5.0)
    elapsed_wall_time = time.time() - t0

    self.assertEqual(final_stat["status"], "COMPLETED")
    self.assertIn("execution_duration_ms", final_stat)

    # Subprocess ran for ~100ms; simulated sleep was 400ms (total wall time >= 500ms).
    # execution_duration_ms must record subprocess time (~100ms) and NOT include the 400ms sleep.
    exec_ms = final_stat["execution_duration_ms"]
    self.assertGreaterEqual(elapsed_wall_time, 0.45)
    self.assertGreaterEqual(exec_ms, 80.0)
    self.assertLess(exec_ms, 300.0)


# ---------------------------------------------------------------------------
# Docker Integration Tests
# ---------------------------------------------------------------------------
class TestReplayScript(unittest.TestCase):
  """Docker integration tests verifying containerized image builds and execution flows."""

  def test_replay_http_async_docker_integration(self) -> None:
    """Verifies Docker container running the new async HTTP server endpoint end-to-end."""
    replay_script_src = os.path.join(repo_root, "generate-images", "replay.py")
    self.assertTrue(os.path.exists(replay_script_src))

    with tempfile.TemporaryDirectory() as temp_dir:
      trace = ["echo 'STEP_1_ASYNC_DOCKER'", "echo 'STEP_2_ASYNC_DOCKER'"]
      with open(os.path.join(temp_dir, "trace.json"), "w") as f:
        json.dump(trace, f)
      shutil.copy(replay_script_src, os.path.join(temp_dir, "replay.py"))
      dockerfile_content = """
FROM python:3.9-slim
RUN apt-get update && apt-get install -y curl
COPY replay.py /replay.py
COPY trace.json /trace.json
ENV PORT=8080
ENV SWEPERF_DISABLE_INTERNAL_SLEEP=1
ENTRYPOINT ["python3", "/replay.py", "/trace.json"]
"""
      with open(os.path.join(temp_dir, "Dockerfile"), "w") as f:
        f.write(dockerfile_content)

      image_name = "test-replay-http-async:latest"
      subprocess.run(["docker", "build", "-t", image_name, "."], cwd=temp_dir, capture_output=True, check=True)
      run_cmd = ["docker", "run", "-d", image_name]
      container_id = subprocess.run(run_cmd, capture_output=True, text=True, check=True).stdout.strip()

      try:
        time.sleep(2)
        # POST /execute via docker exec curl
        post_cmd = [
            "docker", "exec", container_id,
            "curl", "-s", "-X", "POST", "http://localhost:8080/execute",
            "-H", "Content-Type: application/json",
            "-d", '{"start_step": 1, "end_step": 2}'
        ]
        post_out = subprocess.run(post_cmd, capture_output=True, text=True, check=True).stdout
        post_json = json.loads(post_out)
        self.assertEqual(post_json.get("status"), "ACCEPTED")
        job_id = post_json.get("job_id")

        # Poll GET /status
        time.sleep(1)
        stat_cmd = [
            "docker", "exec", container_id,
            "curl", "-s", f"http://localhost:8080/status?job_id={job_id}"
        ]
        stat_out = subprocess.run(stat_cmd, capture_output=True, text=True, check=True).stdout
        stat_json = json.loads(stat_out)
        self.assertEqual(stat_json.get("status"), "COMPLETED")

        # Verify container logs
        logs = subprocess.run(["docker", "logs", container_id], capture_output=True, text=True).stdout
        self.assertIn("STEP_1_ASYNC_DOCKER", logs)
        self.assertIn("STEP_2_ASYNC_DOCKER", logs)
      finally:
        subprocess.run(["docker", "rm", "-f", container_id], capture_output=True)
        subprocess.run(["docker", "rmi", image_name], capture_output=True)

  def test_replay_git_diff_no_pager(self) -> None:
    """Tests that commands with long outputs do not hang on git pagers."""
    replay_script_src = os.path.join(repo_root, "generate-images", "replay.py")

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
      with open(os.path.join(temp_dir, "trace.json"), "w") as f:
        json.dump(trace, f)
      shutil.copy(replay_script_src, os.path.join(temp_dir, "replay.py"))
      dockerfile_content = """
FROM python:3.9-slim
RUN apt-get update && apt-get install -y git curl
COPY replay.py /replay.py
COPY trace.json /trace.json
ENV PORT=8080
ENV SWEPERF_DISABLE_INTERNAL_SLEEP=1
ENTRYPOINT ["python3", "/replay.py", "/trace.json"]
"""
      with open(os.path.join(temp_dir, "Dockerfile"), "w") as f:
        f.write(dockerfile_content)

      image_name = "test-replay-git-diff:latest"
      subprocess.run(["docker", "build", "-t", image_name, "."], cwd=temp_dir, capture_output=True, check=True)
      run_cmd = ["docker", "run", "-d", image_name]
      container_id = subprocess.run(run_cmd, capture_output=True, text=True, check=True).stdout.strip()

      try:
        time.sleep(2)
        # Execute all 9 steps
        post_cmd = [
            "docker", "exec", container_id,
            "curl", "-s", "-X", "POST", "http://localhost:8080/execute",
            "-H", "Content-Type: application/json",
            "-d", '{"start_step": 1, "end_step": 9}'
        ]
        post_out = subprocess.run(post_cmd, capture_output=True, text=True, check=True).stdout
        job_id = json.loads(post_out).get("job_id")

        time.sleep(2)
        stat_cmd = [
            "docker", "exec", container_id,
            "curl", "-s", f"http://localhost:8080/status?job_id={job_id}"
        ]
        stat_out = subprocess.run(stat_cmd, capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(stat_out).get("status"), "COMPLETED")

        logs = subprocess.run(["docker", "logs", container_id], capture_output=True, text=True).stdout
        self.assertIn("SUCCESS_AFTER_DIFF", logs)
      finally:
        subprocess.run(["docker", "rm", "-f", container_id], capture_output=True)
        subprocess.run(["docker", "rmi", image_name], capture_output=True)

  def test_replay_wait_for_claim(self) -> None:
    """Tests claim signal file-watching behavior in Docker container."""
    replay_script_src = os.path.join(repo_root, "generate-images", "replay.py")

    with tempfile.TemporaryDirectory() as temp_dir:
      trace = ["echo 'post_claim_execution_123'"]
      with open(os.path.join(temp_dir, "trace.json"), "w") as f:
        json.dump(trace, f)
      shutil.copy(replay_script_src, os.path.join(temp_dir, "replay.py"))
      dockerfile_content = """
FROM python:3.9-slim
RUN apt-get update && apt-get install -y curl
COPY replay.py /replay.py
COPY trace.json /trace.json
ENV PORT=8080
ENV SWEPERF_DISABLE_INTERNAL_SLEEP=1
ENTRYPOINT ["python3", "/replay.py", "/trace.json"]
"""
      with open(os.path.join(temp_dir, "Dockerfile"), "w") as f:
        f.write(dockerfile_content)

      image_name = "test-replay-claim-image:latest"
      subprocess.run(["docker", "build", "-t", image_name, "."], cwd=temp_dir, capture_output=True, check=True)
      run_cmd = ["docker", "run", "-d", "-e", "WAIT_FOR_CLAIM_FILE=/tmp/claim.txt", image_name]
      container_id = subprocess.run(run_cmd, capture_output=True, text=True, check=True).stdout.strip()

      try:
        time.sleep(2)
        logs_before = subprocess.run(["docker", "logs", container_id], capture_output=True, text=True).stdout
        self.assertNotIn("post_claim_execution_123", logs_before)
        self.assertIn("Waiting for claim signal in /tmp/claim.txt...", logs_before)

        subprocess.run(["docker", "exec", container_id, "sh", "-c", "echo 'agents.x-k8s.io/sandbox-id' > /tmp/claim.txt"], check=True)
        time.sleep(3)
        logs_after = subprocess.run(["docker", "logs", container_id], capture_output=True, text=True).stdout
        self.assertIn("Claim signal received!", logs_after)

        # Execute chunk after claim
        post_cmd = [
            "docker", "exec", container_id,
            "curl", "-s", "-X", "POST", "http://localhost:8080/execute",
            "-H", "Content-Type: application/json",
            "-d", '{"start_step": 1, "end_step": 1}'
        ]
        subprocess.run(post_cmd, capture_output=True, text=True, check=True)
        time.sleep(1)
        logs_exec = subprocess.run(["docker", "logs", container_id], capture_output=True, text=True).stdout
        self.assertIn("post_claim_execution_123", logs_exec)
      finally:
        subprocess.run(["docker", "rm", "-f", container_id], capture_output=True)
        subprocess.run(["docker", "rmi", image_name], capture_output=True)

  def test_replay_wait_for_start_port(self) -> None:
    """Tests legacy TCP socket start trigger in Docker container."""
    replay_script_src = os.path.join(repo_root, "generate-images", "replay.py")

    with tempfile.TemporaryDirectory() as temp_dir:
      trace = ["echo 'post_port_execution_123'"]
      with open(os.path.join(temp_dir, "trace.json"), "w") as f:
        json.dump(trace, f)
      shutil.copy(replay_script_src, os.path.join(temp_dir, "replay.py"))
      dockerfile_content = """
FROM python:3.9-slim
RUN apt-get update && apt-get install -y curl
COPY replay.py /replay.py
COPY trace.json /trace.json
ENV LLM_LATENCY_MU=-5
ENV LLM_LATENCY_SIGMA=0.1
ENV SWEPERF_LEGACY_TCP=1
ENTRYPOINT ["python3", "/replay.py", "/trace.json"]
"""
      with open(os.path.join(temp_dir, "Dockerfile"), "w") as f:
        f.write(dockerfile_content)

      image_name = "test-replay-port-image:latest"
      subprocess.run(["docker", "build", "-t", image_name, "."], cwd=temp_dir, capture_output=True, check=True)
      run_cmd = ["docker", "run", "-d", "-e", "WAIT_FOR_START_PORT=8080", image_name]
      container_id = subprocess.run(run_cmd, capture_output=True, text=True, check=True).stdout.strip()

      try:
        time.sleep(2)
        logs_before = subprocess.run(["docker", "logs", container_id], capture_output=True, text=True).stdout
        self.assertNotIn("post_port_execution_123", logs_before)
        self.assertIn("Starting SWE-perf Legacy TCP Socket Listener on port 8080...", logs_before)

        subprocess.run(["docker", "exec", container_id, "curl", "-X", "GET", "http://localhost:8080/start"], check=True)
        time.sleep(3)
        logs_after = subprocess.run(["docker", "logs", container_id], capture_output=True, text=True).stdout
        self.assertIn("Start signal received via TCP port!", logs_after)
        self.assertIn("post_port_execution_123", logs_after)
      finally:
        subprocess.run(["docker", "rm", "-f", container_id], capture_output=True)
        subprocess.run(["docker", "rmi", image_name], capture_output=True)

  def test_replay_script_execution(self) -> None:
    """Tests default trace execution in Docker container via legacy TCP mode."""
    replay_script_src = os.path.join(repo_root, "generate-images", "replay.py")
    self.assertTrue(os.path.exists(replay_script_src))

    with tempfile.TemporaryDirectory() as temp_dir:
      trace = ["echo 'unique_test_string_12345'", "expr 10 + 25", "mkdir my_test_directory", "ls -l"]
      trace_path = os.path.join(temp_dir, "trace.json")
      with open(trace_path, "w") as f:
        json.dump(trace, f)

      shutil.copy(replay_script_src, os.path.join(temp_dir, "replay.py"))
      dockerfile_content = """
FROM python:3.9-slim
RUN apt-get update && apt-get install -y curl
COPY replay.py /replay.py
COPY trace.json /trace.json
ENV LLM_LATENCY_MU=-5
ENV LLM_LATENCY_SIGMA=0.1
ENV SWEPERF_LEGACY_TCP=1
ENTRYPOINT ["python3", "/replay.py", "/trace.json"]
"""
      with open(os.path.join(temp_dir, "Dockerfile"), "w") as f:
        f.write(dockerfile_content)

      image_name = "test-replay-image:latest"
      build_result = subprocess.run(["docker", "build", "-t", image_name, "."], cwd=temp_dir, capture_output=True, text=True)
      self.assertEqual(build_result.returncode, 0, f"Docker build failed:\nSTDOUT:\n{build_result.stdout}\nSTDERR:\n{build_result.stderr}")

      run_cmd = ["docker", "run", "-d", "-e", "WAIT_FOR_START_PORT=8080", image_name]
      container_id = subprocess.run(run_cmd, capture_output=True, text=True, check=True).stdout.strip()

      try:
        time.sleep(2)
        subprocess.run(["docker", "exec", container_id, "curl", "-X", "GET", "http://localhost:8080/start"], check=True)
        time.sleep(3)
        logs = subprocess.run(["docker", "logs", container_id], capture_output=True, text=True).stdout
        self.assertIn("unique_test_string_12345", logs)
        self.assertIn("35", logs)
        self.assertIn("my_test_directory", logs)
      finally:
        subprocess.run(["docker", "rm", "-f", container_id], capture_output=True)
        subprocess.run(["docker", "rmi", image_name], capture_output=True)


if __name__ == "__main__":
  unittest.main(verbosity=2)

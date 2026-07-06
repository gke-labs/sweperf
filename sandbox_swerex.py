import os
import pexpect
import time
from typing import Any, Optional

from swerex.deployment.local import LocalDeployment, LocalDeploymentConfig
from swerex.runtime.local import LocalRuntime, BashSession
from swerex.runtime.abstract import CreateBashSessionRequest, CreateBashSessionResponse

from agent_sandbox_rl.handles import SandboxHandle

class SandboxBashSession(BashSession):
    def __init__(self, request: CreateBashSessionRequest, handle: SandboxHandle, *, logger=None):
        super().__init__(request, logger=logger)
        self.handle = handle

    async def start(self) -> CreateBashSessionResponse:
        """Spawn the session using kubectl exec instead of local bash."""
        namespace = self.handle._cluster.namespace
        pod_name = self.handle.pod_name
        
        # We spawn a kubectl exec process
        cmd = f"kubectl exec -i -n {namespace} {pod_name} -- /usr/bin/env bash"
        
        self._shell = pexpect.spawn(
            cmd,
            encoding="utf-8",
            codec_errors="backslashreplace",
            echo=False,
            # We don't need to pass local environment variables to kubectl, but pexpect requires some
            env=dict(os.environ.copy())
        )
        time.sleep(0.3)
        cmds = []
        if self.request.startup_source:
            cmds += [f"source {path}" for path in self.request.startup_source] + ["sleep 0.3"]
        cmds += [
            f"export PS1='{self._ps1}'",
            "export PS2=''",
            "export PS0=''",
        ]
        cmd_str = " ; ".join(cmds)
        self.shell.sendline(cmd_str)
        self.shell.expect(self._ps1, timeout=self.request.startup_timeout)
        from swerex.runtime.local import _strip_control_chars
        output = _strip_control_chars(self.shell.before)
        return CreateBashSessionResponse(output=output)

class SandboxRuntime(LocalRuntime):
    def __init__(self, handle: SandboxHandle, *, logger=None, **kwargs):
        super().__init__(logger=logger, **kwargs)
        self.handle = handle

    async def create_session(self, request) -> Any:
        from swerex.runtime.abstract import CreateBashSessionRequest
        if isinstance(request, CreateBashSessionRequest):
            session = SandboxBashSession(request, self.handle, logger=self.logger)
            await session.start()
            self._sessions[request.session] = session
            return CreateBashSessionResponse(output="")
        else:
            return await super().create_session(request)
            
    async def execute(self, command) -> Any:
        from swerex.runtime.abstract import CommandResponse
        # SandboxHandle exec doesn't give us exit code easily, but we can do a trick
        # or we can just use kubectl exec locally
        import subprocess
        namespace = self.handle._cluster.namespace
        pod_name = self.handle.pod_name
        
        cmd_str = command.command
        if isinstance(cmd_str, list):
            import shlex
            cmd_str = shlex.join(cmd_str)
            
        full_cmd = ["kubectl", "exec", "-i", "-n", namespace, pod_name, "--", "bash", "-c", cmd_str]
        res = subprocess.run(full_cmd, capture_output=True, text=True)
        return CommandResponse(
            stdout=res.stdout,
            stderr=res.stderr,
            exit_code=res.returncode
        )

    async def read_file(self, request) -> Any:
        from swerex.runtime.abstract import ReadFileResponse
        import subprocess
        namespace = self.handle._cluster.namespace
        pod_name = self.handle.pod_name
        
        full_cmd = ["kubectl", "exec", "-i", "-n", namespace, pod_name, "--", "cat", request.path]
        res = subprocess.run(full_cmd, capture_output=True)
        content = res.stdout.decode('utf-8', errors=request.errors or 'strict')
        return ReadFileResponse(content=content)

    async def write_file(self, request) -> Any:
        from swerex.runtime.abstract import WriteFileResponse
        import subprocess
        import shlex
        namespace = self.handle._cluster.namespace
        pod_name = self.handle.pod_name
        
        # Safe way to write file is to pass via stdin to cat > path
        path_escaped = shlex.quote(request.path)
        full_cmd = ["kubectl", "exec", "-i", "-n", namespace, pod_name, "--", "bash", "-c", f"cat > {path_escaped}"]
        content_bytes = request.content.encode('utf-8')
        subprocess.run(full_cmd, input=content_bytes, check=True)
        return WriteFileResponse()


class SandboxDeploymentConfig(LocalDeploymentConfig):
    pass

class SandboxDeployment(LocalDeployment):
    def __init__(self, handle: SandboxHandle, *, logger=None, **kwargs):
        super().__init__(logger=logger, **kwargs)
        self.handle = handle
        self._runtime: Optional[SandboxRuntime] = None

    async def start(self):
        """Starts the runtime."""
        self._runtime = SandboxRuntime(handle=self.handle, logger=self.logger)


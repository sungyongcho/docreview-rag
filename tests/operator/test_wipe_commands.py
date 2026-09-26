"""Reset command execution pinned to the verified local Docker endpoint."""

import asyncio

from app.operator.wipe_commands import WipeCommandRunner


def test_docker_commands_pin_endpoint_and_remove_context_overrides(tmp_path, monkeypatch):
    """A later context change cannot redirect commands away from the preview's local daemon."""
    commands = WipeCommandRunner(tmp_path)
    commands.docker_host = "unix:///tmp/verified-test.sock"
    monkeypatch.setenv("DOCKER_CONTEXT", "remote")
    monkeypatch.setenv("DOCKER_HOST", "ssh://remote")
    monkeypatch.setenv("DOCKER_TLS_VERIFY", "1")
    captured = {}

    class Process:
        """Record one command invocation without launching Docker or any child process."""

        returncode = 0

        async def communicate(self, _input):
            """Return a successful read-only command response."""
            return b"test-daemon", b""

    async def spawn(*args, **kwargs):
        """Capture argv and environment at the real subprocess boundary."""
        captured.update(argv=args, environment=kwargs["env"])
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    assert asyncio.run(commands.run("docker", "info")) == "test-daemon"
    assert captured["argv"] == ("docker", "--host", "unix:///tmp/verified-test.sock", "info")
    assert (
        not {"DOCKER_CONTEXT", "DOCKER_HOST", "DOCKER_TLS_VERIFY"} & captured["environment"].keys()
    )

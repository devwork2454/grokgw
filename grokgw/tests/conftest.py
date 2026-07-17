import asyncio
from typing import Iterable


class MockProc:
    """Mock asyncio subprocess for testing grok_runner."""

    def __init__(self, stdout_lines: list[bytes], returncode: int = 0, stderr: bytes = b""):
        self._stdout_lines = stdout_lines
        self._final_returncode = returncode
        self._returncode: int | None = None
        self._stderr = stderr
        self._killed = False
        self.pid = 4242  # fake pgid leader; killpg falls back to kill()

    @property
    def returncode(self) -> int | None:
        return self._returncode

    @property
    def stdout(self):
        proc = self

        async def _aiter():
            for line in proc._stdout_lines:
                yield line
            if proc._returncode is None and not proc._killed:
                proc._returncode = proc._final_returncode

        return _aiter()

    @property
    def stderr(self):
        return self._stderr

    async def wait(self) -> int:
        if self._returncode is None:
            self._returncode = -9 if self._killed else self._final_returncode
        return self._returncode

    def kill(self):
        self._killed = True
        self._returncode = -9

    async def communicate(self):
        out = b"".join(self._stdout_lines)
        if not self._killed:
            self._returncode = self._final_returncode
        return out, self._stderr

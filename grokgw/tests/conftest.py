import asyncio
from typing import Iterable


class MockProc:
    """Mock asyncio subprocess for testing grok_runner."""
    def __init__(self, stdout_lines: list[bytes], returncode: int = 0, stderr: bytes = b""):
        self._stdout_lines = stdout_lines
        self._returncode = returncode
        self._stderr = stderr
        self._killed = False

    @property
    def returncode(self) -> int:
        return self._returncode

    @property
    def stdout(self):
        async def _aiter():
            for line in self._stdout_lines:
                yield line
        return _aiter()

    @property
    def stderr(self):
        return self._stderr

    async def wait(self) -> int:
        return self._returncode

    def kill(self):
        self._killed = True

    async def communicate(self):
        out = b"".join(self._stdout_lines)
        return out, self._stderr

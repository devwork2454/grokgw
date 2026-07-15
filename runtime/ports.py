from __future__ import annotations

import socket
from typing import Optional

_PORT_MIN = 9600
_PORT_MAX = 9699
_in_use: set[int] = set()


def _free(port: int) -> bool:
    # Do not set SO_REUSEADDR — that can report free while Chrome still holds the port.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def acquire_port() -> int:
    for p in range(_PORT_MIN, _PORT_MAX + 1):
        if p in _in_use:
            continue
        if _free(p):
            _in_use.add(p)
            return p
    raise RuntimeError("no free debugging port in 9600-9699")


def release_port(port: int) -> None:
    _in_use.discard(port)

"""Windows-specific compatibility fixes."""

from __future__ import annotations

import socket
import sys

_applied = False


def _relaxed_socketpair(
    family: int | None = None,
    type: int = socket.SOCK_STREAM,
    proto: int = 0,
) -> tuple[socket.socket, socket.socket]:
    if family is None:
        family = socket.AF_INET
    host = "127.0.0.1" if family == socket.AF_INET else "::1"
    lsock = socket.socket(family, type, proto)
    try:
        lsock.bind((host, 0))
        lsock.listen(1)
        addr, port = lsock.getsockname()[:2]
        csock = socket.socket(family, type, proto)
        try:
            csock.setblocking(False)
            try:
                csock.connect((addr, port))
            except (BlockingIOError, InterruptedError):
                pass
            csock.setblocking(True)
            ssock, _ = lsock.accept()
        except Exception:
            csock.close()
            raise
    finally:
        lsock.close()
    return ssock, csock


def apply_windows_compat() -> None:
    global _applied
    if _applied or sys.platform != "win32":
        return
    _applied = True

    original = socket.socketpair

    def socketpair(
        family: int | None = None,
        type: int = socket.SOCK_STREAM,
        proto: int = 0,
    ) -> tuple[socket.socket, socket.socket]:
        if family is None:
            family = socket.AF_INET
        try:
            return original(family=family, type=type, proto=proto)
        except ConnectionError as exc:
            if "Unexpected peer connection" not in str(exc):
                raise
            return _relaxed_socketpair(family=family, type=type, proto=proto)

    socket.socketpair = socketpair  # type: ignore[misc, assignment]

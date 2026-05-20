"""Patch for upstream CPython defect in ProactorEventLoop accept handling.

CPython's ``asyncio.proactor_events.BaseProactorEventLoop._start_serving``
closes the *listening* socket on **any** ``OSError`` raised by the accept
future, then never re-schedules ``accept()``. Source (Python 3.13.x):

    except OSError as exc:
        if sock.fileno() != -1:
            self.call_exception_handler({...})
            sock.close()                # <-- kills the listener
        ...

This is asymmetric with the Linux ``SelectorEventLoop._accept_connection``,
which only tears down on resource-exhaustion errnos
(``EMFILE``/``ENFILE``/``ENOBUFS``/``ENOMEM``) and otherwise lets the
exception propagate to the loop's exception handler — the listener stays
alive.

Effect on Pallium: a single misbehaving client (e.g. an aborted half-open
TCP handshake producing ``WinError 64`` — ``ERROR_NETNAME_DELETED``)
permanently closes the listening socket while the Python process keeps
running. New connection attempts get ECONNREFUSED until the supervisor
TCP probe detects death and restarts the API.

This module installs a replacement ``_start_serving`` that distinguishes
transient per-connection errors (the AcceptEx future failed for a peer
that aborted before the handshake completed — ``sock`` is fine, just
re-schedule) from fatal listener errors (``sock.fileno() == -1`` or
resource exhaustion). The patch is no-op on non-Windows platforms and is
idempotent.
"""

from __future__ import annotations

import errno
import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)

_PATCH_APPLIED_ATTR = "_pallium_accept_patch_applied"

# Resource-exhaustion errnos that should still tear down the accept loop
# the way upstream does — running out of fds is fatal until something
# releases pressure. Mirrors selector_events._accept_connection.
_FATAL_ERRNOS = frozenset({errno.EMFILE, errno.ENFILE, errno.ENOBUFS, errno.ENOMEM})


def apply_patch() -> bool:
    """Apply the ProactorEventLoop accept patch. Returns True if installed.

    Idempotent: safe to call multiple times.
    """
    if sys.platform != "win32":
        return False
    try:
        from asyncio import exceptions, proactor_events, trsock
    except ImportError:  # pragma: no cover — non-CPython runtime
        return False

    base = proactor_events.BaseProactorEventLoop
    if getattr(base, _PATCH_APPLIED_ATTR, False):
        return False

    def _start_serving(  # type: ignore[no-redef]
        self: Any,
        protocol_factory: Any,
        sock: Any,
        sslcontext: Any = None,
        server: Any = None,
        backlog: int = 100,
        ssl_handshake_timeout: Any = None,
        ssl_shutdown_timeout: Any = None,
    ) -> None:
        def loop(f: Any = None) -> None:
            try:
                if f is not None:
                    conn, addr = f.result()
                    if self._debug:
                        logger.debug(
                            "%r got a new connection from %r: %r", server, addr, conn
                        )
                    protocol = protocol_factory()
                    if sslcontext is not None:
                        self._make_ssl_transport(
                            conn,
                            protocol,
                            sslcontext,
                            server_side=True,
                            extra={"peername": addr},
                            server=server,
                            ssl_handshake_timeout=ssl_handshake_timeout,
                            ssl_shutdown_timeout=ssl_shutdown_timeout,
                        )
                    else:
                        self._make_socket_transport(
                            conn,
                            protocol,
                            extra={"peername": addr},
                            server=server,
                        )
                if self.is_closed():
                    return
                f = self._proactor.accept(sock)
            except OSError as exc:
                if sock.fileno() == -1:
                    # Listening socket itself is gone (closed by
                    # _stop_serving or external teardown). Nothing to do.
                    return
                if exc.errno in _FATAL_ERRNOS:
                    # Resource exhaustion — match upstream behavior:
                    # report, close the listener, and let the supervisor
                    # restart us. There's no graceful recovery from EMFILE
                    # at this layer.
                    self.call_exception_handler({
                        "message": "Accept failed (resource exhaustion)",
                        "exception": exc,
                        "socket": trsock.TransportSocket(sock),
                    })
                    sock.close()
                    return
                # Transient per-connection failure — the failed peer's
                # handshake aborted (typical: WinError 64
                # ERROR_NETNAME_DELETED, WSAECONNRESET, WSAECONNABORTED).
                # The LISTENING socket is fine; just log and re-schedule.
                self.call_exception_handler({
                    "message": (
                        "Accept failed for a single connection "
                        "(transient, listener kept alive)"
                    ),
                    "exception": exc,
                    "socket": trsock.TransportSocket(sock),
                })
                try:
                    f = self._proactor.accept(sock)
                except OSError as reschedule_exc:
                    # If even rescheduling fails, the listener really is
                    # broken; fall back to upstream behavior.
                    self.call_exception_handler({
                        "message": "Accept reschedule failed; closing listener",
                        "exception": reschedule_exc,
                        "socket": trsock.TransportSocket(sock),
                    })
                    sock.close()
                    return
                self._accept_futures[sock.fileno()] = f
                f.add_done_callback(loop)
                return
            except exceptions.CancelledError:
                sock.close()
            else:
                self._accept_futures[sock.fileno()] = f
                f.add_done_callback(loop)

        self.call_soon(loop)

    base._start_serving = _start_serving  # type: ignore[method-assign]
    setattr(base, _PATCH_APPLIED_ATTR, True)
    logger.info(
        "applied ProactorEventLoop accept patch "
        "(transient per-connection OSError no longer closes listener)"
    )
    return True

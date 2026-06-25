"""Shared resilient HTTP client for all outbound API calls (Claude, Soniox, Bitrix, etc.).

A single requests.Session with an enlarged connection pool and a Linux TCP_USER_TIMEOUT
adapter that kills dead connections the kernel would otherwise keep alive behind keep-alive
ACKs. Imported wherever the app talks to an external service.
"""
import os
import socket

import requests
from requests.adapters import HTTPAdapter


# Linux TCP_USER_TIMEOUT (kernel-level dead-connection killer). Without this, requests' read
# timeout can be defeated by TCP keep-alive ACKs from the AWS us-east-1 ELB even when no
# response data is flowing — a connection looks "alive" while delivering zero progress.
# Setting this socket option makes the kernel abort the connection if a sent segment hasn't
# been ACKed within the given milliseconds, regardless of keep-alives.
_TCP_USER_TIMEOUT = 18  # SOL constant on Linux
_TCP_USER_TIMEOUT_MS = int(os.getenv('TCP_USER_TIMEOUT_MS', '30000'))


class _DeadConnectionGuardAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        # Only Linux supports TCP_USER_TIMEOUT — silently no-op elsewhere.
        try:
            kwargs['socket_options'] = [
                (socket.IPPROTO_TCP, _TCP_USER_TIMEOUT, _TCP_USER_TIMEOUT_MS),
            ]
        except Exception:
            pass
        return super().init_poolmanager(*args, **kwargs)


def _build_resilient_session() -> requests.Session:
    s = requests.Session()
    # Bigger pool: parallel STT submits + Claude calls + Bitrix calls share this session;
    # a small default (10/10) becomes a bottleneck under load.
    adapter = _DeadConnectionGuardAdapter(pool_connections=32, pool_maxsize=64)
    s.mount('https://', adapter)
    s.mount('http://', adapter)
    return s


HTTP_SESSION = _build_resilient_session()

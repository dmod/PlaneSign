"""Third-party connectivity: the OFFLINE_MODE setting and how unreachable services are recognized.

Offline mode raises the same kind of connection error a real outage produces, at the point where a
request would be sent, so both take one code path and the sign shows the same thing either way.
"""

import errno
import logging
import os
import socket
import tempfile
import time
from urllib.error import URLError

import requests
import shared_config
import websocket

UNREACHABLE_ERRNOS = {errno.ECONNREFUSED, errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ENETDOWN, errno.EHOSTDOWN, errno.ETIMEDOUT}


class ServiceUnreachable(requests.ConnectionError):
    """A third-party service could not be reached."""


class OfflineModeError(ServiceUnreachable):
    """Raised instead of contacting a third-party service while OFFLINE_MODE is on."""


def offline_mode(conf=None):
    conf = shared_config.CONF if conf is None else conf
    try:
        return conf is not None and str(conf.get("OFFLINE_MODE", "false")).lower() == "true"
    except (OSError, EOFError):
        # The config manager has already exited during shutdown.
        return False


_announced = set()


def require_online(service):
    """Raise OfflineModeError instead of contacting `service` while offline mode is on."""
    if not offline_mode():
        if service in _announced:
            _announced.discard(service)
            logging.info("Offline mode off: contacting %s again", service)
        return
    if service not in _announced:
        _announced.add(service)
        logging.info("Offline mode: not contacting %s", service)
    raise OfflineModeError(f"offline mode: {service} is disabled")


def is_offline_error(error):
    """True when `error` means a service could not be reached at all (offline mode or no connectivity)."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, (requests.ConnectionError, websocket.WebSocketAddressException, websocket.WebSocketTimeoutException, socket.gaierror, ConnectionRefusedError, TimeoutError)):
            return True
        # These libraries already classified the failure (a read timeout or dropped stream reached the server).
        if isinstance(error, (requests.RequestException, websocket.WebSocketException)):
            return False
        if isinstance(error, OSError) and error.errno in UNREACHABLE_ERRNOS:
            return True
        if isinstance(error, URLError) and isinstance(error.reason, BaseException):
            error = error.reason
            continue
        # Only OS-level wrappers (such as skyfield's download IOError) carry a connection failure as their cause;
        # any other exception raised while handling one is a separate bug.
        if not isinstance(error, OSError):
            return False
        error = error.__cause__ or error.__context__
    return False


def failure_reason(error):
    """The innermost cause of a connection failure; it names the host without the request URL, which can carry API keys."""
    while True:
        inner = getattr(error, "reason", None)
        if not isinstance(inner, BaseException) and error.args and isinstance(error.args[0], BaseException):
            inner = error.args[0]
        if not isinstance(inner, BaseException) or inner is error:
            return str(error).split(">: ", 1)[-1]
        error = inner


def log_unreachable(service, error):
    """Log an offline failure on one line; offline mode has already been announced once by require_online."""
    if not isinstance(error, OfflineModeError):
        logging.warning("%s unreachable: %s", service, failure_reason(error))


DEFAULT_TIMEOUT = (5, 20)


def get(service, url, *, session=None, **kwargs):
    """GET from a third-party `service`, honoring offline mode, with a (connect, read) timeout unless one is given.

    Libraries that make their own requests (Finnhub's client, skyfield's Loader, websocket-client, favicon)
    still need an explicit require_online() before they are called.
    """
    require_online(service)
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    return (session or requests).get(url, **kwargs)


def download(service, url, path, **kwargs):
    """Stream `url` into the file at `path`, replacing it only once the whole download has arrived.

    Raises requests.HTTPError for an error status, and InterruptedError when shutdown begins mid-download.
    """
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    temporary = None
    try:
        with get(service, url, stream=True, **kwargs) as response:
            response.raise_for_status()
            logging.info("Downloading %s from %s", os.path.basename(path), service)
            with tempfile.NamedTemporaryFile(dir=directory, prefix=".download-", delete=False) as destination:
                temporary = destination.name
                for chunk in response.iter_content(65536):
                    if shared_config.shutdown_in_progress():
                        raise InterruptedError(f"{service} download interrupted by shutdown")
                    destination.write(chunk)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def retry_delay(failures, base, cap, max_doublings=5):
    """Capped exponential backoff for the nth consecutive failure: base, 2x base, 4x base, ... at most cap."""
    return min(cap, base * 2 ** min(failures - 1, max_doublings))


class OfflineToggle:
    """Notices OFFLINE_MODE changing, so a worker can retry right away instead of waiting out a backoff or TTL."""

    def __init__(self):
        self.state = offline_mode()

    def changed(self):
        current = offline_mode()
        if current == self.state:
            return False
        self.state = current
        return True


def wait(seconds):
    """Wait up to `seconds`, returning early when offline mode is toggled. Returns True once shutdown is requested."""
    toggle = OfflineToggle()
    deadline = time.monotonic() + seconds
    while (remaining := deadline - time.monotonic()) > 0:
        if shared_config.shared_shutdown_event.wait(min(1, remaining)):
            return True
        if toggle.changed():
            return False
    return shared_config.shutdown_in_progress()

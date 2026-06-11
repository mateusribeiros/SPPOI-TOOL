#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
import threading
import webbrowser
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _is_truthy(value, default=False):
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _runserver_addrport():
    if len(sys.argv) < 2 or sys.argv[1] != "runserver":
        return ""
    for arg in sys.argv[2:]:
        if not arg.startswith("-"):
            return arg.strip()
    return ""


def _runserver_url():
    host = "127.0.0.1"
    port = "8000"
    addrport = _runserver_addrport()

    if addrport:
        if addrport.isdigit():
            port = addrport
        elif ":" in addrport:
            possible_host, possible_port = addrport.rsplit(":", 1)
            if possible_port.isdigit():
                host = possible_host or host
                port = possible_port
            else:
                host = addrport
        else:
            host = addrport

    host = host.strip("[]")
    if host in {"0.0.0.0", "::", ""}:
        host = "127.0.0.1"
    elif ":" in host:
        host = "localhost"

    return f"http://{host}:{port}"


def _schedule_browser_open():
    if len(sys.argv) < 2 or sys.argv[1] != "runserver":
        return
    if not _is_truthy(os.getenv("SPPOI_AUTO_OPEN_BROWSER"), default=True):
        return

    is_no_reload = "--noreload" in sys.argv
    is_reloader_child = os.environ.get("RUN_MAIN") == "true"

    # With Django autoreload enabled, schedule the browser open only from the
    # parent process so a code change does not keep opening new tabs.
    if is_reloader_child and not is_no_reload:
        return

    url = _runserver_url()

    def _open_browser():
        try:
            webbrowser.open(url, new=2)
        except Exception:
            pass

    timer = threading.Timer(1.5, _open_browser)
    timer.daemon = True
    timer.start()


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
    _schedule_browser_open()
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and available on your PYTHONPATH environment variable?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()

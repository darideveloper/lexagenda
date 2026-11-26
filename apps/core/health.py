"""Dead-man pings for the timers (PLAN §14): a timer that stops pinging is an alarm.

Each timer has one check in healthchecks.io, configured by env:
`HEALTHCHECK_WORK_URL`, `HEALTHCHECK_SWEEP_URL`, `HEALTHCHECK_BRIEF_URL`.
An unset URL is a silent no-op, and a ping that fails never breaks the timer it guards.
"""

import os
import urllib.request

TIMEOUT_SECONDS = 5


def url_for(name):
    return os.environ.get(f"HEALTHCHECK_{name.upper()}_URL", "")


def ping(name, ok=True):
    """Signal one run of `name`; False when unset or unreachable."""
    url = url_for(name)
    if not url:
        return False
    target = url if ok else url.rstrip("/") + "/fail"
    try:
        urllib.request.urlopen(target, timeout=TIMEOUT_SECONDS).close()
        return True
    except Exception:  # ponytail: the ping is telemetry; the timer must still run
        return False

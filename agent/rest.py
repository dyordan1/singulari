#!/usr/bin/env python3
"""How long the loop waits before the next wake. Prints seconds.

Default: the interval given as argv[1]. If the agent's `rest` tool left a
number of minutes in `status/rest`, the file is consumed and the request
honoured within the limit written here: at most an hour at a time, and at most
an hour of rest in any three. The rationale baked into
that number: the agent thinks roughly ten times faster than a person, and people
rarely sleep more than ten hours in twenty-four. Nothing else enforces it.

Rests taken are appended to `status/rest.log` (ISO start, seconds) — that log is
the budget.
"""

import os
import sys
import time
from datetime import datetime

from status import STATUS_DIR, write_now

REST_FILE = os.path.join(STATUS_DIR, "rest")
REST_LOG = os.path.join(STATUS_DIR, "rest.log")
MAX_ONE_REST = 3600
WINDOW = 3 * 3600
MAX_IN_WINDOW = 3600


def requested_seconds() -> float:
    with open(REST_FILE, encoding="utf-8") as f:
        text = f.read().strip()
    os.remove(REST_FILE)
    return float(text) * 60


def rests_in_window(now: float) -> list[tuple[float, float]]:
    """(start, seconds) of each logged rest that still counts at `now`."""
    if not os.path.exists(REST_LOG):
        return []
    rests = []
    with open(REST_LOG, encoding="utf-8") as f:
        for line in f:
            try:
                start, secs = line.split("\t")
                started = datetime.fromisoformat(start).timestamp()
            except ValueError:
                continue
            if now - started < WINDOW:
                rests.append((started, float(secs)))
    return rests


def allowed(wanted: float, now: float) -> float:
    """Seconds of a `wanted`-second rest the limits allow at `now`."""
    return max(0.0, min(wanted, MAX_ONE_REST, MAX_IN_WINDOW - sum(s for _, s in rests_in_window(now))))


def main():
    interval = int(sys.argv[1])
    now = time.time()
    sleep_s = interval
    if os.path.exists(REST_FILE):
        try:
            wanted = requested_seconds()
        except (ValueError, OSError) as e:
            print(f"rest request ignored: {e}", file=sys.stderr)
            wanted = 0
        granted = allowed(wanted, now)
        if granted > interval:
            sleep_s = int(granted)
            os.makedirs(STATUS_DIR, exist_ok=True)
            with open(REST_LOG, "a", encoding="utf-8") as f:
                f.write(f"{datetime.fromtimestamp(now).astimezone().isoformat(timespec='seconds')}\t{sleep_s}\n")
    until = time.strftime("until %H:%M", time.localtime(now + sleep_s))
    write_now("resting on purpose" if sleep_s > interval else "resting", until)
    print(sleep_s)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""How long the loop waits before the next wake. Prints seconds.

Default: the interval given as argv[1]. If the agent left a request in
`status/rest` (a number of minutes, or `until <ISO-8601 time>`), the file is
consumed and the request honoured within the limit written here: at most an hour
at a time, and at most an hour of rest in any three. The rationale baked into
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
    if text.lower().startswith("until"):
        when = datetime.fromisoformat(text[5:].strip())
        if when.tzinfo is None:
            when = when.astimezone()
        return when.timestamp() - time.time()
    return float(text.rstrip("m").strip()) * 60


def used_in_window(now: float) -> float:
    if not os.path.exists(REST_LOG):
        return 0.0
    used = 0.0
    with open(REST_LOG, encoding="utf-8") as f:
        for line in f:
            try:
                start, secs = line.split("\t")
                started = datetime.fromisoformat(start).timestamp()
            except ValueError:
                continue
            if now - started < WINDOW:
                used += float(secs)
    return used


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
        allowed = min(wanted, MAX_ONE_REST, MAX_IN_WINDOW - used_in_window(now))
        if allowed > interval:
            sleep_s = int(allowed)
            os.makedirs(STATUS_DIR, exist_ok=True)
            with open(REST_LOG, "a", encoding="utf-8") as f:
                f.write(f"{datetime.fromtimestamp(now).astimezone().isoformat(timespec='seconds')}\t{sleep_s}\n")
    until = time.strftime("until %H:%M", time.localtime(now + sleep_s))
    write_now("resting on purpose" if sleep_s > interval else "resting", until)
    print(sleep_s)


if __name__ == "__main__":
    main()

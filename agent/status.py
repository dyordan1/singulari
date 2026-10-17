"""The one line the website shows about what the agent is doing right now.

`status/now.json` is written by the loop (poke and rest) as a mechanical
description of the current step. `status/now.txt`, if present, is the agent's
own label and the site shows it instead. Both live under SINGULARI_HOME/status,
outside git.
"""

import json
import os
import time

HOME = os.environ.get("SINGULARI_HOME", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATUS_DIR = os.path.join(HOME, "status")


def write_now(state: str, detail: str = "") -> None:
    os.makedirs(STATUS_DIR, exist_ok=True)
    payload = {"state": state, "detail": detail[:200], "at": time.time()}
    tmp = os.path.join(STATUS_DIR, ".now.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, os.path.join(STATUS_DIR, "now.json"))

"""The agent's seven tools.

Each is a plain function; agent/brain.py builds its tool schema from the
signature and the tool's entry in prompt/tools.toml, which also holds every
line a tool answers with, and runs it in-process, as root. This is the entire
built-in surface the agent is handed. Everything else it builds from these.
"""

from prompts import fill, lines

T = lines("tools.toml")


def shell(command: str) -> str:
    import subprocess

    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=600,
    )
    out = result.stdout or ""
    err = result.stderr or ""
    body = out + ((T["shell"]["stderr"] + err) if err else "")
    if len(body) > 20000:
        body = body[:20000] + T["shell"]["truncated"]
    return fill(T["shell"]["result"], code=result.returncode, output=body)


def read_file(path: str, start: str = "1") -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:  # noqa: BLE001
        return fill(T["read_file"]["error"], path=path, error=e)
    first = max(int(start), 1) - 1
    out, n = [], 0
    for i, line in enumerate(lines[first:], first + 1):
        if n + len(line) > 20000 and out:
            return "".join(out) + fill(T["read_file"]["stopped"], line=i, total=len(lines))
        out.append(line)
        n += len(line)
    return "".join(out)


def edit_file(path: str, old: str, new: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = f.read()
    except Exception as e:  # noqa: BLE001
        return fill(T["edit_file"]["error"], path=path, error=e)
    count = data.count(old)
    if count != 1:
        return fill(T["edit_file"]["not_once"], count=count, path=path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(data.replace(old, new, 1))
    return fill(T["edit_file"]["edited"], path=path, old=len(old), new=len(new))


def write_file(path: str, content: str) -> str:
    import os

    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:  # noqa: BLE001
        return fill(T["write_file"]["error"], path=path, error=e)
    return fill(T["write_file"]["wrote"], bytes=len(content), path=path)


def web_fetch(url: str) -> str:
    import subprocess
    import sys

    script = (
        "import sys\n"
        "from playwright.sync_api import sync_playwright\n"
        "with sync_playwright() as p:\n"
        "    b = p.chromium.launch(headless=True)\n"
        "    pg = b.new_page()\n"
        "    pg.goto(sys.argv[1], wait_until='load', timeout=30000)\n"
        "    pg.wait_for_timeout(1500)\n"
        "    print(pg.evaluate('document.body ? document.body.innerText : \"\"'))\n"
        "    b.close()\n"
    )
    try:
        proc = subprocess.run([sys.executable, "-c", script, url], capture_output=True, timeout=90)
    except Exception as e:  # noqa: BLE001
        return fill(T["web_fetch"]["error"], url=url, error=e)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip().splitlines()
        return fill(T["web_fetch"]["error"], url=url, error=err[-1] if err else "unknown error")
    text = proc.stdout.decode("utf-8", errors="replace").strip()
    if len(text) > 20000:
        text = text[:20000] + T["web_fetch"]["truncated"]
    return text


def rest(minutes: str) -> str:
    import os

    home = os.environ.get("SINGULARI_HOME", "/opt/singulari")
    try:
        n = int(float(minutes))
    except ValueError:
        return fill(T["rest"]["not_a_number"], minutes=minutes)
    try:
        os.makedirs(os.path.join(home, "status"), exist_ok=True)
        with open(os.path.join(home, "status", "rest"), "w", encoding="utf-8") as f:
            f.write(f"{n}\n")
    except Exception as e:  # noqa: BLE001
        return fill(T["rest"]["error"], error=e)
    return fill(T["rest"]["asked"], minutes=n)


def screenshot(url: str) -> str:
    import base64
    import json
    import os
    import subprocess
    import sys
    import time

    script = (
        "import sys\n"
        "from playwright.sync_api import sync_playwright\n"
        "with sync_playwright() as p:\n"
        "    b = p.chromium.launch(headless=True)\n"
        "    pg = b.new_context(viewport={'width': 1280, 'height': 900}).new_page()\n"
        "    pg.goto(sys.argv[1], wait_until='networkidle', timeout=20000)\n"
        "    png = pg.screenshot(full_page=False)\n"
        "    b.close()\n"
        "sys.stdout.buffer.write(png)\n"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script, url],
            capture_output=True,
            timeout=90,
        )
    except Exception as e:  # noqa: BLE001
        return fill(T["screenshot"]["error"], url=url, error=e)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip().splitlines()
        return fill(T["screenshot"]["error"], url=url, error=err[-1] if err else "unknown error")
    png = proc.stdout
    home = os.environ.get("SINGULARI_HOME", "/opt/singulari")
    pending = os.path.join(home, "agent", ".pending_vision.json")
    try:
        os.makedirs(os.path.dirname(pending), exist_ok=True)
        with open(pending, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "url": url,
                    "media_type": "image/png",
                    "data": base64.b64encode(png).decode("ascii"),
                    "ts": time.time(),
                },
                f,
            )
    except Exception as e:  # noqa: BLE001
        return fill(T["screenshot"]["not_held"], url=url, error=e)
    return fill(T["screenshot"]["captured"], url=url, bytes=len(png))

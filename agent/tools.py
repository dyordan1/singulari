"""The agent's seven tools.

Each is a plain function; agent/brain.py derives its tool schema from the
signature and docstring and runs it in-process, as root. This is the entire
built-in surface the agent is handed. Everything else it builds from these.
"""


def shell(command: str) -> str:
    """Run a shell command on this machine as the current user (root) and
    return its combined output.

    Args:
        command: The shell command to execute.

    Returns:
        The command's stdout and stderr, prefixed with the exit code.
    """
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
    body = out + (("\n[stderr]\n" + err) if err else "")
    if len(body) > 20000:
        body = body[:20000] + "\n[...truncated...]"
    return f"[exit {result.returncode}]\n{body}"


def read_file(path: str, start: str = "1") -> str:
    """Read a file from disk and return its contents from a given line. A long
    file comes back in pieces: the result says where it stopped, and you call
    again with that line as `start`.

    Args:
        path: Absolute or relative path to the file.
        start: The line number to begin at (1 is the first line).

    Returns:
        The file contents from that line, or an error line if it cannot be read.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:  # noqa: BLE001
        return f"[error reading {path}: {e}]"
    first = max(int(start), 1) - 1
    out, n = [], 0
    for i, line in enumerate(lines[first:], first + 1):
        if n + len(line) > 20000 and out:
            return "".join(out) + f"\n[...stopped before line {i} of {len(lines)}; call again with start={i}]"
        out.append(line)
        n += len(line)
    return "".join(out)


def edit_file(path: str, old: str, new: str) -> str:
    """Replace one exact passage of a file with another. `old` must appear in
    the file exactly once, whitespace included; include enough surrounding
    lines to make it unique. For a new file or a full rewrite use write_file.

    Args:
        path: Absolute or relative path to the file.
        old: The exact text to replace.
        new: The text to put in its place.

    Returns:
        A short confirmation line, or an error line saying why nothing changed.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = f.read()
    except Exception as e:  # noqa: BLE001
        return f"[error reading {path}: {e}]"
    count = data.count(old)
    if count != 1:
        return f"[nothing changed: `old` appears {count} times in {path}, needs to be exactly 1]"
    with open(path, "w", encoding="utf-8") as f:
        f.write(data.replace(old, new, 1))
    return f"[edited {path}: {len(old)} chars -> {len(new)}]"


def write_file(path: str, content: str) -> str:
    """Write content to a file on disk, creating parent directories and
    overwriting any existing file.

    Args:
        path: Absolute or relative path to the file.
        content: The full contents to write.

    Returns:
        A short confirmation line, or an error line.
    """
    import os

    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:  # noqa: BLE001
        return f"[error writing {path}: {e}]"
    return f"[wrote {len(content)} bytes to {path}]"


def web_fetch(url: str) -> str:
    """Open a URL in a browser and return the page's text as a reader sees it,
    scripts having run. Works for pages built in the browser, your own site
    included, and for plain text or JSON.

    Args:
        url: The URL to open.

    Returns:
        The rendered page text, or an error line.
    """
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
        return f"[error fetching {url}: {e}]"
    if proc.returncode != 0:
        return f"[error fetching {url}: {proc.stderr.decode('utf-8', errors='replace')[-800:]}]"
    text = proc.stdout.decode("utf-8", errors="replace").strip()
    if len(text) > 20000:
        text = text[:20000] + " [...truncated...]"
    return text


def rest(minutes: str) -> str:
    """Ask the loop to wait before waking you again, instead of its usual
    interval. Takes effect when this wake ends. The loop allows up to an hour
    at a time and at most an hour of rest in any three; a longer ask is cut to
    what is allowed.

    Args:
        minutes: How many minutes to rest.

    Returns:
        A confirmation line, or an error line.
    """
    import os

    home = os.environ.get("SINGULARI_HOME", "/opt/singulari")
    try:
        n = int(float(minutes))
    except ValueError:
        return f"[not a number of minutes: {minutes!r}]"
    try:
        os.makedirs(os.path.join(home, "status"), exist_ok=True)
        with open(os.path.join(home, "status", "rest"), "w", encoding="utf-8") as f:
            f.write(f"{n}\n")
    except Exception as e:  # noqa: BLE001
        return f"[could not ask to rest: {e}]"
    return f"[asked to rest {n} minutes after this wake; the loop allows up to 60 at a time, 60 in any 3 hours]"


def screenshot(url: str) -> str:
    """Capture a web page as an image so you can see it.

    Tool results are text, so the image is not in this one; it is placed in
    front of you in the message right after it. Use it on your own site
    (http://localhost:8080) or anywhere on the web.

    Args:
        url: The page to capture.

    Returns:
        A short confirmation that the capture is waiting, or an error line.
    """
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
        return f"[could not capture {url}: {e}]"
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace")[-800:]
        return f"[could not capture {url}: {err}]"
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
        return f"[captured {url} but could not hold the image: {e}]"
    return f"[captured {url} ({len(png)} bytes); it is in front of you now]"

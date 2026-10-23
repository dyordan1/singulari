"""The agent's five tools.

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


def read_file(path: str) -> str:
    """Read a file from disk and return its contents.

    Args:
        path: Absolute or relative path to the file.

    Returns:
        The file contents, or an error line if it cannot be read.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = f.read()
    except Exception as e:  # noqa: BLE001
        return f"[error reading {path}: {e}]"
    if len(data) > 20000:
        data = data[:20000] + "\n[...truncated...]"
    return data


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

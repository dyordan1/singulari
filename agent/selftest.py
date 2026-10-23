#!/usr/bin/env python3
"""Exercise the agent's tools directly, without a model.

Run this on any machine to confirm the five tools actually work — after editing
them, after a fresh box, or just to see them move. It proves the tools, not the
agent: the model's own behaviour is out of scope here.

    python3 agent/selftest.py [url-to-screenshot]

Network- and browser-dependent checks SKIP (not FAIL) when the machine can't do
them, so this is safe to run offline.
"""

import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def load():
    spec = importlib.util.spec_from_file_location("tools", os.path.join(HERE, "tools.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    t = load()
    results = []

    def check(name, ok, note=""):
        results.append((name, ok))
        mark = {True: "PASS", False: "FAIL", None: "SKIP"}[ok]
        print(f"[{mark}] {name}" + (f" — {note}" if note else ""))

    # shell
    out = t.shell("echo singulari && exit 0")
    check("shell runs + captures output", out.startswith("[exit 0]") and "singulari" in out)
    check("shell reports nonzero exit", t.shell("exit 3").startswith("[exit 3]"))

    # write_file / read_file roundtrip
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "sub", "note.txt")
        w = t.write_file(p, "hello\nworld")
        check("write_file creates dirs + writes", w.startswith("[wrote") and os.path.exists(p))
        check("read_file returns contents", t.read_file(p) == "hello\nworld")
        check("read_file from a line", t.read_file(p, "2") == "world")
        check("edit_file replaces a unique passage", t.edit_file(p, "world", "there").startswith("[edited") and t.read_file(p) == "hello\nthere")
        check("edit_file refuses an ambiguous passage", t.edit_file(p, "e", "x").startswith("[nothing changed") and t.read_file(p) == "hello\nthere")
        big = os.path.join(d, "big.txt")
        t.write_file(big, "".join(f"line {i}\n" for i in range(5000)))
        piece = t.read_file(big)
        check("read_file pages a long file", "call again with start=" in piece and piece.startswith("line 0\n"))
        real_home = os.environ.get("SINGULARI_HOME")
        os.environ["SINGULARI_HOME"] = d
        check("rest writes the request", t.rest("45").startswith("[asked to rest 45") and open(os.path.join(d, "status", "rest")).read() == "45\n")
        check("rest refuses a non-number", t.rest("later").startswith("[not a number"))
        if real_home is None:
            del os.environ["SINGULARI_HOME"]
        else:
            os.environ["SINGULARI_HOME"] = real_home
    check("read_file on missing path returns error line", t.read_file("/no/such/file").startswith("[error"))

    # web_fetch (needs playwright + chromium + network)
    r = t.web_fetch("https://example.com")
    if r.startswith("[error"):
        check("web_fetch renders a page", None, r[:120])
    else:
        check("web_fetch renders a page to text", "example" in r.lower() and "<" not in r)

    # screenshot (needs playwright + chromium + a URL)
    url = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        import playwright  # noqa: F401
        have_pw = True
    except Exception:  # noqa: BLE001
        have_pw = False
    if not have_pw:
        check("screenshot captures + holds image", None, "playwright not installed")
    elif not url:
        check("screenshot captures + holds image", None, "pass a URL to test, e.g. http://localhost:8080")
    else:
        home = os.environ.get("SINGULARI_HOME", os.path.dirname(HERE))
        pending = os.path.join(home, "agent", ".pending_vision.json")
        if os.path.exists(pending):
            os.remove(pending)
        res = t.screenshot(url)
        ok = res.startswith("[captured") and os.path.exists(pending)
        if ok:
            import base64
            import json
            with open(pending) as f:
                data = json.load(f)
            raw = base64.b64decode(data["data"])
            ok = raw[:8] == b"\x89PNG\r\n\x1a\n"  # it is a real PNG
            os.remove(pending)
        check("screenshot captures + holds a real PNG", ok, res if not ok else "")

    hard_fails = [n for n, ok in results if ok is False]
    print()
    print(f"{sum(1 for _, ok in results if ok)} pass, "
          f"{len(hard_fails)} fail, "
          f"{sum(1 for _, ok in results if ok is None)} skip")
    return 1 if hard_fails else 0


if __name__ == "__main__":
    sys.exit(main())

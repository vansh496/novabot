"""Ek hi service mein dashboard + bot chalane ka launcher.

Render (ya koi bhi web host) par ek hi process chalta hai, isliye:
  - dashboard (Flask) ek child process mein
  - Discord bot isi main thread mein (blocking `bot.run`)
Koi bhi band ho jaye to dono band ho jayenge aur host service ko restart
kar dega.

Start command:  python start.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    port = os.getenv("PORT") or "5000"
    print(f"[start] python {sys.version.split()[0]} | PORT={port}", flush=True)

    dash = subprocess.Popen([sys.executable, "-u", os.path.join(ROOT, "dashboard", "app.py")])
    try:
        # Dashboard ko upar aane ka thoda waqt de do (health check ke liye)
        time.sleep(1.5)
        print("[start] bot shuru ho raha hai...", flush=True)
        import bot  # noqa: E402  (root module)

        bot.main()  # blocking - yahin bot chalta rahega
    finally:
        print("[start] bot band - dashboard bhi band kar rahe hain", flush=True)
        dash.terminate()
        try:
            dash.wait(timeout=10)
        except subprocess.TimeoutExpired:
            dash.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

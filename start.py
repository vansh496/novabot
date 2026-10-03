"""Ek hi service mein dashboard + bot chalane ka launcher.

Render (ya koi bhi web host) par ek hi process chalta hai, isliye:
  - dashboard (Flask) ek child process mein
  - Discord bot isi main thread mein (blocking `bot.run`)

Mazeed zaroori: Discord ka login kabhi kabhi Cloudflare rate-limit
(Error 1015 / 429) kha leta hai. Aisi surat mein poora process marna
nahi chahiye - dashboard zinda rehne se health check pass hota rahega
aur bot thodi der baad khud dobara login karega.

Start command:  python start.py
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Ek cycle mein kitni baar bot ko dobara try karein, uske baad poora
# process exit kar dete hain taaki Render khud naya (fresh) instance chalaye.
MAX_ATTEMPTS = 10


def _is_rate_limit(text: str) -> bool:
    low = text.lower()
    return any(
        s in low
        for s in ("429", "1015", "rate limit", "too many requests", "cloudflare")
    )


def _sleep(seconds: int, dash: subprocess.Popen) -> bool:
    """Thodi-thodi der mein dashboard ki jaanch karte hue wait karein.

    Returns False agar dashboard hi band ho gaya.
    """
    for _ in range(seconds):
        if dash.poll() is not None:
            return False
        time.sleep(1)
    return dash.poll() is None


def main() -> int:
    port = os.getenv("PORT") or "5000"
    print(f"[start] python {sys.version.split()[0]} | PORT={port}", flush=True)

    dash = subprocess.Popen([sys.executable, "-u", os.path.join(ROOT, "dashboard", "app.py")])
    try:
        # Dashboard ko upar aane ka thoda waqt de do (health check ke liye)
        time.sleep(1.5)
        if dash.poll() is not None:
            print("[start] dashboard shuru hi nahi hua - band", flush=True)
            return 1

        attempt = 0
        while True:
            if dash.poll() is not None:
                print("[start] dashboard band - bot bhi band", flush=True)
                return 1
            attempt += 1
            if attempt > MAX_ATTEMPTS:
                print(
                    f"[start] {MAX_ATTEMPTS} attempts ho gaye - process exit, "
                    "Render khud naya instance chalayega",
                    flush=True,
                )
                return 1

            rate_limited = False
            print(f"[start] bot attempt #{attempt}", flush=True)
            try:
                # Har attempt par naya client - purane (aadhe adhure) state se bachne ke liye
                if "bot" in sys.modules:
                    mod = importlib.reload(sys.modules["bot"])
                else:
                    mod = importlib.import_module("bot")
                mod.main()  # blocking - yahin bot chalta rahega
                # Yahan tak aaya matlab bot band ho gaya (normally kabhi nahi hota)
                print("[start] bot chal kar band hua - dobara shuru", flush=True)
            except KeyboardInterrupt:
                raise
            except SystemExit as exc:
                print(f"[start] SystemExit: {exc}", flush=True)
            except BaseException as exc:  # noqa: BLE001 - upar se process nahi marna
                detail = f"{type(exc).__name__}: {exc}"
                rate_limited = _is_rate_limit(detail)
                print(f"[start] bot crash -> {detail[:400]}", flush=True)

            # Cloudflare wale rate-limit ko theek hone mein minute lagte hain.
            delay = 240 if rate_limited else min(30 * attempt, 120)
            print(f"[start] {delay}s baad dobara koshish...", flush=True)
            if not _sleep(delay, dash):
                print("[start] dashboard band - bot retry band", flush=True)
                return 1
    finally:
        print("[start] dashboard bhi band kar rahe hain", flush=True)
        dash.terminate()
        try:
            dash.wait(timeout=10)
        except subprocess.TimeoutExpired:
            dash.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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


def _log_network() -> None:
    """Boot par server ka outbound IP aur Discord ki pahunch log karein.

    Cloudflare ka Error 1015 / 429 sirf IP par lagta hai - is diagnostic se
    pata chalta hai:
      * kaun sa IP hai (do alag IP service se - ek rate-limit kare to doosri bataye)
      * block IP-specific hai ya User-Agent / path-specific
      * naye instance par naya IP mila ya nahi
    """
    try:
        import requests
    except Exception as exc:  # noqa: BLE001
        print(f"[net] requests nahi mila: {exc}", flush=True)
        return

    def _ip_from_trace(text: str) -> str:
        for line in text.splitlines():
            if line.startswith("ip="):
                return line.split("=", 1)[1]
        return "?"

    ip_sources = (
        ("ipify", "https://api.ipify.org", lambda t: t.strip()[:60]),
        ("cloudflare-trace", "https://www.cloudflare.com/cdn-cgi/trace", _ip_from_trace),
    )
    for name, url, parse in ip_sources:
        try:
            resp = requests.get(url, timeout=6)
            print(f"[net] {name}: HTTP {resp.status_code} -> {parse(resp.text)}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[net] {name}: {type(exc).__name__}", flush=True)

    browser_ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    bot_ua = "DiscordBot (https://github.com/Rapptz/discord.py, 2.7.1) Python/3.13"
    checks = (
        ("discord.com home", "https://discord.com/", None),
        ("gateway default-UA", "https://discord.com/api/v10/gateway", None),
        ("gateway bot-UA", "https://discord.com/api/v10/gateway", bot_ua),
        ("gateway browser-UA", "https://discord.com/api/v10/gateway", browser_ua),
        ("oauth2/token GET", "https://discord.com/api/oauth2/token", browser_ua),
        # Kahi block sirf discord.com zone par hi to nahi? Agar ye 200 dein
        # to matlab IP block "discord.com" tak simit hai, poori IP par nahi.
        ("canary gateway", "https://canary.discord.com/api/v10/gateway", browser_ua),
        ("ptb gateway", "https://ptb.discord.com/api/v10/gateway", browser_ua),
    )
    for name, url, ua in checks:
        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": ua} if ua else {})
            status = resp.status_code
            # 403/429 = Cloudflare ne rok diya; koi bhi doosra code = kam se kam
            # request destination tak pahunchi (block nahi).
            state = "BLOCKED" if status in (403, 429) else "pahunch gaye"
            body = (resp.text or "").replace("\n", " ")[:70]
            print(f"[net] {name}: HTTP {status} [{state}] {body}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[net] {name}: error {type(exc).__name__}", flush=True)


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

        _log_network()

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

            # Cloudflare wale rate-limit ko theek hone mein minute lagte hain
            # aur har chhoti koshish block ko barabar badha bhi sakti hai -
            # isliye rate-limit par kaafi lamba gap rakhte hain.
            delay = 900 if rate_limited else min(60 * attempt, 300)
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

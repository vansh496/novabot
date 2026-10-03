"""Dashboard (Flask) - Discord OAuth2 login ke saath.

Chalane ka tareeqa:  python dashboard/app.py
Browser mein kholein: http://localhost:5000
"""

from __future__ import annotations

import os
import secrets
import sys
import time
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
load_dotenv(os.path.join(ROOT, ".env"))

import emoji_codes  # noqa: E402  (root module)
import settings as settings_store  # noqa: E402  (root module)

API = "https://discord.com/api/v10"
AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
TOKEN_URL = "https://discord.com/api/oauth2/token"

CLIENT_ID = (os.getenv("CLIENT_ID") or "").strip()
CLIENT_SECRET = (os.getenv("CLIENT_SECRET") or "").strip()
REDIRECT_URI = (os.getenv("REDIRECT_URI") or "http://localhost:5000/callback").strip()
BOT_TOKEN = (os.getenv("DISCORD_TOKEN") or "").strip()
SCOPES = "identify guilds"
MANAGE_GUILD = 0x20

app = Flask(__name__)
app.secret_key = (os.getenv("SECRET_KEY") or "").strip() or secrets.token_hex(32)

settings_store.ensure_file()


# ---------------------------------------------------------------------------
# Discord helpers
# ---------------------------------------------------------------------------


def _user_headers() -> dict:
    token = session.get("token")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _bot_headers() -> dict:
    return {"Authorization": f"Bot {BOT_TOKEN}"}


def _api_get(path: str, headers: dict, default=None):
    try:
        resp = requests.get(API + path, headers=headers, timeout=15)
    except requests.RequestException:
        return default
    if resp.status_code == 401:
        # Sirf user token ki 401 par session saaf karein (bot token ki 401 par nahi)
        if str(headers.get("Authorization", "")).startswith("Bearer"):
            session.pop("token", None)
            session.pop("user", None)
        return default
    if resp.status_code != 200:
        return default
    try:
        return resp.json()
    except ValueError:
        return default


def _avatar_url(user: dict) -> str:
    avatar = user.get("avatar")
    if avatar:
        return f"https://cdn.discordapp.com/avatars/{user['id']}/{avatar}.png?size=64"
    return "https://cdn.discordapp.com/embed/avatars/0.png"


def _guild_icon(guild: dict) -> str:
    icon = guild.get("icon")
    if icon:
        return f"https://cdn.discordapp.com/icons/{guild['id']}/{icon}.png?size=128"
    return "https://cdn.discordapp.com/embed/avatars/1.png"


def json_safe(obj):
    """Bade integers (> 2^53) ko string bana do.

    Discord IDs ~19 digit ke hote hain aur JS Number sirf 2^53 tak exact hai,
    isliye JSON number ke roop mein bhejne par last digits chup-chaap round
    ho jaate hain (parseInt/JSON.parse dono par). String bhejne par bilkul safe.
    """
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, int) and abs(obj) > 9007199254740991:  # 2^53 - 1
        return str(obj)
    return obj



_GUILD_CACHE: dict = {}  # user_id -> (monotonic time, guilds)


def user_guilds() -> list:
    """User ke guilds - 30s cache, aur API fail hone par purana data.

    Discord rate-limit (429) ya timeout par khaali list lautana matlab
    "access nahi hai" ka jhootha 403 - user ka save button bhi fail ho jata hai.
    """
    uid = str((session.get("user") or {}).get("id") or "") or "_"
    now = time.monotonic()
    hit = _GUILD_CACHE.get(uid)

    # 30s tak wahi list chalao - har page/save par Discord ko mat tano
    if hit and now - hit[0] < 30:
        return hit[1]

    data = _api_get("/users/@me/guilds", _user_headers(), default=None)
    if isinstance(data, list):
        _GUILD_CACHE[uid] = (now, data)
        return data

    # API fail hui (429/timeout) - thanda cache dikha do warna khaali
    if hit and now - hit[0] < 300:
        return hit[1]
    return []


def can_manage(guild: dict) -> bool:
    try:
        perms = int(guild.get("permissions", 0))
    except (TypeError, ValueError):
        perms = 0
    return bool(perms & MANAGE_GUILD)


def find_guild(guild_id: str):
    for guild in user_guilds():
        if str(guild.get("id")) == str(guild_id) and can_manage(guild):
            return guild
    return None


def has_access(guild_id: str) -> bool:
    return session.get("token") and find_guild(guild_id) is not None


def bot_in_guild(guild_id: str) -> bool:
    if not BOT_TOKEN:
        return False
    try:
        resp = requests.get(f"{API}/guilds/{guild_id}", headers=_bot_headers(), timeout=15)
    except requests.RequestException:
        return False
    return resp.status_code == 200


def invite_url(guild_id: str = None) -> str:
    params = {
        "client_id": CLIENT_ID,
        "permissions": 8,  # Administrator (anti-nuke ko ban/manage chahiye)
        "scope": "bot applications.commands",
    }
    if guild_id:
        params["guild_id"] = str(guild_id)
    return AUTHORIZE_URL + "?" + urlencode(params)


# ---------------------------------------------------------------------------
# Middleware / context
# ---------------------------------------------------------------------------


@app.before_request
def _csrf_protect():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    if request.method == "POST":
        if not session.get("csrf") or request.headers.get("X-CSRF-Token") != session.get("csrf"):
            return jsonify({"ok": False, "error": "CSRF token match nahi hua. Page reload karein."}), 403
    return None


@app.context_processor
def _inject():
    return {
        "discord_user": session.get("user"),
        "csrf_token": session.get("csrf"),
        "client_id": CLIENT_ID,
    }


# ---------------------------------------------------------------------------
# OAuth2 routes
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    return render_template("index.html", logged_in=bool(session.get("token")))


@app.route("/login")
def login():
    if not CLIENT_ID or not CLIENT_SECRET:
        return render_template(
            "index.html",
            logged_in=False,
            error=".env mein CLIENT_ID aur CLIENT_SECRET add karein (.env.example dekhein).",
        ), 500
    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
    }
    return redirect(AUTHORIZE_URL + "?" + urlencode(params))


def _oauth_error(title: str, detail: str):
    """OAuth fail hone par user ko samajh aane wala page + server log dono."""
    print(f"[callback] {title} -> {detail}", flush=True)
    return (
        render_template(
            "message.html",
            title=title,
            text=detail,
        ),
        400,
    )


@app.route("/callback")
def callback():
    saved_state = session.pop("oauth_state", None)
    sent_state = request.args.get("state")
    if not saved_state or sent_state != saved_state:
        return _oauth_error(
            "Login fail: state mismatch",
            "Session cookie wapas nahi mili (browser ne cookie block ki "
            "ya session expire ho gaya). Dobara Login with Discord dabayein. "
            f"[cookie={'haan' if 'session' in request.cookies else 'nahi'} "
            f"saved={'haan' if saved_state else 'nahi'} "
            f"sent={'haan' if sent_state else 'nahi'}]",
        )
    code = request.args.get("code")
    if not code:
        return _oauth_error("Login fail: code nahi mila", "Discord ne code nahi bheja.")

    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    resp = None
    # 429/5xx aane par 2 baar dobara koshish (Discord kabhi kabhi throttle karta hai)
    for attempt in (1, 2):
        try:
            resp = requests.post(TOKEN_URL, data=data, headers=headers, timeout=15)
        except requests.RequestException as exc:
            if attempt == 2:
                return _oauth_error(
                    "Login fail: Discord tak nahi pahunche",
                    f"Network error: {type(exc).__name__}",
                )
            time.sleep(2)
            continue
        if resp.status_code in (429, 500, 502, 503, 504) and attempt == 1:
            print(f"[callback] token exchange {resp.status_code} - 2s baad retry", flush=True)
            time.sleep(2)
            continue
        break

    if resp is None or resp.status_code != 200:
        body = (resp.text[:300] if resp is not None else "no response")
        status = resp.status_code if resp is not None else "none"
        return _oauth_error(
            "Login fail: token exchange",
            f"Discord ne token nahi diya (HTTP {status}). "
            f"Agar isme 429/1015/rate limit dikhe to Discord ke "
            f"Render ke IP par rate-limit ke karan hai - thodi der baad "
            f"dobara koshish karein. Detail: {body}",
        )

    token = resp.json().get("access_token")
    if not token:
        return _oauth_error(
            "Login fail: access_token nahi mila",
            f"Response: {resp.text[:300]}",
        )
    session["token"] = token

    me = _api_get("/users/@me", _user_headers())
    if me:
        session["user"] = {
            "id": str(me["id"]),
            "username": me.get("global_name") or me.get("username") or "User",
            "avatar": _avatar_url(me),
        }
    return redirect(url_for("servers"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@app.route("/servers")
def servers():
    if not session.get("token"):
        return redirect(url_for("login"))

    mine = [g for g in user_guilds() if can_manage(g)]
    bot_ids = set()
    if BOT_TOKEN:
        bot_guilds = _api_get("/users/@me/guilds", _bot_headers(), default=[])
        if isinstance(bot_guilds, list):
            bot_ids = {str(g.get("id")) for g in bot_guilds}

    cards = []
    for guild in mine:
        gid = str(guild["id"])
        cards.append(
            {
                "id": gid,
                "name": guild.get("name", "Server"),
                "icon": _guild_icon(guild),
                "bot_in": gid in bot_ids,
            }
        )
    cards.sort(key=lambda c: (not c["bot_in"], c["name"].lower()))
    return render_template("servers.html", guilds=cards, invite=invite_url())


def _emoji_list(raw):
    """Guild ke emojis ko preview/picker ke liye saaf karo.

    Animated (a:...) pehle, phir static - taki picker mein bonus wale upar aayein.
    """
    out = []
    for e in raw or []:
        if not isinstance(e, dict) or not e.get("id"):
            continue
        out.append(
            {
                "id": str(e["id"]),
                "name": str(e.get("name") or ""),
                "animated": bool(e.get("animated")),
            }
        )
    out.sort(key=lambda x: (not x["animated"], x["name"].lower()))
    return out


_EMOJI_CACHE: dict = {}  # guild_id -> (timestamp, rows)


def _guild_emojis(guild_id: str) -> list:
    """Guild ke emojis (1 minute cache) - shortcode resolve karne ke liye."""
    now = time.time()
    hit = _EMOJI_CACHE.get(str(guild_id))
    if hit and now - hit[0] < 60:
        return hit[1]
    raw = _api_get(f"/guilds/{guild_id}/emojis", _bot_headers(), default=[]) or []
    rows = _emoji_list(raw)
    _EMOJI_CACHE[str(guild_id)] = (now, rows)
    return rows


def _emojitext(text, guild_id: str) -> str:
    """`:fire:` -> `<:fire:ID>` (bhejne se pehle).

    Server-side isliye, taaki pehle se save kiya hua shortcode wala text bhi
    bina edit kiye theek chale - sirf JS par nirbhar nahi rehna chahiye.
    """
    return emoji_codes.resolve(text, _guild_emojis(guild_id))


@app.route("/servers/<guild_id>")
def server(guild_id):
    if not session.get("token"):
        return redirect(url_for("login"))
    guild = find_guild(guild_id)
    if guild is None:
        abort(403)

    raw_channels = _api_get(f"/guilds/{guild_id}/channels", _bot_headers(), default=[]) or []
    raw_roles = _api_get(f"/guilds/{guild_id}/roles", _bot_headers(), default=[])
    raw_emojis = _api_get(f"/guilds/{guild_id}/emojis", _bot_headers(), default=[]) or [] or []

    channels = [
        {"id": str(c["id"]), "name": c.get("name", "")}
        for c in raw_channels
        if c.get("type") in (0, 5)  # text + announcement
    ]
    categories = [
        {"id": str(c["id"]), "name": c.get("name", "")}
        for c in raw_channels
        if c.get("type") == 4
    ]
    roles = [
        {"id": str(r["id"]), "name": r.get("name", "")}
        for r in raw_roles
        if str(r.get("id")) != str(guild_id)
    ]

    cfg = settings_store.get(guild_id)
    modules_on = sum(
        1 for sec in ("welcome", "verification", "tickets", "antinuke") if cfg.get(sec, {}).get("enabled")
    )
    bot_user = _api_get("/users/@me", _bot_headers()) or {}

    return render_template(
        "server.html",
        guild={"id": str(guild_id), "name": guild.get("name", "Server"), "icon": _guild_icon(guild)},
        channels=channels,
        categories=categories,
        roles=roles,
        emojis=_emoji_list(raw_emojis),
        cfg=json_safe(cfg),
        modules_on=modules_on,
        bot_user=bot_user,
        bot_in=bot_in_guild(guild_id),
        invite=invite_url(guild_id),
    )


# ---------------------------------------------------------------------------
# API (dashboard -> settings file -> bot live pick karta hai)
# ---------------------------------------------------------------------------


def _err(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


@app.post("/api/<guild_id>/<section>")
def api_save(guild_id, section):
    if not has_access(guild_id):
        return _err("Access nahi hai.", 403)
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return _err("Galat data.")
    # Save karte hi `:fire:` wale shortcodes ko asli emoji syntax bana do
    payload = emoji_codes.resolve_in(payload, _guild_emojis(guild_id))
    try:
        updated = settings_store.set_section(guild_id, section, payload)
    except KeyError:
        return _err("Section nahi mila.", 404)
    except (ValueError, TypeError):
        return _err("Data valid nahi hai.")
    # IDs string mein bhejo - JSON number ke roop mein JS bigaad deta hai (2^53 se badi)
    return jsonify({"ok": True, "saved": json_safe(updated.get(section, {}))})


# ---------------------------------------------------------------------------
# Dashboard se hi panel / test message bhejna
# (format bilkul cogs jaisa - taake Discord par same dikhe)
# ---------------------------------------------------------------------------


def _fmt_vars(text, guild_id: str) -> str:
    """Welcome/leave ke variables dashboard user se bharo (test message ke liye)."""
    user = session.get("user") or {}
    guild = _member_count_and_name(guild_id)
    uid = str(user.get("id") or "0")
    name = str(user.get("username") or "User")
    return (
        str(text or "")
        .replace("{user}", f"<@{uid}>")
        .replace("{username}", name)
        .replace("{display_name}", name)
        .replace("{server}", str(guild.get("name") or "Server"))
        .replace("{member_count}", str(guild.get("count") or 0))
        .replace("{id}", uid)
    )


def _member_count_and_name(guild_id: str) -> dict:
    """Guild naam + member count.

    GET /guilds/<id> mein `member_count` nahi aata, isliye with_counts maangna
    padta hai (approximate_member_count). Warna message mein "Member count: 0".
    """
    guild = _api_get(f"/guilds/{guild_id}?with_counts=true", _bot_headers(), default={}) or {}
    return {
        "name": guild.get("name"),
        "count": guild.get("member_count") or guild.get("approximate_member_count") or 0,
    }


def _color_int(raw, default: int = 0x5865F2) -> int:
    try:
        return int(str(raw or "").strip().lstrip("#"), 16)
    except ValueError:
        return default


def _post_message(channel_id: str, payload: dict):
    """Bot se message bhejo. (ok, error) return karta hai."""
    try:
        resp = requests.post(
            f"{API}/channels/{channel_id}/messages",
            headers=_bot_headers(),
            json=payload,
            timeout=20,
        )
    except requests.RequestException:
        return None, "Discord se connect nahi ho saka."
    if resp.status_code not in (200, 201):
        return None, f"Discord error {resp.status_code}: {resp.text[:200]}"
    return resp.json(), None


@app.post("/api/<guild_id>/welcome/test")
def api_welcome_test(guild_id):
    """Welcome / Leave ka sample message usi channel par bhejta hai."""
    if not has_access(guild_id):
        return _err("Access nahi hai.", 403)

    payload = request.get_json(silent=True) or {}
    kind = "leave" if payload.get("kind") == "leave" else "welcome"
    cfg = settings_store.get(guild_id).get("welcome", {})
    user = session.get("user") or {}
    name = str(user.get("username") or "User")

    if kind == "leave":
        channel_id = str(cfg.get("leave_channel_id") or "0")
        if channel_id == "0":
            return _err("Leave channel select karke Save karein.")
        text = _emojitext(_fmt_vars(cfg.get("leave_message"), guild_id), guild_id) or f"{name} left."
        _, err = _post_message(channel_id, {"content": text})
        return _err(err) if err else jsonify({"ok": True, "channel": channel_id})

    channel_id = str(cfg.get("channel_id") or "0")
    if channel_id == "0":
        return _err("Welcome channel select karke Save karein.")
    text = _emojitext(_fmt_vars(cfg.get("message"), guild_id), guild_id)

    if cfg.get("use_embed", True):
        info = _member_count_and_name(guild_id)
        embed = {
            "title": f"Welcome {name}!",
            "description": text or None,
            "color": _color_int(cfg.get("embed_color"), 0x57F287),
            "footer": {"text": f"Member #{info['count']}"},
        }
        if user.get("avatar"):
            embed["thumbnail"] = {"url": str(user["avatar"])}
        embed = {k: v for k, v in embed.items() if v is not None}
        body = {"embeds": [embed]}
    else:
        body = {"content": text or f"<@{user.get('id') or '0'}>"}

    _, err = _post_message(channel_id, body)
    return _err(err) if err else jsonify({"ok": True, "channel": channel_id})


@app.post("/api/<guild_id>/verification/panel")
def api_verification_panel(guild_id):
    """Verify panel (embed + Verify button) usi channel par bhejta hai."""
    if not has_access(guild_id):
        return _err("Access nahi hai.", 403)

    cfg = settings_store.get(guild_id).get("verification", {})
    if not cfg.get("enabled"):
        return _err("Pehle Verification ON karein.")
    channel_id = str(cfg.get("channel_id") or "0")
    if channel_id == "0":
        return _err("Panel channel select karke Save karein.")
    if not int(cfg.get("role_id") or 0):
        return _err("Verify role select karke Save karein.")

    embed = {
        "title": "🛡️ Verification",
        "description": _emojitext(cfg.get("message"), guild_id) or "Click the button below to verify.",
        "color": _color_int(cfg.get("embed_color")),
        "footer": {"text": "Neeche diya gaya button dabayein"},
    }
    components = [
        {
            "type": 1,
            "components": [
                {
                    "type": 2,
                    "style": 2,  # success (green) - cogs/verification.py ke same
                    "label": "Verify",
                    "emoji": {"name": "✅"},
                    "custom_id": "verify_button_v1",
                }
            ],
        }
    ]
    _, err = _post_message(channel_id, {"embeds": [embed], "components": components})
    return _err(err) if err else jsonify({"ok": True, "channel": channel_id})


@app.post("/api/<guild_id>/tickets/panel")
def api_tickets_panel(guild_id):
    """Ticket panel (embed + Open Ticket button) usi channel par bhejta hai."""
    if not has_access(guild_id):
        return _err("Access nahi hai.", 403)

    cfg = settings_store.get(guild_id).get("tickets", {})
    if not cfg.get("enabled"):
        return _err("Pehle Tickets ON karein.")
    channel_id = str(cfg.get("panel_channel_id") or "0")
    if channel_id == "0":
        return _err("Panel channel select karke Save karein.")

    embed = {
        "title": "🎫 Support Tickets",
        "description": _emojitext(cfg.get("message"), guild_id) or "Need help? Open a ticket below.",
        "color": _color_int(cfg.get("embed_color")),
        "footer": {"text": "Ek waqt mein ek hi ticket khuli ho sakti hai"},
    }
    components = [
        {
            "type": 1,
            "components": [
                {
                    "type": 2,
                    "style": 1,  # primary (blurple) - cogs/tickets.py ke same
                    "label": "Open Ticket",
                    "emoji": {"name": "🎫"},
                    "custom_id": "ticket_open_v1",
                }
            ],
        }
    ]
    _, err = _post_message(channel_id, {"embeds": [embed], "components": components})
    return _err(err) if err else jsonify({"ok": True, "channel": channel_id})


@app.post("/api/<guild_id>/embed/send")
def api_embed_send(guild_id):
    if not has_access(guild_id):
        return _err("Access nahi hai.", 403)

    payload = request.get_json(silent=True) or {}
    channel_id = str(payload.get("channel_id") or "")
    embed = payload.get("embed")
    if not channel_id or not isinstance(embed, dict):
        return _err("Channel aur embed dono chahiye.")

    channels = _api_get(f"/guilds/{guild_id}/channels", _bot_headers(), default=[]) or []
    if channel_id not in {str(c.get("id")) for c in channels}:
        return _err("Ye channel is server mein nahi mila.")

    # JS resolve karke bhejta hai, phir bhi yahan dobara - koi purana tab /
    # cache wala page shortcode bhej de to Discord text na dikhaye.
    if isinstance(embed.get("title"), str):
        embed["title"] = _emojitext(embed["title"], guild_id)
    if isinstance(embed.get("description"), str):
        embed["description"] = _emojitext(embed["description"], guild_id)
    footer = embed.get("footer")
    if isinstance(footer, dict) and isinstance(footer.get("text"), str):
        footer["text"] = _emojitext(footer["text"], guild_id)

    try:
        resp = requests.post(
            f"{API}/channels/{channel_id}/messages",
            headers=_bot_headers(),
            json={"embeds": [embed]},
            timeout=15,
        )
    except requests.RequestException:
        return _err("Discord se connect nahi ho saka.")
    if resp.status_code != 200:
        return _err(f"Discord error {resp.status_code}: {resp.text[:200]}")
    return jsonify({"ok": True})


@app.errorhandler(403)
def _forbidden(_e):
    return render_template("message.html", title="Access denied", text="Aapke paas is server ka access nahi hai."), 403


@app.errorhandler(404)
def _not_found(_e):
    return render_template("message.html", title="Not found", text="Page nahi mila."), 404


if __name__ == "__main__":
    # Local:  PORT unset -> sirf localhost:5000
    # Render: PORT set hota hai -> 0.0.0.0 par bind karna padta hai (warna
    #         host ka health check dashboard tak nahi pahunchta).
    port = int(os.getenv("PORT") or "5000")
    host = os.getenv("HOST") or ("0.0.0.0" if os.getenv("PORT") else "127.0.0.1")
    print(f"Dashboard: http://{host}:{port}")
    app.run(host=host, port=port, debug=False, threaded=True)

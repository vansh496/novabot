"""`:naam:` wale emoji shortcodes ko Discord ki asli syntax mein badalta hai.

Panel / message mein user `:fire:` likhta hai. Agar waise ka waisa bheja jaye
to Discord use **plain text** dikhata hai - asli emoji sirf
`<:fire:1234567890>` (static) ya `<a:fire:1234567890>` (animated) format mein
render hota hai.

Dashboard ke JS mein yeh kaam `resolveEmojiCodes()` karta hai; ye Python wala
version uska server-side backup hai - purane (shortcode wale) save kiye hue
settings aur bot ke apne panel/command message ke liye, taaki user ko dobara
edit karke save na karna pade.
"""

from __future__ import annotations

import re

# Do hisse hain:
#   1) `<a:naam:id>` / `<:naam:id>` - pehle se laga hua code. Isse hum ID dekhkar
#      theek kar dete hain (galti se animated emoji par static `<:...>` likha ho).
#   2) `:naam:`, `:naam~2:`, `:naam~2`, `<:naam:>`, `:naam>` - shortcodes jo log
#      bahar se chipkate hain. Dono taraf ka `<` / `>` aur band colon dono
#      optional hain kyunki log `:fire`, `:fire>` aur `:fire~2` teeno tarah
#      likh dete hain.
PATTERN = re.compile(
    r"<a?:(?P<ename>[A-Za-z0-9_]{1,32}):(?P<eid>\d+)>"
    r"|<?:(?P<name>[A-Za-z0-9_]{1,32})(?:~\d{1,4})?:?>?"
)


def _lookup(emojis) -> dict:
    """Naam (lowercase) -> (id, animated, asli naam). Emoji objects ya dict dono chalte hain."""
    table: dict = {}
    for e in emojis or []:
        if isinstance(e, dict):
            name, eid, animated = e.get("name"), e.get("id"), e.get("animated")
        else:
            name = getattr(e, "name", None)
            eid = getattr(e, "id", None)
            animated = getattr(e, "animated", False)
        if name and eid:
            table[str(name).lower()] = (str(eid), bool(animated), str(name))
    return table


def resolve(text, emojis) -> str:
    """Shortcodes badal do; jis naam ka emoji hi nahi hai wo waisa hi chhod dete hain.

    Isliye normal text jaise "5:30" ya ":D" ko chhune ka sawal hi nahi -
    unka naam kisi emoji se match hi nahi hota.
    """
    if text is None:
        return ""
    src = str(text)
    if not src:
        return src

    table = _lookup(emojis)
    if not table:
        return src
    by_id = {v[0]: (v[1], v[2]) for v in table.values()}  # id -> (animated, naam)

    def repl(match: re.Match) -> str:
        eid = match.group("eid")
        if eid:
            # Laga hua code: ID hamari hai to animated/static theek kar do,
            # nahi to (kisi aur server ka emoji) haath mat lagao.
            hit = by_id.get(eid)
            if not hit:
                return match.group(0)
            animated, canonical = hit
            return ("<a:" if animated else "<:") + canonical + ":" + eid + ">"

        name = match.group("name")
        if not name:
            return match.group(0)
        item = table.get(name.lower())
        if not item:
            return match.group(0)  # server mein aisa emoji hai hi nahi
        item_id, animated, canonical = item
        return ("<a:" if animated else "<:") + canonical + ":" + item_id + ">"

    return PATTERN.sub(repl, src)


def resolve_in(payload, emojis):
    """Dict ke saare string values resolve kar do (IDs/channels ko chhukar nahi)."""
    if not isinstance(payload, dict):
        return payload
    return {
        k: (resolve(v, emojis) if isinstance(v, str) else v)
        for k, v in payload.items()
    }

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

# Pehla alternative = pehle se sahi syntax (`<a:naam:id>`) - use chhodna hai,
# warna wo andar se dobara resolve hokar toot jayega. Group (1) sirf tab bhartha
# hai jab doosra (shortcode) wala branch match ho.
#
# Doosre branch ke dono taraf `<` / `>` optional hain - log `<:fire:>`, `:fire:`
# aur `:fire~2:` teeno tarah likh dete hain, teeno ko hi asli code bana dena hai.
PATTERN = re.compile(
    r"<a?:[A-Za-z0-9_]{1,32}:\d{6,}>|<?:([A-Za-z0-9_]{1,32})(?:~\d{1,4})?:>?"
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

    def repl(match: re.Match) -> str:
        name = match.group(1)
        if not name:  # pehle se sahi syntax - jaisa hai waisa rehne do
            return match.group(0)
        hit = table.get(name.lower())
        if not hit:
            return match.group(0)  # server mein aisa emoji hai hi nahi
        eid, animated, canonical = hit
        return ("<a:" if animated else "<:") + canonical + ":" + eid + ">"

    return PATTERN.sub(repl, src)


def resolve_in(payload, emojis):
    """Dict ke saare string values resolve kar do (IDs/channels ko chhukar nahi)."""
    if not isinstance(payload, dict):
        return payload
    return {
        k: (resolve(v, emojis) if isinstance(v, str) else v)
        for k, v in payload.items()
    }

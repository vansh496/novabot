# ◆ NovaBot — Discord Bot + Dashboard

Ek complete Discord bot jismein **6 systems** hain aur sab kuch ek **HTML/CSS dashboard** se control hota hai (Discord OAuth2 login ke saath).

## Features

| # | Feature | Kaam kya karta hai |
|---|---------|--------------------|
| 1 | 🎫 **Tickets** | Panel button se private ticket channel, close / reopen / delete + transcript log |
| 2 | 💣 **Anti-Nuke** | Audit log monitor — zyada bans/kicks/channel/role deletes par alert + attacker ban/kick |
| 3 | 👋 **Welcome** | Welcome channel mein embed message |
| 4 | 📩 **Join DM** | Naye member ko turant private DM |
| 5 | 🚪 **Leave** | Member chale to leave message |
| 6 | 🛡️ **Verification** | Button dabao → verify role mil jaye |
| 7 | 📨 **Embed Builder** | Dashboard (live preview) ya `/embed` command se embed |
| 8 | 🌐 **Dashboard** | Login → server select → saari settings → **Save = foran apply (restart nahi)** |

---

## Step 0 — Computer par Python install karein

Agar Python nahi hai to [python.org](https://www.python.org/downloads/) se **Python 3.10+** install karein.
> Install karte waqt **"Add Python to PATH"** ka checkbox zaroor tick karein.

Check karein:

```
python --version
```

---

## Step 1 — Discord Developer Portal setup

1. [discord.com/developers/applications](https://discord.com/developers/applications) kholein → **New Application**
2. Left menu mein **Bot** tab → **Reset Token** → token copy karein *(ye `DISCORD_TOKEN` hai)*
3. Usi page par **Privileged Gateway Intents** → **Server Members Intent** ko **ON** karein
   *(welcome / leave / verification ke liye zaroori hai)*
4. **OAuth2** tab → **Client ID** aur **Client Secret** copy karein
5. Usi page ke **Redirects** mein add karein aur **Save** dabayein:
   ```
   http://localhost:5000/callback
   ```

### Apni User ID lene ka tareeqa
Discord → Settings → Advanced → **Developer Mode ON** → apne naam par **right click** → **Copy User ID**

---

## Step 2 — `.env` file banayein

Project folder mein `.env.example` file hai. Usko Notepad mein kholein, saari values bhar dein, aur
**`.env`** naam se save karein (file name sirf `.env`, bina kisi extension ke):

```
DISCORD_TOKEN=your_bot_token_here
BOT_OWNER_ID=your_user_id_here
CLIENT_ID=your_application_client_id
CLIENT_SECRET=your_client_secret
REDIRECT_URI=http://localhost:5000/callback
SECRET_KEY=koi_bhi_lambi_random_string
DASHBOARD_URL=http://localhost:5000
```

---

## Step 3 — Packages install karein

Project folder mein (yahan se):

```
pip install -r requirements.txt
```

---

## Step 4 — Bot ko server mein invite karein

Browser mein ye URL kholein (apna `CLIENT_ID` daalein):

```
https://discord.com/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=8&scope=bot%20applications.commands
```

> **Note:** Anti-nuke ko bans/channels manage karne hain isliye **Administrator** permission di hai.
> Agar kam permissions chahiye to `permissions=8` ko Discord ke permissions integer se badal lein.

---

## Step 5 — Chalayein

**Terminal 1 (bot):**
```
python bot.py
```

**Terminal 2 (dashboard):**
```
python dashboard/app.py
```

**Browser:**
```
http://localhost:5000
```

→ **Login with Discord** → apna server select karein → settings karein → **Save**
→ Bot ko restart karne ki zaroorat **nahi**, settings foran lagu ho jati hain.

---

## 🚀 Railway par host karein (24x7 online, computer band ho to bhi chalta rahe)

> **Render kaam nahi karta:** Render ke outbound IP range (74.220.x / Choopa) par
> Discord `/api/*` **429** aata hai — bot login hi nahi ho pata (HTML page 200 aata
> hai, isliye galti se lagta hai sab theek hai). **Railway** ke IP se gateway
> **200** aata hai, isliye yahan host kiya ja raha hai.
> Live: `https://novabot-production-31b1.up.railway.app`

`start.py` (bot + dashboard ek hi service mein chalane wala launcher) aur `Procfile`
(`web: python start.py`) project ke saath maujood hain. Railway khud Procfile dekh kar
start command leta hai.

### 1. Railway CLI se deploy

GitHub App install karne par GitHub **password (sudo mode)** maangta hai — bina uske
bhi CLI se deploy ho jata hai:

1. [railwayapp/cli releases](https://github.com/railwayapp/cli/releases) se
   `railway-windows-x86_64.zip` download karein → `railway.exe` nikalein
2. `railway login` → browser mein Railway account se authorize
3. Project folder mein: `railway init --name novabot`
4. Env vars set karein — **value command line mein mat likhein**, stdin se dein:
   ```
   railway variable set DISCORD_TOKEN --stdin --skip-deploys
   ```
   `.env` ke saare 7 keys set karein (`DISCORD_TOKEN`, `BOT_OWNER_ID`, `CLIENT_ID`,
   `CLIENT_SECRET`, `SECRET_KEY`, `REDIRECT_URI`, `DASHBOARD_URL`).

   | Key | Value |
   |-----|-------|
   | `DISCORD_TOKEN` | Developer Portal → Bot → Token |
   | `BOT_OWNER_ID` | Aapki Discord User ID |
   | `CLIENT_ID` | OAuth2 → Client ID |
   | `CLIENT_SECRET` | OAuth2 → Client Secret |
   | `REDIRECT_URI` | `https://<railway-url>/callback` |
   | `DASHBOARD_URL` | `https://<railway-url>` |
   | `SECRET_KEY` | koi lambi random string (session ke liye) |

5. `railway domain` → public domain banao → `railway up --detach` se deploy
6. `railway logs` mein `Logged in as APEX#7583` dikhe matlab **bot live** hai.

> **Auto-deploy off hai:** code badalne par khud `railway up` chalana padega
> (GitHub App connect karke git-push auto-deploy bhi ho sakta hai).

### 2. Discord Developer Portal mein redirect URL

OAuth2 → **Redirects** → naya Railway URL daalein → **Save Changes** dabayein:

```
https://<railway-url>/callback
```

> Portal mein **Server Members Intent ON** rehna chahiye (Step 1 dekhein).

### 3. Zaroori baatein

- **Ek hi jagah chalayein:** Railway ka bot + aapke computer ka bot **ek saath**
  mat chalayein — dono same events dekh kar **double welcome / double alert**
  karenge. Local chalana ho to Railway service ko stop kar dein.
- **Railway ka disk ephemeral hai** — naye deploy par `data/settings.json` repo wala
  version wapas aa jata hai (dashboard ki changes mit jayengi). Permanent chahiye to
  **Railway volume** lagana padega.
- **Usage based billing:** trial ka **$5 credit / 30 din** free hai (card nahi
  chahiye). Credit khatam hone par Hobby plan (card) lena padega.
- Dashboard **development server** (`app.run`) chalata hai — chhoti team ke liye
  theek hai; bada traffic ho to gunicorn lagana behtar hai.
- Restart policy `ON_FAILURE` hai — crash par khud 10 baar tak restart leta hai.

---

## Discord Commands

| Command | Kaam |
|---------|------|
| `/ping` | Latency check |
| `/help` | Saare commands |
| `/welcome setup #channel` | Welcome ON + channel |
| `/welcome test [#channel]` | Sample welcome bhejo |
| `/welcome dm-test` | Sample join DM khud dekho |
| `/welcome leave-test [#channel]` | Sample leave message |
| `/verify setup #channel @role` | Verification set karo |
| `/verify panel [#channel]` | Verify panel bhejo |
| `/ticket setup @support_role [#category] [#log]` | Tickets set karo |
| `/ticket panel [#channel]` | Ticket panel bhejo |
| `/embed` | Modal se embed banao |
| `/antinuke_status` | Anti-nuke ki settings |

Sab se zyada cheezein **dashboard** se hoti hain (Welcome, Leave, Join DM, Verification, Tickets,
Anti-Nuke limits/whitelist, Embed builder).

---

## Anti-Nuke samajhne ke liye

- **⚡ Instant (1 second):** kisi ne bhi **bot add** kiya, member ko **ban/kick** kiya,
  **channel/role** banaya-delete kiya, ya **kisi ko Administrator wali role** de di
  (ya role edit se admin bana diya) → attacker ko turant ban. Ismein admin bhi nahi bachta.
- **📊 Threshold:** bot har **2 second** mein audit log check karta hai. Jo member **window**
  (default 60s) ke andar limit se zyada bans / kicks / bot adds / channel ya role
  creates+deletes karega, use **alert channel** par pakda jayega aur **action** (ban/kick) liya jayega.
- **Whitelist** mein jo IDs hongi, un par kabhi action nahi hota (server owner, bot owner aur
  bot khud hamesha safe).
- Alert channel ko **View Audit Log** + **Send Messages** permission chahiye (Administrator dene se sab aa jata hai).

---

## File structure

```
📁 Project
├── bot.py                 # Bot start yahan se hota hai
├── settings.py            # Shared settings (bot + dashboard dono use karte hain)
├── requirements.txt
├── .env.example           # Isko .env bana kar bharein
├── 📁 cogs
│   ├── general.py         # /ping, /help
│   ├── welcome.py         # Welcome, Leave, Join DM
│   ├── verification.py    # Verification panel
│   ├── tickets.py         # Ticket system
│   ├── antinuke.py        # Anti-nuke (audit log polling)
│   └── embeds.py          # /embed modal
├── 📁 dashboard
│   ├── app.py             # Flask + Discord OAuth2
│   ├── 📁 templates       # HTML (base, index, servers, server)
│   └── 📁 static
│       ├── css/style.css  # Dashboard ka pura design
│       └── js/script.js   # Tabs, save, live embed preview
└── 📁 data
    └── settings.json      # Saari settings (auto ban jati hai)
```

---

## Problem? (Troubleshooting)

> **Python abhi install nahi hai?** Design dekhne ke liye bina Python ke bhi preview kholein:
> `dashboard/static/preview_landing.html` aur `dashboard/static/preview.html`
> (donon files browser mein double-click karke kholein).

| Problem | Hal |
|---------|-----|
| `Intents are missing` / members nahi mil rahe | Developer Portal → Bot → **Server Members Intent ON** → bot restart |
| Dashboard login fail / redirect error | OAuth2 → Redirects mein exact `http://localhost:5000/callback` save karein |
| `DISCORD_TOKEN nahi mila` | `.env` file bana kar token daalein (file ka naam sirf `.env`) |
| Slash commands nahi dikh rahe | Pehli baar sync hone mein 1 ghant tak lag sakta hai — bot restart karein, phir Discord **refresh** (Ctrl+R) |
| Ticket channel nahi banta | Bot ko category/role par **Manage Channels** permission dein |
| Verification role nahi lagta | Bot ki role **verify role se neeche** honi chahiye |
| Anti-nuke alert nahi aata | Alert channel set karein + bot ko **View Audit Log** permission ho |
| `port 5000 already in use` | `.env` mein `REDIRECT_URI` badal kar portal mein bhi wahi daalein, phir `dashboard/app.py` ke `port=5000` ko wahi badlein |

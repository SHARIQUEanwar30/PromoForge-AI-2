"""ONE place for everything you may want to change without touching app.py.

* wording (name, tagline, the short intro line on every page, pop-up texts)
* colours
* the list of AI choices (free or not free, where to get a key)
* the automatic settings that the screen does not show (how many promos, AI call budget)

Plain Python on purpose: edit a string, save, refresh the browser.
"""
from __future__ import annotations

APP_NAME = "PromoForge"
APP_ICON = "🎬"
TAGLINE = ("Upload the episodes of your story. PromoForge finds the best 20 to 60 second moments to use as "
           "promo clips, tells you the exact start and end time, and ranks them from best to worst.")
FOOTER_NOTE = "Scores are a guide to help an editor decide, not a guarantee."

# ------------------------------------------------------------------ colours (used by the CSS in app.py)
COLORS = {
    "bg": "#0f1020",          # page background
    "panel": "#1b1c36",       # boxes and pop-ups
    "accent": "#ff4d6d",      # main colour (buttons, rank badges)
    "accent2": "#ff8a3d",     # second colour of the gradients
    "gold": "#ffd166",        # scores
    "violet": "#7b61ff",      # "What's here" strips
    "text": "#f3f3fa",
    "muted": "#b9bad3",
    "good": "#6cf0a8",        # "strong pick" green
}

# ------------------------------------------------------------------ pages: (name, icon, one-line "What's here")
PAGES = [
    ("Upload & Analyze", "⬆", "Add your episodes, choose how to analyse, and press Run."),
    ("Dashboard", "📊", "A quick summary of your result: episodes read, promos found, and the best picks."),
    ("Story Intelligence", "📖", "A short picture of your story: who speaks most, what moods show up, how episodes end."),
    ("Promo Discovery", "🔥", "All promos, best first. Each card shows exact start and end time, the hook, the cliffhanger, and why it works."),
    ("Editing Desk", "✂️", "Read the script, move the start or end with + / −, then Keep or Skip. The yellow part shows your promo."),
    ("Export", "⬇", "Download your promos as a spreadsheet and as text files, one file for each promo."),
]
FIRST_PAGE = PAGES[0][0]
RESULT_PAGE = "Dashboard"            # where the visitor lands after pressing Run

# ------------------------------------------------------------------ sample stories (made up, safe to show anyone)
SAMPLES = {
    "Sample story 1 (timestamps in blocks)": "story_labelled",
    "Sample story 2 (timestamps inline)": "story_inline",
    "Sample story 3 (no timestamps, so times are estimated)": "story_fountain",
}
NO_SAMPLE = "Try a sample story (no files needed)"

# ------------------------------------------------------------------ AI choices
# provider : internal engine name (none / gemini / openai / anthropic)
# free     : True  -> nobody needs to pay; False -> the visitor must bring a paid key (pop-up appears)
# site_key : True  -> the key stored privately on the hosting site (Secrets / .env) may be used, so visitors type nothing
# base_url : fixed address of the service (the visitor never sees it)
# The model name is never asked: the app picks one from the list the service offers for the key.
PROVIDERS = [
    {"id": "rules", "label": "Rule-based", "provider": "none", "free": True, "site_key": False, "icon": "⚡",
     "blurb": "free · no key · fast"},
    {"id": "gemini", "label": "Gemini", "provider": "gemini", "free": True, "site_key": True, "icon": "✨",
     "blurb": "free · smarter · a few minutes for a full show",
     "key_url": "https://aistudio.google.com/apikey", "company": "Google"},
    {"id": "openai", "label": "OpenAI", "provider": "openai", "free": False, "site_key": False, "icon": "🤖",
     "blurb": "not free · needs your own key", "base_url": "https://api.openai.com/v1",
     "key_url": "https://platform.openai.com/api-keys", "company": "OpenAI"},
    {"id": "claude", "label": "Claude", "provider": "anthropic", "free": False, "site_key": False, "icon": "🧠",
     "blurb": "not free · needs your own key", "base_url": "https://api.anthropic.com",
     "key_url": "https://console.anthropic.com/settings/keys", "company": "Anthropic"},
]
DEFAULT_PROVIDER = "rules"

# ------------------------------------------------------------------ settings the screen does not show
AUTO = {
    "promos_per_episode": 1.2,    # list length = episodes x this ... (a quality floor still drops weak ones)
    "min_promos": 8,              # ... but never fewer than this
    "max_promos": 60,             # ... and never more than this
    "ai_call_budget": 40,         # most AI calls in one run (a 50-episode show needs about 26). Hosting secret
                                  # PROMOFORGE_MAX_CALLS overrides it.
}

# ------------------------------------------------------------------ pop-up wording
POPUP = {
    "paid_title": "🔑 {label} needs your own key",
    "paid_body": ["This AI is <b>not free</b>. To use it you need a key from the company that makes it ({company}).",
                  "If you have one, paste it below. If not, no problem: pick <b>Rule-based</b> or <b>Gemini</b>, both are free."],
    "missing_title": "🔑 {label} needs a free key",
    "missing_body": ["This site has no {label} key saved, so you need your own. It is <b>free</b> and takes about a minute."],
    "quota_title": "⏳ The free AI limit for today is finished",
    "quota_body": ["The free {label} limit on this site is used up for today, so these results were made in "
                   "<b>Rule-based</b> mode. It resets at about <b>{reset}</b> (midnight Pacific time).",
                   "Want AI right now? Make your own free key and paste it below, then press Run analysis again."],
    "badkey_title": "🔑 That key did not work",
    "badkey_body": ["{label} said no to this key. Check that you copied the <b>whole</b> key with no spaces, "
                    "or make a new one."],
    "free_key_steps": ["Open <b>{url}</b> and sign in with your Google account.",
                       "Click <b>Create API key</b>.",
                       "Copy the key and paste it below. Do not add a payment method. It stays free."],
    "paid_key_steps": ["Open <b>{url}</b> and sign in.", "Create a key and copy it.", "Paste it below."],
    "key_placeholder": "Paste your {label} key here",
    "key_note": "Your key is used only for this visit and is never saved.",
    "btn_use_key": "Use your key",
    "btn_use_gemini": "Use Gemini (free)",
    "btn_use_rules": "Use Rule-based",
}

# ------------------------------------------------------------------ how a promo's confidence is shown
STRENGTH = {
    "high": ("🔥 Strong pick", "good"),
    "medium": ("👍 Good pick", "ok"),
    "low": ("⚠️ Double-check", "warn"),
}

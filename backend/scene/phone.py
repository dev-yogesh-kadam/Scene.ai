"""Alerts on the admins' phones, through Telegram (a bot of their own) or ntfy (a topic in the ntfy app), or both.

Set in the admin console (Settings, Phone alerts) and kept in the `phone_alerts` setting. A message that can't be sent
is said in the app's window; it never stops the check that sent it.
"""

import json

import httpx

TELEGRAM = "https://api.telegram.org/bot{}/{}"
LABEL = {"critical": "Critical", "serious": "Serious", "warning": "Warning", "resolved": "Resolved", "test": "Test"}
# ntfy's priorities (5 is the loudest) and the tags it shows as emoji.
PRIORITY = {"critical": "5", "serious": "4", "warning": "3", "resolved": "3", "test": "3"}
TAGS = {"critical": "rotating_light", "serious": "warning", "warning": "warning", "resolved": "white_check_mark", "test": "bell"}


def config(db):
    try:
        found = json.loads(db.setting("phone_alerts", "") or "{}")
    except ValueError:
        found = {}
    return {"telegram_token": found.get("telegram_token", ""), "telegram_chat": found.get("telegram_chat", ""),
            "ntfy_url": found.get("ntfy_url", "")}


def save(db, found):
    db.set_setting("phone_alerts", json.dumps(found))


def shown(found):
    """The settings as the console shows them: the bot's token is never sent back, only its last four characters."""
    token = found["telegram_token"]
    return {"telegram_token_end": token[-4:] if token else "", "telegram_chat": found["telegram_chat"], "ntfy_url": found["ntfy_url"],
            "on": bool((token and found["telegram_chat"]) or found["ntfy_url"])}


async def send(http, db, level, text):
    """Send one alert everywhere it is set to go. Returns {channel: None if sent, else what went wrong}."""
    found, results = config(db), {}
    label = "Scene.ai: " + LABEL.get(level, level.capitalize())   # plain ASCII: it is also an HTTP header (ntfy's Title)
    if found["telegram_token"] and found["telegram_chat"]:
        results["telegram"] = await _attempt(http.post(TELEGRAM.format(found["telegram_token"], "sendMessage"),
                                                       json={"chat_id": found["telegram_chat"], "text": "{}\n{}".format(label, text)}))
    if found["ntfy_url"]:
        results["ntfy"] = await _attempt(http.post(found["ntfy_url"], content=text.encode("utf-8"), headers={
            "Title": label, "Priority": PRIORITY.get(level, "3"), "Tags": TAGS.get(level, "bell")}))
    for channel, problem in results.items():
        if problem:
            print("The {} alert could not be sent: {}".format(channel, problem))
    return results


async def _attempt(request):
    try:
        response = await request
    except httpx.HTTPError as error:
        return "it could not be reached ({})".format(type(error).__name__)
    if response.status_code >= 400:
        try:
            said = response.json().get("description") or response.json().get("error")
        except ValueError:
            said = None
        return "it answered {}{}".format(response.status_code, ": " + said if said else "")
    return None


async def telegram_chat(http, token):
    """The chat of the newest message the bot was sent: after the admin writes to their bot, this is their chat."""
    try:
        response = await http.get(TELEGRAM.format(token, "getUpdates"))
        updates = (response.json().get("result") or []) if response.status_code < 400 else None
    except (httpx.HTTPError, ValueError):
        return None
    if not updates:
        return None
    message = updates[-1].get("message") or updates[-1].get("my_chat_member") or {}
    chat = message.get("chat") or {}
    return str(chat["id"]) if chat.get("id") is not None else None

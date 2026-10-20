import json
import smtplib
import threading
import urllib.parse
import urllib.request
from email.mime.text import MIMEText

from . import db


def _telegram(text):
    tok, chat = db.get_setting("telegram_token"), db.get_setting("telegram_chat")
    if not (tok and chat):
        return None
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data, timeout=15).read()
    return "telegram"


def _email(title, text):
    host, to = db.get_setting("smtp_host"), db.get_setting("smtp_to")
    if not (host and to):
        return None
    msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = title, db.get_setting("smtp_from") or db.get_setting("smtp_user"), to
    s = smtplib.SMTP(host, int(db.get_setting("smtp_port") or 587), timeout=20)
    try:
        if db.get_setting("smtp_tls") == "1":
            s.starttls()
        if db.get_setting("smtp_user"):
            s.login(db.get_setting("smtp_user"), db.get_setting("smtp_pass"))
        s.sendmail(msg["From"], [a.strip() for a in to.split(",")], msg.as_string())
    finally:
        s.quit()
    return "email"


def _webhook(title, text):
    url = db.get_setting("webhook_url")
    if not url:
        return None
    req = urllib.request.Request(url, json.dumps({"title": title, "text": text}).encode(),
                                 {"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=15).read()
    return "webhook"


def send_sync(title, text):
    """Returns (sent_channels, errors)."""
    sent, errs = [], []
    for fn, args in ((_telegram, (f"{title}\n{text}",)), (_email, (title, text)), (_webhook, (title, text))):
        try:
            r = fn(*args)
            if r:
                sent.append(r)
        except Exception as e:  # noqa: BLE001
            errs.append(f"{fn.__name__}: {e}")
    return sent, errs


def notify(title, text, success):
    mode = db.get_setting("notify_on")
    if mode == "none" or (mode == "failure" and success):
        return
    threading.Thread(target=send_sync, args=(title, text), daemon=True).start()

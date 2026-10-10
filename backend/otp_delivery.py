"""Sending one-time codes. Provider is chosen in .env: console (server log), smtp (email), twilio (SMS).

OWNER: Nikhil (stream 2A). Add a provider by adding a function here and a line in PROVIDERS.
"""
import smtplib
from email.message import EmailMessage

import config


class DeliveryError(Exception):
    pass


def _text(code, purpose):
    what = {"register": "confirm your SkyClear account", "login": "sign in to SkyClear", "reset": "reset your SkyClear password"}.get(purpose, "continue")
    return f"Your SkyClear code is {code}. Use it to {what}. It expires in {config.OTP_TTL_MIN} minutes. If you did not ask for it, ignore this message."


def console(user, destination, code, purpose):
    print(f"[otp] to {destination} ({purpose}): {code}")  # development only, codes in logs are a leak in production


def smtp(user, destination, code, purpose):
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = config.SMTP_FROM, destination, f"Your SkyClear code: {code}"
    msg.set_content(_text(code, purpose))
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as s:
            if config.SMTP_USER:
                s.starttls()
                s.login(config.SMTP_USER, config.SMTP_PASSWORD)
            s.send_message(msg)
    except (OSError, smtplib.SMTPException) as e:
        raise DeliveryError(f"smtp: {e}")


def twilio(user, destination, code, purpose):
    import requests
    try:
        r = requests.post(f"https://api.twilio.com/2010-04-01/Accounts/{config.TWILIO_SID}/Messages.json",
                          auth=(config.TWILIO_SID, config.TWILIO_TOKEN), timeout=10,
                          data={"To": destination, "From": config.TWILIO_FROM, "Body": _text(code, purpose)})
        r.raise_for_status()
    except requests.RequestException as e:
        raise DeliveryError(f"twilio: {e}")


PROVIDERS = {"console": console, "smtp": smtp, "twilio": twilio}


def destination_for(user):
    """Where the code goes, by channel: the account's email, or its mobile number."""
    return user.get("phone") if config.OTP_CHANNEL == "sms" else user["email"]


def mask(destination):
    if not destination:
        return ""
    if "@" in destination:
        name, domain = destination.split("@", 1)
        return name[:1] + "***@" + domain
    return destination[:3] + "******" + destination[-4:]


def deliver(user, code, purpose):
    dest = destination_for(user)
    if not dest:
        raise DeliveryError("this account has no address to send the code to")
    PROVIDERS[config.OTP_PROVIDER](user, dest, code, purpose)
    return mask(dest)

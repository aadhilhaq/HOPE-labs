"""What differs between one cluster and the next, as a table rather than in code.

A person should have to know their account and their password, not where the lab keeps five
installs. Each tool carries its own install path (tools.py); this table is only about getting on
to the cluster.
"""
from __future__ import annotations

import os
import re

FEEDBACK_TO = os.environ.get("HOPELABS_FEEDBACK_TO") or "aadhil.haq@tamu.edu"

OTHER = "Other (SLURM)"

SITES = {
    "Grace (TAMU)": {
        "host": "grace.hprc.tamu.edu",
        "auth": "password",
        "hint": "Your NetID.",
        "label": "NetID",
        # Shown in the empty box. People type the address they sign in to TAMU email with, and
        # SSH wants the part before the @.
        "placeholder": "e.g. jdoe  (your NetID only, without @tamu.edu)",
        "note": "Password and a Duo approval, once, however many tools you open.",
    },
    "ACES (TAMU)": {
        # The login nodes are not reachable from outside: the way in is a gateway that accepts a
        # certificate and nothing else, downloaded from the ACES portal and good for 49 hours.
        "host": "login.aces.hprc.tamu.edu",
        "jump": "aces-jump.hprc.tamu.edu:8822",
        "key": "~/.ssh/id_aces_tamu",
        "auth": "certificate",
        "hint": "Your ACCESS account (u.ab123456), not your NetID.",
        "label": "Account",
        "placeholder": "e.g. u.ab123456  (your ACCESS account, not your NetID)",
        "note": "ACES takes a certificate, not a password: get id_aces_tamu and id_aces_tamu-cert.pub "
                "from portal-aces.hprc.tamu.edu (Utilities > sshca), put both in ~/.ssh, and connect "
                "within 49 hours. Not every tool is installed there.",
    },
    OTHER: {
        "host": "",
        "auth": "password",
        "hint": "Whatever you log in with.",
        "label": "Username",
        "placeholder": "your username on that cluster",
        "note": "Any cluster with SLURM and the lab's tools installed in the same layout.",
    },
}


def sites():
    """The names, with the real clusters first and Other last."""
    return [n for n in SITES if n != OTHER] + [OTHER]


def defaults_for(site_name, user=""):
    site = SITES.get(site_name) or {}
    return {
        "host": site.get("host", ""),
        "jump": site.get("jump", ""),
        "key": site.get("key", ""),
        "note": site.get("note", ""),
        "hint": site.get("hint", ""),
        "label": site.get("label", "Username"),
        "placeholder": site.get("placeholder", ""),
        "auth": site.get("auth", "password"),
        "feedback": FEEDBACK_TO,
    }


def clean_user(text):
    """The account as SSH wants it: no spaces, and no e-mail domain.

    The commonest mistake is typing the TAMU e-mail address, which SSH reads as a user called
    "jdoe@tamu.edu" and refuses in a way that looks like a wrong password. The part before the @
    is the NetID, so that is what is used.
    """
    text = (text or "").strip()
    return text.split("@", 1)[0].strip() if "@" in text else text


ACCOUNT_IN_PATH = re.compile(r"^/scratch/user/([^/]+)(/|$)")


def half_typed(path, user):
    """A saved path whose account segment is a strict prefix of the account now in the box was
    saved mid-keystroke, and is dropped rather than kept."""
    m = ACCOUNT_IN_PATH.match((path or "").strip())
    if not m or not user:
        return False
    seg = m.group(1)
    return seg != user and user.startswith(seg)


def parse_jump(text):
    """'host:port' -> (host, port); blank -> None."""
    text = (text or "").strip()
    if not text:
        return None
    host, _, port = text.partition(":")
    return (host, int(port) if port.strip().isdigit() else 22)


# The hub's own page is served on this computer. The band is above the tools' own, which take
# 8000-8999 (aptamer), 8900 (monitor), 9100-9899 (docking), 10100-10899 (HOPE-MD) and
# 11000-11799 (BindCraft2), so a forwarded tool never lands on the hub.
PORT_BASE = 12000
PORT_SPAN = 400


def suggested_port(user):
    seed = (user or "hope") + "|hope-labs"
    return PORT_BASE + (sum(ord(c) * (i + 1) for i, c in enumerate(seed)) % PORT_SPAN)

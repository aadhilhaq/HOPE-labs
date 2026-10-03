"""The settings file on this computer: the sign-in boxes, the installs, and the saved flows.

One module knows where the file is and how it is written, because three parts of the launcher
read it: the window saves the sign-in boxes into it, the hub reads the installs out of it, and
the canvas keeps its flows there. It is deliberately free of tkinter, so the hub can use it on a
machine with no display.

The file is in the person's own home folder on their own computer. Nothing here is ever written
on the cluster: a flow is a few hundred bytes of what was drawn, and it belongs beside the
settings it was drawn with rather than in a quota on Grace.
"""
from __future__ import annotations

import json
import os

CONFIG = os.path.join(os.path.expanduser("~"), ".hope_labs.json")
SCHEMA = 1


def load():
    try:
        with open(CONFIG) as fh:
            kept = json.load(fh)
        return kept if isinstance(kept, dict) else {}
    except (OSError, ValueError):
        return {}


def save(d):
    """Keep these settings, and whatever else is already in the file with them.

    The sign-in boxes are not the only thing kept here: "root" and "installs" are written by
    hand (docs/install-on-grace.md) and "flows" by the canvas, and a save that wrote only its own
    keys would delete them the moment Sign in was pressed, which is to say before they were ever
    read.
    """
    kept = load()                      # before the open below truncates it
    kept.update(dict(d, schema=SCHEMA))
    try:
        with open(CONFIG, "w") as fh:
            json.dump(kept, fh, indent=1)
    except OSError:
        pass


# ---- the flows a person saved ---------------------------------------------
# Kept under one key as {name: the flow as drawn}, which is the shape flow.Flow reads and writes.
# A flow carries its own name as well, so one taken out of the file is a whole flow document and
# can be handed to the runner as it stands.

def flows():
    """Every saved flow, newest name last, as a list of flow documents."""
    kept = load().get("flows")
    if not isinstance(kept, dict):
        return []
    out = []
    for name in sorted(kept, key=lambda n: n.lower()):
        one = kept[name]
        if isinstance(one, dict):
            out.append(dict(one, name=one.get("name") or name))
    return out


def flow_named(name):
    return next((f for f in flows() if f.get("name") == name), None)


def flow_save(doc):
    """Keep this flow under its own name, replacing one saved under that name before.

    The name is the flow's, not a separate label: a flow is reopened, edited and saved again, and
    two names for one thing would be two things the moment one of them was changed.
    """
    name = str((doc or {}).get("name") or "").strip()
    if not name:
        raise ValueError("the flow needs a name before it can be kept")
    kept = load().get("flows")
    kept = dict(kept) if isinstance(kept, dict) else {}
    kept[name] = doc
    save({"flows": kept})
    return flows()


def flow_delete(name):
    kept = load().get("flows")
    kept = dict(kept) if isinstance(kept, dict) else {}
    kept.pop(str(name or ""), None)
    save({"flows": kept})
    return flows()

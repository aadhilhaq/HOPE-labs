#!/usr/bin/env python3
"""Where the launcher's page comes from, and what keeps that safe.

The page is taken from the lab's install when that install's page can work against this
launcher's server, and from the build when it cannot. What is tested here is the deciding, since
getting it wrong either stops changes reaching people or serves them a page whose buttons call
routes their launcher does not have.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from hope_labs import PAGE_API, PAGE_NEEDS, hub                            # noqa: E402

fails = []


def check(cond, what):
    print("%s %s" % ("ok  " if cond else "FAIL", what))
    if not cond:
        fails.append(what)


check(isinstance(PAGE_API, int) and isinstance(PAGE_NEEDS, int),
      "the two contract numbers are numbers")
check(PAGE_NEEDS <= PAGE_API,
      "this build's own page needs %d and its server offers %d: it could not serve itself"
      % (PAGE_NEEDS, PAGE_API))


class FakeSFTP:
    """An install on the far end, as much of one as the deciding reads."""

    def __init__(self, text, files=hub.PAGE_FILES):
        self.text, self.files, self.taken = text, set(files), []

    def open(self, path):
        if not path.endswith("__init__.py"):
            raise IOError(path)
        return FakeFile(self.text)

    def get(self, there, here):
        name = there.rsplit("/", 1)[-1]
        if name not in self.files:
            raise IOError(there)
        self.taken.append(name)
        with open(here, "w") as fh:
            fh.write("# " + name + "\n")

    def listdir(self, path):
        raise IOError(path)

    def close(self):
        pass


class FakeFile:
    def __init__(self, text):
        self.text = text

    def read(self):
        return self.text.encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def version_of(text):
    return hub._page_version(FakeSFTP(text), "/where")


needs, version = version_of('__version__ = "9.9.9"\nPAGE_NEEDS = 4\n')
check((needs, version) == (4, "9.9.9"), "an install states what its page needs: %r" % ((needs, version),))

# An install from before these numbers existed served a page against the server it shipped with,
# so it is read as the first contract rather than refused.
needs, version = version_of('__version__ = "0.1.3"\n')
check(needs == 1, "an install from before the contract reads as the first one: %r" % needs)

check(hub._page_version(FakeSFTP(""), "/where")[0] in (1, None),
      "an install with no package at all is not mistaken for a newer one")


class NoFile(FakeSFTP):
    def open(self, path):
        raise IOError(path)


check(hub._page_version(NoFile(""), "/where") == (None, ""),
      "a folder that is not an install says so rather than guessing")
# --- the cards, which travel the same way the page does ----------------------
# A card added on the cluster must reach a launcher built before it, or every new tool means
# everybody downloading the programme again. The cards are data and travel; the rules about what
# may be linked to what are code and stay here.
import copy                                                                # noqa: E402
import json                                                                # noqa: E402

from hope_flow import cards                                                # noqa: E402

_built_in = copy.deepcopy(cards.catalogue())
check(_built_in.get("rules") == cards.RULES, "a catalogue says which rules it was written for")
check(json.loads(json.dumps(_built_in)) == _built_in, "and is plain JSON, which is how it travels")

_newer = copy.deepcopy(_built_in)
_newer["cards"].append({
    "key": "later", "name": "A Later Tool", "tagline": "added after this launcher was built",
    "tool": "later", "ready": True, "note": "",
    "inputs": [{"key": "target", "label": "target", "kinds": ["target"]}],
    "outputs": [{"key": "complexes", "label": "its designs", "kinds": ["complexes"]}],
    "settings": [{"key": "howmany", "label": "How many", "kind": "number", "default": 5}]})
check(cards.adopt(_newer), "a catalogue with a card this launcher has never seen is adopted")
check("later" in cards.BY_KEY, "and the card is there")
check(cards.link_refused("later", "complexes", "hopemd", "structures") == "",
      "the built-in rules judge the new card's links")
check(cards.link_refused("later", "complexes", "adcp", "sequences") != "",
      "including refusing the ones that make no sense")

_future = copy.deepcopy(_built_in)
_future["rules"] = cards.RULES + 7
check(cards.adopt(_future) == "",
      "a catalogue written for rules this launcher lacks is left alone rather than half-read")
for _rubbish in ({}, {"cards": []}, "not a catalogue", None,
                 {"cards": [{"key": "x"}]}):      # no target card
    check(cards.adopt(_rubbish) == "", "rubbish is refused: %r" % (_rubbish,))
check(cards.adopt(_built_in), "and the built-in catalogue can always be adopted back")
check(sorted(c.key for c in cards.CARDS) == sorted(c["key"] for c in _built_in["cards"]),
      "leaving the cards as they started")

print("\n%s" % ("ALL PASSED" if not fails else "%d FAILED" % len(fails)))
sys.exit(1 if fails else 0)

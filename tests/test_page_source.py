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
print("\n%s" % ("ALL PASSED" if not fails else "%d FAILED" % len(fails)))
sys.exit(1 if fails else 0)

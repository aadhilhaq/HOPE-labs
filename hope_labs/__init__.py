"""HOPE Labs: one front for the lab's tools on Grace.

The launcher signs in to the cluster once, then serves a page on this computer that lists every
tool the lab runs, starts the one you pick on a login node, and opens it in a tab of its own.
The tools are untouched: each is the page it always was, reached through the same connection, so
a person approves Duo once instead of five times.
"""

__version__ = "0.1.7"
APP = "HOPE Labs"
TAGLINE = "the lab's tools, in one place"
BLURB = "Docking, design and simulation on Grace, from one sign-in."
LAB = "HOPE Lab"
AUTHORS = ("Aadhil Haq",)
PI = "Dr. Sandun Fernando"
POWERED_BY = "Powered by HOPE Lab"

CREDIT = ("A launcher for the HOPE Lab's tools on Texas A&M HPRC; the methods each tool runs "
          "belong to their authors, and every run records what it used. %s." % POWERED_BY)

ACK = "Please acknowledge Texas A&M High Performance Research Computing (HPRC) for the computational resources."


def credit(sep=" · "):
    return CREDIT

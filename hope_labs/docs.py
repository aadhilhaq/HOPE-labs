"""The built-in documentation, served at /docs/ by the launcher's own page.

By Aadhil Haq

The layout, the stylesheet and the credit bar come from docskit, which HOPE Labs shares with the
HOPE pipelines, the aptamer pipeline and ADCP docking. This module holds only what is ours: the
sidebar, the colours of this page and the credit line.

A page is an HTML fragment in hope_labs/web/docs/pages/<slug>.html: an <h1>, a lead paragraph,
then sections under <h2>. Screenshots are in hope_labs/web/docs/img/, taken of the running page
by tools/docs_screenshots.py, so they show what the page really looks like. Both live under web/
rather than beside this module because web/ is the folder every build carries into the
executable, so the docs travel with it without a line of their own in the build.
"""
import os

from . import APP, __version__
from . import docskit
from .hub import WEB

HERE = os.path.join(WEB, "docs")

#: The sidebar, in order: (slug, title, section).
NAV = [
    ("index", "Overview", "Start here"),
    ("getting-started", "Getting started", "Start here"),

    ("tools", "The Tools page", "Using HOPE Labs"),
    ("windows", "A tool's tab", "Using HOPE Labs"),
    ("results", "Results", "Using HOPE Labs"),
    ("signing-out", "Signing out", "Using HOPE Labs"),

    ("own-installs", "Your own copies on Grace", "Your own copies"),

    ("how-it-works", "How it works", "Reference"),
    ("troubleshooting", "When something goes wrong", "Reference"),
    ("citing", "How to cite", "Reference"),
]

#: The same holders as the lab's other tools give in their LICENSE files, and the statement
#: HOPE-MD's and the pipelines' pages make. This repository has no LICENSE of its own yet; when it
#: gets one, its copyright line belongs here word for word.
COPYRIGHT = ("Copyright (c) 2026, Aadhil Haq and Sandun Fernando, "
             "HOPE Lab, Texas A&M University. All rights reserved.")

#: Who does the work, for the bar along the bottom: the one library every session runs through,
#: the one tool that is not the lab's, and the machine everything runs on.
CREDITS = [
    'SSH by <a href="https://www.paramiko.org/" target="_blank" rel="noopener">Paramiko</a>',
    "the tools by the HOPE Lab, BindCraft2 by the Pacesa lab",
    "computing by Texas A&amp;M HPRC",
]

#: The page's own colours, from the :root block in web/style.css, under the names the kit uses.
#: The marks take the page's second colour, the rust of the fourth square in the logo.
LIGHT = {"bg": "#eef3f3", "card": "#ffffff", "line": "#d7e2e2", "fg": "#0f1719",
         "dim": "#5f6f71", "accent": "#0d5c6b", "accent2": "#e3eef0", "mark": "#c2603a"}
DARK = {"bg": "#0b1113", "card": "#141d1f", "line": "#22302f", "fg": "#e6eeef",
        "dim": "#94a6a8", "accent": "#5fb3c4", "accent2": "#16292e", "mark": "#e08a63"}

#: Everything the shared layout needs to know about these docs.
SITE = docskit.Site(
    app=APP,
    tagline="the lab's tools, from one sign in",
    version=__version__,
    copyright=COPYRIGHT,
    nav=NAV,
    root=HERE,
    credits=CREDITS,
    # The page has no light or dark switch of its own; it follows the computer, and so do these.
    theme_key="",
    light=LIGHT,
    dark=DARK,
    shots="tools/docs_screenshots.py",
    # How to cite is a page here, opened in a tab of its own by app.js so the launcher's page
    # is not navigated away from.
    cite_href="/docs/citing.html",
)


def render(slug):
    """One page in the shared layout, or None when there is no such page."""
    return docskit.render(SITE, slug)


def respond(path):
    """(status, content type, body, location) for a request under /docs/."""
    return docskit.respond(SITE, path)


def creditbar():
    """The bar along the bottom of the launcher's page."""
    return docskit.creditbar_html(SITE, "/docs/index.html", cite_id="citebar")


def audit():
    """Everything wrong with the pages, as a list of sentences."""
    return docskit.audit(SITE)

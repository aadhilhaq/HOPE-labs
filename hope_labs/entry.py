"""What the launcher does when started, however it was started: `python -m hope_labs`, the
console script, or a bundled executable running a script that imports it."""
import sys


def main(argv=None):
    argv = sys.argv if argv is None else argv
    if "--version" in argv:
        from . import credit, __version__
        print("HOPE Labs %s\n%s" % (__version__, credit()))
        return 0
    # --selftest is for the build: a windowed executable cannot be driven without a display, but
    # it can prove that it starts, that its imports resolve and that what it needs came along.
    if "--selftest" in argv:
        from . import tools, tunnel, hub, clusters, credit            # noqa: F401
        assert len(tools.TOOLS) == 5, "a tool went missing from the catalogue"
        for tool in tools.TOOLS:
            line = tool.command(runs="~/r", port=8123)
            assert tool.install in line or '"$HOME"' in line, line
            assert '"$HOME"/r' in line, (tool.key, line)
        # the three handshakes, each read off what its tool actually prints
        assert tools.BY_KEY["hopemd"].ready("open  http://127.0.0.1:8098/?t=abcDEF_-", 0) == (8098, "abcDEF_-")
        assert tools.BY_KEY["aptamer"].ready("HOPE-APTAMER-LAUNCHER port=8123 node=login2\n"
                                             "HOPE-APTAMER-TOKEN abcdefghijklmnop12", 0) == (8123, "abcdefghijklmnop12")
        assert tools.BY_KEY["pipelines"].ready("something\nopen http://127.0.0.1:8900/?t=tok12345\n"
                                               "Ctrl-C here stops the server", 8900) == (8900, "tok12345")
        assert tools.BY_KEY["hopemd"].ready("nothing yet", 0) is None
        # A copy in somebody's own scratch: one root moves all five, a tool named on its own
        # wins over it, and nothing set leaves the lab's installs alone.
        mine = tools.installs_for("/scratch/user/jane.doe")
        assert len(mine) == 5 and mine["adcp"] == "/scratch/user/jane.doe/ADCP_docking", mine
        assert mine["hopemd"] == "/scratch/user/jane.doe/HOPE-MD/MD", mine
        assert tools.installs_for("") == {}, "no root means the lab's own installs"
        assert tools.installs_for("", {"hopemd": "/u/md"}) == {"hopemd": "/u/md"}
        assert tools.installs_for("/x", {"adcp": "/y"})["adcp"] == "/y"
        assert tools.rebase("/elsewhere/ADCP_docking", "/x") == "/elsewhere/ADCP_docking"
        # the start line follows the copy, and the monitor's environment and run root with it
        line = tools.BY_KEY["pipelines"].command(install=mine["pipelines"], port=8900)
        assert "/scratch/user/jane.doe/HOPE-pipelines" in line, line
        assert "/scratch/group/sflab" not in line, line
        assert '"$HL_ROOT"/envs/hope/bin/activate' in line and '--root "$HL_ROOT"' in line, line
        assert clusters.half_typed("/scratch/user/j/x", "jane.doe")
        # the account box: an e-mail address is cut to the name before the @, and every site
        # shows an example in the empty box
        assert clusters.clean_user(" jdoe@tamu.edu ") == "jdoe"
        assert clusters.clean_user("jdoe") == "jdoe" and clusters.clean_user("") == ""
        assert all(clusters.defaults_for(site)["placeholder"] for site in clusters.sites())
        assert "@tamu.edu" in clusters.defaults_for("Grace (TAMU)")["placeholder"]
        notes = []
        try:
            import paramiko
            notes.append("paramiko " + paramiko.__version__)
        except ImportError:
            notes.append("paramiko NOT INSTALLED - the launcher cannot connect until it is")
        try:
            from . import app
            assert hasattr(app, "App") and hasattr(app, "main"), "no window"
            # A hand-written "root" has to survive the sign-in boxes being written over it:
            # they are saved as Sign in is pressed, just before the installs are read.
            import tempfile, shutil, os as _os
            from . import settings as store
            tmp = tempfile.mkdtemp()
            try:
                store.CONFIG, keep = _os.path.join(tmp, "settings.json"), store.CONFIG
                app.save({"root": "/scratch/user/jane.doe"})
                store.flow_save({"version": 1, "name": "kept", "nodes": [], "edges": []})
                app.save({"site": "Grace (TAMU)", "user": "jane.doe"})
                kept = app.load()
                assert kept.get("root") == "/scratch/user/jane.doe", kept
                assert kept.get("user") == "jane.doe", kept
                assert [f["name"] for f in store.flows()] == ["kept"], kept
                assert app.chosen_installs(kept)["adcp"] == "/scratch/user/jane.doe/ADCP_docking"
                store.CONFIG = keep
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            notes.append("window ok, settings and flows kept across a sign-in")
        except ImportError as exc:
            notes.append("no tkinter here (%s)" % exc)
        import os
        for name in ("index.html", "app.js", "flow.js", "style.css", "tool.html", "tool.js"):
            path = os.path.join(hub.WEB, name)
            assert os.path.isfile(path), "the page is missing from the bundle: " + name
        notes.append("page ok")
        # The canvas: the card catalogue the runner reads, the example it starts from, and that a
        # binder too long to dock is cautioned rather than refused.
        from . import canvas
        from hope_flow.flow import Flow
        assert len(canvas.catalogue()["cards"]) == 8, "a card went missing from the catalogue"
        assert canvas.check(canvas.example())["problems"] == [], canvas.check(canvas.example())
        assert canvas.refusals({"binder_max": 100})["bindcraft:sequences>adcp:sequences"] == "", \
            "a long binder is refused rather than cautioned"
        long_doc = canvas.example()
        for node in long_doc["nodes"]:
            if node["card"] == "target":
                node["settings"]["binder_max"] = 100
            if node["card"] == "bindcraft":
                long_doc["edges"].append({"from": node["id"], "fromPort": "sequences",
                                          "to": "adcp", "toPort": "sequences"})
        said = Flow.from_json(long_doc).warnings()
        assert any("30 residues or fewer" in w for w in said), said
        notes.append("canvas ok, %d cards" % len(canvas.catalogue()["cards"]))
        # the docs ride along in web/, so a build that left them behind is caught here too
        from . import docs
        missing = docs.audit()
        assert not missing, "the docs are not whole: " + "; ".join(missing[:3])
        page = hub.index_page()
        assert "__CREDIT" not in page and 'class="creditbar"' in page, "the bar along the bottom is missing"
        notes.append("docs ok, %d pages" % len(docs.SITE.order))
        print("%s\n  %s\nSELFTEST OK" % (credit(), "\n  ".join(notes)))
        return 0
    from .app import main as run
    run()
    return 0

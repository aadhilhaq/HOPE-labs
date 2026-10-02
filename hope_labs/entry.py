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
        assert clusters.half_typed("/scratch/user/j/x", "jane.doe")
        notes = []
        try:
            import paramiko
            notes.append("paramiko " + paramiko.__version__)
        except ImportError:
            notes.append("paramiko NOT INSTALLED - the launcher cannot connect until it is")
        try:
            from . import app
            assert hasattr(app, "App") and hasattr(app, "main"), "no window"
            notes.append("window ok")
        except ImportError as exc:
            notes.append("no tkinter here (%s)" % exc)
        import os
        for name in ("index.html", "app.js", "style.css", "tool.html", "tool.js"):
            path = os.path.join(hub.WEB, name)
            assert os.path.isfile(path), "the page is missing from the bundle: " + name
        notes.append("page ok")
        print("%s\n  %s\nSELFTEST OK" % (credit(), "\n  ".join(notes)))
        return 0
    from .app import main as run
    run()
    return 0

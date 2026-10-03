#!/usr/bin/env python
"""Queue a design run through the pipelines' own submitting function, and print what it did.

Run by that pipeline's Python, not by the flow's: the two do not agree on a version. The settings
arrive as JSON on standard input, which is the shape the function wants, and one line of JSON goes
back out, which is what the flow reads.
"""
import json
import sys

root = sys.argv[1]
asked = json.load(sys.stdin)
from hope_monitor import launch                                            # noqa: E402

got = launch.submit(root, asked)
print(json.dumps({"jobid": str(got.get("jobid") or ""),
                  "problem": got.get("problem") or "",
                  "rundir": str(got.get("rundir") or ""),
                  "walltime": got.get("walltime") or "",
                  "remarks": (got.get("remarks") or "")[:400]}))

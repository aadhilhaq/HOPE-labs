"""HOPE-flow: the lab's tools, drawn as a graph and run as one.

A person draws a flow on the launcher's canvas - a target, the designs to make from it, where
those are docked, and what is simulated - and this queues the whole of it on the cluster. Each
card is the tool it always was, started the way its own page starts it; what is new is the
junctions between them, and that nobody has to be at the keyboard when one is reached.

Nothing of this stays running while a flow does. Every card is submitted with a dependency on
the one before it, so a flow that has been launched outlives the launcher, the laptop and the
connection that queued it.
"""

__version__ = "0.1.0"
APP = "HOPE-flow"
LAB = "HOPE Lab"
AUTHORS = ("Aadhil Haq",)
PI = "Dr. Sandun Fernando"
COPYRIGHT = ("Copyright (c) 2026, Aadhil Haq and Sandun Fernando, HOPE Lab, "
             "Texas A&M University. All rights reserved.")

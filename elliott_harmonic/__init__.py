"""Harmonic Elliott Wave engine (engine v2).

Inherits the data/pivot/horizon infrastructure of the classical `elliott`
engine and replaces the grammar/parser core with the Harmonic Elliott Wave
model (Ian Copsey, "Fractal Forecasting"):

- impulses subdivide as (a)(b)(c), not five subwaves
- six hard rules incl. the 176.4% wave-(iii) floor and the (iv)-vs-(b)-of-(iii) barrier
- scoring by ratio harmony (projection clusters, numeric alternation)

See .agents/skills/harmonic-elliott-core for the distilled specification.
"""

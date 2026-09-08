# Saturn V: CPACS Dataset

**SATURN V** — NASA’s Apollo Moon launcher, 1967–1973

A parametric digital model of the **Saturn V launch vehicle**, expressed in
[CPACS](https://cpacs.de/) and rendered with [TiGL](https://github.com/DLR-SC/tigl).

[![Build and deploy](https://github.com/DLR-SL/SaturnV-CPACS/actions/workflows/pages.yml/badge.svg)](https://github.com/DLR-SL/SaturnV-CPACS/actions/workflows/pages.yml)

**→ [Explore the model in your browser](https://dlr-sl.github.io/SaturnV-CPACS/)**

CPACS was designed for aircraft. This dataset asks how far it carries beyond
that: a 110 m multi-stage launch vehicle with cryogenic tanks, feed systems and
separation planes, described entirely via [CPACS](https://cpacs.de/), and turned into CAD geometry via [TiGL](https://github.com/DLR-SC/tigl).

<img width="447" height="367" alt="saturnV" src="https://github.com/user-attachments/assets/0b16b022-ffa8-4778-8365-8c7b4d4f2603" />

## Background

**CPACS** (Common Parametric Aircraft Configuration Schema) is an open XML
schema developed at [DLR](https://www.dlr.de/) for describing air and space
vehicles. Its purpose is to act as a *lingua franca* in multidisciplinary
design: aerodynamics, structures, propulsion and mission analysis tools all read
and write the same file. The
description is parametric and hierarchical: a fuselage is a chain of profiles,
positionings and transformations.

**TiGL** (TiGL Geometry Library) is the geometry kernel that goes with it.
Built on [OpenCASCADE](https://www.opencascade.com/), it turns the abstract
CPACS description into a B-rep geometry: lofted surfaces, boolean cutouts,
intersections. It ships C++, Python, MATLAB and Java bindings, plus
**TiGLCreator**, a desktop viewer for inspecting a CPACS file interactively.

This repository contains the CPACS file, the tooling to build geometry from it,
and a web viewer.

## What you can do with it

**Inspect it.** Open `cpacs/saturnV.xml` in TiGLCreator and walk the component
tree, or load `scripts/TiGL/load_model.js` to draw structure, tanks and systems
in one go. The [web viewer](https://dlr-sl.github.io/SaturnV-CPACS/) needs
nothing installed at all.

**Export geometry.** TiGL writes STEP, IGES, BREP, STL, VTK and Collada. The
included `scripts/export_models.py` exports each component as a separate binary
STL plus a JSON manifest, but the same API gives you a single watertight solid,
a specific stage, or a named component:

```python
from tigl3.tigl3wrapper import Tigl3
from tixi3.tixi3wrapper import Tixi3

tixi = Tixi3(); tixi.open("cpacs/saturnV.xml")
tigl = Tigl3(); tigl.open(tixi, "saturnV")
tigl.exportSTEP("saturn_v.stp")
```

**Use it as a test case.** Most CPACS tooling is exercised against transport
aircraft. A launch vehicle stresses different parts of the schema — tanks,
vessels, walls, ducts, fluid connections — which makes this dataset useful for
finding the corners where launcher geometry and an aircraft schema disagree.

**Change it.** Because the description is parametric, editing a station, a
diameter or a profile and re-running the export propagates through the whole
geometry. `scripts/XML/` holds generators that emit tank definitions from
dimensioned inputs, rather than hand-editing hundreds of coordinates.

**Build on it.** Every component carries a stable `uID`, so downstream tools can
attach mass, structural or thermal data to named parts without guessing at
geometry.


## Repository layout

| Path | Contents |
| --- | --- |
| `cpacs/` | The dataset. `saturnV.xml` is the single source of truth for the geometry. |
| `scripts/` | `export_models.py` (CPACS → STL via TiGL), `build_tigl.sh` (build TiGL from source), `render_saturnv.py` / `render.bat` (Blender stills), `TiGL/` (TiGLCreator scripts), `XML/` (tank geometry generators) |
| `web/` | Three.js viewer, bundled with Vite |
| `.github/workflows/` | Build and deployment pipeline |


## Getting started

### Just look at it

Open the [web viewer](https://dlr-sl.github.io/SaturnV-CPACS/). Components can be
toggled and faded individually.

### Open it in TiGLCreator

Install TiGL — the quickest route is conda:

```bash
conda install -c dlr-sc tigl3
tiglcreator --filename cpacs/saturnV.xml --script scripts/TiGL/load_model.js
```

`load_model.js` exists because `drawConfiguration()` only covers fuselages,
wings, rotors, pylons, nacelles and external objects — tanks and generic systems
have to be drawn explicitly.

## Sources

Geometry and station data are traced to primary documentation rather than
eyeballed from photographs. The full reference list, with per-dimension
citations, sits in the header comment of
[`cpacs/saturnV.xml`](cpacs/saturnV.xml) and includes Boeing assembly layout
drawings, MSFC flight manuals (SA-503 / SA-507), the North American Aviation
report on the S-II common bulkhead, and NASA technical reports — many of them
digitised and made accessible by [heroicrelics.org](http://heroicrelics.org/).

## Status

The model is developed incrementally, increasing both geometric fidelity and
semantic depth. Currently established: overall vehicle layout and stations,
structural sections of all three stages, all six propellant tanks, S-IC fuel and
LOX feed systems with pressurization, anti-slosh baffles, engine shrouds and
fins.

Known gaps: S-II and S-IVB engines, the service module engine, the command
module cabin element, and several launch escape system details (rod structure
and torus geometry) are not yet modelled.

Issues and pull requests are welcome — particularly corrections backed by
primary sources.


## License

Licensed under the [Apache License 2.0](LICENSE).

The CPACS dataset and the tooling in this repository are covered by that
license. The historical documents cited as sources are *not* redistributed here;
follow the links in the file header for the originals and their respective
terms.


*Part of ongoing CPACS development and experimentation at DLR.*

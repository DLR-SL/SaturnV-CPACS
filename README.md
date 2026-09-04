# CPACS Saturn V

A digital model of the **Saturn V launch vehicle** based on the [CPACS](https://cpacs.de/) data format.

The project explores how a complex historical launch vehicle can be represented using CPACS and its associated tooling, with a focus on a structured, parametric and interoperable aircraft/vehicle description.

## Preview

Explore the current model in the interactive web preview:

**[CPACS Saturn V – Interactive Preview](https://OWNER.github.io/REPO/)**

## Model

The Saturn V is modelled using the hierarchical structures provided by CPACS. The current work focuses on establishing the launcher geometry and its major propulsion and tank-related components.

The model is being developed incrementally, with the goal of increasing both the geometric fidelity and the semantic representation of the vehicle.

## Roadmap

### Until DLRK

* [ ] S-IC fuel system: 
  * [ ] extend systemArchitecture
  * [x] ⚠️ CPACS: extend `connectionType` enum `fluid`
  * [x] Improve pipe locations w.r.t. [Heroic Relics – S-IC Assembly Layout](http://heroicrelics.org/info/s-ic/s-ic-assy-layout.html)
  * [x] add main sloshing baffles
  * [x] add LOX pressurization
  * [x] add Tim's other systems (ordenance, flightControl)
* [ ] S-II 
  * [x] ⚠️ tanks: improve dimensions and decide on modelling approach (1 tank with 2 vessels?)
  * [ ] add engines
* [ ] S-IV
  * [x] ⚠️ tanks: add LOX tank, improve dimensions and decide on modelling approach 
  * [ ] add engines
* [ ] CSM
  * [ ] add engine
  * [ ] check/fix overall dimensions
  * [ ] ⚠️ add CM cabin element
* [ ] LES: fix dimensions, add missing rods, add torus after TiGL implementation
* [x] Fix positions according to historical documents
* [x] Add engine shrouds and fins
* [x] Add `parentUID` to fuel systems (tanks or motors?)
* [x] Fix launcher position to match the official stations

(⚠️: relevant for DLRK paper)

## Build and deployment

Every push to `main` runs [`.github/workflows/pages.yml`](.github/workflows/pages.yml),
which rebuilds the geometry and publishes the viewer to GitHub Pages:

| Job | What it does |
| --- | --- |
| `export-models` | Builds TiGL from source via [pixi](https://pixi.sh/), then runs `scripts/export_models.py` to export every CPACS component of `saturnV.xml` as a binary STL plus a `models.json` manifest. |
| `build-web` | Bundles the Three.js viewer in `web/` with Vite, with the models copied in as static assets. |
| `deploy` | Publishes the bundle to GitHub Pages. |

### One-time repository setup

Under **Settings → Pages**, set **Source** to **GitHub Actions**. Without it the
`deploy` job fails: the workflow deploys through `actions/deploy-pages` rather
than pushing to a `gh-pages` branch.

No secrets or tokens are needed — the built-in `GITHUB_TOKEN` and the
`pages: write` / `id-token: write` permissions declared in the workflow cover
the deployment.

### Knobs

Both live in the `export-models` job:

* `TIGL_REF` — the DLR-SC/tigl ref to build against. Point it at a feature
  branch when the model relies on TiGL changes that have not landed in `main`.
* `TIGL_DEFLECTION` — tessellation accuracy. TiGL's default `0.001` gives
  roughly 1,070,000 triangles for the full launcher; larger values mean smaller
  files and less VRAM in the browser.

The TiGL build is cached and keyed on the upstream commit, so only the first run
after a TiGL update pays the full build cost.

### Running the pipeline locally

```bash
# Build TiGL once (Linux/WSL; installs pixi under ~/.pixi and TiGL under ~/tigl)
bash scripts/build_tigl.sh

# Export the geometry
cd ~/tigl && pixi run -e python-internal python3 /path/to/repo/scripts/export_models.py

# Serve the viewer
cd web && npm ci && npm run dev
```

On Windows, `scripts/render.bat` wraps the export together with the Blender
stills used for presentations. Set `TIGL_REPO` to your TiGL checkout first.

### Deployment notes

The former GitLab pipeline pre-compressed the site into `.br` and `.gz`
sidecar files, because GitLab Pages only serves a compressed response when such
a file sits next to the original. GitHub Pages does no sidecar negotiation and
compresses on the fly instead, so that step was dropped in the port.

GitHub Pages compresses text content types (HTML, CSS, JS, JSON, SVG). Whether
it also compresses the binary STL payload is worth checking once after the
first deployment:

```bash
curl -s -o /dev/null -D - -H 'Accept-Encoding: br, gzip' \
  https://OWNER.github.io/REPO/models/s-ii_lh2.stl | grep -i content-encoding
```

If nothing comes back, the STLs are served uncompressed — roughly 53 MB instead
of the ~14 MB the GitLab deployment transferred. The fix in that case is to gzip
the STLs at build time and inflate them in the viewer via `DecompressionStream`,
or to raise `TIGL_DEFLECTION`.
## Development

The model is intended to serve as a practical example for working with CPACS beyond conventional aircraft configurations and to explore how complex launch-vehicle architectures can be represented within the CPACS ecosystem.

Further documentation and modelling details will be added as the project evolves.

---

*Part of the ongoing CPACS development and experimentation at DLR.*

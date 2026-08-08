# pymol-cli

Agent-oriented CLI for controlling a live Open-Source PyMOL session.

`pymol-cli` starts a small authenticated JSON-RPC engine inside PyMOL. The CLI
then attaches to that local engine and applies typed operations to the same GUI
session the user sees.

## Installation

Install the full Nix runtime:

```bash
nix profile install github:mulatta/research-skills#pymol-cli
```

Install the agent skill metadata without installing the CLI:

```bash
npx skills add mulatta/research-skills --skill pymol-cli
```

For cross-platform non-Nix development/runtime checks, use Pixi from a checkout:

```bash
pixi run check
pixi run pymol-cli engine start --headless
```

## Engine lifecycle

Start a GUI PyMOL engine by default:

```bash
pymol-cli engine start
```

Start headless PyMOL for CI, servers, or rendering-only workflows:

```bash
pymol-cli engine start --headless
```

Inspect and stop the current engine:

```bash
pymol-cli engine status
pymol-cli engine status --json
pymol-cli engine logs
pymol-cli engine logs --lines 200
pymol-cli engine stop
```

The engine descriptor is written to the user state directory by default. Pass
`--descriptor PATH` to isolate sessions or tests.

## Typed commands

Load a structure:

```bash
pymol-cli structure load model.pdb --object prot
pymol-cli structure load model.cif --object prot
```

Typed structure loading accepts existing local `.pdb`, `.ent`, `.cif`, and
`.mmcif` files only. Paths are resolved in the calling process before crossing
the engine boundary. Object names use ASCII letters, digits, and underscores;
all PyMOL identifier keywords (including `all`, `model`, and `object`) are
rejected. The active runtime's `cmd.get_legal_name()` must also return the exact
requested name, so PyMOL cannot silently rename the loaded object.

List objects and query atoms:

```bash
pymol-cli objects list
pymol-cli atoms count 'prot and polymer'
```

Change the scene:

```bash
pymol-cli scene show cartoon prot
pymol-cli scene show sticks 'prot and resn HEM'
pymol-cli scene hide lines prot
pymol-cli scene color cyan 'prot and chain A'
pymol-cli scene zoom prot --buffer 4
pymol-cli scene label-residues 'prot and name CA'
```

Render or save state:

```bash
pymol-cli render png view.png --width 1600 --height 1200 --dpi 200
pymol-cli session save session.pse
pymol-cli session restore session.pse
pymol-cli session clear
```

Only restore `.pse`/`.psw` files from trusted sources. PyMOL session files use
a pickle-backed format and are therefore excluded from the MCP tool surface.
Render output must end in `.png`; dimensions and DPI are bounded by the engine.
Use `--render-timeout SECONDS` for unusually long ray traces. Reaching that
deadline, disconnecting the caller, or cancelling an MCP render terminates the
active worker without disabling later renders.

Inspect session summary:

```bash
pymol-cli session summary
```

## Unsafe PML escape hatch

Raw PML is intentionally separated under `unsafe`:

```bash
pymol-cli unsafe command 'fragment ala, smoke'
pymol-cli unsafe command 'bg_color white'
```

Prefer typed commands for normal automation. Use `unsafe` only when a typed
operation does not exist or the user explicitly asks for raw PyMOL/PML behavior.

## GUI and headless behavior

- `pymol-cli engine start` opens a GUI PyMOL process and starts the engine from
  inside that process. Qt GUI builds pump engine work on the GUI owner thread so
  PyMOL command calls do not run from RPC client threads.
- `pymol-cli engine start --headless` launches `pymol -cq` and pumps engine work
  on the PyMOL owner thread. A regression test covers the previous hang where
  `pymol.cmd` was called directly from a socket client thread.
- Render requests snapshot the live session and render in a headless worker, so
  PNG output does not depend on the GUI framebuffer being visible or awake. Qt
  events continue while the worker renders. Cached initialization lets a fresh
  authenticated stop client bypass busy owner work, cancel the child, then close
  PyMOL from the next top-level Qt tick. If `pymol` is absent from `PATH`, the
  worker uses the current interpreter's `python -m pymol` entry point.
- Render output is verified as a nonempty PNG before atomic publication. Request
  deadlines and caller disconnects propagate cancellation to the active worker;
  cancellation removes temporary output and preserves any older target.
- Concurrent `engine start` calls are serialized with an OS file lock. A separate
  private mutation lock serializes descriptor reads, atomic replacements, and
  instance-owned deletion. Endpoint descriptors, locks, and token-bearing bootstrap
  files and engine logs use `0600` on POSIX or a protected current-user DACL on
  Windows.
- Launch nonces remain valid across executable wrappers without trusting parent-PID
  topology. Failed wrapper cleanup preserves a live descriptor whenever safe
  identity-bound termination is unavailable.

## Security boundaries

- MCP never exposes raw PML, Python execution, or session restore.
- Typed structure loading passes an explicit allowlisted parser to PyMOL; file
  extensions that PyMOL could execute (`.py`, `.pml`, `.pse`) are rejected.
- CLI `session restore` is trusted-local-file functionality, not a safe import
  mechanism for downloaded session files.
- Engine TCP accepts loopback connections only, requires a random descriptor
  token, limits clients/frame sizes, and times out incomplete authentication and
  frames.
- Descriptors record process creation identity. Windows compares creation FILETIME
  on the same process handle used for termination; Linux combines boot ID with start
  ticks and signals through `pidfd`. macOS and legacy descriptors refuse unsafe
  PID-only fallback. Stale descriptors therefore cannot kill a reused PID.
- Authenticated initialization returns server-owned `instance_id`; clients compare it
  with their descriptor snapshot before issuing domain operations.

## MCP adapter

Start PyMOL first, then run the stdio MCP adapter from your MCP client:

```bash
pymol-cli engine start
pymol-mcp
```

The MCP adapter exposes the typed engine operations only:

```text
atoms_count
structure_load
objects_list
scene_show
scene_hide
scene_color
scene_zoom
scene_label_residues
render_png
session_summary
session_clear
session_save
```

Raw PML is intentionally not exposed through MCP. Use the CLI-only
`pymol-cli unsafe command ...` escape hatch when raw PyMOL commands are
explicitly required. Pass `--descriptor PATH` to `pymol-mcp` if the engine was
started with a non-default descriptor. Tool calls remain FIFO while cancellation
notifications stay responsive during long renders or queued work.

## Legacy XML-RPC commands

The older XML-RPC surface is still present for compatibility:

```bash
pymol-cli launch --headless
pymol-cli status
pymol-cli do 'bg_color white'
pymol-cli script view.pml
pymol-cli load structure.cif --object protein
pymol-cli count 'polymer'
pymol-cli ligand-pocket --object protein --ligand HEM --chains A,B --send
```

New automation should prefer the engine hierarchy above. XML-RPC remains useful
only for attaching to existing `pymol -R` sessions or replaying old workflows.
`pymol-cli launch` now starts a detached process directly by default; pass
`--pueue` only when explicit pueue supervision is wanted.

---
name: pymol-cli
description: Control live Open-Source PyMOL sessions through the pymol-cli engine. Use when the user asks to open PyMOL, load structures, show/color/zoom selections, count atoms, render PNGs, save/restore sessions, or apply explicit PyMOL commands. Prefer typed engine commands; use raw PML only through the unsafe namespace when explicitly needed.
---

# pymol-cli

Use `pymol-cli` for local PyMOL visualization control. The current primary
workflow is an authenticated JSON-RPC engine started inside the local PyMOL
process. CLI commands attach to the descriptor for that engine.

## Core rules

- Start or verify the local engine before sending visualization commands:
  `pymol-cli engine status` then `pymol-cli engine start` if needed.
- GUI is the default. Use `pymol-cli engine start --headless` on servers, CI, or
  render-only tasks.
- Prefer typed commands (`structure`, `objects`, `atoms`, `scene`, `render`,
  `session`) over raw PML. The MCP adapter exposes only these typed operations.
- Raw PML belongs only under `pymol-cli unsafe command`. Use it when the user
  explicitly asks for a PyMOL command or no typed command exists.
- Typed structure loading accepts local `.pdb`, `.ent`, `.cif`, and `.mmcif`
  files only. Never rename scripts or sessions to bypass that allowlist. Use an
  ASCII identifier that is not a PyMOL keyword for `--object`; rewritten names
  are rejected rather than silently changed.
- Treat `.pse`/`.psw` restore as trusted-local-file functionality. PyMOL
  sessions are pickle-backed and MCP intentionally does not expose restore.
- Keep biological claims grounded in structure/sequence sources. PyMOL
  selections and renders are visualization/geometry evidence, not annotation
  authority.
- Do not connect to non-local hosts or reuse descriptors from another user unless
  explicitly instructed. Lifecycle code authenticates server `instance_id` against
  its descriptor snapshot and refuses forced shutdown without a Windows process
  handle or Linux pidfd bound to matching creation identity.

## Common commands

```bash
# Start PyMOL with the embedded local engine
pymol-cli engine start
pymol-cli engine start --headless

# Check/stop the engine
pymol-cli engine status
pymol-cli engine status --json
pymol-cli engine logs
pymol-cli engine logs --lines 200
pymol-cli engine stop

# Load and inspect structures
pymol-cli structure load model.pdb --object prot
pymol-cli structure load model.cif --object prot
pymol-cli objects list
pymol-cli atoms count 'prot and polymer'

# Scene operations
pymol-cli scene show cartoon prot
pymol-cli scene show sticks 'prot and resn HEM'
pymol-cli scene hide lines prot
pymol-cli scene color cyan 'prot and chain A'
pymol-cli scene zoom prot --buffer 4
pymol-cli scene label-residues 'prot and name CA'

# Render/session operations
pymol-cli render png view.png --width 1600 --height 1200 --dpi 200
pymol-cli session summary
pymol-cli session save session.pse
pymol-cli session restore session.pse
pymol-cli session clear

# Explicit unsafe PML escape hatch
pymol-cli unsafe command 'bg_color white'
pymol-cli unsafe command 'fragment ala, smoke'
```

Use `--descriptor PATH` when working with a non-default engine descriptor.

## Recommended workflow

1. Start the engine:

   ```bash
   pymol-cli engine start
   ```

2. Load the model:

   ```bash
   pymol-cli structure load structures/4hhb_assembly1.cif --object hb
   ```

3. Apply a reproducible view:

   ```bash
   pymol-cli scene show cartoon 'hb and polymer'
   pymol-cli scene color red 'hb and chain A+C'
   pymol-cli scene color marine 'hb and chain B+D'
   pymol-cli scene show sticks 'hb and resn HEM'
   pymol-cli scene color orange 'hb and resn HEM'
   pymol-cli scene zoom hb --buffer 8
   ```

4. Render or save the session:

   ```bash
   pymol-cli render png hb.png --width 1600 --height 1200 --dpi 200
   pymol-cli session save hb.pse
   ```


## MCP adapter

When an MCP client needs PyMOL tools, start the local engine first and run the
stdio adapter:

```bash
pymol-cli engine start
pymol-mcp
```

Available MCP tools mirror the typed engine API: `atoms_count`,
`structure_load`, `objects_list`, `scene_show`, `scene_hide`, `scene_color`,
`scene_zoom`, `scene_label_residues`, `render_png`, `session_summary`,
`session_clear`, and `session_save`. Raw PML and session restore are not
available through MCP.

Use `pymol-mcp --descriptor PATH` when the engine uses a non-default descriptor.

## Legacy XML-RPC compatibility

Older XML-RPC commands are still available for existing `pymol -R` sessions:

```bash
pymol-cli launch --headless
pymol-cli status
pymol-cli do 'bg_color white'
pymol-cli script view.pml
pymol-cli load structure.cif --object protein
pymol-cli count 'polymer'
pymol-cli ligand-pocket --object protein --ligand HEM --chains A,B --send
```

For new automation, prefer the engine hierarchy above.

## Troubleshooting

- Render requests snapshot the live session and render in a headless worker, so
  GUI sleep/visibility should not produce black PNGs. Output is verified before
  atomic publication. `--render-timeout`, caller disconnects, and MCP cancellation
  terminate active work without publishing partial output; later renders still work.
- `engine status` says no descriptor: run `pymol-cli engine start`.
- Check startup output with `pymol-cli engine logs` when PyMOL fails to become ready.
- Command times out: check whether PyMOL is still starting, crashed, or waiting
  for a GUI prompt. Retry with `--headless` for non-interactive environments.
- Selection counts are zero: verify object name, chain id, residue name, and
  whether the file contains the biological assembly or asymmetric unit.
- GUI opens but command changes do not appear: run `pymol-cli objects list` and
  `pymol-cli atoms count all` to confirm the CLI is attached to the expected
  engine descriptor.

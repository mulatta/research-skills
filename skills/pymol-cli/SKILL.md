---
name: pymol-cli
description: Control, inspect, and render local Open-Source PyMOL sessions through pymol-cli's authenticated typed engine and MCP interface. Use whenever the user asks to load PDB or mmCIF structures, inspect objects or atom selections, change molecular representations, colors, labels, or views, render PNG images, manage PyMOL sessions, inspect ligands or binding pockets, or automate repeatable molecular visualization through the installed CLI. Do not use for developing PyMOL plugins or for unrelated structure prediction, docking, sequence, or literature tasks. Prefer typed engine operations; use legacy XML-RPC only for an explicitly existing `pymol -R` session.
compatibility: Requires pymol-cli and a compatible local Open-Source PyMOL installation. GUI operation requires a graphical session; headless operation does not.
---

# pymol-cli

Use `pymol-cli` to control a local GUI session the user sees or an explicitly started headless session. New automation uses the authenticated typed engine. Legacy XML-RPC commands exist only to attach to an explicitly requested `pymol -R` session.

## Core rules

- Check `pymol-cli engine status` when engine state is uncertain. Start an engine only when no reachable engine exists. If reachable engine mode conflicts with requested visible or headless behavior, explain mismatch and ask before stopping or replacing it.
- Start GUI mode by default. Use `pymol-cli engine start --headless` for CI, servers, or rendering-only work.
- Prefer typed `structure`, `objects`, `atoms`, `scene`, `render`, and `session` commands.
- Inspect objects and atom counts before mutating a selection whose contents are uncertain.
- Use `pymol-cli unsafe command` only when no typed operation exists or user explicitly requests raw PML. Inspect exact command first. Require confirmation before code execution, filesystem or network access, or destructive behavior; never interpolate untrusted metadata into raw PML.
- Do not treat a downloaded `.pse` or `.psw` file as safe data. Session restore is trusted-local functionality backed by Python pickle.
- Keep structure loads local and explicit. Typed loading accepts existing `.pdb`, `.ent`, `.cif`, and `.mmcif` files.
- Keep engine and legacy XML-RPC connections on localhost. Use a non-local legacy host only when user explicitly supplies and trusts it; XML-RPC has no engine token authentication.
- Inspect session summary and confirm or save state before `session clear`, `session restore`, or `engine stop`. Confirm before overwriting existing PNG or session output.
- Save commands, paths, selections, and render settings when user needs reproducibility.
- Render visual deliverables, verify output is nonempty PNG, and inspect image when visual quality matters.
- Use structural databases or literature for biological claims. PyMOL selections and distances provide visualization or geometry evidence, not biological annotation by themselves.

## Choose interface

| Situation | Interface |
|---|---|
| Normal local GUI or headless automation | Typed engine CLI |
| Agent integration needing typed-only operations | MCP through `pymol-mcp` |
| Existing session explicitly started with `pymol -R` | Legacy XML-RPC CLI |
| Missing typed operation or explicit raw PML request | CLI-only `unsafe command` |

Do not start a typed engine and legacy XML-RPC session for the same task unless user explicitly wants separate sessions.

## Standard workflow

1. Check current engine:

   ```bash
   pymol-cli engine status --json
   ```

2. If unavailable, start GUI engine. Use `--headless` only when task or environment requires it:

   ```bash
   pymol-cli engine start
   ```

3. Load local structure:

   ```bash
   pymol-cli structure load structure.cif --object prot
   ```

4. Inspect before styling:

   ```bash
   pymol-cli objects list --json
   pymol-cli atoms count 'prot and polymer' --json
   ```

5. Apply typed scene operations:

   ```bash
   pymol-cli scene show cartoon 'prot and polymer'
   pymol-cli scene hide lines prot
   pymol-cli scene color cyan 'prot and chain A'
   pymol-cli scene zoom prot --buffer 5
   pymol-cli scene label-residues 'prot and chain A and resi 58+87'
   ```

6. Render and verify:

   ```bash
   pymol-cli render png view.png --width 1600 --height 1200 --dpi 300
   ```

7. Inspect session summary when reporting final state:

   ```bash
   pymol-cli session summary --json
   ```

Read [typed command reference](references/typed-commands.md) when exact command coverage or flags are unclear. Treat `pymol-cli <group> <command> --help` as canonical interface.

## Common workflows

### Load and style one structure

```bash
pymol-cli engine status --json
pymol-cli structure load model.cif --object prot
pymol-cli scene show cartoon 'prot and polymer'
pymol-cli scene color gray70 'prot and polymer'
pymol-cli scene zoom prot --buffer 5
```

Typed object names use ASCII letters, digits, and underscores. Reserved PyMOL identifiers such as `all`, `model`, `object`, and `protein` are rejected.

### Inspect a selection

```bash
pymol-cli objects list --json
pymol-cli atoms count 'prot and chain A' --json
pymol-cli atoms count 'prot and resn ATP' --json
```

A zero count means selection needs investigation. Verify object name, chain identifiers, residue names, and whether file contains asymmetric unit or biological assembly.

### Change representation and color

```bash
pymol-cli scene hide lines prot
pymol-cli scene show surface 'prot and chain A'
pymol-cli scene show cartoon 'prot and chain B'
pymol-cli scene color cyan 'prot and chain A'
pymol-cli scene color slate 'prot and chain B'
```

### Use missing PyMOL operation

Typed engine currently has no general rotate, orient, transparency, background, alignment, or spectrum operation. Use narrow raw PML only when needed:

```bash
pymol-cli unsafe command 'rotate x, 30'
pymol-cli unsafe command 'bg_color white'
```

Never invent a typed subcommand. Record recurring missing operations as CLI feature gaps.

### Save trusted session

```bash
pymol-cli session save view.pse
```

Restore only user-created or otherwise trusted sessions:

```bash
pymol-cli session restore trusted-view.pse
```

Read [security boundaries](references/security.md) before restoring sessions, loading unusual files, or using raw PML.

### Inspect a ligand pocket with typed selections

```bash
pymol-cli atoms count 'prot and resn ATP' --json
pymol-cli atoms count 'byres (prot and polymer within 4 of (prot and resn ATP))' --json
pymol-cli scene show sticks 'byres (prot and polymer within 4 of (prot and resn ATP))'
pymol-cli scene color yelloworange 'byres (prot and polymer within 4 of (prot and resn ATP))'
pymol-cli scene zoom 'prot and resn ATP' --buffer 5
```

Require nonzero ligand and pocket counts before styling. Use legacy `ligand-pocket` helper only against matching XML-RPC session.

## MCP

Start engine first, then launch adapter:

```bash
pymol-cli engine start
pymol-mcp
```

MCP exposes typed operations only. It intentionally omits raw PML and session restore, but it still has authorized local file read/write capability and is not an untrusted-input sandbox. Read [MCP reference](references/mcp.md) when configuring an MCP client or handling cancellation.

## Legacy XML-RPC

Use legacy commands only when user explicitly references an existing `pymol -R` session or old workflow:

```bash
pymol-cli status --host localhost --port 9123
pymol-cli do --host localhost --port 9123 'bg_color white'
```

Read [legacy XML-RPC reference](references/legacy-xmlrpc.md) before using `launch`, `status`, `do`, `script`, legacy `load`, legacy `count`, or `ligand-pocket`.

## Troubleshooting

- Missing descriptor: start engine.
- Descriptor exists but connection fails: inspect `pymol-cli engine logs`; do not delete or kill processes by PID manually.
- Selection count is zero: inspect objects, chains, residue names, and assembly choice.
- Render deadline expires: increase `--render-timeout` or render without `--ray`.
- GUI or Qt startup fails: report failure; use `--headless` only when user accepts headless operation.
- Existing `pymol -R` session: use legacy compatibility surface rather than silently creating another session.

Read [engine lifecycle](references/engine-lifecycle.md) for process or descriptor failures and [troubleshooting](references/troubleshooting.md) for decision trees.

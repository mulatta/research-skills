# Typed command reference

Use this reference for current authenticated engine coverage. Run `pymol-cli <group> <command> --help` before relying on flags not listed here.

## Engine

Representative forms; consult subcommand help for complete flags.

```bash
pymol-cli engine start [--headless] [--descriptor PATH] [--log PATH]
pymol-cli engine status [--descriptor PATH] [--json]
pymol-cli engine logs [--descriptor PATH] [--lines N]
pymol-cli engine stop [--descriptor PATH]
```

## Structures and queries

```bash
pymol-cli structure load FILE --object NAME
pymol-cli objects list --json
pymol-cli atoms count SELECTION --json
```

Typed structure loading accepts existing local `.pdb`, `.ent`, `.cif`, and `.mmcif` files. Object names are validated against PyMOL legal-name behavior and reserved identifiers.

## Scene operations

```bash
pymol-cli scene show REPRESENTATION SELECTION
pymol-cli scene hide REPRESENTATION SELECTION
pymol-cli scene color COLOR SELECTION
pymol-cli scene zoom SELECTION [--buffer FLOAT]
pymol-cli scene label-residues SELECTION
```

Current typed coverage does not include general background, orient, rotate, transparency, alignment, RMSD, spectrum, named selections, or scene storage. Do not invent commands for these operations.

## Rendering

Example with every optional render setting enabled:

```bash
pymol-cli render png view.png --width 1600 --height 1200 --dpi 200 --ray --render-timeout 120
```

Output must end in `.png`. Engine bounds dimensions and DPI, renders to temporary target, validates nonempty PNG, then publishes atomically.

## Sessions

Inspect summary and confirm or save state before clear, restore, or stop. Confirm before replacing an existing session or render output.

```bash
pymol-cli session summary --json
pymol-cli session clear
pymol-cli session save FILE.pse
pymol-cli session restore TRUSTED_FILE.pse
```

Session restore is CLI-only trusted-local behavior and is not part of MCP surface.

## Unsafe escape hatch

```bash
pymol-cli unsafe command 'ONE PML COMMAND'
```

Use only for missing typed operations or explicit raw PML request. MCP never exposes this operation.

## Common attach options

Typed engine commands accept some or all of:

```text
--descriptor PATH
--timeout SECONDS
--render-timeout SECONDS
--json
```

Consult subcommand help because not every option applies to every command.

# MCP reference

Read this reference when configuring `pymol-mcp`, choosing CLI versus MCP, or handling cancellation.

## Start

```bash
pymol-cli engine start
pymol-mcp
```

Pass `--descriptor PATH` to `pymol-mcp` when engine uses non-default descriptor.

## Exposed tools

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

MCP does not expose raw PML, Python execution, session restore, or legacy XML-RPC helpers. Keep those exclusions intact. Typed-only means reduced capability, not sandboxing: do not expose adapter or descriptor to an untrusted client.

## Selection guidance

Inspect with `objects_list` and `atoms_count` before mutation when selection is uncertain. MCP tool calls remain FIFO. Cancellation notifications remain responsive while long render or queued work is active.

## File boundaries

`structure_load` can read arbitrary authorized local paths with allowed structure extensions. `session_save` and `render_png` can create directories and replace authorized local targets. Validate every read/write path and confirm before overwrite. `session_clear` destroys current state, so inspect and save or confirm first.

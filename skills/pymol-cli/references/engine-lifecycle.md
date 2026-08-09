# Engine lifecycle

Read this reference when engine startup, shutdown, descriptor, GUI, or headless behavior needs diagnosis.

## Normal lifecycle

```bash
pymol-cli engine status --json
pymol-cli engine start
pymol-cli engine logs --lines 80
pymol-cli engine stop
```

`engine start` opens GUI PyMOL by default. Add `--headless` only for CI, servers, or rendering-only workflows. If reachable descriptor mode differs from requested visible or headless behavior, report mismatch and ask before stopping or replacing that session. Concurrent starts are serialized, so do not add external PID files or manual locks.

The engine descriptor lives in user state directory unless `--descriptor PATH` is supplied. Use same descriptor for all commands belonging to isolated session.

## Failure routing

### Descriptor does not exist

Run `engine start`. Do not fall back to legacy `launch` unless task explicitly requires XML-RPC.

### Descriptor exists but engine is unreachable

1. Run `engine status --json`.
2. Read `engine logs --lines 200`.
3. Check whether descriptor path was overridden.
4. Use `engine stop` only when authenticated identity checks permit safe termination.
5. Start fresh engine after stale state has been resolved.

Inspect session summary and save user state before stopping a reachable engine. Confirm before closing a user-visible GUI. Do not kill descriptor PID manually. Descriptor includes process identity data specifically to avoid terminating reused PIDs.

### GUI startup fails

Report Qt/display error. Ask before changing requested visible workflow to headless. `--headless` changes user-visible behavior even though rendering remains available.

### Long render blocks work

Render uses separate headless worker and supports cancellation. Increase `--render-timeout SECONDS` only when ray trace is expected to exceed default. Cancellation must preserve older target and remove temporary output.

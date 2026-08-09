# Troubleshooting

Use this reference after normal typed workflow fails.

## Cannot connect

```text
Does descriptor exist?
├─ no  → pymol-cli engine start
└─ yes → pymol-cli engine status --json
          ├─ reachable   → continue task
          └─ unreachable → pymol-cli engine logs --lines 200
```

Confirm same `--descriptor` path is used. Do not switch to legacy XML-RPC merely because typed engine is unavailable.

## Selection returns zero atoms

1. `pymol-cli objects list --json`
2. Count object: `pymol-cli atoms count 'OBJECT' --json`
3. Count chain: `pymol-cli atoms count 'OBJECT and chain A' --json`
4. Count residue: `pymol-cli atoms count 'OBJECT and resn LIG' --json`
5. Check whether input is asymmetric unit or biological assembly.

Avoid mutating scene until expected selection is nonzero.

## Render fails or times out

- Confirm output ends in `.png`.
- Confirm parent path is writable.
- Retry without `--ray` when ray tracing is unnecessary.
- Increase `--render-timeout` when expensive ray render is expected.
- Verify older target remains intact after cancellation or failure.

## Operation lacks typed command

Check `pymol-cli --help` and relevant group help. If genuinely absent, use one narrow `unsafe command` or legacy interface only when its session model matches task. Never invent a typed subcommand.

## Existing PyMOL window is not typed engine

Ask how session was started. If it is explicit `pymol -R`, use legacy XML-RPC. Otherwise explain that ordinary PyMOL window cannot be safely attached and ask before restarting it under `pymol-cli engine start`.

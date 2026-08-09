# Legacy XML-RPC compatibility

Use this surface only for an explicitly existing `pymol -R` session or replaying an old workflow. New automation should use authenticated typed engine commands. Keep XML-RPC on localhost unless user explicitly supplies and trusts a remote host; this legacy surface has no engine token authentication.

## Connect to existing session

```bash
pymol-cli status --host localhost --port 9123
pymol-cli do --host localhost --port 9123 'bg_color white'
pymol-cli script --host localhost --port 9123 view.pml
pymol-cli count --host localhost --port 9123 'polymer'
```

## Start XML-RPC session

```bash
pymol-cli launch
pymol-cli launch --headless
pymol-cli launch --pueue
```

Legacy `launch` starts detached process directly by default. `--pueue` is opt-in, not default.

## Legacy load helper

```bash
pymol-cli load structure.cif --object prot --style cartoon --color gray70
```

This helper generates PML and sends it through XML-RPC. Remote URL loading requires explicit `--allow-url`. Prefer typed `structure load` for local files.

## Ligand pocket helper

```bash
pymol-cli ligand-pocket   --object prot --ligand HEM --chains A,B --distance 4   --color A:cyan --color B:slate   --mark A:58,87 --mark B:63,92   --grid --scene heme_pockets --output heme-pockets.pml --send
```

Without `--send`, helper generates PML. Before sending, it validates ligand presence and marked residues unless `--no-validate` is supplied. `--strict-chains` rejects partial chain occupancy.

Do not describe this helper as typed engine or MCP functionality. Do not silently launch separate XML-RPC PyMOL solely to use helper against typed engine session.

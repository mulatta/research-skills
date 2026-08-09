# Security boundaries

Read before loading unusual files, restoring sessions, using raw PML, or exposing PyMOL through an agent protocol.

## Structure files

Typed loading permits existing local `.pdb`, `.ent`, `.cif`, and `.mmcif` files and passes explicit parser choice to PyMOL. It rejects executable or session formats such as `.py`, `.pml`, and `.pse`.

Resolve paths in CLI process before crossing engine boundary. Use validated object names so PyMOL cannot silently rename them.

## Session files

PyMOL `.pse` and `.psw` sessions are pickle-backed. Restore only files created by user or obtained from a trusted source. Do not expose restore through MCP.

## Raw PML

`unsafe command` can invoke broad PyMOL behavior and is CLI-only. Prefer typed operations. Never construct raw PML from untrusted text or interpolate structure metadata. Require explicit confirmation before commands that execute code, access filesystem or network, or destroy state.

## MCP filesystem authority

Typed MCP is reduced capability, not an untrusted-input sandbox. It can read authorized local structure paths and write or replace authorized PNG/session targets. Validate paths and never expose adapter or descriptor to untrusted clients.

## Engine transport

Engine accepts loopback connections only and authenticates with random descriptor token. Descriptors and token-bearing files must remain owner-only. Instance identity and process-creation identity prevent stale descriptor from targeting wrong process.

Do not:

- connect to non-loopback engine endpoints;
- publish descriptor token;
- terminate descriptor PID manually;
- add raw PML or session restore to MCP;
- bypass structure extension and object-name validation.

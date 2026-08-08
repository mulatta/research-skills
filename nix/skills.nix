_:

# Single source of truth for skill ↔ package mapping.
#
# Fields (all optional):
#   package – package attr name from `self.packages.<system>` to install
#             (default: <name>). Package must carry `share/skills/<name>/`.
#   extra   – additional home-manager module to merge into per-skill module.
{
  pymol-cli = { };
}

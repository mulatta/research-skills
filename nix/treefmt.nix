_: {
  projectRootFile = "flake.nix";
  programs.nixfmt.enable = true;
  programs.ruff.format = true;
  programs.ruff.check = true;

  programs.mypy.enable = true;
  programs.mypy.directories."pymol-cli/pymol_cli" = { };

  settings.global.excludes = [ "*.lock" ];
}

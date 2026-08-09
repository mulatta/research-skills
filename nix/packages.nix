{ callPackage }:
{
  biomcp = callPackage ../biomcp/package.nix { };
  pymol-cli = callPackage ../pymol-cli { };
}

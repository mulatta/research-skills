{ biomcp, callPackage }:
{
  inherit biomcp;
  pymol-cli = callPackage ../pymol-cli { };
}

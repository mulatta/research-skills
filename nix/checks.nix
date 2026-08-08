{
  lib,
  packages,
  treefmtCheck,
}:

lib.mapAttrs' (name: lib.nameValuePair "package-${name}") packages // { formatting = treefmtCheck; }

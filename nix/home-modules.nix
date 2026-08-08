{
  self,
  inputs,
  lib,
}:
let
  registry = import ./skills.nix { inherit inputs; };

  mkBaseModule =
    name: def:
    { pkgs, config, ... }:
    let
      packageName = def.package or name;
      pkg = self.packages.${pkgs.stdenv.hostPlatform.system}.${packageName};
      skillDir = "${pkg}/share/skills/${name}";
    in
    {
      key = "research-skills/base/${name}";
      home.packages = [ pkg ];
      home.file = lib.listToAttrs (
        map (
          dir: lib.nameValuePair "${dir}/${name}" { source = skillDir; }
        ) config.programs.research-skills.skillDirs
      );
    };

  mkSkillModule =
    name: def:
    let
      extra = def.extra or (_: { });
    in
    {
      key = "research-skills/${name}";
      imports = [
        ./home-manager-common.nix
        (mkBaseModule name def)
        (extra { inherit self inputs; })
      ];
    };
in
builtins.mapAttrs mkSkillModule registry

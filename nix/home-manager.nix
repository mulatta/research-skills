{
  self,
  inputs,
}:
{
  lib,
  config,
  pkgs,
  ...
}:
let
  cfg = config.programs.research-skills;

  registry = import ./skills.nix { inherit inputs; };

  allSkills = builtins.attrNames registry;
  defaultSkills = allSkills;

  skillPackage =
    name:
    let
      packageName = registry.${name}.package or name;
    in
    cfg.package.${packageName};

  skillSource = name: "${skillPackage name}/share/skills/${name}";
in
{
  imports = [ ./home-manager-common.nix ];

  options.programs.research-skills = {
    enable = lib.mkEnableOption "research-skills LLM agent tools";

    skills = lib.mkOption {
      type = lib.types.listOf (lib.types.enum allSkills);
      default = defaultSkills;
      description = ''
        Which skills to install. CLI skills install the tool binary into
        `home.packages` and the corresponding skill definition into every
        directory listed in `programs.research-skills.skillDirs`.

        Defaults to all CLI-backed skills.
      '';
      example = [ "pymol-cli" ];
    };

    package = lib.mkOption {
      type = lib.types.attrsOf lib.types.package;
      default = self.packages.${pkgs.stdenv.hostPlatform.system};
      defaultText = lib.literalExpression "self.packages.${pkgs.stdenv.hostPlatform.system}";
      description = "Attribute set of research-skills packages.";
    };

    skillsSrc = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      description = ''
        Deprecated. Skill definitions now ship inside the packages at
        `$out/share/skills/<name>/`; this option is ignored.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    warnings =
      lib.optional (cfg.skillsSrc != null)
        "programs.research-skills.skillsSrc is deprecated and ignored; skill files now ship inside the packages.";

    home.packages = map skillPackage cfg.skills;

    home.file = lib.listToAttrs (
      lib.concatMap (
        name:
        map (dir: {
          name = "${dir}/${name}";
          value.source = skillSource name;
        }) cfg.skillDirs
      ) cfg.skills
    );
  };
}

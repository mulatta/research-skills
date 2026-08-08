{
  formatter,
  pkgs,
}:

let
  nativePackages =
    with pkgs;
    [
      git
      mypy
      nodejs
      pymol
      python3
      python3Packages.pytest
      ruff
    ]
    ++ [
      formatter
    ];
in
{
  default = pkgs.mkShellNoCC {
    packages = nativePackages;
  };

  uv = pkgs.mkShellNoCC {
    packages = nativePackages ++ [ pkgs.uv ];
    UV_PYTHON_DOWNLOADS = "never";
  };

  pixi = pkgs.mkShellNoCC {
    packages = with pkgs; [
      git
      pixi
    ];
  };
}

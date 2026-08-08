{
  lib,
  pymol,
  python3Packages,
}:

python3Packages.buildPythonApplication {
  pname = "pymol-cli";
  version = "0.1.0";

  src = ./.;

  pyproject = true;

  build-system = [ python3Packages.hatchling ];

  dependencies = [ pymol ];

  makeWrapperArgs = [
    "--prefix"
    "PATH"
    ":"
    (lib.makeBinPath [ pymol ])
  ];

  nativeCheckInputs = [
    python3Packages.mypy
    python3Packages.pytestCheckHook
    python3Packages.ruff
    pymol
  ];

  postInstall = ''
    mkdir -p $out/share/skills
    cp -r ${../skills/pymol-cli} $out/share/skills/pymol-cli
  '';

  preCheck = ''
    ruff format --check .
    ruff check .
    mypy pymol_cli tests
  '';

  pythonImportsCheck = [ "pymol_cli" ];

  meta = {
    description = "Control authenticated local PyMOL engine and MCP sessions";
    license = lib.licenses.mit;
    mainProgram = "pymol-cli";
    maintainers = [ ];
  };
}

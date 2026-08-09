{
  lib,
  rustPlatform,
  fetchFromGitHub,
  stdenv,
  makeWrapper,
  cacert,
}:
rustPlatform.buildRustPackage (finalAttrs: {
  pname = "biomcp";
  version = "0.8.25";

  __structuredAttrs = true;
  strictDeps = true;

  src = fetchFromGitHub {
    owner = "genomoncology";
    repo = "biomcp";
    tag = "v${finalAttrs.version}";
    hash = "sha256-DhUfA3WcTtyYavMbGOURyzfhHNUJ0CEx9QTDvHITGH0=";
  };

  cargoHash = "sha256-aOrMShRasa7vEg3FC0IqGvAvUFtts+Z7xHfv/qOZxt0=";

  nativeBuildInputs = lib.optionals stdenv.hostPlatform.isLinux [ makeWrapper ];

  cargoTestFlags = [ "--lib" ];

  postInstall = ''
    mkdir -p "$out/share/skills/biomcp"
    cp -R ${finalAttrs.src}/skills/. "$out/share/skills/biomcp/"
  '';

  preCheck = ''
    export HOME="$TMPDIR/home"
    export XDG_CACHE_HOME="$TMPDIR/cache"
    export XDG_CONFIG_HOME="$TMPDIR/config"
    export XDG_DATA_HOME="$TMPDIR/data"
    mkdir -p "$HOME" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME"
  '';

  postFixup = lib.optionalString stdenv.hostPlatform.isLinux ''
    for bin in biomcp biomcp-cli; do
      wrapProgram "$out/bin/$bin" \
        --set-default SSL_CERT_FILE "${cacert}/etc/ssl/certs/ca-bundle.crt"
    done
  '';

  doInstallCheck = true;
  installCheckPhase = ''
    runHook preInstallCheck

    export HOME="$TMPDIR/home"
    export XDG_CACHE_HOME="$TMPDIR/cache"
    export XDG_CONFIG_HOME="$TMPDIR/config"
    export XDG_DATA_HOME="$TMPDIR/data"
    mkdir -p "$HOME" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME"

    $out/bin/biomcp --version
    $out/bin/biomcp-cli --version
    $out/bin/biomcp list >/dev/null
    $out/bin/biomcp serve-http --help >/dev/null

    test -f "$out/share/skills/biomcp/SKILL.md"
    diff -r ${finalAttrs.src}/skills "$out/share/skills/biomcp"

    runHook postInstallCheck
  '';

  passthru.category = "Data";

  meta = {
    description = "Biomedical CLI and MCP server for biomedical data sources";
    homepage = "https://biomcp.org";
    changelog = "https://github.com/genomoncology/biomcp/releases/tag/v${finalAttrs.version}";
    license = lib.licenses.mit;
    mainProgram = "biomcp";
    platforms = lib.platforms.unix;
  };
})

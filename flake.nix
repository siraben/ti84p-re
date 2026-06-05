{
  description = "TI-84 Plus OS reverse-engineering wiki (mdBook) + RE tooling";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
      in {
        # `nix build`  -> static HTML wiki in ./result
        packages.default = pkgs.stdenvNoCC.mkDerivation {
          pname = "ti84-re-wiki";
          version = "1.0";
          src = ./.;
          nativeBuildInputs = [ pkgs.mdbook pkgs.mdbook-mermaid ];
          buildPhase = ''
            mdbook-mermaid install .       # generate mermaid.min.js + mermaid-init.js
            mdbook build --dest-dir $out
          '';
          dontInstall = true;
          dontFixup = true;
        };

        # `nix run` -> live server with hot-reload at http://127.0.0.1:3000
        apps.default = {
          type = "app";
          program = "${pkgs.writeShellScript "ti84-wiki-serve" ''
            export PATH=${pkgs.mdbook-mermaid}/bin:$PATH   # preprocessor must be on PATH
            ${pkgs.mdbook-mermaid}/bin/mdbook-mermaid install . || true  # ensure mermaid JS assets exist
            exec ${pkgs.mdbook}/bin/mdbook serve --hostname 127.0.0.1 --port 3000 "$@"
          ''}";
        };

        devShells.default = pkgs.mkShell {
          packages = [ pkgs.mdbook pkgs.mdbook-mermaid ];
        };
      });
}

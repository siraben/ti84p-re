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
        katexDir = "${pkgs.katex}/lib/node_modules/katex";
        z80dasm = pkgs.stdenv.mkDerivation {
          pname = "z80dasm";
          version = "1.2.0";
          src = pkgs.fetchurl {
            url = "https://geeklan.co.uk/files/z80dasm-1.2.0.tar.gz";
            hash = "sha256-jaLEpYo5F6ginewNqX5xj5Dt6EmFQk10RWV1v1rP7sg=";
          };
        };
        # pseudocode.js (renders LaTeX algorithm blocks; not packaged in nixpkgs)
        pseudocodeJs = pkgs.fetchurl {
          url = "https://cdn.jsdelivr.net/npm/pseudocode@2.4.1/build/pseudocode.min.js";
          sha256 = "sha256-aVkDxqyzrB+ExUsOY9PdyelkDhn/DfrjWu08aVpqNlo=";
        };
        pseudocodeCss = pkgs.fetchurl {
          url = "https://cdn.jsdelivr.net/npm/pseudocode@2.4.1/build/pseudocode.min.css";
          sha256 = "sha256-VwMV//xgBPDyRFVSOshhRhzJRDyBmIACniLPpeXNUdc=";
        };
        # Vendor client-side assets mdBook can't supply (KaTeX math + pseudocode.js).
        setupAssets = ''
          KATEX_DIR=${katexDir} \
          PSEUDOCODE_JS=${pseudocodeJs} PSEUDOCODE_CSS=${pseudocodeCss} \
          bash tools/setup-wiki-assets.sh
        '';
      in {
        # `nix build`  -> static HTML wiki in ./result
        packages.default = pkgs.stdenvNoCC.mkDerivation {
          pname = "ti84-re-wiki";
          version = "1.0";
          src = ./.;
          nativeBuildInputs = [
            pkgs.mdbook pkgs.mdbook-mermaid pkgs.bash pkgs.python3 pkgs.katex
            pkgs.nodejs pkgs.z3 z80dasm
          ];
          buildPhase = ''
            mdbook-mermaid install .       # generate mermaid.min.js + mermaid-init.js
            ${setupAssets}                  # vendor KaTeX (css/js/fonts)
            mdbook build --dest-dir $out
            cp -r web/mathprint $out/mathprint   # standalone renderer, outside the book
            cp -r web/graphing $out/graphing     # standalone graph pipeline demo
            python3 tools/cachebust-mathprint.py $out/mathprint
            python3 tools/check-mdbook-output.py $out
            python3 tools/check-katex-output.py $out
            node tools/test-mathprint.js
            python3 tools/test_trace_lcd.py
            python3 tools/test_mathprint_extractors.py
            python3 tools/test_mathprint_draw_trace.py
            python3 tools/test_analyze_mathprint_records.py
            python3 tools/test_mathprint_saturation.py
            PYTHONPATH=tools python3 tools/test_analyze_retail_boot.py
            PYTHONPATH=tools python3 tools/test_bcall_tables.py
            node tools/test-graph-coordinate.js
            node tools/test-graphing-demo.js
            python3 tools/test_analyze_graph_regraph.py
            PYTHONPATH=tools python3 tools/test_graph_circle.py
            PYTHONPATH=tools python3 tools/test_fixture_tools.py
            python3 tools/test_wiki_style.py
            python3 tools/test_symbol_tables.py
            PYTHONPATH=tools python3 -m unittest \
              tools.test_tibasic_coverage tools.test_tibasic_for_paren \
              tools.test_tibasic_saturation tools.test_tibasic_numeric_errors
          '';
          dontInstall = true;
          dontFixup = true;
        };
        packages.z80dasm = z80dasm;

        # `nix run` -> live server with hot-reload at http://127.0.0.1:3000
        apps.default = {
          type = "app";
          program = "${pkgs.writeShellScript "ti84-wiki-serve" ''
            export PATH=${pkgs.mdbook-mermaid}/bin:$PATH   # preprocessor must be on PATH
            ${pkgs.mdbook-mermaid}/bin/mdbook-mermaid install . || true  # ensure mermaid JS assets exist
            ${setupAssets}                                 # vendor KaTeX (css/js/fonts)
            exec ${pkgs.mdbook}/bin/mdbook serve --hostname 127.0.0.1 --port 3000 "$@"
          ''}";
        };

        devShells.default = pkgs.mkShell {
          packages = [
            pkgs.ghidra
            pkgs.jdk21
            pkgs.mdbook
            pkgs.mdbook-mermaid
            pkgs.python3
            pkgs.spasm-ng
            pkgs.z3
            z80dasm
          ];
          # In the dev shell, run:  setup-wiki-assets   (vendors KaTeX before `mdbook serve`)
          shellHook = ''
            export KATEX_DIR=${katexDir}
            alias setup-wiki-assets='bash tools/setup-wiki-assets.sh'
          '';
        };
        devShells.browser-tests = pkgs.mkShell {
          packages = [ pkgs.playwright-test ];
        };
      });
}

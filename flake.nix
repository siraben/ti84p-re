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
          src = pkgs.fetchFromGitHub {
            owner = "erikarn";
            repo = "z80dasm";
            rev = "41b40654471be769f9a30bceb81ff6e7e1fd7d55";
            hash = "sha256-xfJElI85LH0FFdy54s4bbMraDKQmcXnhrhnP4SOLsfA=";
          };
          postUnpack = ''sourceRoot=$sourceRoot/src'';
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
            pkgs.chromium pkgs.nodejs pkgs.z3 z80dasm
          ];
          buildPhase = ''
            export PYTHONPATH=$PWD/tools
            mdbook-mermaid install .       # generate mermaid.min.js + mermaid-init.js
            ${setupAssets}                  # vendor KaTeX (css/js/fonts)
            mdbook build --dest-dir $out
            cp -r web/mathprint $out/mathprint   # standalone renderer, outside the book
            cp -r web/graphing $out/graphing     # standalone graph pipeline demo
            python3 -m ti84re.wiki.cachebust_mathprint $out/mathprint
            python3 -m ti84re.wiki.check_mdbook_output $out
            python3 -m ti84re.wiki.check_katex_output $out
            python3 -m ti84re.wiki.check_rendering docs $out
            node tools/js/test-mathprint.js
            python3 -m tests.trace.test_trace_lcd
            python3 -m tests.mathprint.test_mathprint_extractors
            python3 -m tests.mathprint.test_mathprint_draw_trace
            python3 -m tests.mathprint.test_analyze_mathprint_records
            python3 -m tests.mathprint.test_mathprint_saturation
            python3 -m tests.boot.test_analyze_retail_boot
            python3 -m tests.rom.test_bcall_tables
            node tools/js/test-graph-coordinate.js
            node tools/js/test-graphing-demo.js
            python3 -m tests.graphing.test_analyze_graph_regraph
            python3 -m tests.graphing.test_graph_circle
            python3 -m tests.tifiles.test_fixture_tools
            python3 -m tests.wiki.test_wiki_style
            python3 -m tests.rom.test_symbol_tables
            python3 -m unittest \
              tests.tibasic.test_tibasic_coverage tests.tibasic.test_tibasic_for_paren \
              tests.tibasic.test_tibasic_saturation tests.tibasic.test_tibasic_numeric_errors \
              tests.rom.test_rom_provenance tests.boot.test_compare_boot_pages \
              tests.rom.test_database_health_report \
              tests.hardware.test_hardware_probe tests.hardware.test_build_hardware_probes tests.wiki.test_needed_probe_docs tests.hardware.test_exact_hardware_probe \
              tests.emulators.test_emulator_probe_build
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
            pkgs.unzip
            pkgs.z3
            z80dasm
          ];
          # In the dev shell, run:  setup-wiki-assets   (vendors KaTeX before `mdbook serve`)
          shellHook = ''
            export KATEX_DIR=${katexDir}
            export PYTHONPATH=$PWD/tools''${PYTHONPATH:+:$PYTHONPATH}
            alias setup-wiki-assets='bash tools/setup-wiki-assets.sh'
          '';
        };
        devShells.browser-tests = pkgs.mkShell {
          packages = [ pkgs.playwright-test ];
        };
      });
}

// Z80 assembly grammar for highlight.js (mdBook bundles hljs without a Z80 dialect).
// Loaded as an additional-js. We register the language and then authoritatively
// (re-)highlight every `language-z80` block on DOMContentLoaded, so the result is
// correct no matter whether mdBook's book.js highlight pass ran before or after us.
(function () {
  if (typeof hljs === "undefined") return;

  if (!hljs.getLanguage("z80")) {
    hljs.registerLanguage("z80", function (hljs) {
      var MNEMONICS =
        "adc add and bit call ccf cp cpd cpdr cpi cpir cpl daa dec di djnz ei ex " +
        "exx halt im in inc ind indr ini inir jp jr ld ldd lddr ldi ldir neg nop " +
        "or otdr otir out outd outi pop push res ret reti retn rl rla rlc rlca rld " +
        "rr rra rrc rrca rrd rst sbc scf set sla sll sra srl sub xor";
      var REGISTERS =
        "a b c d e f h l i r af bc de hl sp pc ix iy ixh ixl iyh iyl " +
        "z nz nc po pe m p"; // registers + condition codes

      return {
        name: "Z80",
        case_insensitive: true,
        keywords: { keyword: MNEMONICS, built_in: REGISTERS },
        contains: [
          hljs.COMMENT(";", "$"),
          // labels at line start, incl. hex-address labels:  foo:  LAB_1234:  61F4:
          { className: "symbol", scope: "symbol", begin: /^\s*[0-9A-Za-z_.$][\w.$]*:/ },
          { className: "number", scope: "number", begin: /\b0x[0-9A-Fa-f]+\b/ }, // 0x1A2F
          { className: "number", scope: "number", begin: /\$[0-9A-Fa-f]+/ }, // $1A2F
          { className: "number", scope: "number", begin: /\b[0-9][0-9A-Fa-f]*[hH]\b/ }, // 1A2Fh
          { className: "number", scope: "number", begin: /%[01]+/ }, // %1010
          // bare hex words (addresses/operands): a digit then 2+ hex chars, so
          // pure-letter mnemonics (add, dec, daa, ccf…) and registers are NOT eaten.
          { className: "number", scope: "number", begin: /\b[0-9][0-9A-Fa-f]{2,}\b/ },
          hljs.C_NUMBER_MODE,
          hljs.QUOTE_STRING_MODE,
          { className: "string", scope: "string", begin: /'/, end: /'/ },
          {
            className: "meta",
            scope: "meta",
            begin: /\.[A-Za-z]+|\b(?:equ|org|defb|defw|defs|db|dw|ds)\b/i,
          }, // directives
        ],
      };
    });
  }

  function highlightZ80() {
    var blocks = document.querySelectorAll("code.language-z80");
    for (var i = 0; i < blocks.length; i++) {
      var block = blocks[i];
      var text = block.textContent;
      var res;
      try {
        res = hljs.highlight(text, { language: "z80" }); // hljs v10/v11
      } catch (e) {
        try {
          res = hljs.highlight("z80", text); // hljs v9 signature
        } catch (e2) {
          continue;
        }
      }
      block.innerHTML = res.value;
      block.classList.add("hljs");
      block.removeAttribute("data-highlighted");
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", highlightZ80);
  } else {
    highlightZ80();
  }
})();

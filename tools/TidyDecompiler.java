// TidyDecompiler.java — set a less-verbose, global Decompiler display profile.
//
// These are *tool* options (Edit > Tool Options > Decompiler): they apply to EVERY
// function's decompilation in this Ghidra tool, not just one routine, and persist
// with the tool. Run once from the Script Manager (green ▶) with the program open;
// then click any function (or press F5) to re-render with the new profile.
//
// What it changes and why (tuned for the Z80 / TI-OS decompilations):
//   * Disable printing of type casts  — removes the (byte *)/(char)/(ushort)/(code)
//     coercion noise that dominates 8-bit code.  <-- biggest readability win
//   * Display Namespaces = off         — drops `namespace::name` prefixes.
//   * Print calling convention name=off— drops the "__stdcall"-style annotations.
//   * Maximum characters per line = 120— fewer mid-expression line wraps.
//   * Simplify extended integer ops / predication / for-loops / unreachable code
//     — fold CONCAT/SUB/CARRY chains and flag predication where the decompiler can.
//
// Note: param_1/bVarN names and the in_F/unaff_/extraout_ register pseudo-vars are
// NOT controlled by a global toggle — they come from per-function prototypes and the
// Z80 8-bit register model. Apply signatures / run "Decompiler Parameter ID" to fix
// those; this script only handles the global display verbosity.

import ghidra.app.script.GhidraScript;
import ghidra.framework.options.ToolOptions;
import ghidra.framework.plugintool.PluginTool;

public class TidyDecompiler extends GhidraScript {
    @Override
    public void run() throws Exception {
        PluginTool tool = state.getTool();
        if (tool == null) {
            println("No tool available — run this from the GUI Script Manager, not headless.");
            return;
        }
        ToolOptions o = tool.getOptions("Decompiler");

        // --- Display: the verbosity reducers ---
        o.setBoolean("Display.Disable printing of type casts", true);
        o.setBoolean("Display.Display Namespaces", false);
        o.setBoolean("Display.Print calling convention name", false);
        o.setInt("Display.Maximum characters in a code line", 120);

        // --- Analysis: let the decompiler fold 8-bit / flag idioms ---
        o.setBoolean("Analysis.Simplify extended integer operations", true);
        o.setBoolean("Analysis.Simplify predication", true);
        o.setBoolean("Analysis.Recover -for- loops", true);
        o.setBoolean("Analysis.Eliminate unreachable code", true);

        println("Decompiler display profile applied (tool-wide).");
        println("Press F5 / re-select a function to re-decompile with fewer casts.");
    }
}

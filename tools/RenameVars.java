import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.pcode.*;
import ghidra.program.model.symbol.SourceType;
import java.nio.file.*;
import java.util.*;

// Apply confident decompiler variable names from tools/varnames.txt.
// Line format: <space>:<addrhex> <TAB> <default-name> <TAB> <new-name>
//
// Each function is decompiled ONCE; every wanted symbol is collected from that
// single HighFunction and renamed from it, so the decompiler's rename-renumbering
// (which forces a re-decompile per rename interactively) never bites us here.
public class RenameVars extends GhidraScript {
    public void run() throws Exception {
        String dir = getScriptArgs().length > 0 ? getScriptArgs()[0] : ".";
        AddressFactory af = currentProgram.getAddressFactory();

        // group entries by function address, preserving order
        Map<String, Map<String, String>> byFunc = new LinkedHashMap<>();
        for (String line : Files.readAllLines(Paths.get(dir + "/varnames.txt"))) {
            line = line.trim();
            if (line.isEmpty() || line.startsWith("#")) continue;
            String[] p = line.split("\t");
            if (p.length < 3) continue;
            byFunc.computeIfAbsent(p[0].trim(), k -> new LinkedHashMap<>())
                  .put(p[1].trim(), p[2].trim());
        }

        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        int renamed = 0, funcs = 0;
        for (Map.Entry<String, Map<String, String>> e : byFunc.entrySet()) {
            String[] loc = e.getKey().split(":");
            if (loc.length != 2) continue;
            AddressSpace sp = af.getAddressSpace(loc[0]);
            if (sp == null) continue;
            try {
                Address a = sp.getAddress(Long.parseLong(loc[1], 16));
                Function f = getFunctionAt(a);
                if (f == null) continue;
                DecompileResults res = dec.decompileFunction(f, 30, monitor);
                HighFunction hf = res.getHighFunction();
                if (hf == null) continue;
                funcs++;
                Map<String, String> want = e.getValue();
                List<HighSymbol> syms = new ArrayList<>();
                Iterator<HighSymbol> it = hf.getLocalSymbolMap().getSymbols();
                while (it.hasNext()) syms.add(it.next());
                for (HighSymbol hs : syms) {
                    String nn = want.get(hs.getName());
                    if (nn == null) continue;
                    try {
                        HighFunctionDBUtil.updateDBVariable(hs, nn, null, SourceType.USER_DEFINED);
                        renamed++;
                    } catch (Exception ex) {
                        println("  skip " + e.getKey() + " " + hs.getName() + ": " + ex.getMessage());
                    }
                }
            } catch (Exception ex) {
                println("  error " + e.getKey() + ": " + ex.getMessage());
            }
        }
        dec.dispose();
        println("Renamed variables: " + renamed + " across " + funcs + " functions");
    }
}

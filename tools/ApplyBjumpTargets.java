import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import java.nio.file.*;

// Disassemble + create a function at each bjump trampoline target (the OS's
// hot cross-page routines), so they are present even if not reached by flow.
public class ApplyBjumpTargets extends GhidraScript {
    public void run() throws Exception {
        String dir = getScriptArgs()[0];
        AddressFactory af = currentProgram.getAddressFactory();
        int made = 0, unnamed = 0;
        for (String line : Files.readAllLines(Paths.get(dir + "/bjumps.txt"))) {
            String[] p = line.trim().split("\\s+");
            if (p.length < 3) continue;
            int addr = Integer.parseInt(p[1], 16), page = Integer.parseInt(p[2], 16);
            AddressSpace sp = (page == 0) ? af.getDefaultAddressSpace()
                                          : af.getAddressSpace(String.format("page_%02X", page));
            if (sp == null) continue;
            try {
                Address a = sp.getAddress(addr);
                if (getInstructionAt(a) == null) disassemble(a);
                Function f = getFunctionAt(a);
                if (f == null) { f = createFunction(a, null); if (f != null) made++; }
                if (f != null && f.getName().startsWith("FUN_")) unnamed++;
            } catch (Exception e) {}
        }
        println("bjump targets: new functions=" + made + ", still-unnamed(FUN_)=" + unnamed);
    }
}

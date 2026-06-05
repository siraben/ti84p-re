import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.SourceType;
import java.nio.file.*;

// Apply accumulated confident function names from tools/names.txt.
// Line format: <space>:<addrhex> <tab> <name>
public class RenameFns extends GhidraScript {
    public void run() throws Exception {
        String dir = getScriptArgs().length > 0 ? getScriptArgs()[0] : ".";
        AddressFactory af = currentProgram.getAddressFactory();
        int n = 0;
        for (String line : Files.readAllLines(Paths.get(dir + "/names.txt"))) {
            line = line.trim();
            if (line.isEmpty() || line.startsWith("#")) continue;
            String[] p = line.split("\\s+", 2);
            if (p.length < 2) continue;
            String[] loc = p[0].split(":");
            if (loc.length != 2) continue;
            AddressSpace sp = af.getAddressSpace(loc[0]);
            if (sp == null) continue;
            try {
                Address a = sp.getAddress(Long.parseLong(loc[1], 16));
                if (getInstructionAt(a) == null) disassemble(a);
                Function f = getFunctionAt(a);
                if (f == null) f = createFunction(a, p[1].trim());
                else f.setName(p[1].trim(), SourceType.USER_DEFINED);
                n++;
            } catch (Exception e) {}
        }
        println("Renamed functions: " + n);
    }
}

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.SourceType;
import java.nio.file.*;

// Reads bcall_targets.txt (name, id, addr, page) and disassembles+names each
// OS routine at its real entry point in the matching overlay page.
public class ApplyBcalls extends GhidraScript {
    public void run() throws Exception {
        String dir = getScriptArgs().length > 0 ? getScriptArgs()[0] : ".";
        AddressFactory af = currentProgram.getAddressFactory();
        AddressSpace ram = af.getDefaultAddressSpace();
        int named = 0, dis = 0;
        for (String line : Files.readAllLines(Paths.get(dir + "/bcall_targets.txt"))) {
            String[] p = line.trim().split("\\s+");
            if (p.length < 4) continue;
            String name = p[0];
            int addr = Integer.parseInt(p[2], 16);
            int page = Integer.parseInt(p[3], 16);
            AddressSpace sp = (page == 0) ? ram : af.getAddressSpace(String.format("page_%02X", page));
            if (sp == null) continue;
            try {
                Address a = sp.getAddress(addr);
                if (getInstructionAt(a) == null) { disassemble(a); dis++; }
                Function f = getFunctionAt(a);
                if (f == null) f = createFunction(a, name);
                if (f != null && f.getName().startsWith("FUN_")) f.setName(name, SourceType.USER_DEFINED);
                createLabel(a, name, true);
                setPlateComment(a, "bcall(" + name + ")  id=0x" + p[1] + "  [" + String.format("%02X:%04X", page, addr) + "]");
                named++;
            } catch (Exception e) {}
        }
        println("bcall routines named: " + named + "  newly disassembled: " + dis);
        analyzeChanges(currentProgram);
        println("ApplyBcalls complete. total functions=" + currentProgram.getFunctionManager().getFunctionCount());
    }
}

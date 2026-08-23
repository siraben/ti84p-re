import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

// Print the raw disassembly listing for one or more SPACE:START:END ranges,
// with function offsets and reference annotations. Read-only.
//
// Usage:
//   ghidra-analyzeHeadless PROJECT_DIR PROJECT -process PROGRAM -noanalysis \
//     -readOnly -scriptPath tools -postScript InspectListing.java \
//     page_02:74a0:7530 ram:9d95:9e10
public class InspectListing extends GhidraScript {
    private Address parseAddr(String space, String hex) throws Exception {
        AddressSpace sp = currentProgram.getAddressFactory().getAddressSpace(space);
        if (sp == null) throw new IllegalArgumentException("unknown address space: " + space);
        return sp.getAddress(Long.parseLong(hex, 16));
    }

    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length == 0) {
            printerr("InspectListing requires SPACE:START:END arguments");
            return;
        }
        for (String arg : args) {
            String[] f = arg.split(":");
            if (f.length != 3) {
                printerr("location must be SPACE:START:END, e.g. page_02:74a0:7530");
                return;
            }
            Address start = parseAddr(f[0], f[1]);
            Address end = parseAddr(f[0], f[2]);
            println("==== " + f[0] + ":" + f[1] + "-" + f[2] + " ====");
            if (getInstructionAt(start) == null) disassemble(start);
            Instruction ins = getInstructionAt(start);
            FunctionManager fm = currentProgram.getFunctionManager();
            ReferenceManager rm = currentProgram.getReferenceManager();
            while (ins != null && ins.getAddress().compareTo(end) <= 0) {
                Address a = ins.getAddress();
                Function fn = fm.getFunctionContaining(a);
                String fnName = "";
                if (fn != null) {
                    long off = a.getOffset() - fn.getEntryPoint().getOffset();
                    fnName = "  ; in " + fn.getName() + (off == 0 ? "" : String.format("+%x", off));
                }
                String refs = "";
                Reference[] rs = rm.getReferencesFrom(a);
                if (rs.length > 0) {
                    StringBuilder sb = new StringBuilder("  ; -> ");
                    for (Reference r : rs) sb.append(r.getToAddress()).append(" ");
                    refs = sb.toString();
                }
                println(String.format("%-8s %-24s%s%s",
                        a.toString(), ins.toString(), fnName, refs));
                ins = ins.getNext();
            }
        }
    }
}

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

// Print instructions that reference given RAM addresses, with containing function.
public class FindRefs extends GhidraScript {
    public void run() throws Exception {
        long[] addrs = {0x858D, 0x8593, 0x858F, 0x8599};  // cxMain, cxRedisp, cxPPutAway, cxPage
        ReferenceManager rm = currentProgram.getReferenceManager();
        for (long t : addrs) {
            Address ta = toAddr(t);
            println("\n### refs to " + ta + " ###");
            int n = 0;
            for (Reference r : rm.getReferencesTo(ta)) {
                Address from = r.getFromAddress();
                Function f = getFunctionContaining(from);
                Instruction in = getInstructionAt(from);
                println("  " + from + "  " + (in != null ? in.toString() : "?") + "   in " + (f != null ? f.getName() : "-"));
                if (++n >= 12) break;
            }
            if (n == 0) println("  (none)");
        }
    }
}

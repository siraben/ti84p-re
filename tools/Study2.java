import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

// Decompile FP / VAT / cross-page-trampoline routines for docs 05-06.
public class Study2 extends GhidraScript {
    public void run() throws Exception {
        AddressFactory af = currentProgram.getAddressFactory();
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        String[][] t = {
            {"ram","2b09","FUN_2b09 (thunk target / cross-page jumper)"},
            {"ram","229e","_FPAdd"},
            {"ram","1a2f","_OP1ToOP2"},
            {"ram","0e60","_ChkFindSym"},
            {"ram","1308","_DelVar"},
            {"ram","0f81","_InsertMem"},
        };
        for (String[] x : t) {
            AddressSpace sp = af.getAddressSpace(x[0]);
            Address a = sp.getAddress(Long.parseLong(x[1],16));
            Function f = getFunctionAt(a);
            println("\n##### " + x[2] + "  @"+x[0]+":"+x[1] + " #####");
            if (f == null) { println("(no function)"); continue; }
            DecompileResults r = di.decompileFunction(f, 30, monitor);
            String c = (r!=null && r.decompileCompleted()) ? r.getDecompiledFunction().getC() : "(failed)";
            if (c.length() > 1500) c = c.substring(0,1500) + "\n...[truncated]";
            println(c);
        }
    }
}

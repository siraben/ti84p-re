import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

public class Study7 extends GhidraScript {
    public void run() throws Exception {
        AddressFactory af = currentProgram.getAddressFactory();
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        String[][] t = {
            {"ram","08fa","FUN_08fa (loads cxMain+cxPage)"},
            {"ram","08e9","FUN_08e9 (loads cxPage)"},
            {"ram","04ca","FUN_04ca (called by _PutAway)"},
            {"ram","081c","FUN_081c (LDIR near cxMain)"},
        };
        for (String[] x : t) {
            AddressSpace sp = af.getAddressSpace(x[0]);
            Address a = sp.getAddress(Long.parseLong(x[1],16));
            Function f = getFunctionAt(a);
            println("\n##### " + x[2] + "  @"+x[0]+":"+x[1] + " #####");
            if (f == null) { println("(no function at exact addr)"); f = getFunctionContaining(a); if(f==null) continue; }
            DecompileResults r = di.decompileFunction(f, 30, monitor);
            String c = (r!=null && r.decompileCompleted()) ? r.getDecompiledFunction().getC() : "(failed)";
            if (c.length() > 1100) c = c.substring(0,1100) + "\n...[truncated]";
            println(c);
        }
    }
}

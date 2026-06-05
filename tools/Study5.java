import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

public class Study5 extends GhidraScript {
    public void run() throws Exception {
        AddressFactory af = currentProgram.getAddressFactory();
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        String[][] t = {
            {"ram","028c","boot_continuation (reset target)"},
            {"ram","2793","_JError"},
            {"ram","0936","_AppInit"},
            {"ram","08af","_PutAway"},
            {"page_3C","420D","_SendAByte (link)"},
        };
        for (String[] x : t) {
            AddressSpace sp = af.getAddressSpace(x[0]);
            Address a = sp.getAddress(Long.parseLong(x[1],16));
            Function f = getFunctionAt(a);
            println("\n##### " + x[2] + "  @"+x[0]+":"+x[1] + " #####");
            if (f == null) { println("(no function)"); continue; }
            DecompileResults r = di.decompileFunction(f, 30, monitor);
            String c = (r!=null && r.decompileCompleted()) ? r.getDecompiledFunction().getC() : "(failed)";
            if (c.length() > 1300) c = c.substring(0,1300) + "\n...[truncated]";
            println(c);
        }
    }
}

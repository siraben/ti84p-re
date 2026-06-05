import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

// Decompile a fixed set of key routines to gather material for RE docs.
public class Study extends GhidraScript {
    public void run() throws Exception {
        AddressFactory af = currentProgram.getAddressFactory();
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        String[][] targets = {
            {"ram","04b2","_GetCSC (keypad scan)"},
            {"ram","0e65","_FindSym (VAT lookup)"},
            {"ram","10b8","_CreateReal (var alloc)"},
            {"page_01","5b4c","_PutC (LCD char out)"},
            {"page_06","491e","_GetKey (key input)"},
        };
        for (String[] t : targets) {
            AddressSpace sp = af.getAddressSpace(t[0]);
            if (sp == null) { println("## "+t[2]+": no space "+t[0]); continue; }
            Address a = sp.getAddress(Long.parseLong(t[1],16));
            Function f = getFunctionAt(a);
            println("\n##### " + t[2] + "  @" + t[0] + ":" + t[1] + " #####");
            if (f == null) { println("(no function)"); continue; }
            DecompileResults r = di.decompileFunction(f, 30, monitor);
            String c = (r!=null && r.decompileCompleted()) ? r.getDecompiledFunction().getC() : "(decompile failed)";
            if (c.length() > 1600) c = c.substring(0,1600) + "\n...[truncated]";
            println(c);
        }
    }
}

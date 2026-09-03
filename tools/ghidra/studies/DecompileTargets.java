import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressFactory;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Function;

// Decompile a list of routines and print truncated C for RE notes.
//
// Each script argument names one target as SPACE:ADDR[:LABEL], e.g.
//   ram:0e65:_FindSym  page_01:5b4c:_PutC  page_38:4000
// Run headless with
//   analyzeHeadless . ti84 -process -noanalysis -readOnly \
//     -scriptPath tools/ghidra/studies -postScript DecompileTargets.java ram:0e65:_FindSym
// or from the Script Manager, where the arguments are requested interactively.
public class DecompileTargets extends GhidraScript {
    private static final int TIMEOUT_SECONDS = 30;
    private static final int MAX_CHARS = 1600;

    public void run() throws Exception {
        String[] targets = getScriptArgs();
        if (targets.length == 0) {
            targets = askString("Targets", "SPACE:ADDR[:LABEL] ...").trim().split("\\s+");
        }
        AddressFactory factory = currentProgram.getAddressFactory();
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        for (String target : targets) {
            String[] parts = target.split(":", 3);
            if (parts.length < 2) {
                println("## " + target + ": expected SPACE:ADDR[:LABEL]");
                continue;
            }
            String label = parts.length == 3 ? parts[2] : parts[0] + ":" + parts[1];
            AddressSpace space = factory.getAddressSpace(parts[0]);
            if (space == null) {
                println("## " + label + ": no address space " + parts[0]);
                continue;
            }
            Address address = space.getAddress(Long.parseLong(parts[1], 16));
            Function function = getFunctionAt(address);
            println("\n##### " + label + "  @" + parts[0] + ":" + parts[1] + " #####");
            if (function == null) {
                println("(no function)");
                continue;
            }
            DecompileResults results = decompiler.decompileFunction(function, TIMEOUT_SECONDS, monitor);
            String code = results != null && results.decompileCompleted()
                ? results.getDecompiledFunction().getC()
                : "(decompile failed)";
            if (code.length() > MAX_CHARS) {
                code = code.substring(0, MAX_CHARS) + "\n...[truncated]";
            }
            println(code);
        }
    }
}

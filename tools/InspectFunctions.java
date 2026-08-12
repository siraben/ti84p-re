import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressFactory;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Function;

// Create missing function entries, follow their local flow, and print focused
// decompiler output. The project may be opened read-only so exploratory entry
// creation never persists.
//
// Usage:
//   ghidra-analyzeHeadless PROJECT_DIR PROJECT -process PROGRAM -noanalysis \
//     -readOnly -scriptPath tools -postScript InspectFunctions.java \
//     page_34:6d26 page_34:737a
public class InspectFunctions extends GhidraScript {
    private Address parseLocation(String text) throws Exception {
        String[] fields = text.split(":", 2);
        if (fields.length != 2) {
            throw new IllegalArgumentException(
                "location must be SPACE:ADDR, for example page_34:6d26"
            );
        }
        AddressFactory factory = currentProgram.getAddressFactory();
        AddressSpace space = factory.getAddressSpace(fields[0]);
        if (space == null) {
            throw new IllegalArgumentException("unknown address space: " + fields[0]);
        }
        return space.getAddress(Long.parseLong(fields[1], 16));
    }

    public void run() throws Exception {
        String[] arguments = getScriptArgs();
        if (arguments.length == 0) {
            printerr("InspectFunctions requires at least one SPACE:ADDR argument");
            return;
        }
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        for (String argument : arguments) {
            Address address = parseLocation(argument);
            if (getInstructionAt(address) == null) {
                disassemble(address);
            }
            Function function = getFunctionAt(address);
            if (function == null) {
                function = createFunction(address, null);
            }
            println("FUNCTION\t" + address + "\t" +
                    (function == null ? "creation failed" : function.getName()));
            if (function == null) {
                continue;
            }
            DecompileResults results = decompiler.decompileFunction(function, 60, monitor);
            if (results == null || !results.decompileCompleted()) {
                println("DECOMPILE_FAILED\t" + address + "\t" +
                        (results == null ? "no result" : results.getErrorMessage()));
                continue;
            }
            println(results.getDecompiledFunction().getC());
        }
        decompiler.dispose();
    }
}

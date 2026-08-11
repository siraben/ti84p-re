import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressFactory;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import ghidra.program.model.symbol.ReferenceManager;

// Inspect function ownership and xrefs for page-aware locations.
// Usage with the rebuilt database:
//   ghidra-analyzeHeadless . ti84 -process ti84_page00.bin -noanalysis \
//     -readOnly -scriptPath tools -postScript InspectLocations.java \
//     page_3D:40f1 page_3D:437e
public class InspectLocations extends GhidraScript {
    private Address parseLocation(String text) throws Exception {
        String[] fields = text.split(":", 2);
        if (fields.length != 2) {
            throw new IllegalArgumentException(
                "location must be SPACE:ADDR, for example page_3D:40f1"
            );
        }
        AddressFactory factory = currentProgram.getAddressFactory();
        AddressSpace space = factory.getAddressSpace(fields[0]);
        if (space == null) {
            throw new IllegalArgumentException("unknown address space: " + fields[0]);
        }
        return space.getAddress(Long.parseLong(fields[1], 16));
    }

    private String functionName(Function function) {
        return function == null ? "-" : function.getName();
    }

    public void run() throws Exception {
        String[] arguments = getScriptArgs();
        if (arguments.length == 0) {
            printerr("InspectLocations requires at least one SPACE:ADDR argument");
            return;
        }
        ReferenceManager references = currentProgram.getReferenceManager();
        for (String argument : arguments) {
            Address target = parseLocation(argument);
            if (getInstructionAt(target) == null) {
                disassemble(target);
            }
            Function containing = getFunctionContaining(target);
            Function entry = getFunctionAt(target);
            Instruction instruction = getInstructionAt(target);
            Instruction owner = getInstructionContaining(target);
            println(
                "LOCATION\t" + target +
                "\tentry=" + functionName(entry) +
                "\tcontaining=" + functionName(containing) +
                "\tinstruction=" + (instruction == null ? "-" : instruction) +
                "\towner=" + (owner == null ? "-" : owner.getAddress() + " " + owner)
            );
            ReferenceIterator iterator = references.getReferencesTo(target);
            int count = 0;
            while (iterator.hasNext()) {
                Reference reference = iterator.next();
                Address source = reference.getFromAddress();
                Function sourceFunction = getFunctionContaining(source);
                Instruction sourceInstruction = getInstructionAt(source);
                println(
                    "XREF\t" + target +
                    "\tfrom=" + source +
                    "\ttype=" + reference.getReferenceType() +
                    "\tfunction=" + functionName(sourceFunction) +
                    "\tinstruction=" +
                    (sourceInstruction == null ? "-" : sourceInstruction)
                );
                count++;
            }
            println("XREF_COUNT\t" + target + "\t" + count);
        }
    }
}

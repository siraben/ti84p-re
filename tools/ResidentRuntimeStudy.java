import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressFactory;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;

/**
 * Dump the OS routines that constrain a resident assembly runtime.
 *
 * Run against the existing project without modifying it:
 *
 * ghidra-analyzeHeadless /path/to/repo ti84 -readOnly \
 *   -process ti84_page00.bin -noanalysis -scriptPath tools \
 *   -postScript ResidentRuntimeStudy.java
 */
public class ResidentRuntimeStudy extends GhidraScript {
    private DecompInterface decompiler;
    private AddressFactory addresses;

    private Address address(String spaceName, String offset) {
        AddressSpace space = addresses.getAddressSpace(spaceName);
        return space == null ? null : space.getAddress(Long.parseLong(offset, 16));
    }

    private void dumpFunction(String spaceName, String offset, String label)
            throws Exception {
        Address entry = address(spaceName, offset);
        println("\n##### " + label + " @" + spaceName + ":" + offset + " #####");
        if (entry == null) {
            println("(missing address space)");
            return;
        }
        Function function = getFunctionAt(entry);
        if (function == null) {
            function = getFunctionContaining(entry);
        }
        if (function == null) {
            println("(no containing function)");
            return;
        }
        DecompileResults result = decompiler.decompileFunction(function, 60, monitor);
        if (result == null || !result.decompileCompleted()) {
            println("(decompile failed)");
            return;
        }
        println(result.getDecompiledFunction().getC());
    }

    private void dumpInstructions(String spaceName, String start, String end) {
        Address cursor = address(spaceName, start);
        Address last = address(spaceName, end);
        println("\n##### instructions @" + spaceName + ":" + start + "-" + end
                + " #####");
        if (cursor == null || last == null) {
            println("(missing address space)");
            return;
        }
        Instruction instruction = getInstructionContaining(cursor);
        if (instruction == null) {
            instruction = getInstructionAfter(cursor);
        }
        while (instruction != null && instruction.getAddress().compareTo(last) <= 0) {
            println(instruction.getAddress() + ": " + instruction);
            instruction = instruction.getNext();
        }
    }

    @Override
    public void run() throws Exception {
        addresses = currentProgram.getAddressFactory();
        decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);

        dumpFunction("page_38", "4113", "asm_token_handler");
        dumpFunction("page_07", "5758", "_ExecutePrgm");
        dumpFunction("page_07", "57b4", "asm_payload_handoff");
        dumpFunction("ram", "0f81", "_InsertMem");
        dumpFunction("ram", "1368", "_DelMem");
        dumpFunction("ram", "0fa6", "_EnoughMem");
        dumpFunction("ram", "0e20", "_MemChk");
        dumpFunction("ram", "1308", "_DelVar");
        dumpFunction("page_07", "6248", "_Arc_Unarc");
        dumpFunction("page_3D", "6745", "_FlashToRam");

        // The decompiler collapses several shared tails in this range. The
        // instruction dump preserves the size checks, hex decode, handoff,
        // and cleanup exactly as the ROM stores them.
        dumpInstructions("page_07", "5700", "5840");
    }
}

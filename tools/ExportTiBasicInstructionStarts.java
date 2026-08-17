import java.io.PrintWriter;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.mem.Memory;

// Export instruction boundaries for the bounded TI-BASIC saturation audit.
// Parser and control-flow table words are seeded as code roots before export;
// the table bytes themselves remain data.
public class ExportTiBasicInstructionStarts extends GhidraScript {
    private static final String[][] REGIONS = {
        {"page_38", "4100", "77ff"},
        {"page_02", "54ef", "56c2"},
        {"page_02", "673e", "67ff"},
        {"page_33", "435f", "4d4f"},
        {"ram", "0e20", "17ff"},
        {"ram", "1f00", "27ff"},
    };

    private static final String[][] ENTRIES = {
        {"page_38", "4130"}, {"page_38", "4180"},
        {"page_38", "4870"}, {"page_38", "5826"},
        {"page_38", "5987"}, {"page_38", "59c5"},
        {"page_38", "5ab3"}, {"page_38", "5c00"},
        {"page_38", "6251"}, {"page_38", "679f"},
        {"page_38", "6910"}, {"page_38", "69c5"},
        {"page_38", "6a15"}, {"page_38", "7010"},
        {"page_38", "7244"}, {"page_38", "7248"},
        {"page_38", "72da"}, {"page_38", "7511"},
        {"page_38", "7521"}, {"page_38", "752a"},
        {"page_38", "753e"}, {"page_38", "758a"},
        {"page_38", "778f"},
        {"page_02", "54ef"}, {"page_02", "555d"},
        {"page_02", "55e7"}, {"page_02", "562f"},
        {"page_02", "5676"}, {"page_02", "673e"},
        {"page_33", "435f"},
        {"ram", "0e20"}, {"ram", "0fa6"}, {"ram", "0ff0"},
        {"ram", "100b"}, {"ram", "1080"}, {"ram", "1183"},
        {"ram", "12a1"}, {"ram", "1308"}, {"ram", "1475"},
        {"ram", "14f0"}, {"ram", "1518"}, {"ram", "151e"},
        {"ram", "159c"}, {"ram", "15a3"}, {"ram", "1690"},
        {"ram", "1735"}, {"ram", "1749"},
        {"ram", "1f0f"}, {"ram", "1fd6"}, {"ram", "2119"},
        {"ram", "2123"}, {"ram", "212d"}, {"ram", "26e8"},
        {"ram", "26ec"}, {"ram", "26f4"}, {"ram", "26fc"},
        {"ram", "2700"}, {"ram", "2715"}, {"ram", "2719"},
        {"ram", "2721"},
    };

    private Address address(String spaceName, long offset) {
        AddressSpace space = currentProgram.getAddressFactory().getAddressSpace(spaceName);
        if (space == null) {
            throw new IllegalArgumentException("unknown address space: " + spaceName);
        }
        return space.getAddress(offset);
    }

    private Address address(String spaceName, String offset) {
        return address(spaceName, Long.parseLong(offset, 16));
    }

    private int byteAt(Address location) throws Exception {
        return currentProgram.getMemory().getByte(location) & 0xff;
    }

    private void seedWordTable(String space, int table, int count) throws Exception {
        Address base = address(space, table);
        for (int index = 0; index < count; index++) {
            int low = byteAt(base.add(index * 2L));
            int high = byteAt(base.add(index * 2L + 1));
            int target = low | high << 8;
            if (0x4000 <= target && target < 0x8000) {
                disassemble(address(space, target));
            }
        }
    }

    private String bytes(Instruction instruction) throws Exception {
        StringBuilder result = new StringBuilder();
        for (byte value : instruction.getBytes()) {
            result.append(String.format("%02X", value & 0xff));
        }
        return result.toString();
    }

    public void run() throws Exception {
        String[] arguments = getScriptArgs();
        if (arguments.length != 1) {
            throw new IllegalArgumentException(
                "ExportTiBasicInstructionStarts requires one absolute output path"
            );
        }
        for (String[] entry : ENTRIES) {
            disassemble(address(entry[0], entry[1]));
        }
        seedWordTable("page_38", 0x4000, 87);
        seedWordTable("page_33", 0x4381, 13);

        try (PrintWriter output = new PrintWriter(arguments[0])) {
            output.println("# space\taddress\tbytes\tinstruction");
            for (String[] region : REGIONS) {
                AddressSet set = new AddressSet(
                    address(region[0], region[1]), address(region[0], region[2])
                );
                InstructionIterator instructions =
                    currentProgram.getListing().getInstructions(set, true);
                while (instructions.hasNext()) {
                    Instruction instruction = instructions.next();
                    output.printf(
                        "%s\t%04X\t%s\t%s%n",
                        instruction.getAddress().getAddressSpace().getName(),
                        instruction.getAddress().getOffset(),
                        bytes(instruction),
                        instruction.toString().replace('\t', ' ')
                    );
                }
            }
        }
    }
}

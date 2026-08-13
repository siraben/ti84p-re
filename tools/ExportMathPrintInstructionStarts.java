import java.io.PrintWriter;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;

// Export instruction starts already recognized by the rebuilt Ghidra database
// inside the bounded MathPrint saturation regions. The Python audit uses this
// mask to avoid treating embedded handler tables as executable merely because
// z80dasm can decode their bytes linearly.
//
// Usage:
//   ghidra-analyzeHeadless /path/to/repo ti84 -process ti84_page00.bin \
//     -noanalysis -readOnly -scriptPath tools \
//     -postScript ExportMathPrintInstructionStarts.java /absolute/output/path
public class ExportMathPrintInstructionStarts extends GhidraScript {
    private static final String[][] REGIONS = {
        {"page_34", "4690", "5d02"},
        {"page_34", "5d07", "6d7f"},
        {"page_34", "700c", "71ff"},
        {"page_34", "737a", "779f"},
        {"page_33", "4f23", "4fbf"},
        {"page_39", "49a8", "5d4f"},
        {"page_39", "672e", "6b8f"},
        {"page_01", "5a59", "5aff"},
        {"page_01", "624c", "68cf"},
        {"page_04", "4025", "43ff"},
        {"page_07", "44de", "462f"},
        {"page_07", "5417", "544f"},
    };

    private static final String[][] ENTRIES = {
        {"page_34", "4690"}, {"page_34", "473a"}, {"page_34", "4862"},
        {"page_34", "4900"}, {"page_34", "5678"}, {"page_34", "5699"},
        {"page_34", "56df"}, {"page_34", "56e3"}, {"page_34", "56ec"},
        {"page_34", "5795"}, {"page_34", "58f9"}, {"page_34", "5935"},
        {"page_34", "5996"}, {"page_34", "5a05"}, {"page_34", "5a99"},
        {"page_34", "5d07"}, {"page_34", "5d1a"}, {"page_34", "5d96"},
        {"page_34", "5da6"}, {"page_34", "5e85"}, {"page_34", "5fe7"},
        {"page_34", "6016"}, {"page_34", "6105"}, {"page_34", "6143"},
        {"page_34", "620a"}, {"page_34", "622f"}, {"page_34", "62a1"},
        {"page_34", "6315"}, {"page_34", "6347"}, {"page_34", "6375"},
        {"page_34", "637e"}, {"page_34", "63ad"}, {"page_34", "63b2"},
        {"page_34", "640e"}, {"page_34", "6504"}, {"page_34", "65aa"},
        {"page_34", "660a"}, {"page_34", "6873"}, {"page_34", "6c37"},
        {"page_34", "6ccd"}, {"page_34", "700c"}, {"page_34", "6d0c"},
        {"page_34", "706a"}, {"page_34", "70b8"}, {"page_34", "702c"},
        {"page_34", "7133"}, {"page_34", "70a0"}, {"page_34", "70e2"},
        {"page_34", "7087"}, {"page_34", "7102"}, {"page_34", "717e"},
        {"page_34", "70c1"}, {"page_34", "71c6"},
        {"page_34", "737a"}, {"page_34", "7393"}, {"page_34", "7609"},
        {"page_34", "73b9"}, {"page_34", "740b"}, {"page_34", "744f"},
        {"page_34", "73d6"}, {"page_34", "7485"}, {"page_34", "743f"},
        {"page_34", "73db"}, {"page_34", "7436"}, {"page_34", "745a"},
        {"page_34", "74aa"}, {"page_34", "7455"}, {"page_34", "74f5"},
        {"page_34", "764a"}, {"page_34", "7632"}, {"page_34", "7647"},
        {"page_34", "7661"}, {"page_34", "76c2"}, {"page_34", "762b"},
        {"page_34", "76a4"}, {"page_34", "76a9"}, {"page_34", "76f1"},
        {"page_34", "773d"},
        {"page_33", "4f23"}, {"page_33", "4f42"},
        {"page_39", "49a8"}, {"page_39", "4a56"}, {"page_39", "4a74"},
        {"page_39", "4c27"}, {"page_39", "4c5a"}, {"page_39", "4ca4"},
        {"page_39", "4ce9"}, {"page_39", "4dca"}, {"page_39", "4de6"},
        {"page_39", "4e8e"}, {"page_39", "4f1a"}, {"page_39", "4f9a"},
        {"page_39", "5167"}, {"page_39", "5949"}, {"page_39", "59e0"},
        {"page_39", "59f9"}, {"page_39", "5b10"}, {"page_39", "5b1d"},
        {"page_39", "672e"}, {"page_39", "683d"}, {"page_39", "68ae"},
        {"page_39", "69c8"}, {"page_39", "6abf"},
        {"page_01", "5a59"}, {"page_01", "5a60"}, {"page_01", "5a89"},
        {"page_01", "624c"}, {"page_01", "6297"}, {"page_01", "6431"},
        {"page_01", "6453"}, {"page_01", "66e5"}, {"page_01", "66ea"},
        {"page_01", "6702"},
        {"page_04", "4025"}, {"page_04", "4029"}, {"page_04", "4155"},
        {"page_04", "4157"}, {"page_04", "431d"}, {"page_04", "4382"},
        {"page_07", "44de"}, {"page_07", "4588"}, {"page_07", "45b6"},
        {"page_07", "5417"}, {"page_07", "542b"}, {"page_07", "5443"},
    };

    private Address address(String spaceName, String offset) throws Exception {
        AddressSpace space = currentProgram.getAddressFactory().getAddressSpace(spaceName);
        if (space == null) {
            throw new IllegalArgumentException("unknown address space: " + spaceName);
        }
        return space.getAddress(Long.parseLong(offset, 16));
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
                "ExportMathPrintInstructionStarts requires one absolute output path"
            );
        }
        for (String[] entry : ENTRIES) {
            Address target = address(entry[0], entry[1]);
            if (getInstructionAt(target) == null) {
                disassemble(target);
            }
        }
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

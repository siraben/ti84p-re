import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.data.*;
import ghidra.program.model.listing.*;
import java.util.*;

// Every `CALL cross_page_jump` (CD 09 2B) is a tail-jump that consumes the 3
// inline bytes (.dw addr; .db page) and never returns to +3. Mark those bytes
// as data and make the CALL non-returning so disassembly doesn't run into them.
public class FixInlineBjumps extends GhidraScript {
    public void run() throws Exception {
        Listing lst = currentProgram.getListing();
        DataType word = new WordDataType(), b = new ByteDataType();
        List<Address> sites = new ArrayList<>();
        for (Instruction in : lst.getInstructions(true)) {
            try {
                if ((getByte(in.getAddress()) & 0xFF) == 0xCD
                        && (getByte(in.getAddress().add(1)) & 0xFF) == 0x09
                        && (getByte(in.getAddress().add(2)) & 0xFF) == 0x2B)
                    sites.add(in.getAddress());
            } catch (Exception e) {}
        }
        int fixed = 0;
        for (Address a : sites) {
            try {
                Instruction in = lst.getInstructionAt(a);
                if (in == null) continue;
                int addr = (getByte(a.add(3)) & 0xFF) | ((getByte(a.add(4)) & 0xFF) << 8);
                int page = getByte(a.add(5)) & 0x3F;
                in.setFallThrough(null);                 // tail-jump: no return to +3
                clearListing(a.add(3), a.add(5));
                createData(a.add(3), word);
                createData(a.add(5), b);
                if (lst.getInstructionAt(a).getComment(CodeUnit.EOL_COMMENT) == null)
                    setEOLComment(a, String.format("bjump -> page_%02X:%04X", page, addr));
                fixed++;
            } catch (Exception e) {}
        }
        println("inline bjump sites fixed: " + fixed);
        analyzeChanges(currentProgram);
        println("functions=" + currentProgram.getFunctionManager().getFunctionCount());
    }
}

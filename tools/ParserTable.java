import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.data.*;
import ghidra.program.model.listing.*;

// Define the parser handler-address table at page_38:4000 and disassemble its targets.
public class ParserTable extends GhidraScript {
    public void run() throws Exception {
        AddressSpace p = currentProgram.getAddressFactory().getAddressSpace("page_38");
        DataType ptr = new PointerDataType();
        int entries = 0, funcs = 0;
        for (int off = 0x4000; off <= 0x40AC; off += 2) {
            Address slot = p.getAddress(off);
            int w = (getByte(slot) & 0xFF) | ((getByte(slot.add(1)) & 0xFF) << 8);
            if (w < 0x4000 || w > 0x7FFF) continue;          // not a handler address
            try {
                clearListing(slot, slot.add(1));
                createData(slot, ptr);                        // mark table slot as a pointer
                entries++;
                Address tgt = p.getAddress(w);
                if (getInstructionAt(tgt) == null) disassemble(tgt);
                if (getFunctionAt(tgt) == null && createFunction(tgt, null) != null) funcs++;
            } catch (Exception e) {}
        }
        setEOLComment(p.getAddress(0x4000), "parser handler dispatch table (token/operator -> handler)");
        println("parser table: " + entries + " handler pointers, " + funcs + " new handler functions");
    }
}

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;

public class DumpTI84 extends GhidraScript {
    public void run() throws Exception {
        long[] vecs = {0x00,0x08,0x10,0x18,0x20,0x28,0x30,0x38,0x66};
        for (long v : vecs) {
            Address a = toAddr(v);
            disassemble(a);
            if (getFunctionAt(a) == null) {
                try { createFunction(a, String.format("vec_%04x", v)); } catch (Exception e) {}
            }
        }
        analyzeChanges(currentProgram);

        FunctionManager fm = currentProgram.getFunctionManager();
        println("=== FUNCTIONS: " + fm.getFunctionCount() + " ===");
        for (Function f : fm.getFunctions(true)) {
            println(String.format("%-18s @%s  size=%d", f.getName(), f.getEntryPoint(), f.getBody().getNumAddresses()));
        }

        println("=== DISASM @0000 (first 30 instrs) ===");
        Instruction ins = getInstructionAt(toAddr(0));
        int c = 0;
        while (ins != null && c < 30) { println(ins.getAddress() + ": " + ins.toString()); ins = ins.getNext(); c++; }

        println("=== DISASM @0038 IM1 handler (first 20) ===");
        ins = getInstructionAt(toAddr(0x38)); c = 0;
        while (ins != null && c < 20) { println(ins.getAddress() + ": " + ins.toString()); ins = ins.getNext(); c++; }

        println("=== STRINGS (first 40) ===");
        DataIterator di = currentProgram.getListing().getDefinedData(true);
        int sc = 0;
        while (di.hasNext() && sc < 40) {
            Data d = di.next();
            if (d.hasStringValue()) { println(d.getAddress() + ": " + d.getValue()); sc++; }
        }
    }
}

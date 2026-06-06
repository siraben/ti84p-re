import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import java.io.*;
import java.nio.file.*;
import java.math.BigInteger;

// Dump an operand-stripped mnemonic signature for each bcall routine, so two OS
// versions can be diffed without relocation noise. Loads page overlays from
// <dir>/rom.bin, reads <dir>/targets.txt (name<TAB>id<TAB>addr<TAB>page), and
// writes <dir>/mnem.txt:  id <TAB> name <TAB> mnemonic-sequence.
public class DumpBcalls extends GhidraScript {
    public void run() throws Exception {
        String dir = getScriptArgs()[0];
        byte[] rom = Files.readAllBytes(Paths.get(dir + "/rom.bin"));
        AddressSpace ram = currentProgram.getAddressFactory().getDefaultAddressSpace();
        Memory mem = currentProgram.getMemory();
        int npages = rom.length / 0x4000;
        // overlay each flash page 1..N-1 at the 0x4000 window (page 0 is the imported program)
        for (int p = 1; p < npages; p++) {
            boolean allzero = true;
            for (int k = 0; k < 0x4000; k++) if (rom[p*0x4000+k] != 0) { allzero = false; break; }
            if (allzero) continue;            // skip pages absent from this OS image
            try {
                InputStream is = new ByteArrayInputStream(rom, p*0x4000, 0x4000);
                mem.createInitializedBlock(String.format("page_%02X", p),
                        ram.getAddress(0x4000), is, 0x4000, monitor, true);
            } catch (Exception e) {}
        }
        StringBuilder out = new StringBuilder();
        for (String line : Files.readAllLines(Paths.get(dir + "/targets.txt"))) {
            String[] q = line.split("\t");
            if (q.length < 4) continue;
            String name = q[1] == null ? "" : q[0];
            int id = Integer.parseInt(q[1].trim(), 16);
            int a  = Integer.parseInt(q[2].trim(), 16);
            int pg = Integer.parseInt(q[3].trim(), 16) & 0x3F;
            Address addr = resolve(pg, a);
            String mn = (addr == null) ? "?nopage" : dumpMnem(addr);
            out.append(String.format("%04X\t%s\t%s\n", id, q[0], mn));
        }
        Files.write(Paths.get(dir + "/mnem.txt"), out.toString().getBytes());
        println("DumpBcalls wrote " + dir + "/mnem.txt");
    }

    Address resolve(int pg, int a) {
        if (pg == 0) return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(a & 0xFFFF);
        MemoryBlock b = currentProgram.getMemory().getBlock(String.format("page_%02X", pg));
        if (b == null) return null;
        try { return b.getStart().add((a & 0x3FFF)); } catch (Exception e) { return null; }
    }

    String dumpMnem(Address addr) {
        try {
            if (getInstructionAt(addr) == null) disassemble(addr);
        } catch (Exception e) {}
        StringBuilder s = new StringBuilder();
        Instruction ins = getInstructionAt(addr);
        int n = 0;
        while (ins != null && n < 120) {
            s.append(ins.getMnemonicString()).append(' ');
            n++;
            ghidra.program.model.symbol.FlowType ft = ins.getFlowType();
            if (ft.isTerminal() || (ft.isJump() && !ft.isConditional() && !ft.isCall())) break;
            Address na = ins.getFallThrough();
            if (na == null) break;
            if (getInstructionAt(na) == null) { try { disassemble(na); } catch (Exception e) {} }
            ins = getInstructionAt(na);
        }
        if (n == 0) return "?nodisasm";
        return s.toString().trim();
    }
}

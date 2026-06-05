import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.data.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.symbol.SourceType;
import java.nio.file.*;
import java.util.*;

public class BuildTI84 extends GhidraScript {

    public void run() throws Exception {
        Memory mem = currentProgram.getMemory();
        AddressFactory af = currentProgram.getAddressFactory();
        AddressSpace ram = af.getDefaultAddressSpace();
        AddressSpace io = af.getAddressSpace("io");

        // --- 1. Memory blocks for RAM (0x8000-0xFFFF) and I/O ports ---
        try {
            if (mem.getBlock(ram.getAddress(0x8000)) == null)
                mem.createUninitializedBlock("RAM", ram.getAddress(0x8000), 0x8000, false);
            println("Created RAM block 8000-FFFF");
        } catch (Exception e) { println("RAM block: " + e); }
        if (io != null) {
            try {
                if (mem.getBlock(io.getAddress(0)) == null)
                    mem.createUninitializedBlock("PORTS", io.getAddress(0), 0x100, false);
                println("Created I/O block 0000-00FF (io space)");
            } catch (Exception e) { println("io block: " + e); }
        }

        // --- 2. Seed Z80 vectors + name handlers ---
        long[] vecs = {0x00,0x08,0x10,0x18,0x20,0x28,0x30,0x38,0x66};
        for (long v : vecs) { disassemble(ram.getAddress(v));
            if (getFunctionAt(ram.getAddress(v))==null)
                try { createFunction(ram.getAddress(v), null); } catch (Exception e){} }
        analyzeChanges(currentProgram);

        rename(ram, 0x2a2f, "bcall_dispatcher");
        rename(ram, 0x006d, "isr_im1");
        rename(ram, 0x0000, "reset");
        comment(ram, 0x0000, "RST 00h / CPU reset. IN port2 bit7 (batt/link), JP boot @0x028c.");
        comment(ram, 0x0028, "RST 28h = bcall(): 2-byte ID follows opcode; dispatched @bcall_dispatcher.");
        comment(ram, 0x0038, "RST 38h = IM1 interrupt vector -> isr_im1 @0x006d.");

        // --- 3. RAM variable labels from ti83plus.inc ---
        int rc = applyLabels("/tmp/ti84_build/ram.txt", ram);
        println("Applied RAM labels: " + rc);

        // --- 4. Port labels in io space ---
        int pc = 0;
        if (io != null) pc = applyLabels("/tmp/ti84_build/ports.txt", io);
        println("Applied port labels: " + pc);

        // --- 5. Detect & type TI BCD floating-point constants in page 0 ---
        int fc = applyFloats(ram);
        println("Defined TI BCD floats: " + fc);

        println("BuildTI84 complete.");
    }

    void rename(AddressSpace s, long a, String name) {
        try { Function f = getFunctionAt(s.getAddress(a));
            if (f != null) f.setName(name, SourceType.USER_DEFINED); } catch (Exception e){}
    }
    void comment(AddressSpace s, long a, String c) {
        try { setEOLComment(s.getAddress(a), c); } catch (Exception e){}
    }

    int applyLabels(String path, AddressSpace space) throws Exception {
        int n = 0;
        for (String line : Files.readAllLines(Paths.get(path))) {
            String[] p = line.trim().split("\\s+", 2);
            if (p.length < 2) continue;
            try { createLabel(space.getAddress(Long.parseLong(p[0],16)), p[1], true); n++; }
            catch (Exception e) {}
        }
        return n;
    }

    // TI float: b0=type(0/0x80), b1=exp(+0x80), b2..b8 = 7 bytes BCD (14 digits)
    int applyFloats(AddressSpace ram) throws Exception {
        StructureDataType tif = new StructureDataType("TIFloat", 0);
        tif.add(new ByteDataType(), "type", "0x00 real, 0x80 negative");
        tif.add(new ByteDataType(), "exp", "exponent + 0x80");
        tif.add(new ArrayDataType(new ByteDataType(), 7, 1), "mantissa", "14 packed BCD digits");
        DataType dt = currentProgram.getDataTypeManager().resolve(tif, null);

        Listing lst = currentProgram.getListing();
        int count = 0;
        for (long a = 0x0000; a <= 0x3FF7; a++) {
            Address addr = ram.getAddress(a);
            int b0 = getByte(addr) & 0xFF;
            if (b0 != 0x00 && b0 != 0x80) continue;
            int b1 = getByte(addr.add(1)) & 0xFF;
            if (b1 < 0x60 || b1 > 0xA0) continue;          // plausible exponent window
            int[] dig = new int[14]; boolean ok = true; boolean any = false;
            for (int i = 0; i < 7; i++) {
                int b = getByte(addr.add(2 + i)) & 0xFF;
                int hi = b >> 4, lo = b & 0xF;
                if (hi > 9 || lo > 9) { ok = false; break; }
                dig[i*2] = hi; dig[i*2+1] = lo;
                if (hi != 0 || lo != 0) any = true;
            }
            if (!ok || !any) continue;
            if (dig[0] == 0) continue;                      // normalized: leading digit nonzero
            // require all 9 bytes currently undefined (don't clobber code)
            boolean free = true;
            for (int i = 0; i < 9; i++) {
                CodeUnit cu = lst.getCodeUnitContaining(addr.add(i));
                if (cu instanceof Instruction || (cu instanceof Data && ((Data)cu).isDefined())) { free = false; break; }
            }
            if (!free) continue;
            try {
                clearListing(addr, addr.add(8));
                createData(addr, dt);
                StringBuilder sb = new StringBuilder(b0==0x80?"-":"");
                sb.append(dig[0]).append('.');
                for (int i = 1; i < 14; i++) sb.append(dig[i]);
                sb.append("e").append(b1 - 0x80);
                setEOLComment(addr, "TI float = " + sb);
                createLabel(addr, String.format("flt_%04x", a), true);
                count++;
                a += 8; // skip past this float
            } catch (Exception e) {}
        }
        return count;
    }
}

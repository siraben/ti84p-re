import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.data.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.SourceType;
import java.io.*;
import java.nio.file.*;
import java.util.*;

public class BuildTI84Full extends GhidraScript {
    Map<Integer,String> bcalls = new HashMap<>();

    public void run() throws Exception {
        String dir = getScriptArgs().length > 0 ? getScriptArgs()[0] : "/tmp/ti84_build";
        byte[] rom = Files.readAllBytes(Paths.get(dir + "/rom.bin"));
        Memory mem = currentProgram.getMemory();
        AddressFactory af = currentProgram.getAddressFactory();
        AddressSpace ram = af.getDefaultAddressSpace();
        AddressSpace io = af.getAddressSpace("io");
        int npages = rom.length / 0x4000;

        // 1. Overlays for flash pages 1..N-1 at 0x4000 (page 0 already imported at 0x0000)
        int ov = 0;
        for (int p = 1; p < npages; p++) {
            try {
                InputStream is = new ByteArrayInputStream(rom, p * 0x4000, 0x4000);
                mem.createInitializedBlock(String.format("page_%02X", p),
                        ram.getAddress(0x4000), is, 0x4000, monitor, true);
                ov++;
            } catch (Exception e) { println("page " + p + ": " + e); }
        }
        println("Overlays created: " + ov);

        // 2. RAM + I/O blocks
        try { mem.createUninitializedBlock("RAM", ram.getAddress(0x8000), 0x8000, false); } catch (Exception e) {}
        if (io != null) try { mem.createUninitializedBlock("PORTS", io.getAddress(0), 0x100, false); } catch (Exception e) {}

        // 3. Load bcall table
        for (String line : Files.readAllLines(Paths.get(dir + "/bcalls.txt"))) {
            String[] p = line.trim().split("\\s+", 2);
            if (p.length == 2) bcalls.put(Integer.parseInt(p[0], 16), p[1]);
        }
        println("bcall names loaded: " + bcalls.size());

        // 4. Seed page-0 vectors + handler names + comments
        long[] vecs = {0x00,0x08,0x10,0x18,0x20,0x28,0x30,0x38,0x66};
        for (long v : vecs) { disassemble(ram.getAddress(v));
            if (getFunctionAt(ram.getAddress(v)) == null) try { createFunction(ram.getAddress(v), null); } catch (Exception e){} }

        analyzeChanges(currentProgram);

        // 6. bcall fixup (multi-pass: ID->data, fallthrough +3, name comment)
        int fixed = fixBcalls();
        println("bcall sites fixed: " + fixed);
        analyzeChanges(currentProgram);

        // 7. Names / comments on page 0
        setName(0x2a2f, "bcall_dispatcher"); setName(0x006d, "isr_im1"); setName(0x0000, "reset");
        eol(0x0000, "RST 00h / CPU reset.");
        eol(0x0028, "RST 28h = bcall(): 2-byte ID follows; dispatched @bcall_dispatcher.");
        eol(0x0038, "RST 38h = IM1 interrupt vector -> isr_im1.");

        // 8. RAM + port labels
        println("RAM labels: " + applyLabels(dir + "/ram.txt", ram));
        if (io != null) println("Port labels: " + applyLabels(dir + "/ports.txt", io));

        // 9. Full ROM-wide analysis (ASCII strings + data across all overlays)
        analyzeAll(currentProgram);

        // 10. TI BCD floats across all initialized blocks (claims remaining undefined)
        println("TI floats: " + applyFloats());

        println("BuildTI84Full complete. pages=" + npages);
    }

    void setName(long a, String n) { try { Function f = getFunctionAt(toAddr(a)); if (f != null) f.setName(n, SourceType.USER_DEFINED); } catch (Exception e){} }
    void eol(long a, String c) { try { setEOLComment(toAddr(a), c); } catch (Exception e){} }

    int fixBcalls() {
        Listing lst = currentProgram.getListing();
        DataType word = new WordDataType();
        Set<Address> done = new HashSet<>();
        int total = 0;
        for (int pass = 0; pass < 6; pass++) {
            List<Address> sites = new ArrayList<>();
            for (Instruction in : lst.getInstructions(true)) {
                if (done.contains(in.getAddress())) continue;
                int op;
                try { op = getByte(in.getAddress()) & 0xFF; } catch (Exception e) { continue; }
                if (op == 0xEF) sites.add(in.getAddress());   // rst 28h opcode
            }
            if (sites.isEmpty()) break;
            for (Address a : sites) {
                done.add(a);
                try {
                    int lo = getByte(a.add(1)) & 0xFF, hi = getByte(a.add(2)) & 0xFF;
                    int id = lo | (hi << 8);
                    String name = bcalls.get(id);
                    Instruction in = lst.getInstructionAt(a);
                    if (in != null) in.setFallThrough(a.add(3));
                    clearListing(a.add(1), a.add(2));
                    createData(a.add(1), word);
                    setEOLComment(a, "bcall(" + (name != null ? name : String.format("0x%04X", id)) + ")");
                    disassemble(a.add(3));
                    total++;
                } catch (Exception e) {}
            }
        }
        return total;
    }

    int applyLabels(String path, AddressSpace space) throws Exception {
        int n = 0;
        for (String line : Files.readAllLines(Paths.get(path))) {
            String[] p = line.trim().split("\\s+", 2);
            if (p.length < 2) continue;
            try { createLabel(space.getAddress(Long.parseLong(p[0], 16)), p[1], true); n++; } catch (Exception e) {}
        }
        return n;
    }

    int applyFloats() throws Exception {
        StructureDataType tif = new StructureDataType("TIFloat", 0);
        tif.add(new ByteDataType(), "type", "0x00 real, 0x80 negative");
        tif.add(new ByteDataType(), "exp", "exponent + 0x80");
        tif.add(new ArrayDataType(new ByteDataType(), 7, 1), "mantissa", "14 packed BCD digits");
        DataType dt = currentProgram.getDataTypeManager().resolve(tif, null);
        Listing lst = currentProgram.getListing();
        int count = 0;
        for (MemoryBlock blk : currentProgram.getMemory().getBlocks()) {
            if (!blk.isInitialized() || blk.getName().equals("RAM") || blk.getName().equals("PORTS")) continue;
            Address start = blk.getStart(), end = blk.getEnd();
            for (Address addr = start; addr.compareTo(end.subtract(9)) < 0; ) {
                try {
                    int b0 = getByte(addr) & 0xFF;
                    if (b0 != 0x00 && b0 != 0x80) { addr = addr.add(1); continue; }
                    int b1 = getByte(addr.add(1)) & 0xFF;
                    if (b1 < 0x60 || b1 > 0xA0) { addr = addr.add(1); continue; }
                    int[] dig = new int[14]; boolean ok = true, any = false;
                    for (int i = 0; i < 7; i++) {
                        int b = getByte(addr.add(2 + i)) & 0xFF, hi = b >> 4, lo = b & 0xF;
                        if (hi > 9 || lo > 9) { ok = false; break; }
                        dig[i*2] = hi; dig[i*2+1] = lo; if (hi != 0 || lo != 0) any = true;
                    }
                    if (!ok || !any || dig[0] == 0) { addr = addr.add(1); continue; }
                    boolean free = true;
                    for (int i = 0; i < 9; i++) {
                        CodeUnit cu = lst.getCodeUnitContaining(addr.add(i));
                        if (cu instanceof Instruction || (cu instanceof Data && ((Data)cu).isDefined())) { free = false; break; }
                    }
                    if (!free) { addr = addr.add(1); continue; }
                    clearListing(addr, addr.add(8));
                    createData(addr, dt);
                    StringBuilder sb = new StringBuilder(b0 == 0x80 ? "-" : "");
                    sb.append(dig[0]).append('.');
                    for (int i = 1; i < 14; i++) sb.append(dig[i]);
                    sb.append("e").append(b1 - 0x80);
                    setEOLComment(addr, "TI float = " + sb);
                    count++;
                    addr = addr.add(9);
                } catch (Exception e) { addr = addr.add(1); }
            }
        }
        return count;
    }
}

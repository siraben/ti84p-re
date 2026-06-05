import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.data.*;
import java.nio.file.*;
import java.util.*;

public class BuildTypes extends GhidraScript {
    DataTypeManager dtm;
    String dir;

    public void run() throws Exception {
        dtm = currentProgram.getDataTypeManager();
        dir = getScriptArgs().length > 0 ? getScriptArgs()[0] : ".";

        println("TIVarType:  " + mkEnum("TIVarType",  "ty_vartype.txt", 1));
        println("TIError:    " + mkEnum("TIError",    "ty_error.txt",   1));
        println("TIKeyCode:  " + mkEnum("TIKeyCode",  "ty_keycode.txt", 1));
        println("TIToken:    " + mkEnum("TIToken",    "ty_token.txt",   1));

        DataType flt = ensureFloat();
        mkCompound(flt);
        mkSystemFlags();
        println("Applied regions: " + applyRegions());
        println("BuildTypes complete.");
    }

    int mkEnum(String name, String file, int size) throws Exception {
        EnumDataType e = new EnumDataType(name, size);
        int n = 0;
        for (String line : Files.readAllLines(Paths.get(dir + "/" + file))) {
            String[] p = line.trim().split("\\s+");
            if (p.length < 2) continue;
            try { e.add(p[0], Long.parseLong(p[1], 16)); n++; } catch (Exception ex) {}
        }
        dtm.addDataType(e, DataTypeConflictHandler.REPLACE_HANDLER);
        return n;
    }

    DataType ensureFloat() {
        DataType d = dtm.getDataType("/TIFloat");
        if (d != null) return d;
        StructureDataType t = new StructureDataType("TIFloat", 0);
        t.add(new ByteDataType(), "type", "0x00 real, 0x80 negative");
        t.add(new ByteDataType(), "exp", "exponent + 0x80");
        t.add(new ArrayDataType(new ByteDataType(), 7, 1), "mantissa", "14 packed BCD digits");
        return dtm.addDataType(t, DataTypeConflictHandler.REPLACE_HANDLER);
    }

    void mkCompound(DataType flt) {
        StructureDataType cx = new StructureDataType("TIComplex", 0);
        cx.add(flt, "re", null); cx.add(flt, "im", null);
        dtm.addDataType(cx, DataTypeConflictHandler.REPLACE_HANDLER);

        StructureDataType lh = new StructureDataType("TIListHdr", 0);
        lh.add(new WordDataType(), "size", "element count; followed by TIFloat[size]");
        dtm.addDataType(lh, DataTypeConflictHandler.REPLACE_HANDLER);

        StructureDataType mh = new StructureDataType("TIMatrixHdr", 0);
        mh.add(new ByteDataType(), "cols", null); mh.add(new ByteDataType(), "rows", null);
        mh.setDescription("followed by TIFloat[rows*cols], column-major");
        dtm.addDataType(mh, DataTypeConflictHandler.REPLACE_HANDLER);

        // VAT record (RAM, grows downward) - representative layout
        StructureDataType vat = new StructureDataType("VATEntry", 0);
        vat.add(new ByteDataType(), "typeID", "TIVarType");
        vat.add(new ByteDataType(), "version", null);
        vat.add(new WordDataType(), "dataAddr", null);
        vat.add(new ByteDataType(), "dataPage", "flash page, 0=RAM");
        vat.add(new ByteDataType(), "nameLen", "name bytes follow (reverse order)");
        dtm.addDataType(vat, DataTypeConflictHandler.REPLACE_HANDLER);

        // Flash app/OS header field (TLV) + certificate marker - library refs
        StructureDataType ah = new StructureDataType("FlashHeaderField", 0);
        ah.add(new ByteDataType(), "fieldTypeHi", "0x80 = field marker");
        ah.add(new ByteDataType(), "fieldTypeLo", null);
        ah.setDescription("TI flash TLV header field; length nibble in low byte, value follows");
        dtm.addDataType(ah, DataTypeConflictHandler.REPLACE_HANDLER);
    }

    void mkSystemFlags() throws Exception {
        TreeMap<Integer, List<String>> byOff = new TreeMap<>();
        for (String line : Files.readAllLines(Paths.get(dir + "/ty_flagbytes.txt"))) {
            String[] p = line.trim().split("\\s+");
            if (p.length < 2) continue;
            int off = Integer.parseInt(p[1], 16);
            byOff.computeIfAbsent(off, k -> new ArrayList<>()).add(p[0]);
        }
        if (byOff.isEmpty()) return;
        int size = byOff.lastKey() + 1;
        StructureDataType sf = new StructureDataType("SystemFlags", size);
        for (Map.Entry<Integer, List<String>> e : byOff.entrySet()) {
            String nm = e.getValue().get(0);
            String cm = String.join(", ", e.getValue());
            try { sf.replaceAtOffset(e.getKey(), new ByteDataType(), 1, nm, cm); } catch (Exception ex) {}
        }
        sf.setDescription("IY-indexed system flags (base @ flags = 0x89F0)");
        dtm.addDataType(sf, DataTypeConflictHandler.REPLACE_HANDLER);
    }

    int applyRegions() throws Exception {
        int n = 0;
        for (String line : Files.readAllLines(Paths.get(dir + "/ty_regions.txt"))) {
            String[] p = line.trim().split("\\t");
            if (p.length < 2) continue;
            try {
                Address a = toAddr(Long.parseLong(p[0].trim(), 16));
                String tyName = p[1].trim();
                String cnt = p.length > 2 ? p[2].trim() : "";
                DataType dt;
                if (tyName.equals("byte") && !cnt.isEmpty())
                    dt = new ArrayDataType(new ByteDataType(), Integer.parseInt(cnt), 1);
                else if (tyName.equals("byte"))
                    dt = new ByteDataType();
                else { dt = dtm.getDataType("/" + tyName); if (dt == null) continue; }
                clearListing(a, a.add(dt.getLength() - 1));
                createData(a, dt);
                n++;
            } catch (Exception ex) {}
        }
        return n;
    }
}

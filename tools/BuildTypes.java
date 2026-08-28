import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressFactory;
import ghidra.program.model.address.AddressSpace;
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

        StructureDataType op = new StructureDataType("TIOpRegister", 0);
        op.add(flt, "value", "9-byte stored-number image");
        op.add(new ArrayDataType(new ByteDataType(), 2, 1), "guard",
            "two trailing BCD guard bytes used during calculation");
        op.setDescription("11-byte OP register slot");
        dtm.addDataType(op, DataTypeConflictHandler.REPLACE_HANDLER);

        StructureDataType lh = new StructureDataType("TIListHdr", 0);
        lh.add(new WordDataType(), "size", "element count; followed by TIFloat[size]");
        dtm.addDataType(lh, DataTypeConflictHandler.REPLACE_HANDLER);

        StructureDataType mh = new StructureDataType("TIMatrixHdr", 0);
        mh.add(new ByteDataType(), "columns", null); mh.add(new ByteDataType(), "rows", null);
        mh.setDescription("followed by TIFloat[rows*columns], row-major");
        dtm.addDataType(mh, DataTypeConflictHandler.REPLACE_HANDLER);

        // Fixed-token VAT record.  The VAT grows downward, so this structure is
        // ordered from the lowest-address name byte through the high-address
        // type byte.  Named program/appvar/group entries have a variable-length
        // name prefix but share the six metadata bytes after the matched name.
        StructureDataType vat = new StructureDataType("VATEntry", 0);
        vat.add(new ArrayDataType(new ByteDataType(), 3, 1), "name", "fixed token/name bytes; high-address byte is matched first");
        vat.add(new ByteDataType(), "dataPage", "flash page, 0=RAM");
        vat.add(new ByteDataType(), "dataAddrHi", null);
        vat.add(new ByteDataType(), "dataAddrLo", null);
        vat.add(new ByteDataType(), "version", null);
        vat.add(new ByteDataType(), "t2", "secondary type/version metadata");
        vat.add(new ByteDataType(), "typeID", "low 5 bits = TIVarType; high bits carry archive state");
        vat.setDescription("9-byte fixed-token VAT entry, stored high-address-first by the downward-growing VAT");
        dtm.addDataType(vat, DataTypeConflictHandler.REPLACE_HANDLER);

        // OS "context" control block (active mode's handler vectors) @ cxMain=0x858D
        StructureDataType ctx = new StructureDataType("Context", 0);
        ctx.add(new PointerDataType(), "cxMain", "main/event handler");
        ctx.add(new PointerDataType(), "cxPPutAway", "putaway handler ptr");
        ctx.add(new PointerDataType(), "cxPutAway", "putaway");
        ctx.add(new PointerDataType(), "cxRedisp", "redisplay/repaint handler");
        ctx.add(new PointerDataType(), "cxErrorEP", "error entry point");
        ctx.add(new PointerDataType(), "cxSizeWind", "window size handler");
        ctx.add(new ByteDataType(), "cxPage", "flash page of handlers");
        ctx.add(new ByteDataType(), "cxCurApp", "current context id (= a key code)");
        ctx.setDescription("14-byte active context block @0x858D; cxPrev begins its saved shadow");
        dtm.addDataType(ctx, DataTypeConflictHandler.REPLACE_HANDLER);

        StructureDataType parser = new StructureDataType("TIBasicParserState", 0);
        parser.add(new ArrayDataType(new ByteDataType(), 9, 1), "basic_prog",
            "current program identity/name image");
        parser.add(new WordDataType(), "basic_start", "start of token stream");
        parser.add(new WordDataType(), "next_parse_byte", "current parse cursor");
        parser.add(new WordDataType(), "basic_end", "inclusive parser/refill boundary");
        parser.add(new ByteDataType(), "num_arguments", "active argument count");
        parser.setDescription("contiguous TI-BASIC program and parse-cursor state @0x9652");
        dtm.addDataType(parser, DataTypeConflictHandler.REPLACE_HANDLER);

        StructureDataType linkHeader = new StructureDataType("LinkPacketHeader", 0);
        linkHeader.add(new ByteDataType(), "machine_id", null);
        linkHeader.add(new ByteDataType(), "command_id", null);
        linkHeader.add(new WordDataType(), "data_length", "little-endian payload length");
        linkHeader.setDescription("four-byte TI link packet header @0x8674");
        dtm.addDataType(linkHeader, DataTypeConflictHandler.REPLACE_HANDLER);

        StructureDataType archive = new StructureDataType("ArchiveWorkspacePrefix", 0);
        archive.add(new ByteDataType(), "page", "0x83EE");
        archive.add(new WordDataType(), "data_ptr", "0x83EF");
        archive.add(new WordDataType(), "vat_ptr", "0x83F1; start of the 12-byte saved slice");
        archive.add(new WordDataType(), "dest_ptr", "0x83F3");
        archive.add(new WordDataType(), "data_size", "0x83F5");
        archive.add(new WordDataType(), "size", "0x83F7");
        archive.add(new WordDataType(), "size_full", "0x83F9");
        archive.add(new ArrayDataType(new ByteDataType(), 2, 1), "unknown_tail",
            "0x83FB-0x83FC; included in the saved vat_ptr tail");
        archive.setDescription("confirmed archive workspace prefix; not a 12-byte ArcInfo object");
        dtm.addDataType(archive, DataTypeConflictHandler.REPLACE_HANDLER);

        StructureDataType hash = new StructureDataType("CompactHashResult", 0);
        hash.add(new ByteDataType(), "length", null);
        hash.add(new ArrayDataType(new ByteDataType(), 16, 1), "bytes", null);
        dtm.addDataType(hash, DataTypeConflictHandler.REPLACE_HANDLER);

        StructureDataType framebuffer = new StructureDataType("MonoFramebuffer", 0);
        DataType framebufferRow = new ArrayDataType(new ByteDataType(), 12, 1);
        framebuffer.add(new ArrayDataType(framebufferRow, 64, 12), "rows",
            "64 rows of 96 one-bit pixels, MSB first");
        dtm.addDataType(framebuffer, DataTypeConflictHandler.REPLACE_HANDLER);

        StructureDataType tableBand = new StructureDataType("TableCacheBand", 0);
        tableBand.add(new ArrayDataType(flt, 7, flt.getLength()), "value", null);
        DataType tableBandType = dtm.addDataType(
            tableBand, DataTypeConflictHandler.REPLACE_HANDLER
        );
        StructureDataType tableCache = new StructureDataType("TableValueCache", 0);
        tableCache.add(new ArrayDataType(tableBandType, 3, tableBandType.getLength()),
            "band", "three 0x3F-byte scroll bands");
        dtm.addDataType(tableCache, DataTypeConflictHandler.REPLACE_HANDLER);

        StructureDataType window = new StructureDataType("GraphWindowValues", 0);
        for (String field : new String[] {
                "x_min", "x_max", "x_scale", "y_min", "y_max", "y_scale",
                "theta_min", "theta_max", "theta_step", "t_min", "t_max", "t_step",
                "plot_start", "n_max", "u0", "v0", "n_min", "u02", "v02", "w0",
                "plot_step", "x_resolution", "w02" }) {
            window.add(flt, field, null);
        }
        dtm.addDataType(window, DataTypeConflictHandler.REPLACE_HANDLER);

        StructureDataType worker = new StructureDataType("RamWorkerDescriptor", 0);
        worker.add(new WordDataType(), "length", "little-endian code length");
        worker.setDescription("length-prefixed worker; copied code begins at +2");
        dtm.addDataType(worker, DataTypeConflictHandler.REPLACE_HANDLER);

        StructureDataType certificateTail = new StructureDataType("CertificateMetadataTail", 0);
        certificateTail.add(new ByteDataType(), "restriction_control", "selected-half offset 0x1DD2");
        certificateTail.add(new ArrayDataType(new ByteDataType(), 13, 1),
            "restriction_record", "selected-half offsets 0x1DD3-0x1DDF");
        certificateTail.add(new ArrayDataType(new ByteDataType(), 10, 1),
            "unresolved_1de0_1de9", null);
        certificateTail.add(new ArrayDataType(new ByteDataType(), 0x66, 1),
            "gc_recovery", "selected-half offsets 0x1DEA-0x1E4F");
        certificateTail.add(new ArrayDataType(new ByteDataType(), 0xC8, 1),
            "ti84_app_trials", "selected-half offsets 0x1E50-0x1F17");
        certificateTail.add(new ArrayDataType(new ByteDataType(), 0xC8, 1),
            "alternate_model_span", "selected-half offsets 0x1F18-0x1FDF");
        certificateTail.add(new ArrayDataType(new ByteDataType(), 0x20, 1),
            "validity", "selected-half offsets 0x1FE0-0x1FFF");
        certificateTail.setDescription(
            "partial certificate-half tail; dynamically based at selected half + 0x1DD2"
        );
        dtm.addDataType(certificateTail, DataTypeConflictHandler.REPLACE_HANDLER);

        StructureDataType arena = new StructureDataType("MathPrintArenaState", 0);
        arena.add(new WordDataType(), "structural_begin", "0x8DAF");
        arena.add(new WordDataType(), "extended_leaf_end", "0x8DB1");
        arena.add(new ArrayDataType(new ByteDataType(), 9, 1), "unknown_04", "0x8DB3-0x8DBB");
        arena.add(new WordDataType(), "leaf_begin", "0x8DBC");
        arena.add(new WordDataType(), "leaf_end", "0x8DBE");
        arena.add(new WordDataType(), "unknown_11", "0x8DC0");
        arena.add(new WordDataType(), "active_leaf", "0x8DC2");
        arena.setDescription("verified MathPrint arena boundaries with one unresolved word");
        dtm.addDataType(arena, DataTypeConflictHandler.REPLACE_HANDLER);

        StructureDataType viewport = new StructureDataType("EqDispViewportState", 0);
        viewport.add(new ByteDataType(), "physical_x", null);
        viewport.add(new ByteDataType(), "physical_y", null);
        viewport.add(new ByteDataType(), "right_bound", null);
        viewport.add(new ByteDataType(), "bottom_bound", null);
        viewport.add(new WordDataType(), "logical_x", null);
        viewport.add(new WordDataType(), "logical_y", null);
        viewport.add(new WordDataType(), "horizontal_clip", null);
        viewport.add(new WordDataType(), "vertical_clip", null);
        viewport.setDescription("MathPrint physical and logical viewport state @0x8DFA");
        dtm.addDataType(viewport, DataTypeConflictHandler.REPLACE_HANDLER);

        StructureDataType record = new StructureDataType("SettledRecordHeader", 0);
        record.add(new WordDataType(), "id", "arena record ID");
        record.add(new ByteDataType(), "type", "leaf/object or structural render type");
        for (String field : new String[] {
                "word03", "word05", "word07", "word09",
                "word0B", "word0D", "word0F", "word11" }) {
            record.add(new WordDataType(), field, "render-type-specific field");
        }
        record.add(new ByteDataType(), "byte13", "first payload byte or type-specific data");
        record.setDescription("20-byte MathPrint settled-record header");
        dtm.addDataType(record, DataTypeConflictHandler.REPLACE_HANDLER);

        StructureDataType forOps = new StructureDataType("TIForOpsRecord", 0);
        forOps.add(new ByteDataType(), "sentinel", null);
        forOps.add(new WordDataType(), "continuation", "for_first_update or for_steady_update");
        forOps.add(new WordDataType(), "state", "0x0012 in the natural For(/End path");
        forOps.setDescription("five-byte natural For(/End OPS record");
        dtm.addDataType(forOps, DataTypeConflictHandler.REPLACE_HANDLER);

        StructureDataType sourceTypeRow = new StructureDataType("EqDispSourceTypeRow", 0);
        sourceTypeRow.add(new WordDataType(), "source_token", null);
        sourceTypeRow.add(new ByteDataType(), "render_type", null);
        dtm.addDataType(sourceTypeRow, DataTypeConflictHandler.REPLACE_HANDLER);

        StructureDataType childScanRow = new StructureDataType("EqDispChildScanRow", 0);
        childScanRow.add(new ByteDataType(), "scan_kind", null);
        childScanRow.add(new ArrayDataType(new ByteDataType(), 4, 1), "child_order", null);
        dtm.addDataType(childScanRow, DataTypeConflictHandler.REPLACE_HANDLER);

        StructureDataType geometryRow = new StructureDataType("EqDispAllocationGeometryRow", 0);
        geometryRow.add(new ByteDataType(), "workspace_units", null);
        geometryRow.add(new ByteDataType(), "child_count", null);
        geometryRow.add(new ByteDataType(), "record_size", null);
        dtm.addDataType(geometryRow, DataTypeConflictHandler.REPLACE_HANDLER);

        StructureDataType stats = new StructureDataType("TIStatResultsPrefix", 0);
        for (String field : new String[] {
                "StatN", "XMean", "SumX", "SumXSqr", "StdX", "StdPX",
                "MinX", "MaxX", "MinY", "MaxY", "YMean", "SumY",
                "SumYSqr", "StdY", "StdPY", "SumXY", "Corr", "MedX",
                "Q1", "Q3", "QuadA", "QuadB", "QuadC", "CubeD", "QuartE",
                "MedX1", "MedX2", "MedX3", "MedY1", "MedY2", "MedY3" }) {
            stats.add(flt, field, null);
        }
        stats.setDescription("confirmed 31-result prefix of statVars @0x8A3A");
        dtm.addDataType(stats, DataTypeConflictHandler.REPLACE_HANDLER);

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
        // `flags` is 0x89F0 and the next official region, `statVars`, begins at
        // 0x8A3A.  Keep unnamed flag bytes in the structure so ROM accesses
        // through IY+0x3F and later offsets remain inside the typed region.
        int size = 0x8A3A - 0x89F0;
        if (byOff.lastKey() >= size)
            throw new IllegalStateException("flag-byte offset exceeds flags-to-statVars span");
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
        int lineNumber = 0;
        for (String raw : Files.readAllLines(Paths.get(dir + "/ty_regions.txt"))) {
            lineNumber++;
            String line = raw.trim();
            if (line.isEmpty() || line.startsWith("#")) continue;
            String[] p = line.split("\\t");
            if (p.length < 2 || p.length > 4)
                throw new IllegalArgumentException(
                    "ty_regions.txt:" + lineNumber + ": malformed row: " + raw
                );
            try {
                Address a = parseLocation(p[0].trim());
                String tyName = p[1].trim();
                String cnt = p.length > 2 ? p[2].trim() : "";
                DataType dt;
                if (tyName.equals("byte"))
                    dt = new ByteDataType();
                else if (tyName.equals("word"))
                    dt = new WordDataType();
                else {
                    dt = dtm.getDataType("/" + tyName);
                    if (dt == null)
                        throw new IllegalArgumentException("unknown data type: " + tyName);
                }
                if (!cnt.isEmpty())
                    dt = new ArrayDataType(dt, Integer.parseInt(cnt), dt.getLength());
                clearListing(a, a.add(dt.getLength() - 1));
                createData(a, dt);
                n++;
            } catch (Exception exception) {
                throw new IllegalArgumentException(
                    "ty_regions.txt:" + lineNumber + ": " + raw, exception
                );
            }
        }
        return n;
    }

    Address parseLocation(String text) {
        if (!text.contains(":")) return toAddr(Long.parseLong(text, 16));
        String[] fields = text.split(":", 2);
        AddressFactory factory = currentProgram.getAddressFactory();
        AddressSpace space = factory.getAddressSpace(fields[0]);
        if (space == null)
            throw new IllegalArgumentException("unknown address space: " + fields[0]);
        return space.getAddress(Long.parseLong(fields[1], 16));
    }
}

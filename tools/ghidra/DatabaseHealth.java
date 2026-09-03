import ghidra.app.script.GhidraScript;
import ghidra.framework.Application;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.security.MessageDigest;
import java.util.*;

// Emit a machine-readable health summary for the rebuilt full-ROM database.
public class DatabaseHealth extends GhidraScript {
    static class PageHealth {
        String name;
        long bytes;
        long undefinedBytes;
        PageHealth(String name, long bytes, long undefinedBytes) {
            this.name = name;
            this.bytes = bytes;
            this.undefinedBytes = undefinedBytes;
        }
    }

    String quote(String value) {
        return "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\"";
    }

    boolean isFlashBlock(MemoryBlock block) {
        String name = block.getName();
        if (name.matches("page_[0-9A-Fa-f]{2}")) return true;
        return !block.isOverlay()
            && block.getStart().getAddressSpace().equals(
                currentProgram.getAddressFactory().getDefaultAddressSpace())
            && block.getStart().getOffset() == 0
            && block.getSize() == 0x4000;
    }

    int pageNumber(MemoryBlock block) {
        if (block.getName().matches("page_[0-9A-Fa-f]{2}"))
            return Integer.parseInt(block.getName().substring(5), 16);
        return 0;
    }

    PageHealth inspectPage(MemoryBlock block, Listing listing) throws Exception {
        long undefined = 0;
        Address address = block.getStart();
        Address end = block.getEnd();
        while (address.compareTo(end) <= 0) {
            if (listing.getUndefinedDataAt(address) != null) undefined++;
            address = address.next();
            if (address == null) break;
        }
        return new PageHealth(
            String.format("%02X", pageNumber(block)), block.getSize(), undefined
        );
    }

    String flashSha256(List<MemoryBlock> blocks) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        Collections.sort(blocks, Comparator.comparingInt(this::pageNumber));
        for (MemoryBlock block : blocks) {
            byte[] bytes = new byte[(int) block.getSize()];
            int read = currentProgram.getMemory().getBytes(block.getStart(), bytes);
            if (read != bytes.length)
                throw new IOException("short read from " + block.getName());
            digest.update(bytes);
        }
        StringBuilder result = new StringBuilder();
        for (byte value : digest.digest()) result.append(String.format("%02x", value & 0xFF));
        return result.toString();
    }

    boolean isInlineBjump(Instruction instruction) {
        try {
            Address address = instruction.getAddress();
            return (getByte(address) & 0xFF) == 0xCD
                && (getByte(address.add(1)) & 0xFF) == 0x09
                && (getByte(address.add(2)) & 0xFF) == 0x2B;
        } catch (Exception error) {
            return false;
        }
    }

    boolean inlineBjumpResolved(Instruction instruction, Listing listing) {
        try {
            Address address = instruction.getAddress();
            int targetAddress = (getByte(address.add(3)) & 0xFF)
                | ((getByte(address.add(4)) & 0xFF) << 8);
            int page = getByte(address.add(5)) & 0x3F;
            Data word = listing.getDefinedDataAt(address.add(3));
            Data pageByte = listing.getDefinedDataAt(address.add(5));
            if (instruction.getFallThrough() != null || word == null || pageByte == null)
                return false;
            AddressSpace space = page == 0
                ? currentProgram.getAddressFactory().getDefaultAddressSpace()
                : currentProgram.getAddressFactory().getAddressSpace(
                    String.format("page_%02X", page)
                );
            if (space == null) return false;
            Address target = space.getAddress(targetAddress);
            return listing.getInstructionAt(target) != null;
        } catch (Exception error) {
            return false;
        }
    }

    public void run() throws Exception {
        String output = getScriptArgs().length > 0 ? getScriptArgs()[0] : null;
        Listing listing = currentProgram.getListing();
        FunctionManager functions = currentProgram.getFunctionManager();
        Memory memory = currentProgram.getMemory();

        List<PageHealth> pages = new ArrayList<>();
        List<MemoryBlock> flashBlocks = new ArrayList<>();
        for (MemoryBlock block : memory.getBlocks()) {
            if (block.isInitialized() && isFlashBlock(block)) {
                flashBlocks.add(block);
                pages.add(inspectPage(block, listing));
            }
        }
        Collections.sort(pages, Comparator.comparing(page -> page.name));

        long instructionCount = 0;
        long instructionBytes = 0;
        long functionInstructions = 0;
        long overlapCount = 0;
        long bjumpSites = 0;
        long unresolvedBjumps = 0;
        List<String> unresolvedBjumpLocations = new ArrayList<>();
        AddressSet occupied = new AddressSet();
        for (Instruction instruction : listing.getInstructions(true)) {
            instructionCount++;
            instructionBytes += instruction.getLength();
            if (functions.getFunctionContaining(instruction.getAddress()) != null)
                functionInstructions++;
            if (occupied.intersects(instruction.getMinAddress(), instruction.getMaxAddress()))
                overlapCount++;
            occupied.addRange(instruction.getMinAddress(), instruction.getMaxAddress());
            if (isInlineBjump(instruction)) {
                bjumpSites++;
                if (!inlineBjumpResolved(instruction, listing)) {
                    unresolvedBjumps++;
                    unresolvedBjumpLocations.add(instruction.getAddress().toString());
                }
            }
        }

        long untypedSymbols = 0;
        List<String> untypedSymbolLocations = new ArrayList<>();
        SymbolIterator symbols = currentProgram.getSymbolTable().getAllSymbols(true);
        while (symbols.hasNext()) {
            Symbol symbol = symbols.next();
            Address address = symbol.getAddress();
            if (!symbol.isPrimary() || symbol.getSource() == SourceType.DEFAULT)
                continue;
            if (!memory.contains(address) || symbol.getSymbolType() == SymbolType.FUNCTION)
                continue;
            if (listing.getInstructionContaining(address) != null)
                continue;
            if (listing.getDefinedDataContaining(address) == null) {
                untypedSymbols++;
                untypedSymbolLocations.add(
                    address.toString() + " " + symbol.getName(true)
                );
            }
        }

        long undefinedBytes = 0;
        for (PageHealth page : pages) undefinedBytes += page.undefinedBytes;
        double functionCoverage = instructionCount == 0 ? 0.0
            : (100.0 * functionInstructions / instructionCount);

        StringWriter buffer = new StringWriter();
        PrintWriter json = new PrintWriter(buffer);
        json.println("{");
        json.println("  \"schema\": \"ti84p-re.database-health.v1\",");
        json.println("  \"program\": " + quote(currentProgram.getName()) + ",");
        json.println("  \"ghidra_version\": " + quote(Application.getApplicationVersion()) + ",");
        json.println("  \"rom_sha256\": " + quote(flashSha256(flashBlocks)) + ",");
        json.println("  \"loaded_flash_pages\": " + pages.size() + ",");
        json.println("  \"undefined_flash_bytes\": " + undefinedBytes + ",");
        json.println("  \"instruction_count\": " + instructionCount + ",");
        json.println("  \"instruction_bytes\": " + instructionBytes + ",");
        json.println("  \"overlapping_instructions\": " + overlapCount + ",");
        json.println("  \"function_count\": " + functions.getFunctionCount() + ",");
        json.println("  \"instructions_in_functions\": " + functionInstructions + ",");
        json.println(String.format(Locale.ROOT,
            "  \"function_instruction_coverage_percent\": %.6f,", functionCoverage));
        json.println("  \"inline_cross_page_jumps\": " + bjumpSites + ",");
        json.println("  \"unresolved_cross_page_jumps\": " + unresolvedBjumps + ",");
        json.println("  \"symbols_without_typed_storage\": " + untypedSymbols + ",");
        json.println("  \"unresolved_cross_page_jump_locations\": [");
        for (int index = 0; index < unresolvedBjumpLocations.size(); index++) {
            json.print("    " + quote(unresolvedBjumpLocations.get(index)));
            json.println(index + 1 == unresolvedBjumpLocations.size() ? "" : ",");
        }
        json.println("  ],");
        json.println("  \"symbols_without_typed_storage_locations\": [");
        for (int index = 0; index < untypedSymbolLocations.size(); index++) {
            json.print("    " + quote(untypedSymbolLocations.get(index)));
            json.println(index + 1 == untypedSymbolLocations.size() ? "" : ",");
        }
        json.println("  ],");
        json.println("  \"pages\": [");
        for (int index = 0; index < pages.size(); index++) {
            PageHealth page = pages.get(index);
            json.print("    {\"page\": " + quote(page.name)
                + ", \"bytes\": " + page.bytes
                + ", \"undefined_bytes\": " + page.undefinedBytes + "}");
            json.println(index + 1 == pages.size() ? "" : ",");
        }
        json.println("  ]");
        json.println("}");
        json.flush();

        String rendered = buffer.toString();
        println(rendered);
        if (output != null) {
            try (PrintWriter file = new PrintWriter(output, "UTF-8")) {
                file.print(rendered);
            }
        }
    }
}

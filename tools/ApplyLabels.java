import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
import java.nio.file.*;

// Apply non-function ROM and RAM labels from tools/labels.txt.
// Line format: <space>:<addrhex> <tab> <name> [<tab> primary|alias]
public class ApplyLabels extends GhidraScript {
    private Address parseLocation(AddressFactory factory, String text) {
        String[] fields = text.split(":", 2);
        if (fields.length != 2) return null;
        AddressSpace space = factory.getAddressSpace(fields[0]);
        if (space == null) return null;
        return space.getAddress(Long.parseLong(fields[1], 16));
    }

    private Symbol existingSymbol(SymbolTable symbols, Address address, String name) {
        SymbolIterator matches = symbols.getSymbols(name);
        while (matches.hasNext()) {
            Symbol symbol = matches.next();
            if (symbol.getAddress().equals(address)) return symbol;
        }
        return null;
    }

    public void run() throws Exception {
        String dir = getScriptArgs().length > 0 ? getScriptArgs()[0] : ".";
        AddressFactory factory = currentProgram.getAddressFactory();
        SymbolTable symbols = currentProgram.getSymbolTable();
        int applied = 0;
        for (String raw : Files.readAllLines(Paths.get(dir + "/labels.txt"))) {
            String line = raw.trim();
            if (line.isEmpty() || line.startsWith("#")) continue;
            String[] fields = line.split("\\s+");
            if (fields.length < 2 || fields.length > 3) {
                throw new IllegalArgumentException("invalid labels.txt row: " + raw);
            }
            Address address = parseLocation(factory, fields[0]);
            if (address == null) {
                throw new IllegalArgumentException("unknown label address: " + fields[0]);
            }
            String name = fields[1];
            if (fields.length == 3 &&
                    !fields[2].equals("primary") && !fields[2].equals("alias")) {
                throw new IllegalArgumentException("invalid label mode: " + fields[2]);
            }
            boolean primary = fields.length < 3 || fields[2].equals("primary");
            Symbol existing = existingSymbol(symbols, address, name);
            if (existing != null) {
                if (primary && !existing.isPrimary()) existing.setPrimary();
                continue;
            }
            createLabel(address, name, primary);
            applied++;
        }
        println("Applied non-function labels: " + applied);
    }
}

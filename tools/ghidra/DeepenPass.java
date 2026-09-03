import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.data.*;
import java.nio.file.*;
import java.util.*;

// Follow flow from all known entry points, then name every rst 28h bcall site
// (including ones revealed by the new cross-page disassembly).
public class DeepenPass extends GhidraScript {
    public void run() throws Exception {
        String dir = getScriptArgs().length > 0 ? getScriptArgs()[0] : ".";
        Map<Integer,String> bc = new HashMap<>();
        for (String line : Files.readAllLines(Paths.get(dir + "/bcalls.txt"))) {
            String[] p = line.trim().split("\\s+", 2);
            if (p.length == 2) bc.put(Integer.parseInt(p[0], 16), p[1]);
        }
        int before = currentProgram.getFunctionManager().getFunctionCount();
        analyzeAll(currentProgram);
        int after = currentProgram.getFunctionManager().getFunctionCount();
        println("functions " + before + " -> " + after);

        Listing lst = currentProgram.getListing();
        DataType word = new WordDataType();
        Set<Address> done = new HashSet<>();
        int total = 0, knownName = 0;
        for (int pass = 0; pass < 6; pass++) {
            List<Address> sites = new ArrayList<>();
            for (Instruction in : lst.getInstructions(true)) {
                if (done.contains(in.getAddress())) continue;
                int op; try { op = getByte(in.getAddress()) & 0xFF; } catch (Exception e) { continue; }
                if (op == 0xEF) sites.add(in.getAddress());
            }
            if (sites.isEmpty()) break;
            for (Address a : sites) {
                done.add(a);
                try {
                    int id = (getByte(a.add(1)) & 0xFF) | ((getByte(a.add(2)) & 0xFF) << 8);
                    String name = bc.get(id);
                    Instruction in = lst.getInstructionAt(a);
                    if (in != null) in.setFallThrough(a.add(3));
                    clearListing(a.add(1), a.add(2));
                    createData(a.add(1), word);
                    setEOLComment(a, "bcall(" + (name != null ? name : String.format("0x%04X", id)) + ")");
                    disassemble(a.add(3));
                    total++; if (name != null) knownName++;
                } catch (Exception e) {}
            }
        }
        println("bcall sites named: " + total + " (" + knownName + " resolved to a name)");
        analyzeChanges(currentProgram);
        println("DeepenPass complete. functions=" + currentProgram.getFunctionManager().getFunctionCount());
    }
}

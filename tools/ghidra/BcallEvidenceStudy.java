import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressFactory;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceManager;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Dump the listing, references, and decompiler output for selected bcall bodies.
 *
 * Run against the generated project without modifying it:
 *
 * ghidra-analyzeHeadless PROJECT_DIR ti84 -process -noanalysis -readOnly \
 *   -scriptPath tools/ghidra -postScript BcallEvidenceStudy.java \
 *   tools/symbols/bcall_targets.txt /tmp/bcall-evidence.txt 4030 4051
 */
public class BcallEvidenceStudy extends GhidraScript {
    private record Target(String name, int id, int address, int page) {}

    private AddressFactory addresses;
    private DecompInterface decompiler;

    private Address address(Target target) {
        String spaceName = target.page == 0 ? "ram" : String.format("page_%02X", target.page);
        AddressSpace space = addresses.getAddressSpace(spaceName);
        return space == null ? null : space.getAddress(target.address);
    }

    private static Map<Integer, Target> readTargets(Path path) throws Exception {
        Map<Integer, Target> targets = new HashMap<>();
        for (String line : Files.readAllLines(path, StandardCharsets.UTF_8)) {
            if (line.isBlank() || line.startsWith("#")) {
                continue;
            }
            String[] fields = line.split("\\t");
            if (fields.length < 4) {
                continue;
            }
            int id = Integer.parseInt(fields[1], 16);
            targets.put(id, new Target(
                    fields[0], id, Integer.parseInt(fields[2], 16),
                    Integer.parseInt(fields[3], 16) & 0x3f));
        }
        return targets;
    }

    private void appendTarget(StringBuilder out, Target target) throws Exception {
        Address entry = address(target);
        out.append(String.format("\n===== %04X %s -> %02X:%04X =====\n",
                target.id, target.name, target.page, target.address));
        if (entry == null) {
            out.append("missing address space\n");
            return;
        }

        Function function = getFunctionAt(entry);
        if (function == null) {
            function = getFunctionContaining(entry);
        }
        if (function == null) {
            out.append("no containing function; linear entry listing:\n");
            if (getInstructionAt(entry) == null) {
                disassemble(entry);
            }
            Instruction instruction = getInstructionAt(entry);
            for (int count = 0; instruction != null && count < 160; count++) {
                out.append(String.format("  %-14s %s\n", instruction.getAddress(), instruction));
                if (instruction.getFlowType().isTerminal()
                        || (instruction.getFlowType().isJump()
                        && !instruction.getFlowType().isConditional())) {
                    break;
                }
                Address next = instruction.getFallThrough();
                if (next == null) {
                    break;
                }
                if (getInstructionAt(next) == null) {
                    disassemble(next);
                }
                instruction = getInstructionAt(next);
            }
            return;
        }
        out.append("function: ").append(function.getName())
                .append(" entry=").append(function.getEntryPoint())
                .append(" body=").append(function.getBody()).append('\n');

        ReferenceManager references = currentProgram.getReferenceManager();
        out.append("references to bcall target:\n");
        int referenceCount = 0;
        for (Reference current : references.getReferencesTo(entry)) {
            out.append("  ").append(current.getFromAddress())
                    .append(" ").append(current.getReferenceType()).append('\n');
            referenceCount++;
        }
        if (referenceCount == 0) {
            out.append("  none\n");
        }

        out.append("listing:\n");
        Instruction instruction = getInstructionAt(function.getEntryPoint());
        int count = 0;
        while (instruction != null && function.getBody().contains(instruction.getAddress())) {
            out.append(String.format("  %-14s %s\n", instruction.getAddress(), instruction));
            instruction = instruction.getNext();
            if (++count >= 600) {
                out.append("  ... listing truncated at 600 instructions\n");
                break;
            }
        }

        DecompileResults result = decompiler.decompileFunction(function, 60, monitor);
        out.append("decompiler:\n");
        if (result == null || !result.decompileCompleted()) {
            out.append("  failed\n");
        } else {
            out.append(result.getDecompiledFunction().getC()).append('\n');
        }
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 3) {
            printerr("usage: BcallEvidenceStudy.java TARGETS OUTPUT ID [ID ...]");
            return;
        }
        Map<Integer, Target> targets = readTargets(Path.of(args[0]));
        List<Target> selected = new ArrayList<>();
        for (int index = 2; index < args.length; index++) {
            int id = Integer.parseInt(args[index], 16);
            Target target = targets.get(id);
            if (target == null) {
                throw new IllegalArgumentException(String.format("unknown bcall ID %04X", id));
            }
            selected.add(target);
        }

        addresses = currentProgram.getAddressFactory();
        decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        StringBuilder output = new StringBuilder();
        for (Target target : selected) {
            appendTarget(output, target);
        }
        Files.writeString(Path.of(args[1]), output.toString(), StandardCharsets.UTF_8);
        println("BcallEvidenceStudy wrote " + args[1]);
    }
}

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.*;
import java.nio.file.*;

// Apply reviewed base-plus-offset references from tools/poffsets.txt.
// Line format: <from-space>:<addr> <tab> <operand> <tab>
//              <base-space>:<addr> <tab> <offset-hex>
public class ApplyOffsetRefs extends GhidraScript {
    private Address parseLocation(AddressFactory factory, String text) {
        String[] fields = text.split(":", 2);
        if (fields.length != 2) return null;
        AddressSpace space = factory.getAddressSpace(fields[0]);
        if (space == null) return null;
        return space.getAddress(Long.parseLong(fields[1], 16));
    }

    public void run() throws Exception {
        String dir = getScriptArgs().length > 0 ? getScriptArgs()[0] : ".";
        AddressFactory factory = currentProgram.getAddressFactory();
        ReferenceManager references = currentProgram.getReferenceManager();
        int applied = 0;
        for (String raw : Files.readAllLines(Paths.get(dir + "/poffsets.txt"))) {
            String line = raw.trim();
            if (line.isEmpty() || line.startsWith("#")) continue;
            String[] fields = line.split("\\s+");
            if (fields.length != 4) {
                throw new IllegalArgumentException("invalid poffsets.txt row: " + raw);
            }
            Address from = parseLocation(factory, fields[0]);
            Address base = parseLocation(factory, fields[2]);
            if (from == null || base == null) {
                throw new IllegalArgumentException("unknown poffset address: " + raw);
            }
            int operand = Integer.parseInt(fields[1]);
            long offset = Long.parseLong(fields[3], 16);
            Instruction instruction = getInstructionAt(from);
            if (instruction == null || operand >= instruction.getNumOperands()) {
                throw new IllegalArgumentException(
                    "invalid poffset source operand: " + fields[0] + " op " + operand
                );
            }

            Address expected = base.add(offset);
            Reference matched = null;
            int memoryReferences = 0;
            for (Reference old : references.getReferencesFrom(from)) {
                if (old.getOperandIndex() != operand || !old.isMemoryReference()) continue;
                memoryReferences++;
                if (old.getToAddress().equals(expected)) matched = old;
            }
            RefType type;
            if (memoryReferences == 1 && matched != null) {
                type = matched.getReferenceType();
                references.delete(matched);
            } else if (memoryReferences == 0) {
                Object[] objects = instruction.getOpObjects(operand);
                Scalar scalar = null;
                for (Object object : objects) {
                    if (object instanceof Scalar) {
                        if (scalar != null)
                            throw new IllegalArgumentException(
                                "ambiguous poffset scalar operand: " + fields[0] +
                                " op " + operand
                            );
                        scalar = (Scalar) object;
                    }
                }
                if (scalar == null || scalar.getUnsignedValue() != expected.getOffset()) {
                    throw new IllegalArgumentException(
                        "poffset scalar mismatch: " + fields[0] + " op " + operand +
                        " expected " + expected
                    );
                }
                type = RefType.DATA;
            } else {
                throw new IllegalArgumentException(
                    "poffset target mismatch: " + fields[0] + " op " + operand +
                    " expected " + expected + " across " + memoryReferences + " memory refs"
                );
            }
            Reference reference = references.addOffsetMemReference(
                from, base, true, offset, type, SourceType.USER_DEFINED, operand
            );
            references.setPrimary(reference, true);
            applied++;
        }
        println("Applied offset references: " + applied);
    }
}

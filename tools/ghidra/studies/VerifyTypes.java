import ghidra.app.script.GhidraScript;
import ghidra.program.model.data.*;
import ghidra.program.model.listing.*;
public class VerifyTypes extends GhidraScript {
  public void run() throws Exception {
    DataTypeManager d = currentProgram.getDataTypeManager();
    for (String n : new String[]{"TIVarType","TIError","TIKeyCode","TIToken","TIFloat","TIComplex","VATEntry","SystemFlags"}) {
      DataType t = d.getDataType("/"+n);
      println(String.format("  %-12s %s  (%d bytes)", n, t!=null?t.getClass().getSimpleName():"MISSING", t!=null?t.getLength():-1));
    }
    println("=== SystemFlags fields (first 12) ===");
    Structure sf = (Structure)d.getDataType("/SystemFlags");
    int i=0; for (DataTypeComponent c : sf.getDefinedComponents()){ if(i++>=12)break;
      println(String.format("  +0x%02X %s  // %s", c.getOffset(), c.getFieldName(), c.getComment())); }
    println("=== typed regions ===");
    Listing l = currentProgram.getListing();
    for (long a : new long[]{0x8478,0x8450,0x85d0,0x89f0,0x9340}) {
      Data dt = l.getDataAt(toAddr(a));
      println(String.format("  %04X -> %s : %s", a, dt!=null?dt.getDataType().getName():"(none)", dt!=null?dt.getDataType().getDisplayName():""));
    }
    println("=== TIVarType members sample ===");
    ghidra.program.model.data.Enum e=(ghidra.program.model.data.Enum)d.getDataType("/TIVarType");
    for (long v : new long[]{0,1,4,5,0x0C,0x15,0x17}) println("  "+v+" = "+e.getName(v));
  }
}

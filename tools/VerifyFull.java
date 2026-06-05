import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
public class VerifyFull extends GhidraScript {
  public void run() throws Exception {
    Listing l = currentProgram.getListing();
    int fn = currentProgram.getFunctionManager().getFunctionCount();
    long ins=0; for (Instruction i : l.getInstructions(true)) ins++;
    println("functions="+fn+"  instructions="+ins);
    int blocks=0; for (MemoryBlock b: currentProgram.getMemory().getBlocks()) blocks++;
    println("memory blocks="+blocks);
    println("=== sample bcall comments (page 0) ===");
    int n=0;
    for (Instruction i : l.getInstructions(true)) {
      String c = i.getComment(CodeUnit.EOL_COMMENT);
      if (c!=null && c.startsWith("bcall(") && n<14){ println("  "+i.getAddress()+": "+i+"   "+c); n++; }
    }
    println("=== string count + samples across pages ===");
    int sc=0; DataIterator di=l.getDefinedData(true);
    while(di.hasNext()){ Data d=di.next(); if(d.hasStringValue()){ sc++; if(sc<=8) println("  "+d.getAddress()+": "+d.getValue()); } }
    println("total strings="+sc);
  }
}

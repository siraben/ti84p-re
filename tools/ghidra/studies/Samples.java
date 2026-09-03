import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
public class Samples extends GhidraScript {
  public void run() throws Exception {
    Listing l = currentProgram.getListing();
    println("=== overlay strings (page_*) ===");
    int n=0; DataIterator di=l.getDefinedData(true);
    while(di.hasNext() && n<22){ Data d=di.next();
      if(d.hasStringValue() && d.getAddress().toString().startsWith("page_")){
        String v=d.getValue().toString().trim();
        if(v.length()>=3){ println("  "+d.getAddress()+": "+v); n++; } } }
    println("=== TI floats off page 0 ===");
    int f=0; di=l.getDefinedData(true);
    while(di.hasNext() && f<10){ Data d=di.next();
      if("TIFloat".equals(d.getDataType().getName()) && !d.getAddress().toString().startsWith("ram:")){
        println("  "+d.getAddress()+": "+d.getComment(CodeUnit.EOL_COMMENT)); f++; } }
  }
}

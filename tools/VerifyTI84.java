import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
public class VerifyTI84 extends GhidraScript {
  public void run() throws Exception {
    println("=== TI floats ===");
    SymbolTable st = currentProgram.getSymbolTable();
    for (Symbol s : st.getAllSymbols(false)) {
      if (s.getName().startsWith("flt_")) {
        CodeUnit cu = currentProgram.getListing().getCodeUnitAt(s.getAddress());
        String c = cu!=null?cu.getComment(CodeUnit.EOL_COMMENT):null;
        println("  "+s.getAddress()+" "+s.getName()+"  "+c);
      }
    }
    println("=== sample RAM labels resolve ===");
    for (long a : new long[]{0x8447,0x844b,0x844c,0x89f0,0x85bc,0x8478,0x9824}) {
      Symbol[] ss = st.getSymbols(toAddr(a));
      println(String.format("  %04X -> %s", a, ss.length>0?ss[0].getName():"(none)"));
    }
  }
}

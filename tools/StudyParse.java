import ghidra.app.script.GhidraScript; import ghidra.app.decompiler.*;
import ghidra.program.model.address.*; import ghidra.program.model.listing.*;
public class StudyParse extends GhidraScript { public void run() throws Exception {
  DecompInterface di=new DecompInterface(); di.openProgram(currentProgram);
  AddressSpace sp=currentProgram.getAddressFactory().getAddressSpace("page_38");
  Address a=sp.getAddress(0x5b7b); Function f=getFunctionAt(a);
  println("##### parse core FUN_page_38_5b7b #####");
  if(f!=null){ DecompileResults r=di.decompileFunction(f,40,monitor);
    if(r!=null&&r.decompileCompleted()){String s=r.getDecompiledFunction().getC(); println(s.length()>2200?s.substring(0,2200):s);} }
}}

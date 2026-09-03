import ghidra.app.script.GhidraScript; import ghidra.program.model.address.*;
import ghidra.program.model.data.*; import ghidra.program.model.listing.*;
import java.nio.file.*;
// Mark the page-0 bjump trampoline table entries: data bytes + target comment.
public class RamRoutines extends GhidraScript { public void run() throws Exception {
  String dir=getScriptArgs()[0]; int n=0;
  DataType word=new WordDataType(), b=new ByteDataType();
  for(String line:Files.readAllLines(Paths.get(dir+"/bjumps.txt"))){
    String[] p=line.trim().split("\\s+"); if(p.length<3)continue;
    long off=Long.parseLong(p[0],16); int addr=Integer.parseInt(p[1],16),page=Integer.parseInt(p[2],16);
    try{ Address a=toAddr(off);
      if(getInstructionAt(a)==null) disassemble(a);
      Instruction in=getInstructionAt(a); if(in!=null) in.setFallThrough(a.add(6));
      clearListing(a.add(3),a.add(5));
      createData(a.add(3),word); createData(a.add(5),b);
      setEOLComment(a,String.format("bjump -> page_%02X:%04X",page,addr));
      n++;
    }catch(Exception e){}
  }
  println("bjump trampolines fixed: "+n);
}}

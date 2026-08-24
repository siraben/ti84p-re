.nolist
#include "app.inc"
.list

; The release source uses this bcall name, which the old bundled include omits.
#define _fillBasePageTable 5011h

; Build with both the SPASM-ng include directory and the directory containing
; the pinned community source on the include path. The included source starts
; its App payload at 4080h and leaves programEnd at the media-header boundary.
defpage(0, "TruVid")
#include "truVid.z80"

; One same-page, silent frame. This exercises the original App wrapper, RAM
; core, normal CLEAR cleanup, and settings path without contributed host tools
; or external audio/video data.
.db 0
.dw videoData
.db 0
.dw 1
videoData:
.fill 1536,0

.echo "program=",program
.echo "programEnd=",programEnd
.echo "videoData=",videoData
.echo "quit=",quit
.echo "isInRam=",isInRam
.echo "appVarDoesntExist=",appVarDoesntExist
.echo "wrapsToNextPage=",wrapsToNextPage
.echo "checkBHL=",checkBHL
validate()

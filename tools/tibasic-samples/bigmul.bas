{3,2,1}->L1
{5,4}->L2
{0,0,0,0,0}->L3
For(I,1,3)
For(J,1,2)
L3(I+J-1)+L1(I)*L2(J)->S
int(S/10)->C
S-10*C->L3(I+J-1)
L3(I+J)+C->L3(I+J)
End
End
Disp L3
Disp L3(4)

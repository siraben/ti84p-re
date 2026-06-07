{1,1,2}->L1
{2,3,4}->L2
{0,0,0,0}->L3
{1,0,0,0}->L4
1->P
While P
L4(P)->V
P-1->P
If L3(V)=0
Then
1->L3(V)
Disp V
For(E,1,3)
If L1(E)=V
Then
P+1->P
L2(E)->L4(P)
End
End
End
End
Disp L3

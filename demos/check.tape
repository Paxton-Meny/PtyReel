# PtyReel validating one of its own tapes. Run from the repository root.
Output demos/out/check.svg
Require python3
Set Title "ptyreel --check"
Set Width 900
Set Height 360
Set TypingSpeed 40ms

Hide
Type "export PYTHONPATH=src"
Enter
Sleep 300ms
Show

Type "python3 -m ptyreel --check demos/hello.tape && echo 'the tape is valid'"
Enter
Sleep 1800ms

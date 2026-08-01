# The README hero. Nothing here needs anything beyond a shell, and nothing it
# prints depends on the machine, so the rendered file is stable enough for
# continuous integration to check that it is still up to date.
Output demos/out/hello.svg
Set Title "ptyreel"
Set Width 900
Set Height 420
Set TypingSpeed 45ms
Set LoopDelay 2500ms

Type "echo 'recorded in a real pty, rendered as one svg'"
Enter
Sleep 1200ms

Type "printf '\\e[32m+\\e[0m %s\\n' 'no browser' 'no gif encoder' 'nothing to install'"
Enter
Sleep 1800ms

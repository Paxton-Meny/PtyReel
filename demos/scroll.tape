# Output taller than the window, so the content scrolls as the session runs.
# Nothing it prints depends on the machine, so continuous integration checks
# that the rendered file is still up to date, which keeps the scrolling path of
# the renderer exercised end to end.
Output demos/out/scroll.svg
Set Title "scrolling"
Set Width 900
Set Height 400
Set TypingSpeed 40ms
Set LoopDelay 2500ms

Type "for i in {1..15}; do printf 'line %2d of 30\\n' $i; done"
Enter
Sleep 1200ms

Type "for i in {16..30}; do printf '\\e[32mline %2d of 30\\e[0m\\n' $i; done"
Enter
Sleep 1800ms

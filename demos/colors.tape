# Colour and text attributes, straight from the terminal's own escapes.
Output demos/out/colors.svg
Set Title "colors"
Set Width 900
Set Height 420
Set TypingSpeed 35ms

Type "printf '\\e[31mred \\e[32mgreen \\e[33myellow \\e[34mblue\\e[0m\\n'"
Enter
Sleep 900ms

Type "printf '\\e[1mbold\\e[0m \\e[4munderline\\e[0m \\e[90mfaint\\e[0m\\n'"
Enter
Sleep 900ms

Type "ls --color=always /usr | head -n 3"
Enter
Sleep 1500ms

import re, pathlib, sys

t = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
root = re.search(r'<div class="(hiw-demo[^"]*)"', t)
print("root:", root.group(1) if root else "none")
chars = re.findall(r'<span style="visibility: (\w+)">', t)
print("char spans visible/hidden:", chars.count("visible"), "/", chars.count("hidden"))
caret = "hiw-caret" in t
print("caret present:", caret)

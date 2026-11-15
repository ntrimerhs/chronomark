import pathlib, sys

t = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
i = t.find('id="how-heading"')
end = t.find("</h1>", i)
print(t[i:end + 5])

"""Type the About paragraph in when the section appears."""

from pathlib import Path

jsx = Path(r"C:\Users\xrisa\Desktop\chronomark\frontend\src\components\AboutThread.jsx")
t = jsx.read_text(encoding="utf-8")

# the copy lives in a constant so the typing can walk it
para_const = '''const PARAGRAPH =
  'ChronoMark reads a recorded lecture the way you would, only it doesn\\u2019t forget. ' +
  'Ask about a definition, a proof, or the example you half remember, and it answers with the ' +
  'second it came from. Then you jump back to that moment instead of scrubbing through two hours ' +
  'of video.'

'''
if "const PARAGRAPH" not in t:
    t = t.replace("const THREAD", para_const + "const THREAD") if "const THREAD" in t else t
    if "const PARAGRAPH" not in t:
        t = t.replace("export default function AboutGlass()", para_const + "export default function AboutGlass()")

# typing state, started by the reveal
if "typedCount" not in t:
    t = t.replace(
        "  const [useGL, setUseGL] = useState(false)" if "useGL" in t else "  const [inView, setInView] = useState(false)",
        "  const [inView, setInView] = useState(false)\n  const [typedCount, setTypedCount] = useState(0)",
    )

jsx.write_text(t, encoding="utf-8")
print("paragraph const:", "const PARAGRAPH" in t)
print("typed state:", "typedCount" in t)

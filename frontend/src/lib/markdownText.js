/* Currency, not LaTeX.

   Answers are rendered with remark-math, which treats any `$...$` pair as inline
   maths. A financial answer says "$75 average spend gives $3,375 per sitting",
   and those two currency signs read as one maths span -- the amounts collapse
   into italic nonsense ("75averagespendgives3,375"). The document set here is
   hotels, valuations and lectures, so currency is far more common than LaTeX.

   A span only counts as maths when it looks like an expression: it must not
   begin with a digit followed by a space, which is how money reads. Everything
   else is left exactly as the model wrote it, and an escaped `\$` renders as a
   literal dollar sign. */

const SPAN_RE = /\$([^$\n]+)\$/g;
const MONEY_START_RE = /^\d[\d.,]*(\s|$)/;

export function protectCurrency(text) {
  const source = typeof text === 'string' ? text : String(text ?? '');
  return source.replace(SPAN_RE, (whole, span) =>
    MONEY_START_RE.test(span) ? `\\$${span}\\$` : whole,
  );
}

export default protectCurrency;

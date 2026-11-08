import json
import re
import os
from dotenv import load_dotenv
from huggingface_hub import InferenceClient
from openai import OpenAI

load_dotenv()

_HF_MODEL = "meta-llama/Llama-3.1-8B-Instruct"

_OPENAI_MODEL = "gpt-4o-mini"

# Llama 3.1's officially supported languages are English, German, French,
# Italian, Portuguese, Hindi, Spanish and Thai — Greek is not among them. On
# Greek questions the 8B model mis-accents words ("ορίσμα" for "όρισμα"),
# leaves dangling references and repeats itself. So OpenAI is preferred
# whenever a key is present; HF stays as a fallback so the app still answers
# when OpenAI is unreachable.
_openai_api_key = os.getenv("OPENAI_API_KEY")
_deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
_deepseek_base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
_hf_token = os.getenv("HF_TOKEN")

# DeepSeek first when its key exists: same OpenAI surface, a tenth of the price,
# and it also does vision. OpenAI is kept as a fallback so nothing breaks if a
# key is missing.
if _deepseek_api_key:
    _openai_client = OpenAI(base_url=_deepseek_base, api_key=_deepseek_api_key)
    _OPENAI_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
    _PROVIDER = "DeepSeek"
elif _openai_api_key:
    _openai_client = OpenAI(api_key=_openai_api_key)
    _PROVIDER = "OpenAI"
else:
    _openai_client = None
    _PROVIDER = "none"

# Kept at module level under the old name: this client is the HF fallback.
client = InferenceClient(provider="auto", api_key=_hf_token) if _hf_token else None

if _openai_client:
    print(f"[LLM] Using {_PROVIDER} {_OPENAI_MODEL} (fallback: {_HF_MODEL})")
elif client:
    print(f"[LLM] Using {_HF_MODEL}")
else:
    print("[LLM] No OPENAI_API_KEY or HF_TOKEN set — answering is disabled")

# gpt-4o-mini has a 128k-token window, so the transcript no longer has to be
# squeezed to fit. Llama 3.1 8B has ~8k: at ~4 chars/token, 26k chars leaves
# ~1500 tokens for the system prompt, question and output.
_MAX_CONTEXT_CHARS = {"openai": 120_000, "hf": 26_000}

# 600 truncated any answer that had to explain a multi-step example: the
# response stopped mid-explanation, which reads as the model skipping the rest
# and moving on. gpt-4o-mini accepts far more, so the ceiling was the problem.
_MAX_OUTPUT_TOKENS = 1600
_TEMPERATURE = 0.25


def _extract_json(text: str):
    """Pull the first JSON object out of a model reply.

    Some models wrap JSON in prose or code fences, so the object is extracted
    rather than parsed directly from the whole reply.
    """
    if not text:
        return {}
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {}
    try:
        return json.loads(cleaned[start:end + 1])
    except ValueError:
        return {}


def _chat_json(messages, max_tokens=600, temperature=0):
    """A chat completion that must come back as JSON.

    A model occasionally answers in prose instead of JSON. One retry with a
    stricter instruction is cheaper than failing the whole call.
    """
    if not _openai_client:
        return {}

    def once(problem):
        try:
            completion = _create(
                model=_OPENAI_MODEL,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:
            print(f"[LLM] JSON call failed: {exc}")
            return {}
        raw = completion.choices[0].message.content or ""
        parsed = _extract_json(raw)
        if not parsed and problem:
            print(f"[LLM] {_OPENAI_MODEL} ignored the JSON request; retrying once")
        return parsed

    parsed = once(True)
    if parsed:
        return parsed

    strict = list(messages) + [{
        "role": "user",
        "content": "Return ONLY the JSON object. No explanation, no code fences. "
                   "Start your reply with { and end it with }.",
    }]
    return once(False)


def _create(**kwargs):
    """Chat completion with thinking disabled.

    DeepSeek enables reasoning by default at effort "high", and reasoning tokens
    are billed as output. On a normal answer that is pure cost; on a long prompt
    it can consume the whole max_tokens budget before any text is produced. The
    OpenAI-compatible endpoint takes the toggle through extra_body.
    """
    if _deepseek_api_key and "extra_body" not in kwargs:
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    return _openai_client.chat.completions.create(**kwargs)


def transcribe_image(data_url: str) -> str:
    """Read every piece of text visible in a frame.

    Called once per keyframe at upload time. Speech never contains on-screen
    code -- a lecturer says "print of message", not `print(message)` -- so
    without this the transcript can describe an example but not reproduce it,
    and the model fills the gap with invented code.
    """
    if not _openai_client:
        return ""

    try:
        completion = _create(
            model=_OPENAI_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Read the text in this image.\n\n"
                                "Output ONLY that text, exactly as it appears, "
                                "preserving line breaks and indentation. Include "
                                "code verbatim with its punctuation.\n\n"
                                "Do not describe the image. Do not explain what "
                                "you are doing. Do not add commentary, notes, "
                                "translations or quotation marks. If there is no "
                                "text, output nothing at all."
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            # 700 truncated a slide carrying four code examples: the reader
            # returned the first block and dropped the rest, so only one of
            # them ever reached the index.
            max_tokens=2000,
            temperature=0,
        )
        return (completion.choices[0].message.content or "").strip()
    except Exception as exc:
        print(f"[OCR] frame read failed: {exc}")
        return ""


def cite_answer(answer: str, context: str, question: str):
    """Pick a short verbatim quote from the transcript for each claim.

    The model never states a time here -- it copies a phrase, and main.py
    locates that phrase in Whisper's word timings. That separates "what was
    said" from "when it was said", which is what makes the timestamp exact
    instead of guessed.
    """
    if not _openai_client or not (answer or "").strip() or not (context or "").strip():
        return []

    try:
        completion = _create(
            model=_OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You extract supporting quotes. Reply with JSON only, "
                        'shape {"quotes": ["...", "..."]}. Each quote must be '
                        "copied VERBATIM from the transcript excerpts: 4 to 12 "
                        "words, no paraphrase, no ellipsis, no added words. "
                        "Return one quote for EVERY numbered example or distinct "
                        "claim in the answer -- if the answer has four examples, "
                        "return four quotes, in the order they appear. Omit only "
                        "claims the excerpts do not support; do not merge two "
                        "examples into one quote."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Answer:\n{answer}\n\nTranscript excerpts:\n{context}"
                        f"\n\nQuestion:\n{question}"
                    ),
                },
            ],
            max_tokens=600,
            temperature=0,
        )
        payload = _extract_json(completion.choices[0].message.content or "")
        quotes = payload.get("quotes") or []
        return [str(q).strip() for q in quotes if str(q).strip()]
    except Exception as exc:
        print(f"[Cite] quote extraction failed: {exc}")
        return []


def extract_examples(on_screen_text: str, limit: int = 8):
    """Ask the model which worked examples the video shows.

    Pattern formats fail the moment a course uses different file names, a
    different language, or no files at all. The model reads the on-screen text
    and answers the actual question, in any language.
    """
    if not _openai_client or not (on_screen_text or "").strip():
        return []

    payload = _chat_json(
        [
            {
                "role": "system",
                "content": (
                    "You read text captured from the screen of a recorded "
                    "lesson and list the worked examples, code snippets, demos "
                    "or exercises it shows. Reply with JSON only: "
                    '{"examples": [{"name": "short label", "code": "the code or '
                    'content, verbatim"}]}. '
                    "One entry per distinct example. Do not invent examples, do "
                    "not merge two into one, and do not include ordinary slide "
                    "bullets. If nothing on screen is an example, return an "
                    f"empty list. At most {limit} entries."
                ),
            },
            {"role": "user", "content": on_screen_text},
        ],
        max_tokens=1400,
    )
    if not payload:
        return []

    results = []
    for item in payload.get("examples") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        code = str(item.get("code") or "").strip()
        if name or code:
            results.append({"name": name or code[:40], "code": code})
        if len(results) >= limit:
            break
    return results


def map_examples_to_excerpts(examples, context):
    """For each known example, the transcript excerpt that discusses it.

    The examples are already identified -- each is a labelled chunk read off the
    slide -- so this only asks which excerpt talks about it. That is a much
    narrower question than "find the example", and the model answers it with a
    verbatim label that main.py then snaps to a real segment start.
    """
    if not _openai_client or not examples or not (context or "").strip():
        return {}

    listing = "\n".join(f"- {name}" for name in examples)
    try:
        completion = _create(
            model=_OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You match code examples to the part of a lecture that "
                        "explains them. Reply with JSON only, shape "
                        '{"matches": [{"example": "...", "excerpt": "mm:ss-mm:ss"}]}. '
                        "Copy each excerpt label EXACTLY as it appears in the "
                        "transcript, never invent one. Use each excerpt at most "
                        "once. Omit an example when no excerpt discusses it."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Examples:\n{listing}\n\n"
                        f"Transcript excerpts:\n{context}"
                    ),
                },
            ],
            max_tokens=600,
            temperature=0,
        )
        payload = _extract_json(completion.choices[0].message.content or "")
        result = {}
        for match in payload.get("matches") or []:
            name = str(match.get("example") or "").strip()
            excerpt = str(match.get("excerpt") or "").strip()
            if name and excerpt:
                result[name] = excerpt
        return result
    except Exception as exc:
        print(f"[Cite] example mapping failed: {exc}")
        return {}


def digest_segment(text: str, label: str = ""):
    """Compress one chunk of a lecture into a structured digest.

    Answers currently send the model dozens of raw transcript segments on every
    question. A pre-computed digest per chunk carries the same outline for a
    fraction of the tokens, and it is built once at upload rather than on every
    question.
    """
    if not _openai_client or not (text or "").strip():
        return None

    payload = _chat_json(
        [
            {
                "role": "system",
                "content": (
                    "You summarise one part of a recorded lecture. Reply with "
                    "JSON only, shape: "
                    '{"topics": ["..."], "definitions": ["..."], '
                    '"examples": [{"name": "...", "start": "m:ss"}], '
                    '"key_points": ["..."]}. '
                    "Use only what the text says; never add outside knowledge. "
                    "Keep the whole reply under 120 words. Timestamps must be "
                    "copied from the segment labels, never invented."
                ),
            },
            {
                "role": "user",
                "content": f"{label}\n\nTranscript:\n{text}",
            },
        ],
        max_tokens=700,
    )
    return payload or None


def ask_llama(
    question: str,
    context: str,
    history: list[dict] | None = None,
    answer_language: str = "same as the question",
    summary_mode: bool = False,
    transcript_available: bool = True,
    images: list[str] | None = None,
):
    if not transcript_available:
        style_instruction = (
            "No transcript excerpts are available. Answer the user's question "
            "using your general knowledge and any video cues that may be "
            "available in the surrounding context. Do not ask the user to "
            "provide transcript excerpts. Keep the answer concise, helpful, "
            "and honest about any uncertainty. "
        )
    elif summary_mode:
        style_instruction = (
            "The user wants a summary of the entire video. You are given ALL "
            "the transcript segments in chronological order. Write a thorough "
            "summary that covers the main topic, every significant concept or "
            "point the video introduces, key examples, and the overall flow. "
            "After summarising the video content, add a short paragraph of "
            "relevant general knowledge that gives the user useful context "
            "about the subject matter. Keep the tone clear and educational. "
        )
    else:
        style_instruction = (
            "Structure your answer as one educational paragraph (or a few short "
            "paragraphs if the topic needs it). First convey what the video "
            "explains about the topic, then enrich it with accurate general "
            "knowledge. Where it helps understanding, include a concrete, simple "
            "example — clearly presented but not prefaced with a label like "
            "'Example:'. Prefer the video's own example when the transcript "
            "has one (see the examples rule below). Everything should read as "
            "a single natural explanation. "
        )

    messages = [
        {
            "role": "system",
            "content": (
                "You are an intelligent educational assistant. "
                "\n\nHOW TO WRITE (this matters as much as the content):\n"
                "- Write like a person explaining something, not like a report. "
                "Plain, warm, direct sentences.\n"
                "- Never use em dashes (—) or en dashes (–). Use a comma, a full "
                "stop, or the word 'και'. This is the single clearest sign of "
                "machine-written text.\n"
                "- No emoji, no icons, no decorative symbols.\n"
                "- No bullet lists unless the user explicitly asks for a list.\n"
                "- Avoid stock phrasing: 'Αξίζει να σημειωθεί', 'Είναι σημαντικό "
                "να σημειωθεί', 'Συνοψίζοντας', 'Σε αυτό το πλαίσιο', 'Ωστόσο', "
                "'Επιπλέον' at the start of sentences, and their English "
                "equivalents ('It is worth noting', 'In this context', "
                "'Furthermore', 'Moreover').\n"
                "- Do not announce what you are about to do, and do not restate "
                "the question. Start with the answer.\n"
                "- Vary sentence length. A short sentence is fine.\n"                "\nTIMESTAMPS (citations):\n"
                "- Excerpts labelled [mm:ss-mm:ss] are speech. Cite those for "
                "when something is explained.\n"
                "- Excerpts labelled [on screen] are text read off a slide and "
                "carry no time by design. Never attach a time to them, and never "
                "treat the moment a slide first appeared as the moment the topic "
                "was explained.\n"
                "- Every paragraph that tells the user something about the video "
                "ends with exactly one citation: the start time of the excerpt it "
                "came from, written as inline code in mm:ss format, e.g. "
                "`04:12`. At most one per paragraph, at the end of it.\n"
                "- Copy the time from the start of a \"[mm:ss-mm:ss]\" excerpt "
                "you were given. Never invent a time, never round it, and never "
                "cite a moment that is not in the excerpts. A citation that does "
                "not match an excerpt is deleted before the user sees the answer.\n"
                "- Do not cite a paragraph that only restates the question or "
                "adds general knowledge of your own; those carry no citation.\n"
                "\nHOW TO PRESENT EXAMPLES (important):\n"
                "- Put each example and its explanation together. Show the "
                "example, then explain that example immediately underneath, "
                "then move to the next one.\n"
                "- Never list several examples first and explain them "
                "afterwards. If there are four examples, the reader should meet "
                "them as four blocks, each followed by its own explanation.\n"
                "- The explanation belongs to the example above it, so do not "
                "start it by restating the code. Say what it does and why it "
                "matters.\n"


                "The user is watching a video and asks questions about it. "
                "Timestamped transcript excerpts from the video are provided "
                "below (format \"[mm:ss-mm:ss] text\"). "
                "\n\nYour job:\n"
                "1. Read the transcript excerpts carefully and identify every "
                "relevant fact, definition, rule, or example the video provides "
                "about the topic.\n"
                "2. Use that video content as the foundation of your answer — "
                "it must be the dominant source.\n"
                "3. Expand on it with accurate general knowledge to make the "
                "answer educational and complete.\n"
                "4. Where useful, include a simple concrete example that "
                "illustrates the concept — blend it naturally into the text.\n"
                "\nRules:\n"
                "- Never copy transcript text word-for-word; paraphrase into "
                "clean, fluent prose.\n"
                "- Skip any garbled or incomplete transcript segment.\n"
                "- Separate the video's substantive content from the speaker's "
                "colloquial asides, jokes, visual mnemonics and figures of "
                "speech. Never restate an aside as a definition or as a "
                "technical property of the subject. If an aside genuinely aids "
                "intuition, attribute it as the speaker's informal way of "
                "describing something; otherwise leave it out.\n"
                "- Never produce circular definitions (do not define a word "
                "using the same word).\n"
                "- Do not invent facts; if something is uncertain say so briefly.\n"
                "- When an example needs several things explained, explain "
                "each of them in order before moving on. Never skip a step or "
                "summarise it away to save space.\n"
                "- If the transcript covers part of what was asked, answer that "
                "part fully and say plainly which part it does not cover.\n"
                "- Do not label sections ('From the video:', 'Example:', etc.) — "
                "the answer must read as one cohesive explanation.\n"
                "- When referring to the person speaking in the video, use a "
                "neutral term such as 'the speaker' (or the equivalent in the "
                "response language, e.g. 'ο ομιλητής' in Greek). Never assume "
                "or invent a role, title, or name for them.\n"
                "- If the video is a programming/coding tutorial and the "
                "transcript describes or walks through actual code, and the "
                "user's question is about that code, include a short code "
                "snippet that faithfully represents what the video describes. "
                "Put it in a fenced Markdown code block with the correct "
                "language tag (e.g. ```python). Only add a snippet when code "
                "is genuinely relevant to the question — don't force one into "
                "unrelated or non-technical answers.\n"
                "- A snippet is part of the paragraph that introduces it, so it "
                "does not get a timestamp of its own: the citation closes the "
                "paragraph it belongs to (see TIMESTAMPS).\n"
                "- Examples rule (applies to any example you give, whether in "
                "prose, code, or a step-by-step walkthrough): first check "
                "whether the transcript excerpts already contain an example "
                "for this concept. If they do, base your example closely on "
                "that one — reuse the same scenario, values, or steps rather "
                "than substituting an unrelated example of your own, and stay "
                "close to what the video actually shows without straying far "
                "from it. That block ends with the citation of the excerpt it "
                "was drawn from, exactly like any other paragraph. "
                "If the transcript does NOT contain an example for this "
                "concept, you may construct one from general knowledge, but "
                "you must say plainly that it is not from the video (e.g. "
                "start it with 'This example isn't from the video, but...' or "
                "the equivalent in the response language) — never present an "
                "invented example as if the video showed it, and that block "
                "carries no citation.\n"
                "- When the question concerns a finite automaton, graph, tree, "
                "stack, queue, or another state-based data structure, give a "
                "small step-by-step example following the examples rule above "
                "when the transcript provides enough information. For an "
                "automaton, name the relevant states, identify the initial "
                "and accepting state when known, and show a short input "
                "moving through the states with plain text arrows such as "
                "`q0 --1--> q1`. For a data structure, show the operations "
                "and the resulting state after each step.\n"
                f"{style_instruction}"
                "Use prior conversation turns (if any) to understand follow-up "
                "questions.\n"
                f"Respond in {answer_language}."
            ),
        },
    ]

    for turn in history or []:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    def messages_for(backend: str):
        """Same conversation, with the transcript trimmed to that backend's window."""
        limit = _MAX_CONTEXT_CHARS[backend]
        trimmed = context
        if len(trimmed) > limit:
            trimmed = trimmed[:limit] + "\n[...transcript truncated...]"

        text = (
            f"Transcript excerpts:\n{trimmed}\n\nQuestion:\n{question}"
            if transcript_available
            else f"Question:\n{question}"
        )

        # Images only reach a vision-capable backend. The HF fallback is
        # text-only, so it gets the plain string rather than a request it would
        # reject.
        if images and backend == "openai":
            text += (
                "\n\nStills from the video at the cited moments are included. "
                "Use them when the question is about what is on screen -- code, "
                "a diagram, a slide -- and say so when you rely on them."
            )
            content = [{"type": "text", "text": text}]
            content.extend(
                {"type": "image_url", "image_url": {"url": url}} for url in images
            )
        else:
            content = text

        return messages + [{"role": "user", "content": content}]

    if _openai_client:
        try:
            completion = _create(
                model=_OPENAI_MODEL,
                messages=messages_for("openai"),
                max_tokens=_MAX_OUTPUT_TOKENS,
                temperature=_TEMPERATURE,
            )
            return completion.choices[0].message.content.strip()
        except Exception as e:
            if not client:
                raise
            print(f"[LLM] {_OPENAI_MODEL} failed ({type(e).__name__}: {e}); falling back to {_HF_MODEL}")

    if not client:
        raise RuntimeError("No LLM backend configured: set OPENAI_API_KEY or HF_TOKEN.")

    completion = client.chat.completions.create(
        model=_HF_MODEL,
        messages=messages_for("hf"),
        max_tokens=_MAX_OUTPUT_TOKENS,
        temperature=_TEMPERATURE,
    )

    return completion.choices[0].message.content.strip()
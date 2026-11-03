import json
import re
import fact_check
from sentences import split as sentence_split

# Magazine columns (the Heisman Watch, the recruiting story, the rivalry issue): gemma answers a prompt with JSON
# {"title", "body"}. One writer for all of them: retries a broken or thin answer, drops sentences with numbers the
# prompt's facts don't contain, and lays the body out in paragraphs.

PARAGRAPHS = 4
MIN_LENGTH = 200     # characters; shorter answers are retried
ATTEMPTS = 3

def paragraphs(text, count=PARAGRAPHS):
    """Keeps the model's paragraphs; a column that came back as one block is split into about `count` by sentence."""
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(parts) > 1:
        return "\n\n".join(parts)
    sentences = sentence_split(text.strip())
    size = max(1, -(-len(sentences) // count))
    return "\n\n".join(" ".join(sentences[i:i + size]) for i in range(0, len(sentences), size))

def split_paragraphs(body):
    return [p.strip() for p in body.split("\n\n") if p.strip()]

def write(selected_model, prompt, fallback_title):
    """(title, body) for a column prompt; RuntimeError when the model gives no usable answer."""
    import ai_engine
    allowed = fact_check.spoken_numbers(prompt)
    for _attempt in range(ATTEMPTS):
        try:
            data = json.loads(ai_engine.call_ollama(selected_model, prompt, force_json=True))
        except Exception:
            continue
        body = paragraphs(fact_check.drop_invented(ai_engine.clean_text(str(data.get('body') or "")), allowed))
        if len(body) > MIN_LENGTH:
            return ai_engine.clean_text(str(data.get('title') or "")) or fallback_title, body
    raise RuntimeError("The model didn't return a usable column. Is Ollama running?")

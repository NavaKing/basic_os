import re
from sentences import split as sentence_split

# Numbers check: small models drift into made-up scores ("forty-five to twenty") even with the facts in front of them.
# A line that states a number the facts don't contain is dropped. Small numbers (0-4) are everyday words ("one of the best").
NUMBER_WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
                                            "fifteen sixteen seventeen eighteen nineteen".split())}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
CHECKED_FROM = 5

def spoken_numbers(text):
    """Every number in the text, written as digits ('227', '1,200') or words ('forty-five', 'eighteen')."""
    found = {int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", text)}
    compound = re.compile(r"\b(" + "|".join(TENS) + r")(?:[- ](one|two|three|four|five|six|seven|eight|nine))?\b")
    for tens, ones in compound.findall(text.lower()):
        found.add(TENS[tens] + (NUMBER_WORDS[ones] if ones else 0))
    rest = compound.sub(" ", text.lower())  # so the "five" in "forty-five" isn't counted again
    for word in re.findall(r"\b(" + "|".join(NUMBER_WORDS) + r")\b", rest):
        found.add(NUMBER_WORDS[word])
    return found

def invented_numbers(text, allowed):
    return sorted(n for n in spoken_numbers(text) if n >= CHECKED_FROM and n not in allowed)

TAGS = re.compile(r"[#@]\w+")              # hashtags and handles ("#7220SPEED", "@Wyo88") aren't claims
YEARS = re.compile(r"\b(?:19|20)\d\d\b")   # nor are years ("the 2026 season")
PARAGRAPH_BREAK = re.compile(r"\n\s*\n")

def drop_invented(text, allowed):
    """The text without its sentences that state a number missing from the facts (paragraph breaks kept)."""
    keep = lambda sentence: not invented_numbers(YEARS.sub(" ", TAGS.sub(" ", sentence)), allowed)
    paragraphs = [" ".join(s for s in sentence_split(p) if keep(s)) for p in PARAGRAPH_BREAK.split(text or "")]
    return "\n\n".join(p for p in paragraphs if p.strip()).strip()

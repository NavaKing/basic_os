import re

# Splitting text into sentences. A period after a ranking or a name suffix doesn't end a sentence:
# "No. 6 Indiana", "Michigan St. won", "Cameron Ward Jr. threw", "Wyoming vs. Hawaii".
ABBREVIATIONS = ("No", "St", "Jr", "Sr", "vs")
SENTENCE_END = re.compile("".join(rf"(?<!\b{a}\.)" for a in ABBREVIATIONS) + r"(?<=[.!?])\s+")

def split(text):
    return SENTENCE_END.split((text or "").strip())

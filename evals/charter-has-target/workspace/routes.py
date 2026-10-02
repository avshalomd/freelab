KEYWORDS = {"billing": ["invoice", "refund", "charge"], "tech": ["error", "crash", "login"]}


def route(text: str) -> str:
    low = text.lower()
    for team, words in KEYWORDS.items():
        if any(w in low for w in words):
            return team
    return "general"

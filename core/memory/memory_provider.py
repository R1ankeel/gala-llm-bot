"""MemoryProvider: рендерит известное о собеседнике в текст промпта."""

from core.memory.gender_resolver import resolve_gender


class FactsMemoryProvider:
    def __init__(self, store, gender_heuristics: dict, max_facts: int = 3):
        self.store = store
        self.gender_heuristics = gender_heuristics
        self.max_facts = max_facts

    def render(self, addressee_nick: str, current_message: str) -> str | None:
        profile = self.store.get_profile(addressee_nick)
        gender, _source = resolve_gender(addressee_nick, profile, self.gender_heuristics)
        if profile is None and gender is None:
            return None

        bio: list[str] = []
        if profile is not None:
            name = profile.real_name or profile.display_name
            if name:
                bio.append(name)
            if profile.age is not None:
                bio.append(f"{profile.age} лет")
            if profile.job:
                bio.append(profile.job)
            if profile.city:
                bio.append(f"из {profile.city}")

        gender_text = {
            "male": "Пол: мужской.",
            "female": "Пол: женский.",
            None: "Пол: неизвестен.",
        }[gender]

        text = "Ты знаешь об этом собеседнике:"
        if bio:
            text += " " + ", ".join(bio) + "."
        text += " " + gender_text

        facts = self.store.get_recent_facts(addressee_nick, limit=self.max_facts)
        if facts:
            rendered_facts = "; ".join(f.fact for f in facts)
            text += f" Известные факты: {rendered_facts}."
        return text

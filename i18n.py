"""Język odpowiedzi (en/pl) na czas jednego zapytania HTTP. Teksty piszemy obok siebie: tr("polski", "English")."""
import contextvars

_LANG = contextvars.ContextVar("lang", default="en")


def set_lang(lang):
    _LANG.set("pl" if lang == "pl" else "en")


def lang():
    return _LANG.get()


def tr(pl, en):
    return pl if _LANG.get() == "pl" else en


if __name__ == "__main__":
    assert tr("tak", "yes") == "yes"
    set_lang("pl")
    assert tr("tak", "yes") == "tak"
    print("i18n.py: OK")

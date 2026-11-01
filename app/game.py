"""Logika genotypów — czysta, bez bazy; losowość wstrzykiwana (``rng``) na potrzeby testów."""
from __future__ import annotations

import random
import secrets
from typing import Callable

ALPHABET = "0123"
LENGTH = 10
# k zgodnych pozycji -> waga w procentach
MATCH_WEIGHTS = {5: 25, 6: 35, 7: 25, 8: 10, 9: 5}
WIN_ONE_IN = 150


def count_matches(a: str, b: str) -> int:
    return sum(1 for x, y in zip(a, b) if x == y)


def random_genotype(rng: random.Random) -> str:
    return "".join(rng.choice(ALPHABET) for _ in range(LENGTH))


def new_genotype(taken: Callable[[str], bool], rng: random.Random | None = None) -> str:
    """Losuje genotyp, którego ``taken`` nie zna (unikalny względem historii)."""
    rng = rng or random.SystemRandom()
    while True:
        g = random_genotype(rng)
        if not taken(g):
            return g


def pick_matches(rng: random.Random) -> int:
    ks = list(MATCH_WEIGHTS)
    return rng.choices(ks, weights=[MATCH_WEIGHTS[k] for k in ks])[0]


def make_match(target: str, k: int, rng: random.Random) -> str:
    """Ciąg zgodny z ``target`` na dokładnie ``k`` losowych pozycjach (reszta: inny symbol)."""
    same = set(rng.sample(range(len(target)), k))
    out = []
    for i, ch in enumerate(target):
        if i in same:
            out.append(ch)
        else:
            out.append(rng.choice([c for c in ALPHABET if c != ch]))
    return "".join(out)


def is_win(rng: random.Random | None = None) -> bool:
    """Szansa 1/150 na trafienie całego genotypu."""
    if rng is not None:
        return rng.randrange(WIN_ONE_IN) == 0
    return secrets.randbelow(WIN_ONE_IN) == 0


def roll(target: str, rng: random.Random | None = None) -> tuple[int, str]:
    """Zwykły (nie-wygrywający) rzut: (liczba zgodnych pozycji, genotyp gracza)."""
    rng = rng or random.SystemRandom()
    k = pick_matches(rng)
    return k, make_match(target, k, rng)

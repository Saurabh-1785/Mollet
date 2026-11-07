"""Beginner Python problems. Hidden tests never reach the browser."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Problem:
    id: str
    title: str
    concept: str
    difficulty: str
    statement: str
    entry: str  # function the tests call
    starter: str
    # (args tuple, expected) pairs, run by the Otari sandbox, never shown.
    hidden_tests: list[tuple[tuple[Any, ...], Any]] = field(default_factory=list)
    # One visible example so the statement is concrete.
    example: str = ""


PROBLEMS: list[Problem] = [
    Problem(
        id="count-vowels",
        title="Count the vowels",
        concept="loops and membership tests (`in`)",
        difficulty="Warm-up",
        statement=(
            "Write `count_vowels(text)` that returns how many vowels (a, e, i, o, u) "
            "appear in `text`. Upper-case vowels count too."
        ),
        entry="count_vowels",
        starter="def count_vowels(text):\n    # your code here\n    pass\n",
        example='count_vowels("Otari") -> 3',
        hidden_tests=[
            (("Otari",), 3),
            (("",), 0),
            (("rhythm",), 0),
            (("AEIOU aeiou",), 10),
            (("Hello, World!",), 3),
        ],
    ),
    Problem(
        id="fizzbuzz",
        title="FizzBuzz, one number",
        concept="conditionals and the modulo operator (`%`)",
        difficulty="Warm-up",
        statement=(
            "Write `fizzbuzz(n)` that returns `\"FizzBuzz\"` if `n` is divisible by 3 and 5, "
            "`\"Fizz\"` if only by 3, `\"Buzz\"` if only by 5, and otherwise the number as a string."
        ),
        entry="fizzbuzz",
        starter="def fizzbuzz(n):\n    # your code here\n    pass\n",
        example='fizzbuzz(9) -> "Fizz"',
        hidden_tests=[
            ((3,), "Fizz"),
            ((5,), "Buzz"),
            ((15,), "FizzBuzz"),
            ((7,), "7"),
            ((30,), "FizzBuzz"),
            ((1,), "1"),
        ],
    ),
    Problem(
        id="is-palindrome",
        title="Palindrome check",
        concept="string slicing and normalising text",
        difficulty="Core",
        statement=(
            "Write `is_palindrome(text)` that returns `True` if `text` reads the same "
            "forwards and backwards, ignoring case and spaces."
        ),
        entry="is_palindrome",
        starter="def is_palindrome(text):\n    # your code here\n    pass\n",
        example='is_palindrome("Never odd or even") -> True',
        hidden_tests=[
            (("racecar",), True),
            (("Never odd or even",), True),
            (("python",), False),
            (("",), True),
            (("Ab ba",), True),
            (("ab",), False),
        ],
    ),
    Problem(
        id="largest",
        title="Largest number, no max()",
        concept="tracking a running value in a loop",
        difficulty="Core",
        statement=(
            "Write `largest(numbers)` that returns the largest number in a non-empty list, "
            "without using the built-in `max()`. Lists may contain negative numbers."
        ),
        entry="largest",
        starter="def largest(numbers):\n    # your code here\n    pass\n",
        example="largest([3, 9, 2]) -> 9",
        hidden_tests=[
            (([3, 9, 2],), 9),
            (([-5, -2, -9],), -2),
            (([7],), 7),
            (([1, 1, 1],), 1),
            (([0, -1, 100, 99],), 100),
        ],
    ),
    Problem(
        id="word-count",
        title="Word frequencies",
        concept="dictionaries and `str.split()`",
        difficulty="Stretch",
        statement=(
            "Write `word_count(sentence)` that returns a dictionary mapping each lower-cased "
            "word to how many times it appears. Words are separated by spaces."
        ),
        entry="word_count",
        starter="def word_count(sentence):\n    # your code here\n    pass\n",
        example='word_count("the cat the") -> {"the": 2, "cat": 1}',
        hidden_tests=[
            (("the cat the",), {"the": 2, "cat": 1}),
            (("",), {}),
            (("Hi hi HI",), {"hi": 3}),
            (("a b c",), {"a": 1, "b": 1, "c": 1}),
        ],
    ),
    Problem(
        id="sum-digits",
        title="Sum of digits",
        concept="integer division (`//`) and remainder (`%`)",
        difficulty="Stretch",
        statement=(
            "Write `sum_digits(n)` that returns the sum of the digits of a non-negative "
            "integer `n`."
        ),
        entry="sum_digits",
        starter="def sum_digits(n):\n    # your code here\n    pass\n",
        example="sum_digits(2026) -> 10",
        hidden_tests=[
            ((2026,), 10),
            ((0,), 0),
            ((9,), 9),
            ((1111,), 4),
            ((987654321,), 45),
        ],
    ),
]

BY_ID: dict[str, Problem] = {p.id: p for p in PROBLEMS}


def get(problem_id: str) -> Problem | None:
    return BY_ID.get(problem_id)


def public_view(p: Problem) -> dict[str, str]:
    """What the browser and the MCP tool may see: no hidden tests."""
    return {
        "id": p.id,
        "title": p.title,
        "concept": p.concept,
        "difficulty": p.difficulty,
        "statement": p.statement,
        "example": p.example,
        "entry": p.entry,
    }

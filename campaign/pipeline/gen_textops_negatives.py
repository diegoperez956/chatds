#!/usr/bin/env python3
"""Seeded generator of HARD NEGATIVES for textops: questions ABOUT a text operation, code look-alikes, verb-sense look-alikes and
comparison questions.  Own templates, own word bank; never reads dev/calib.  make(n, seed) -> list of requests that textops must NOT answer.
Also POS: control requests that must keep working with the guard on (checked against the unguarded parser in test_prestep.py)."""
import random

OPN = ["uppercase", "lowercase", "title case", "capitalization", "all caps", "palindromes", "acronyms", "initials", "reversing", "sorting words",
       "word count", "character count", "vowels", "letter case", "camel case", "snake case", "capital letters", "small letters"]
OPV = ["uppercase", "lowercase", "capitalize", "reverse", "count", "sort", "title case", "alphabetize", "repeat", "replace", "spell"]
THING = ["a list", "a string", "an array", "a sentence", "words", "a file", "a word", "text", "a dictionary", "names", "a paragraph"]
LANG = ["python", "javascript", "java", "c", "sql", "bash", "rust", "go", "excel", "regex"]
PRE = ["", "", "", "hey ", "please ", "ok so ", "quick question ", "hi, "]
VS = [("uppercase", "lowercase"), ("title case", "sentence case"), ("capitalize", "uppercase"), ("reverse", "sort"), ("upper", "lower"),
      ("letters", "characters"), ("words", "tokens"), ("camel case", "snake case")]
SENSE = ["capitalize on this opportunity", "count on me", "reverse engineering is fun", "reverse psychology works", "title of the movie",
         "the upper hand in negotiation", "lower back pain", "lower the price", "title page of a book", "reverse mortgage rates",
         "count on it", "upper class history", "lower prices at the store", "reverse osmosis filter", "reverse gear on a car"]


def make(n, seed=7):
    r = random.Random(seed)
    out = set()
    fams = [
        lambda: "%s vs %s difference" % r.choice(VS),
        lambda: "difference between %s and %s" % r.choice(VS),
        lambda: "%s versus %s" % r.choice(VS),
        lambda: "what is the difference between %s and %s" % r.choice(VS),
        lambda: "%s or %s which is better" % r.choice(VS),
        lambda: "how do i %s %s in %s" % (r.choice(OPV), r.choice(THING), r.choice(LANG)),
        lambda: "how to %s %s" % (r.choice(OPV), r.choice(THING)),
        lambda: "how can i %s %s using %s" % (r.choice(OPV), r.choice(THING), r.choice(LANG)),
        lambda: "%s %s function" % (r.choice(OPV), r.choice(["words", "letters", "text", "string", "characters"])),
        lambda: "%s %s in %s" % (r.choice(OPV), r.choice(["a list", "an array", "a file", "a dictionary", "the rows"]), r.choice(LANG)),
        lambda: "what is %s" % r.choice(OPN),
        lambda: "what does %s mean" % r.choice(OPN),
        lambda: "explain %s" % r.choice(OPN),
        lambda: "explain %s to me" % r.choice(OPN),
        lambda: "why do people use %s" % r.choice(OPN),
        lambda: "is it rude to use %s" % r.choice(["all caps", "uppercase", "lowercase", "title case"]),
        lambda: "history of %s" % r.choice(OPN),
        lambda: "rules for %s" % r.choice(OPN),
        lambda: "examples of %s" % r.choice(OPN),
        lambda: "tell me about %s" % r.choice(OPN),
        lambda: "when should i use %s" % r.choice(OPN),
        lambda: "should i write in %s" % r.choice(["all caps", "uppercase", "lowercase"]),
        lambda: "what is the best way to %s %s" % (r.choice(OPV), r.choice(THING)),
        lambda: "best practice for %s in %s" % (r.choice(OPN), r.choice(LANG)),
        lambda: "does %s matter in %s" % (r.choice(OPN), r.choice(LANG)),
        lambda: "%s tutorial" % r.choice(OPN),
        lambda: r.choice(SENSE),
        lambda: "who invented %s" % r.choice(OPN),
        lambda: "where does the word %s come from" % r.choice(["uppercase", "capital", "palindrome", "acronym"]),
        lambda: "what are the rules of %s" % r.choice(OPN),
        lambda: "what is a %s" % r.choice(["palindrome", "acronym", "vowel", "consonant", "syllable", "anagram"]),
    ]
    guard = 0
    while len(out) < n and guard < n * 50:
        guard += 1
        out.add((r.choice(PRE) + r.choice(fams)()).strip())
    return sorted(out)


POS = ["uppercase hello world", "make river stone all caps", "reverse hello", "how many vowels in banana", "count the words in the quick brown fox",
       "is level a palindrome", "capitalize mango", "sort the words in zebra apple mango", "what is hello backwards", "title case the quick brown fox",
       "can you reverse piano", "please lowercase LOUD NOISE", "replace a with e in banana", "initials of john ronald tolkien", "spell cat",
       "repeat hi 3 times", "how many letters in pepper", "first word of red green blue", "remove the spaces from a b c", "say ok twice"]

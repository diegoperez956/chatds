#!/usr/bin/env python3
"""Seeded generator of text-operation requests and look-alike negatives for the textops C/Python parity test.
Independent of campaign/eval (own phrasings, own word bank); never reads dev or calib."""
import random

W = ("river stone cloud mango zebra piano harbor candle ladder pepper window orange castle jungle lemon quiet marble ember falcon "
     "violet thunder maple copper walrus tulip anchor bamboo cactus donkey eagle fabric glacier hammer iguana jacket kettle").split()
TXT = ["hello world", "the quick brown fox", "i like apples", "Racecar", "A man a plan", "level", "Never odd or even", "red green blue",
       "keep it simple", "x", "Mississippi", "one two  three", "Hello, World!", "abc123", "UPPER lower", "don't stop", "mr smith goes", "a1b2 c3"]


def arg(r, multi=None):
    k = r.random()
    if k < 0.45:
        return r.choice(W)
    if k < 0.8:
        return " ".join(r.choice(W) for _ in range(r.randint(2, 5)))
    return r.choice(TXT)


def quote(r, a):
    return r.choice(['"%s"', "'%s'", "`%s`", "%s"]) % a if r.random() < 0.4 else a


PRE = ["", "", "", "please ", "hi, ", "hey ", "thanks, now ", "ok so ", "can you ", "could you please ", "i want you to ", "tell me ", "what is ", "whats "]
POST = ["", "", "", "", "?", " please", ".", " pls", "!"]
UN = ["words", "letters", "vowels", "characters", "chars"]


def request(r):
    a0 = arg(r)
    a = quote(r, a0)
    fam = r.randrange(24)
    u = r.choice(UN)
    t = {
        0: lambda: r.choice(["uppercase %s", "make %s uppercase", "convert %s to all caps", "%s in capital letters", "make %s all caps", "turn %s into uppercase"]) % a,
        1: lambda: r.choice(["lowercase %s", "make %s lowercase", "convert %s to all lowercase", "%s in lower case", "change %s to lowercase"]) % a,
        2: lambda: r.choice(["title case %s", "convert %s to title case", "make %s title case", "%s in title case"]) % a,
        3: lambda: r.choice(["capitalize %s", "capitalize the first letter of %s", "make %s capitalized", "capitalise %s"]) % a,
        4: lambda: r.choice(["reverse %s", "flip %s", "reverse the text %s", "spell %s backwards", "write %s backwards", "%s backwards", "reverse the string %s"]) % a,
        5: lambda: r.choice(["reverse the words in %s", "flip the word order of %s", "reverse the order of the words in %s"]) % a,
        6: lambda: r.choice(["how many %s in %s", "count the %s in %s", "%s in %s", "how many %s are in %s", "number of %s in %s", "how many %s are there in the word %s"]) % (u, a),
        7: lambda: r.choice(["length of the text %s", "what is the length of the string %s", "how long is the word %s"]) % a,
        8: lambda: r.choice(["how many characters in %s without spaces", "character count of %s excluding spaces", "how many chars in %s with spaces"]) % a,
        9: lambda: r.choice(["remove the spaces from %s", "delete all spaces in %s", "strip spaces from %s", "%s without spaces", "make %s without spaces"]) % a,
        10: lambda: (lambda f: f % (a, r.randint(1, 12)) if "%d" in f else f % a)(
            r.choice(["repeat %s %d times", "say %s %d times", "write %s %d times", "repeat %s twice", "say %s thrice"])),
        11: lambda: (lambda x, y: r.choice(["replace %s with %s in %s", "change %s to %s in %s", "swap %s for %s in %s", "replace the letter %s with %s in %s"]) % (x, y, a))(
            r.choice(list("aeiou")), r.choice(list("xyz"))),
        12: lambda: r.choice(["get the initials of %s", "initials of %s", "first letter of each word in %s", "first letters of every word in %s"]) % a,
        13: lambda: r.choice(["acronym for %s", "make an acronym from %s", "what is the acronym of %s"]) % a,
        14: lambda: r.choice(["sort the words in %s alphabetically", "put the words of %s in alphabetical order", "alphabetize %s", "sort words in %s", "sort %s alphabetically"]) % a,
        15: lambda: r.choice(["first word of %s", "last word of %s", "what is the first word in %s", "the last word in %s"]) % a,
        16: lambda: r.choice(["is %s a palindrome", "check if %s is a palindrome", "is %s palindrome", "palindrome check %s"]) % a,
        17: lambda: r.choice(["spell out %s", "spell %s", "letters of %s", "list the letters of %s"]) % a,
        # negatives and look-alikes
        18: lambda: r.choice(["what is the capital of france", "who is ada lovelace", "how many words in the english language", "how many letters in the alphabet",
                                 "reverse a linked list in python", "sort the files in dir.txt alphabetically", "flip a coin", "replace foo with bar in notes.txt",
                                 "what is the length of the nile", "convert 5 miles to km", "how many vowels in english", "uppercase a string in javascript",
                                 "count the words in file.txt", "repeat after me", "hello", "thanks", "what is 2+2", "write a poem about rivers",
                                 "capitalize on the market", "make me a sandwich", "how many times did brazil win", "is the earth round", "list files",
                                 "sort it", "reverse it", "how many words are in a novel", "what does nasa stand for"]),
        19: lambda: " ".join(r.choice(W + ["the", "of", "in", "with", "to", "uppercase", "reverse", "count", "words", "replace", "how", "many"]) for _ in range(r.randint(2, 8))),
    }.get(fam, lambda: "")
    out = t() if fam < 20 else None
    if out is None:  # typo / casing / spacing damage on a clean request
        base = request(r)
        k = r.randrange(4)
        if k == 0 and len(base) > 4:
            i = r.randrange(1, len(base) - 1)
            base = base[:i] + base[i + 1:]
        elif k == 1 and len(base) > 4:
            i = r.randrange(0, len(base) - 1)
            base = base[:i] + base[i + 1] + base[i] + base[i + 2:]
        elif k == 2:
            base = base.upper() if r.random() < 0.5 else base.capitalize()
        else:
            base = "  " + base.replace(" ", "  ", 1) + "  "
        return base
    return r.choice(PRE) + out + r.choice(POST)


def make(n, seed):
    r = random.Random(seed)
    qs = []
    while len(qs) < n:
        q = request(r)
        if q and len(q) <= 127:
            qs.append(q)
    # hand edge cases: boundaries and junk
    qs += ["", " ", "a", "reverse", "uppercase", "x" * 127, "reverse " + "x" * 119, "reverse " + "x" * 120, '"', '""', "'", "uppercase '", "reverse `abc", "how many words are in msg (python)", "uppercase (hello world)", "uppercase [x]", "reverse roster_today", "uppercase names",
           "repeat " + "ab " * 40 + "3 times", "replace a with b in " + "a" * 100, "replace a with " + "b" * 50 + " in " + "a" * 60,
           "caf\xe9 uppercase", "uppercase \x01abc", "uppercase\tabc", "is  a palindrome", "reverse : :", "reverse hello ?", "reverse 'a b' c"]
    return qs


if __name__ == "__main__":
    import sys
    print("\n".join(make(int(sys.argv[1]), int(sys.argv[2]))))

---
slug: nfc-before-tokenising
title: "NFD text was unfindable: combining marks are not word characters"
kind: bug
created: 2026-08-17
updated: 2026-08-17
checked: 2026-11-04T15:26:54+00:00
sources:
  - src/pagelore/search.py
---

## Cause

The tokenizer is `\w+` with the Unicode flag, and `\w` does not match combining
marks (category Mn). macOS hands out NFD, most editors write NFC. Unnormalised,
the NFD form of `ёлка` tokenised as `['е', 'лка']` and the NFD `йогурт` as
`['и', 'огурт']`, so recall across an NFC/NFD boundary was zero — on the two most
common diacritic letters in Russian, in a store whose stated invariant is that it
must stay bilingual, developed on the platform that produces the broken form.

The one bilingual test in the suite used the only two Cyrillic words in its
fixture that carry no diacritic, so it passed throughout.

## Fix

Normalise to NFC before tokenising, and fold with `casefold()` rather than
`lower()`, which also covers `STRASSE` against `straße`. Both the query and the
indexed text go through the same function, so either input form finds either
stored form.

CJK is a separate and unfixed problem, now documented rather than implied: `\w+`
returns one token per unbroken ideograph run, so Chinese, Japanese and Korean
collapse to whole-phrase equality and Thai fragments meaninglessly. A real
segmenter is not in the standard library, which is a constraint this skill accepts
elsewhere too.

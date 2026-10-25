#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MediaCleanup.py — organise a personal MKV media library, built on MKVToolNix.
Author:  Atik Ansari — https://github.com/atikansari-ghr
Project: https://github.com/atikansari-ghr/MediaCleanup
License: MIT

Merges variant copies of the same title (best video track plus every audio
track in the configured languages), strips promotional tags and attachments,
embeds full metadata and cover art, downloads sidecar subtitles, and renames
everything to one canonical format.

Key guarantees:
- Sources are only ever READ. Output is written to a temp file and atomically
  moved into place; --inplace replaces a source only after verifying the
  output's track counts and duration.
- mkvmerge -J JSON identification drives every track decision.
- --dry-run previews every action, including the predicted final filename.
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import csv
import dataclasses
import datetime as _dt
import difflib
import fnmatch
import hashlib
import json
import logging
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Kept in step with the newest entry in CHANGELOG.md; --version reports it and
# --check-update compares it with the latest GitHub release.
__version__ = "1.12.1"
GITHUB_REPO = "atikansari-ghr/MediaCleanup"

# Optional dependency: 'rich' enables colored log output and end-of-run summary
# tables. Without it the script runs identically with plain-text output.
#   pip install rich
try:
    from rich.console import Console as _RichConsole
    from rich.logging import RichHandler as _RichHandler
    from rich.table import Table as _RichTable
    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False

# Populated in main() when rich output is active (installed, not --no-color/NO_COLOR).
_RICH_ENABLED: bool = False
_CONSOLE: Optional["_RichConsole"] = None

# =========================
# Language table
# =========================

# Complete ISO 639 registry (generated from the ISO 639-2 standard: every
# language with a 639-1 code, plus common 639-2/3-only media tags).
# Line format: bibliographic-639-2 | terminological-639-2 (or empty) | 639-1 | English name
_ISO639_DATA = """\
aar||aa|Afar
abk||ab|Abkhazian
afr||af|Afrikaans
aka||ak|Akan
alb|sqi|sq|Albanian
amh||am|Amharic
ara||ar|Arabic
arg||an|Aragonese
arm|hye|hy|Armenian
asm||as|Assamese
ava||av|Avaric
ave||ae|Avestan
aym||ay|Aymara
aze||az|Azerbaijani
bak||ba|Bashkir
bam||bm|Bambara
baq|eus|eu|Basque
bel||be|Belarusian
ben||bn|Bengali
bis||bi|Bislama
bos||bs|Bosnian
bre||br|Breton
bul||bg|Bulgarian
bur|mya|my|Burmese
cat||ca|Catalan
cha||ch|Chamorro
che||ce|Chechen
chi|zho|zh|Chinese
chu||cu|Church Slavic
chv||cv|Chuvash
cmn|||Mandarin Chinese
cor||kw|Cornish
cos||co|Corsican
cre||cr|Cree
cze|ces|cs|Czech
dan||da|Danish
div||dv|Divehi
dut|nld|nl|Dutch
dzo||dz|Dzongkha
eng||en|English
epo||eo|Esperanto
est||et|Estonian
ewe||ee|Ewe
fao||fo|Faroese
fij||fj|Fijian
fil|||Filipino
fin||fi|Finnish
fre|fra|fr|French
fry||fy|Western Frisian
ful||ff|Fulah
geo|kat|ka|Georgian
ger|deu|de|German
gla||gd|Scottish Gaelic
gle||ga|Irish
glg||gl|Galician
glv||gv|Manx
gre|ell|el|Greek
grn||gn|Guarani
guj||gu|Gujarati
hak|||Hakka Chinese
hat||ht|Haitian
hau||ha|Hausa
hbs||sh|Serbo-Croatian
heb||he|Hebrew
her||hz|Herero
hin||hi|Hindi
hmo||ho|Hiri Motu
hrv||hr|Croatian
hun||hu|Hungarian
ibo||ig|Igbo
ice|isl|is|Icelandic
ido||io|Ido
iii||ii|Sichuan Yi
iku||iu|Inuktitut
ile||ie|Interlingue
ina||ia|Interlingua
ind||id|Indonesian
ipk||ik|Inupiaq
ita||it|Italian
jav||jv|Javanese
jpn||ja|Japanese
kal||kl|Kalaallisut
kan||kn|Kannada
kas||ks|Kashmiri
kau||kr|Kanuri
kaz||kk|Kazakh
khm||km|Khmer
kik||ki|Kikuyu
kin||rw|Kinyarwanda
kir||ky|Kirghiz
kom||kv|Komi
kon||kg|Kongo
kor||ko|Korean
kua||kj|Kuanyama
kur||ku|Kurdish
lao||lo|Lao
lat||la|Latin
lav||lv|Latvian
lim||li|Limburgan
lin||ln|Lingala
lit||lt|Lithuanian
ltz||lb|Luxembourgish
lub||lu|Luba-Katanga
lug||lg|Ganda
mac|mkd|mk|Macedonian
mah||mh|Marshallese
mal||ml|Malayalam
mao|mri|mi|Maori
mar||mr|Marathi
may|msa|ms|Malay
mlg||mg|Malagasy
mlt||mt|Maltese
mon||mn|Mongolian
nan|||Min Nan Chinese
nau||na|Nauru
nav||nv|Navajo
nbl||nr|South Ndebele
nde||nd|North Ndebele
ndo||ng|Ndonga
nep||ne|Nepali
nno||nn|Norwegian Nynorsk
nob||nb|Norwegian Bokmål
nor||no|Norwegian
nya||ny|Chichewa
oci||oc|Occitan
oji||oj|Ojibwa
ori||or|Odia
orm||om|Oromo
oss||os|Ossetian
pan||pa|Punjabi
per|fas|fa|Persian
pli||pi|Pali
pol||pl|Polish
por||pt|Portuguese
pus||ps|Pashto
que||qu|Quechua
roh||rm|Romansh
rum|ron|ro|Romanian
run||rn|Rundi
rus||ru|Russian
sag||sg|Sango
san||sa|Sanskrit
sin||si|Sinhala
slo|slk|sk|Slovak
slv||sl|Slovenian
sme||se|Northern Sami
smo||sm|Samoan
sna||sn|Shona
snd||sd|Sindhi
som||so|Somali
sot||st|Southern Sotho
spa||es|Spanish
srd||sc|Sardinian
srp||sr|Serbian
ssw||ss|Swati
sun||su|Sundanese
swa||sw|Swahili
swe||sv|Swedish
tah||ty|Tahitian
tam||ta|Tamil
tat||tt|Tatar
tel||te|Telugu
tgk||tg|Tajik
tgl||tl|Tagalog
tha||th|Thai
tib|bod|bo|Tibetan
tir||ti|Tigrinya
ton||to|Tonga
tsn||tn|Tswana
tso||ts|Tsonga
tuk||tk|Turkmen
tur||tr|Turkish
twi||tw|Twi
uig||ug|Uighur
ukr||uk|Ukrainian
urd||ur|Urdu
uzb||uz|Uzbek
ven||ve|Venda
vie||vi|Vietnamese
vol||vo|Volapük
wel|cym|cy|Welsh
wln||wa|Walloon
wol||wo|Wolof
xho||xh|Xhosa
yid||yi|Yiddish
yor||yo|Yoruba
yue|||Cantonese
zha||za|Zhuang
zul||zu|Zulu"""

# Built-in language knowledge: ISO 639-2 bibliographic code (canonical key)
# -> (ISO 639-1, display name). Parsed from the registry above.
_LANGUAGE_TABLE: Dict[str, Tuple[str, str]] = {}
# ISO 639-2/T terminology variants -> the bibliographic canonical key (fra -> fre).
_ISO2_ALIASES: Dict[str, str] = {}
for _line in _ISO639_DATA.splitlines():
    _bib, _term, _one, _name = _line.split("|", 3)
    _LANGUAGE_TABLE[_bib] = (_one, _name)
    if _term:
        _ISO2_ALIASES[_term] = _bib

# Common alternate English names -> canonical key (the ISO name differs).
_NAME_ALIASES: Dict[str, str] = {
    "oriya": "ori", "farsi": "per", "dhivehi": "div", "maldivian": "div",
    "flemish": "dut", "castilian": "spa", "mandarin": "cmn", "myanmar": "bur",
    "panjabi": "pan", "pushto": "pus", "kyrgyz": "kir", "uyghur": "uig",
    "sinhalese": "sin", "bangla": "ben",
}

# Curated native-script / misspelling tokens (merged into detection tokens so
# 'und' tracks named in the language's own script are still recognized).
_EXTRA_NAME_TOKENS: Dict[str, Tuple[str, ...]] = {
    "tel": ("తెలుగు", "తెలుగ", "telegu"),
    "hin": ("हिंदी", "हिन्दी"),
    "tam": ("தமிழ்",),
    "mal": ("മലയാളം",),
    "kan": ("ಕನ್ನಡ",),
    "ben": ("বাংলা", "bangla"),
    "mar": ("मराठी",),
    "guj": ("ગુજરાતી",),
    "pan": ("ਪੰਜਾਬੀ", "panjabi"),
    "urd": ("اردو",),
    "kor": ("한국어", "한국어 (korean)"),
    "jpn": ("日本語",),
    "chi": ("中文", "普通话", "简体", "繁體"),
    "fre": ("français", "francais"),
    "ger": ("deutsch",),
    "spa": ("español", "espanol", "latino"),
    "por": ("português", "portugues", "brazilian"),
    "rus": ("русский",),
    "ara": ("العربية",),
    "tha": ("ไทย",),
    "vie": ("tiếng việt",),
    "ita": ("italiano",),
    "tur": ("türkçe", "turkce"),
    "heb": ("עברית",),
    "per": ("فارسی", "farsi"),
    "ukr": ("українська",),
}

_DEFAULT_TARGETS: Tuple[str, ...] = ("hin", "eng", "tel")


def resolve_language(token: str) -> Optional[str]:
    """
    Resolve a user token to the canonical ISO 639-2 key, or None if unknown.
    Accepts every form: 2-letter (ko), 3-letter bibliographic (kor) and
    terminological (fra), full English name (Korean), and common alternate
    names (Farsi, Punjabi, Bangla, ...). Case-insensitive; BCP-47 tags like
    'zh-Hans' resolve via their primary subtag.
    """
    t = str(token).strip().lower()
    if not t:
        return None
    if t in _LANGUAGE_TABLE:
        return t
    if t in _ISO2_ALIASES:
        return _ISO2_ALIASES[t]
    if t in _NAME_ALIASES:
        return _NAME_ALIASES[t]
    for iso2, (iso1, name) in _LANGUAGE_TABLE.items():
        if t == iso1 or t == name.lower():
            return iso2
    # BCP-47 / IETF tag: try the primary subtag ('zh-Hans' -> 'zh')
    if "-" in t or "_" in t:
        primary = re.split(r"[-_]", t)[0]
        if primary != t:
            return resolve_language(primary)
    return None


# --- Language identification from subtitle text -------------------------------
# Releases stripped of track metadata tag every track 'und'. The text of a
# subtitle track still says what language it is, so identify it directly rather
# than guessing from track order. Two stages: writing system first (decisive on
# its own for most scripts), then function-word frequency for the writing
# systems several languages share.

# Subtitle codecs whose payload is readable text.
_TEXT_SUB_CODECS: Tuple[str, ...] = (
    "S_TEXT/UTF8", "S_TEXT/ASCII", "S_TEXT/SSA", "S_TEXT/ASS", "S_TEXT/WEBVTT",
)

# Writing systems used by exactly one language we care about.
_SCRIPT_LANG: Dict[str, str] = {
    "HANGUL": "kor", "THAI": "tha", "HEBREW": "heb", "GREEK": "gre",
    "TAMIL": "tam", "TELUGU": "tel", "KANNADA": "kan", "MALAYALAM": "mal",
    "BENGALI": "ben", "GUJARATI": "guj", "GURMUKHI": "pan", "ORIYA": "ori",
    "SINHALA": "sin", "MYANMAR": "bur", "KHMER": "khm", "LAO": "lao",
    "GEORGIAN": "geo", "ARMENIAN": "arm", "ETHIOPIC": "amh", "TIBETAN": "tib",
}

# Writing systems shared by several languages - decided by function words.
_SCRIPT_GROUP: Dict[str, Tuple[str, ...]] = {
    "LATIN": ("eng", "spa", "por", "fre", "ita", "ger", "dut", "dan", "swe",
              "nor", "fin", "est", "lav", "lit", "pol", "cze", "slo", "slv",
              "hun", "rum", "tur", "vie", "ind", "may", "hrv", "srp", "alb",
              "ice", "tgl", "cat"),
    "CYRILLIC": ("rus", "ukr", "bul", "srp", "mac", "bel"),
    "ARABIC": ("ara", "per", "urd"),
    "DEVANAGARI": ("hin", "mar", "nep"),
}

# High-frequency function words. Words shared by neighbouring languages are kept
# in both lists on purpose: they contribute equally and cancel out, leaving the
# exclusive ones (Danish 'mig/af' vs Norwegian 'meg/av') to decide.
_STOPWORDS: Dict[str, Set[str]] = {k: set(v.split()) for k, v in {
    "eng": "the and you that for was with have this but not are his her she him they all",
    "spa": "que los las por con una para pero como más está esto son del muy hay cuando bien",
    "por": "que não uma para com mais como está isso são você dos mas muito quando bem tem",
    "cat": "que els les amb una per però com això són molt quan bé tinc també fer",
    "fre": "que les des pour pas vous nous une avec dans est sur plus mais tout être elle",
    "ita": "che non per una con sono più come questo quando anche solo cosa bene tutto",
    "ger": "und der die das ist nicht ich sie mit den ein auf für wir aber was dass",
    "dut": "het een niet dat van ik je wij maar voor met zijn ook nog wat naar",
    "dan": "det er ikke jeg til af med har mig dig sig efter hvad hvor men også",
    "nor": "det er ikke jeg til av med har meg deg seg etter hva hvor men også",
    "swe": "det är inte jag och att till av med har mig dig sig efter vad var men också",
    "ice": "það er ekki ég til að með hef mig þig sig eftir hvað hvar en líka",
    "fin": "että on ei ja se minä sinä hän mutta kun niin vain siitä tämä ole",
    "est": "on ei ja see ma sa ta aga kui nii ainult sellest see ole mis",
    "lav": "ir nav un tas es tu viņš bet kad tā tikai par šis ko kā",
    "lit": "yra nėra ir tai aš tu jis bet kai taip tik apie šis ką kaip",
    "pol": "nie że jest to ja ty on ale kiedy tak tylko się jak co żeby",
    "cze": "ne že je to já ty on ale když tak jen se jak co jsem jsi jsou pro",
    "slo": "nie že je to ja ty on ale keď tak len sa ako čo som si sú pre",
    "slv": "ne da je to jaz ti on ampak ko tako samo se kako kaj sem si so",
    "hrv": "ne da je to ja ti on ali kad tako samo se kako što sam si su gdje",
    "srp": "ne da je to ja ti on ali kad tako samo se kako šta sam si su gde",
    "hun": "nem hogy van ez én te ő de amikor így csak magát hogyan mit vagyok",
    "rum": "nu că este asta eu tu el dar când așa doar se cum ce sunt",
    "tur": "bir bu ne için ile ama çok daha var yok gibi kadar sonra ben sen",
    "vie": "không là của và có được người này thì cho những một với anh tôi",
    "ind": "yang tidak dan ini itu untuk dengan dari saya kamu akan ada bisa sudah",
    "may": "yang tidak dan ini itu untuk dengan dari saya awak akan ada boleh sudah",
    "alb": "nuk që është kjo unë ti ai por kur kështu vetëm si çfarë jam",
    "tgl": "ang mga sa na ng ay hindi ako ikaw siya para pero kung yung",
    "rus": "не что это как все меня тебя очень если так его она они был",
    "ukr": "не що це як все мене тебе дуже якщо так його вона вони був",
    "bul": "не какво това как всичко мен теб много ако така него тя те беше",
    "mac": "не што ова како сè мене тебе многу ако така него таа тие беше",
    "bel": "не што гэта як усё мяне цябе вельмі калі так яго яна яны быў",
    "ara": "في من على أن لا ما هذا هو هي إلى مع كان عن كل",
    "per": "در از که این را با به می برای است او آن هم یک",
    "urd": "میں سے کہ یہ کو نے ہے ہیں کیا اور پر ایک نہیں تھا",
    "hin": "है हैं नहीं में से को का की के और यह वह हूँ था थी थे क्या मैं तुम आप हम रहा रही रहे लिए साथ बहुत",
    "mar": "आहे नाही आहेत मध्ये ला चा ची चे आणि हे तो ती मी तू आम्ही होता होती खूप पण काय",
    "nep": "छ छैन हुन् हो होइन मा बाट लाई यो त्यो तिमी हामी थियो गर्नु भने पनि तर धेरै के",
}.items()}

# Letters only one language of its group uses - a tiebreak for pairs whose
# function words largely coincide. Every character here must be near-exclusive:
# a letter common in a neighbouring language (Slovak 'ä', also ordinary in
# Finnish, German and Estonian) drags the wrong language to the top.
_MARKER_CHARS: Dict[str, str] = {
    "cze": "řěů", "slo": "ľŕô", "pol": "łżźęą", "hrv": "đ", "srp": "đ",
    "rum": "ăâșț", "hun": "őű", "tur": "ışğ", "vie": "ơư", "est": "õ",
    "lav": "ķņģļ", "lit": "ųėį", "dan": "ø", "nor": "ø", "ice": "þð",
    "ger": "ß", "spa": "ñ", "por": "ã", "cat": "ŀ", "alb": "ë",
}

# Minimum share of tokens that must be function words of the winning language,
# and how far ahead of the runner-up it must be. Below either, the track keeps
# its 'und' tag: a wrong language tag is worse than an honest unknown.
_LANGID_MIN_SCORE = 0.02
_LANGID_MIN_MARGIN = 0.05


def _lang_tokens(text: str) -> List[str]:
    """
    Split text into words. A word character is any letter OR combining mark:
    Python's word-character class excludes marks, which would shred Devanagari,
    Tamil and vowelled Arabic into bare consonants and destroy the counts.
    """
    return "".join(
        ch if unicodedata.category(ch)[0] in ("L", "M") else " " for ch in text
    ).split()


def _script_histogram(text: str) -> Dict[str, int]:
    counts: Dict[str, int] = collections.Counter()
    for ch in text:
        if not ch.isalpha():
            continue
        try:
            counts[unicodedata.name(ch).split()[0]] += 1
        except ValueError:
            pass
    return counts


def _strip_subtitle_markup(text: str) -> str:
    """Reduce a subtitle file to its spoken words."""
    text = re.sub(r"<[^>]+>|\{[^}]*\}", " ", text)                          # HTML / ASS overrides
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", text)                       # SDH sound cues
    text = re.sub(r"^\s*\d+\s*$", " ", text, flags=re.M)                    # cue numbers
    text = re.sub(r"^.*-->.*$", " ", text, flags=re.M)                      # timings
    text = re.sub(r"^Dialogue:[^,]*(?:,[^,]*){8},", " ", text, flags=re.M)  # ASS field prefix
    return text


def identify_text_language(text: str) -> Tuple[Optional[str], float]:
    """
    Identify the language of subtitle text.

    Returns (canonical ISO 639-2 code, confidence 0-1), or (None, 0.0) when the
    text is too short or two languages score too close to call.
    """
    text = _strip_subtitle_markup(text)
    hist = _script_histogram(text)
    if not hist:
        return None, 0.0
    total = sum(hist.values())

    # Japanese mixes kana with Han; any real kana presence settles it.
    kana = hist.get("HIRAGANA", 0) + hist.get("KATAKANA", 0)
    if kana and kana / total > 0.02:
        return "jpn", 1.0

    script = max(hist.items(), key=lambda kv: kv[1])[0]
    if script in ("CJK", "IDEOGRAPHIC"):
        return "chi", 1.0
    if script in _SCRIPT_LANG:
        return _SCRIPT_LANG[script], 1.0

    group = _SCRIPT_GROUP.get(script)
    if not group:
        return None, 0.0

    low = text.lower()
    words = _lang_tokens(low)
    if len(words) < 20:
        return None, 0.0
    bag = collections.Counter(words)

    scores: Dict[str, float] = {}
    for lang in group:
        stop = _STOPWORDS.get(lang)
        if not stop:
            continue
        hits = sum(bag[w] for w in stop)
        bonus = sum(low.count(ch) for ch in _MARKER_CHARS.get(lang, "")) * 3
        scores[lang] = (hits + bonus) / len(words)
    if not scores:
        return None, 0.0

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best, best_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
    if best_score < _LANGID_MIN_SCORE:
        return None, 0.0
    margin = (best_score - runner_up) / best_score
    if margin < _LANGID_MIN_MARGIN:
        return None, 0.0
    return best, round(min(1.0, margin), 3)


def _build_language_maps(targets: Tuple[str, ...]) -> Tuple[Dict[str, str], Dict[str, Tuple[str, ...]], Dict[str, Tuple[str, ...]]]:
    """Build (display_map, iso_codes, name_tokens) for the configured targets."""
    display: Dict[str, str] = {}
    iso_codes: Dict[str, Tuple[str, ...]] = {}
    tokens: Dict[str, Tuple[str, ...]] = {}
    for iso2 in targets:
        iso1, name = _LANGUAGE_TABLE[iso2]
        aliases = tuple(a for a, canon in _ISO2_ALIASES.items() if canon == iso2)
        display[iso2] = name
        iso_codes[iso2] = tuple(c for c in (iso2, iso1, *aliases) if c)
        tokens[iso2] = (name.lower(), iso2) + _EXTRA_NAME_TOKENS.get(iso2, ())
    return display, iso_codes, tokens


def iso2_to_iso1(iso2: str) -> Optional[str]:
    """ISO 639-2 -> 639-1 (e.g. 'hin' -> 'hi'); None when there is no 2-letter code."""
    entry = _LANGUAGE_TABLE.get(_ISO2_ALIASES.get(iso2, iso2))
    return entry[0] or None if entry else None


def iso1_to_iso2(iso1: str) -> Optional[str]:
    """ISO 639-1 -> 639-2 (e.g. 'en' -> 'eng')."""
    for iso2, (one, _name) in _LANGUAGE_TABLE.items():
        if one == iso1:
            return iso2
    return None


# =========================
# Configurable constants
# =========================

@dataclasses.dataclass(frozen=True)
class Config:
    # Tool paths — loaded from MediaCleanup.toml (same folder as this script).
    # No defaults here on purpose: load_config() is the single source of truth.
    MKVTOOLNIX_DIR: Path
    MKVMERGE_EXE: Path
    MKVPROPEDIT_EXE: Path
    MKVINFO_EXE: Path
    MKVEXTRACT_EXE: Path

    # Optional: FileBot (portable licensed) for pre-rename normalization.
    # If the path doesn't exist, FileBot steps are skipped gracefully.
    FILEBOT_EXE: Path

    # Roots — loaded from MediaCleanup.toml [paths]
    MOVIES_ROOT: Path
    TV_ROOT: Path
    WORK_ROOT: Path
    OUTPUT_ROOT: Path

    FILEBOT_DB: str = "TheMovieDB"

    # Cover art API keys — MediaCleanup.toml [coverart] section.
    # An empty string disables that source; local poster files always work.
    TMDB_API_KEY: str = ""
    FANARTTV_API_KEY: str = ""
    OMDB_API_KEY: str = ""

    # OpenSubtitles.com — MediaCleanup.toml [subtitles] section (--subtitles mode).
    # All three credentials are required for downloads; languages are ISO 639-1.
    OS_API_KEY: str = ""
    OS_USERNAME: str = ""
    OS_PASSWORD: str = ""
    SUB_LANGS: Tuple[str, ...] = ("en",)

    # Filename prefixes to strip — MediaCleanup.toml [naming] strip_prefixes.
    # Empty by default; the generic www./domain rule works without it.
    STRIP_PREFIXES: Tuple[str, ...] = ()

    # Similarity grouping for Movies (per-folder)
    SIMILARITY_THRESHOLD_DEFAULT: float = 0.88

    # Target languages — MediaCleanup.toml [languages] targets.
    # Canonical keys are ISO 639-2 codes; ORDER = audio track order in output.
    # Default (no [languages] section): Hindi, English, Telugu.
    LANG_CANONICAL_ORDER: Tuple[str, ...] = _DEFAULT_TARGETS
    # Identify tracks tagged 'und' — [languages] detect_undetermined.
    DETECT_UNDETERMINED_LANGS: bool = True
    # When no database knows a title, name and tag the file from facts in the file
    # itself — [naming] local_fallback; --no-local-name turns it off.
    LOCAL_NAME_FALLBACK: bool = True
    # Look for a newer release at most once a day and print a one-line notice —
    # [updates] check; --no-update-check skips it for one run.
    UPDATE_CHECK: bool = True
    # Full display names used in the output filename bracket list and track naming.
    LANG_DISPLAY_MAP: Dict[str, str] = dataclasses.field(
        default_factory=lambda: _build_language_maps(_DEFAULT_TARGETS)[0])
    # Canonical -> accepted ISO codes (lower)
    LANG_ISO_CODES: Dict[str, Tuple[str, ...]] = dataclasses.field(
        default_factory=lambda: _build_language_maps(_DEFAULT_TARGETS)[1])
    # Canonical -> fuzzy name tokens (lower; substring checks against track names)
    LANG_NAME_TOKENS: Dict[str, Tuple[str, ...]] = dataclasses.field(
        default_factory=lambda: _build_language_maps(_DEFAULT_TARGETS)[2])

    # Exclude audio if name indicates commentary/descriptive
    AUDIO_EXCLUDE_TOKENS: Tuple[str, ...] = ("commentary", "descriptive", "description", "director", "narration")

    # Video codec preference
    VIDEO_CODEC_PREF: Tuple[str, ...] = ("hevc", "h265", "x265", "avc", "h264", "x264")

    # Resolution targets — height-based (2160p, 1080p, 720p)
    RES_TARGETS: Tuple[int, ...] = (2160, 1080, 720)
    # Width counterparts paired 1-to-1 with RES_TARGETS (used as primary signal)
    RES_WIDTH_TARGETS: Tuple[int, ...] = (3840, 1920, 1280)

    # Audio codec preference (best first)
    AUDIO_CODEC_RANK: Tuple[str, ...] = (
        "a_truehd", "dts-hd", "dts_hd", "dts", "eac3", "ac3", "aac", "mp3", "vorbis", "opus"
    )

    # Subtitle codec preference (best first)
    SUB_CODEC_RANK: Tuple[str, ...] = (
        "s_text/utf8", "s_text/ass", "s_text/ssa", "s_text/webvtt", "s_hdmv/pgs", "s_vobsub"
    )

    # Working copy caching
    # By default: reuse working file if size+mtime match; if mismatch, recopy.
    # Optional: compute sha256 when size matches but mtime differs (enabled here for safety).
    HASH_ON_MTIME_MISMATCH: bool = True

    # Long path handling: use \\?\ prefix for Windows paths when needed
    ENABLE_WIN_LONG_PATH_PREFIX: bool = True


class ConfigError(Exception):
    """Raised when MediaCleanup.toml is missing or invalid."""


_SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = _SCRIPT_DIR / "MediaCleanup.toml"


def load_config(config_file: Path = CONFIG_FILE) -> Config:
    """
    Load tool/media paths from MediaCleanup.toml (same folder as the script).

    Required:
      [tools] mkvtoolnix_dir
      [paths] movies_root, tv_root, work_root, output_root
    Optional:
      [tools] mkvmerge/mkvpropedit/mkvinfo/mkvextract  (default: <mkvtoolnix_dir>\\<name>.exe)
      [filebot] exe, db                                 (FileBot skipped if exe missing)
    """
    if not config_file.exists():
        raise ConfigError(
            f"Config file not found: {config_file}\n"
            "Create it with [tools], [paths] (and optional [filebot]) sections. Example:\n"
            "  [tools]\n"
            "  mkvtoolnix_dir = 'D:\\Tools\\mkvtoolnix'\n"
            "  [paths]\n"
            "  movies_root = 'D:\\Media\\Movies'\n"
            "  tv_root     = 'D:\\Media\\TV'\n"
            "  work_root   = 'D:\\Media\\ToFix'\n"
            "  output_root = 'D:\\Media\\Fixed'"
        )
    try:
        with config_file.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Invalid TOML in {config_file}: {e}")

    tools = data.get("tools", {}) or {}
    filebot = data.get("filebot", {}) or {}
    paths = data.get("paths", {}) or {}
    coverart = data.get("coverart", {}) or {}
    subtitles = data.get("subtitles", {}) or {}
    naming = data.get("naming", {}) or {}

    prefixes_raw = naming.get("strip_prefixes") or []
    if not isinstance(prefixes_raw, list):
        raise ConfigError("[naming] strip_prefixes must be a list of strings, "
                          'e.g. strip_prefixes = ["SomeDistributor"]')
    strip_prefixes = tuple(str(x).strip() for x in prefixes_raw if str(x).strip())

    sub_langs_raw = subtitles.get("languages") or ["en"]
    if not isinstance(sub_langs_raw, list):
        raise ConfigError(f"[subtitles] languages must be a list of ISO codes, got: {sub_langs_raw!r}")
    sub_langs = tuple(str(x).strip().lower() for x in sub_langs_raw if str(x).strip()) or ("en",)

    # [languages] targets — audio languages to keep, in output track order.
    languages = data.get("languages", {}) or {}
    targets_raw = languages.get("targets") or list(_DEFAULT_TARGETS)
    if not isinstance(targets_raw, list) or not targets_raw:
        raise ConfigError("[languages] targets must be a non-empty list, e.g. targets = [\"hin\", \"eng\", \"tel\"]")
    targets: List[str] = []
    for token in targets_raw:
        iso2 = resolve_language(str(token))
        if iso2 is None:
            raise ConfigError(
                f"[languages] unknown language {token!r}. Use any ISO 639-1 code ('ko'), "
                f"ISO 639-2 code ('kor'), or English name ('Korean') — "
                f"{len(_LANGUAGE_TABLE)} languages supported.")
        if iso2 not in targets:
            targets.append(iso2)
    lang_order = tuple(targets)

    detect_und = languages.get("detect_undetermined", True)
    if not isinstance(detect_und, bool):
        raise ConfigError("[languages] detect_undetermined must be true or false")
    lang_display, lang_iso_codes, lang_tokens = _build_language_maps(lang_order)

    local_fallback = naming.get("local_fallback", True)
    if not isinstance(local_fallback, bool):
        raise ConfigError("[naming] local_fallback must be true or false")

    updates = data.get("updates", {}) or {}
    update_check = updates.get("check", True)
    if not isinstance(update_check, bool):
        raise ConfigError("[updates] check must be true or false")

    def required(section: Dict[str, Any], section_name: str, key: str) -> str:
        v = section.get(key)
        if not v:
            raise ConfigError(f"Missing required key '{key}' in [{section_name}] of {config_file}")
        return str(v)

    def as_path(value: str) -> Path:
        """Relative TOML paths resolve against the script folder, so a cloned
        project with tools in runtimes\\ works regardless of install location."""
        p = Path(value)
        return p if p.is_absolute() else (_SCRIPT_DIR / p)

    mkvtoolnix_dir = as_path(required(tools, "tools", "mkvtoolnix_dir"))

    def tool_exe(key: str, default_name: str) -> Path:
        v = tools.get(key)
        return as_path(str(v)) if v else mkvtoolnix_dir / default_name

    # FileBot is optional: point at a guaranteed-nonexistent path when not configured
    # so all FILEBOT_EXE.exists() checks skip FileBot gracefully.
    fb = filebot.get("exe")
    filebot_exe = as_path(str(fb)) if fb else (_SCRIPT_DIR / "__filebot_not_configured__")

    return Config(
        MKVTOOLNIX_DIR=mkvtoolnix_dir,
        MKVMERGE_EXE=tool_exe("mkvmerge", "mkvmerge.exe"),
        MKVPROPEDIT_EXE=tool_exe("mkvpropedit", "mkvpropedit.exe"),
        MKVINFO_EXE=tool_exe("mkvinfo", "mkvinfo.exe"),
        MKVEXTRACT_EXE=tool_exe("mkvextract", "mkvextract.exe"),
        FILEBOT_EXE=filebot_exe,
        MOVIES_ROOT=as_path(required(paths, "paths", "movies_root")),
        TV_ROOT=as_path(required(paths, "paths", "tv_root")),
        # work_root is legacy (remuxing now reads sources directly) — accepted
        # for backward compatibility but never used or created.
        WORK_ROOT=as_path(str(paths["work_root"])) if paths.get("work_root") else (_SCRIPT_DIR / "logs" / "work"),
        OUTPUT_ROOT=as_path(required(paths, "paths", "output_root")),
        FILEBOT_DB=str(filebot.get("db", "TheMovieDB")),
        TMDB_API_KEY=str(coverart.get("tmdb_api_key", "") or ""),
        FANARTTV_API_KEY=str(coverart.get("fanarttv_api_key", "") or ""),
        OMDB_API_KEY=str(coverart.get("omdb_api_key", "") or ""),
        OS_API_KEY=str(subtitles.get("api_key", "") or ""),
        OS_USERNAME=str(subtitles.get("username", "") or ""),
        OS_PASSWORD=str(subtitles.get("password", "") or ""),
        SUB_LANGS=sub_langs,
        STRIP_PREFIXES=strip_prefixes,
        LANG_CANONICAL_ORDER=lang_order,
        DETECT_UNDETERMINED_LANGS=detect_und,
        LOCAL_NAME_FALLBACK=local_fallback,
        UPDATE_CHECK=update_check,
        LANG_DISPLAY_MAP=lang_display,
        LANG_ISO_CODES=lang_iso_codes,
        LANG_NAME_TOKENS=lang_tokens,
    )


# Populated by main() via load_config(); module-level so all helpers can read it.
CFG: Config = None  # type: ignore[assignment]
# =========================
# FileBot formats
# =========================

# Final Movie naming
# Example output:
#   Movie Name (Year) - tt1234567 - HDRip.1080p.x265 - [Telugu + Hindi + English].mkv
MOVIE_FILEBOT_FORMAT = r"""{n} ({y}){ imdbid ? " - ${imdbid}" : (tmdbid ? " - tmdb${tmdbid}" : "") } - {
  def s = source ?: media?.Source ?: 'HDRip'
  s.replaceAll(/\s+/,'')
}.{vf}.{
  def c = vc?.toString()?.toLowerCase()
  if (c?.contains('hevc') || c?.contains('h.265') || c?.contains('x265')) 'x265'
  else if (c?.contains('avc') || c?.contains('h.264') || c?.contains('x264')) 'x264'
  else vc
} - [{
  audio.collect{ it.'Language/String' ?: it.Language ?: 'und' }
       .collect{ l ->
         def x = l.toString().replaceAll(/\s*\(.+\)$/, '').trim()
         def c = x.toLowerCase()
         if (c == '' || c == 'und' || c == 'unknown') return 'English'
         if (x.length() > 3) return x.capitalize()
         c = c.split(/[-_]/)[0]
         def dn = ''
         try { dn = new java.util.Locale(c).getDisplayLanguage(java.util.Locale.ENGLISH) } catch(e) {}
         return (dn && dn.toLowerCase() != c) ? dn : x.capitalize()
       }
       .unique()
       .join(' + ')
}]"""

# Final TV episode naming
# Example output:
#   Show Name (Year) - S01E03 - Episode Title - 1080p.x265 - [Telugu + Hindi + English].mkv
# {n} may already carry a disambiguating year on TheTVDB ('Show Name (2024)'),
# which would render as 'Show Name (2024) (2024)' — strip it before adding {y}.
TV_FILEBOT_FORMAT = r"""{n.replaceAll(/\s*\(\d{4}\)$/, '')} ({y}) - S{s.pad(2)}E{e.pad(2)} - {t} - {vf}.{
  def c = vc?.toString()?.toLowerCase()
  if (c?.contains('hevc') || c?.contains('h.265') || c?.contains('x265')) 'x265'
  else if (c?.contains('avc') || c?.contains('h.264') || c?.contains('x264')) 'x264'
  else vc
} - [{
  audio
    .collect { it.'Language/String' ?: it.Language ?: 'und' }
    .collect { l ->
      def x = l.toString().replaceAll(/\s*\(.+\)$/, '').trim()
      def c = x.toLowerCase()
      if (c == '' || c == 'und' || c == 'unknown') return 'English'
      if (x.length() > 3) return x.capitalize()
      c = c.split(/[-_]/)[0]
      def dn = ''
      try { dn = new java.util.Locale(c).getDisplayLanguage(java.util.Locale.ENGLISH) } catch(e) {}
      return (dn && dn.toLowerCase() != c) ? dn : x.capitalize()
    }
    .unique()
    .join(' + ')
}]"""


# =========================
# Logging & results
# =========================

@dataclasses.dataclass
class Result:
    kind: str  # "movie_cleanup", "movie_merge", "tv_cleanup"
    source_items: List[Path]
    output_path: Optional[Path]
    ok: bool
    reason: str = ""
    details: Dict[str, Any] = dataclasses.field(default_factory=dict)


_LOG_LOCK = threading.Lock()


# --- Keeping secrets out of logs -------------------------------------------------------
# TMDB, OMDb and fanart.tv take the API key in the URL's query string, and the log file is
# always written at DEBUG level, so a failed request could print a working key into a log that
# someone then pastes into a bug report. Every log handler therefore passes its output through
# redact_secrets(): known credential values are masked wherever they appear, and so is any
# `key=value` pair that names an API key, token or password.

_SECRET_PARAM_RX = re.compile(r"(?i)(api[_-]?key|apikey|access[_-]?token|token|password|passwd|secret)=([^&\s\"']+)")
_BEARER_RX = re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._~+/=-]{12,})")


def _secret_values() -> List[str]:
    values: List[str] = []
    cfg = globals().get("CFG")
    if cfg is not None:
        for name, minimum in (("TMDB_API_KEY", 6), ("FANARTTV_API_KEY", 6), ("OMDB_API_KEY", 6),
                              ("OS_API_KEY", 6), ("OS_PASSWORD", 5)):
            v = str(getattr(cfg, name, "") or "")
            if len(v) >= minimum:
                values.append(v)
    token = os.environ.get("MEDIACLEANUP_GITHUB_TOKEN", "").strip()
    if len(token) >= 8:
        values.append(token)
    return values


def redact_secrets(text: str) -> str:
    """`text` with every credential masked as ***."""
    if not text:
        return text
    out = _SECRET_PARAM_RX.sub(lambda m: f"{m.group(1)}=***", text)
    out = _BEARER_RX.sub(lambda m: f"{m.group(1)}***", out)
    for v in _secret_values():
        out = out.replace(v, "***")
    return out


class _RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
            clean = redact_secrets(message)
            if clean != message:
                record.msg, record.args = clean, ()
            if record.exc_info and not record.exc_text:
                import traceback
                record.exc_text = redact_secrets("".join(traceback.format_exception(*record.exc_info)).rstrip("\n"))
            elif record.exc_text:
                record.exc_text = redact_secrets(record.exc_text)
        except Exception:
            pass                      # a logging filter must never break the program
        return True


def setup_logging(verbose: bool, log_file: Optional[Path]) -> None:
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    # A Windows console is usually cp1252, and the tool legitimately prints text
    # it cannot encode — a film's original title in Kannada or Telugu, a track
    # name in its own script. Replacing those characters keeps the message
    # readable; raising would take down the worker that logged it.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    if _RICH_ENABLED and _CONSOLE is not None:
        # Rich renders timestamp + colored level itself; message-only format.
        rh = _RichHandler(console=_CONSOLE, show_path=False, rich_tracebacks=False,
                          omit_repeated_times=False)
        rh.setLevel(logging.DEBUG if verbose else logging.INFO)
        rh.setFormatter(logging.Formatter("%(message)s"))
        rh.addFilter(_RedactingFilter())
        logger.addHandler(rh)
    else:
        sh = logging.StreamHandler(sys.stdout)
        sh.setLevel(logging.DEBUG if verbose else logging.INFO)
        sh.setFormatter(fmt)
        sh.addFilter(_RedactingFilter())
        logger.addHandler(sh)

    # Log file is always plain text (grep-able), regardless of console styling.
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        fh.addFilter(_RedactingFilter())
        logger.addHandler(fh)


# Result.reason values that mean "nothing to do" rather than "work done".
_SKIP_REASONS = ("already_has_cover", "already_covered", "already_named",
                 "ledger_skip", "dry-run", "unchanged", "film_unidentified",
                 "show_unidentified")


def print_results_table(title: str, results: List[Result]) -> None:
    """
    Render an end-of-run summary table (rich only; silently does nothing in
    plain mode — the classic logging summary lines are always emitted anyway).
    Columns: File | Action | Status | Detail with green OK / yellow SKIP / red FAIL.
    """
    if not _RICH_ENABLED or _CONSOLE is None or not results:
        return

    table = _RichTable(title=title, header_style="bold cyan", border_style="dim",
                       title_style="bold", expand=False)
    table.add_column("File", overflow="fold", max_width=70)
    table.add_column("Action", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Detail", overflow="fold", max_width=70)

    def sort_key(r: Result) -> str:
        return r.source_items[0].name.lower() if r.source_items else ""

    for r in sorted(results, key=sort_key):
        name = r.source_items[0].name if r.source_items else "?"
        if r.ok and r.details.get("rename_failed"):
            # The file was tagged and cleaned, but it still carries its release
            # name — reporting a bare OK hid that from the summary entirely.
            status = "[yellow]PARTIAL[/yellow]"
        elif r.ok and r.details.get("local_named"):
            # Named and cleaned from the file alone: no database confirmed it.
            status = "[cyan]LOCAL[/cyan]"
        elif r.ok and r.reason in _SKIP_REASONS:
            status = "[yellow]SKIP[/yellow]"
        elif r.ok:
            status = "[green]OK[/green]"
        else:
            status = "[red]FAIL[/red]"

        if not r.ok:
            detail = r.reason
        elif r.details.get("rename_failed"):
            detail = f"not renamed: {r.details['rename_failed']}"
        elif r.details.get("local_named"):
            detail = f"from the file alone -> {r.details['local_named']}"
        elif r.details.get("predicted"):
            detail = f"-> {r.details['predicted']}"
        elif r.kind == "rename" and (r.details.get("new") or r.details.get("proposed")):
            detail = f"-> {Path(str(r.details.get('new') or r.details.get('proposed'))).name}"
        elif r.kind == "coverart":
            detail = str(r.details.get("note") or r.details.get("source") or r.reason or "")
        elif r.kind == "subtitles":
            detail = ", ".join(r.details.get("langs") or []) or r.reason
        elif r.output_path is not None and r.output_path.name != name:
            detail = f"-> {r.output_path.name}"
        else:
            detail = r.reason or ""

        table.add_row(name, r.kind, status, detail or "")

    _CONSOLE.print(table)


# =========================
# Windows path safety
# =========================

def win_long_path(p: Path) -> str:
    s = str(p)
    if os.name != "nt" or not CFG.ENABLE_WIN_LONG_PATH_PREFIX:
        return s
    # If already has prefix
    if s.startswith("\\\\?\\"):
        return s
    # For UNC paths
    if s.startswith("\\\\"):
        return "\\\\?\\UNC\\" + s.lstrip("\\")
    # For drive paths
    if re.match(r"^[A-Za-z]:\\", s):
        return "\\\\?\\" + s
    return s


def sanitize_filename(name: str) -> str:
    # Replace invalid Windows characters and normalize whitespace.
    name = re.sub(r'[<>:"/\\|?*]+', " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    # Remove trailing dots/spaces (Windows restriction)
    name = name.rstrip(" .")
    return name


# =========================
# Subprocess wrapper
# =========================

@dataclasses.dataclass
class CmdResult:
    ok: bool
    rc: int
    out: str
    err: str
    cmd: List[str]


def run_cmd(cmd: List[str], timeout_sec: int = 600) -> CmdResult:
    logging.debug("CMD: %s", " ".join(cmd))
    try:
        # Force UTF-8 decoding to avoid Windows cp1252 UnicodeDecodeError on tool output.
        # mkvmerge JSON is UTF-8; other tools are safe with replacement for unexpected bytes.
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
        return CmdResult(ok=(p.returncode == 0), rc=p.returncode, out=p.stdout or "", err=p.stderr or "", cmd=cmd)
    except subprocess.TimeoutExpired as e:
        return CmdResult(ok=False, rc=124, out=(e.stdout or ""), err=f"TimeoutExpired: {e}", cmd=cmd)
    except Exception as e:
        return CmdResult(ok=False, rc=1, out="", err=f"Exception: {e}", cmd=cmd)


def validate_tools(need_propedit: bool = False) -> None:
    required = [CFG.MKVMERGE_EXE]
    if need_propedit:
        required.append(CFG.MKVPROPEDIT_EXE)
    missing = [exe for exe in required if not exe.exists()]
    if missing:
        raise FileNotFoundError(f"Missing MKVToolNix binary(ies): {', '.join(str(p) for p in missing)}")
    logging.info("MKVToolNix mkvmerge: %s", CFG.MKVMERGE_EXE)
    if need_propedit:
        logging.info("MKVToolNix mkvpropedit: %s", CFG.MKVPROPEDIT_EXE)
    if CFG.FILEBOT_EXE.exists():
        logging.info("FileBot: %s (db=%s)", CFG.FILEBOT_EXE, CFG.FILEBOT_DB)
    else:
        logging.info("FileBot: not found (optional) at %s", CFG.FILEBOT_EXE)



# =========================
# FileBot integration (optional)
# =========================

_FILEBOT_TITLE_RX = re.compile(r"^(?P<title>.+?)\s*\((?P<year>\d{4})\)(?:\s*-\s*(?P<imdb>tt\d+)\b)?", re.IGNORECASE)

def parse_title_year_imdb_from_filename(path: Path) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Parse 'Name (Year) - tt1234567' from a filename (best-effort)."""
    m = _FILEBOT_TITLE_RX.search(path.stem)
    if not m:
        return None, None, None
    title = m.group("title").strip()
    year = m.group("year").strip()
    imdb = (m.group("imdb").strip() if m.group("imdb") else None)
    return title, year, imdb

def run_filebot_rename_mkvs(mkvs: List[Path], dry_run: bool) -> List[Path]:
    """
    Run FileBot to normalize movie filename(s) to: {n} ({y})
    Returns updated paths in the same order (matched by file size; hash only if needed).
    """
    if dry_run or not mkvs:
        return mkvs
    if not CFG.FILEBOT_EXE.exists():
        return mkvs

    # FileBot works best when invoked with explicit file list.
    parent_dirs = {p.parent for p in mkvs}
    if len(parent_dirs) != 1:
        # Process one folder at a time; but our movie-group working copies are normally co-located
        logging.debug("FileBot rename skipped (multiple parent dirs): %s", parent_dirs)
        return mkvs
    out_dir = next(iter(parent_dirs))

    before = [(p, p.stat().st_size) for p in mkvs]

    # Plain str() paths: the FileBot launcher cannot locate its bundled JRE when
    # invoked via a \\?\-prefixed path ("bundled JRE missing or corrupted" error).
    cmd = [
        str(CFG.FILEBOT_EXE),
        "-rename",
        *[str(p) for p in mkvs],
        "--db", CFG.FILEBOT_DB,
        "--format", "{n} ({y}) - {imdbid}",
        "--output", str(out_dir),
        "--action", "move",
        "--conflict", "override",
        "-non-strict",
    ]
    r = run_cmd(cmd, timeout_sec=900)
    if not r.ok:
        logging.warning("FileBot rename failed (continuing without FileBot). rc=%s stderr=%s", r.rc, r.err.strip())
        return mkvs

    # Map renamed files back to originals by size (unique in nearly all cases for variant files).
    candidates = list(out_dir.glob("*.mkv"))
    by_size: Dict[int, List[Path]] = {}
    for c in candidates:
        try:
            by_size.setdefault(c.stat().st_size, []).append(c)
        except Exception:
            continue

    resolved: List[Path] = []
    for old_path, old_size in before:
        options = by_size.get(old_size, [])
        if len(options) == 1:
            resolved.append(options[0])
            continue
        if not options:
            # If FileBot didn't touch it (or it moved unexpectedly), fall back
            resolved.append(old_path)
            continue
        # Ambiguous: hash-match (rare)
        try:
            old_hash = sha256_file(old_path)
            match = None
            for opt in options:
                if sha256_file(opt) == old_hash:
                    match = opt
                    break
            resolved.append(match or old_path)
        except Exception:
            resolved.append(old_path)

    return resolved

# Cache to ensure we run FileBot only once per episode output path during a single run
_FILEBOT_TV_RENAMED_CACHE: set[str] = set()

# Global disable switch if FileBot is not runnable (e.g., bundled JRE missing)
_FILEBOT_DISABLED: bool = False


def run_filebot_rename_tv_mkv(mkv: Path, dry_run: bool) -> Path:
    """
    Post-step FileBot rename for a SINGLE TV episode MKV (best-effort).

    Goal: normalize ONLY the *base* TV episode name via FileBot:
        Show (Year) - SxxEyy - Episode Title

    The script will then append the technical suffix derived from MKVToolNix:
        - Res.Codec - [Audio Languages]

    Hardening:
      - runs at most once per episode path (in-process cache)
      - safe fallback if FileBot is missing or fails (returns original path)
      - if FileBot reports missing/corrupt bundled JRE, disable further FileBot attempts for this run
    """
    if dry_run or not mkv or not mkv.exists():
        return mkv

    if not CFG.FILEBOT_EXE.exists():
        return mkv

    global _FILEBOT_DISABLED
    if _FILEBOT_DISABLED:
        return mkv

    # Ensure we only try once per path per run
    try:
        key = str(mkv.resolve()).lower()
    except Exception:
        key = str(mkv).lower()
    if key in _FILEBOT_TV_RENAMED_CACHE:
        return mkv
    _FILEBOT_TV_RENAMED_CACHE.add(key)

    TV_BASE_FORMAT = TV_FILEBOT_FORMAT

    out_dir = mkv.parent
    try:
        before_size = mkv.stat().st_size
    except Exception:
        before_size = None

    # Plain str() paths — FileBot's launcher breaks on \\?\-prefixed paths.
    cmd = [
        str(CFG.FILEBOT_EXE),
        "-rename", str(mkv),
        "--db", "TheTVDB",
        "--format", TV_BASE_FORMAT,
        "--output", str(out_dir),
        "--action", "move",
        "--conflict", "override",
        "-non-strict",
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except Exception as e:
        logging.warning("FileBot TV rename failed to execute: %s", e)
        return mkv

    if proc.returncode != 0:
        out_txt = (proc.stdout or "").strip()
        err_txt = (proc.stderr or "").strip()
        logging.warning("FileBot TV rename failed (rc=%s). STDOUT=%s STDERR=%s",
                        proc.returncode, out_txt, err_txt)

        # Disable further attempts if FileBot itself cannot run due to bundled JRE missing
        if "bundled java runtime environment" in out_txt.lower() and ("missing" in out_txt.lower() or "corrupted" in out_txt.lower()):
            _FILEBOT_DISABLED = True
        return mkv

    # FileBot moved/renamed the file. Find the resulting MKV (best-effort).
    try:
        candidates = sorted(out_dir.glob("*.mkv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if before_size is not None:
            candidates = [p for p in candidates if p.exists() and p.stat().st_size == before_size]
        if candidates:
            new_path = candidates[0]
            try:
                _FILEBOT_TV_RENAMED_CACHE.add(str(new_path.resolve()).lower())
            except Exception:
                _FILEBOT_TV_RENAMED_CACHE.add(str(new_path).lower())
            return new_path
    except Exception:
        pass

    return mkv



# TMDB series id per (show, year), resolved once per run.
_TV_SERIES_ID_CACHE: Dict[str, Optional[int]] = {}
_TV_SERIES_ID_LOCK = threading.Lock()


def _tmdb_search_best(title: str, year: Optional[str], is_tv: bool) -> Optional[int]:
    """
    Search TMDB and return the best id, VERIFYING the year when one is known.

    TMDB's `year` parameter only re-ranks results, it does not filter them: a
    search for 'The Film' with year=2026 still returns the more
    popular 'Franchise: The Film' (2017) first. Taking results[0]
    blindly would attach that film's metadata, poster and IMDB id to an
    unrelated file, so a result whose release year actually matches is
    required — exact first, then ±1 for release-date drift. When a year is
    known and nothing matches it, nothing is returned: another title's data is
    worse than none.
    """
    kind = "tv" if is_tv else "movie"
    date_key = "first_air_date" if is_tv else "release_date"
    url = (f"https://api.themoviedb.org/3/search/{kind}"
           f"?api_key={CFG.TMDB_API_KEY}&query={urllib.parse.quote(title)}")
    if year:
        url += f"&first_air_date_year={year}" if is_tv else f"&year={year}"

    results = (_http_get_json(url) or {}).get("results") or []
    if not results:
        return None
    if not year:
        return results[0].get("id")
    try:
        want = int(year)
    except (TypeError, ValueError):
        return results[0].get("id")

    for tolerance in (0, 1):
        for r in results:
            ry = str(r.get(date_key) or "")[:4]
            if ry.isdigit() and abs(int(ry) - want) <= tolerance and r.get("id"):
                if r is not results[0]:
                    logging.debug("TMDB %s %r (%s): skipped better-ranked %r (%s)",
                                  kind, title, year, results[0].get("title") or results[0].get("name"),
                                  str(results[0].get(date_key) or "")[:4])
                return int(r["id"])

    logging.info("No TMDB %s titled %r from %s — using nothing rather than a different title.",
                 kind, title, year)
    return None


_TV_SERIES_BY_NAME_CACHE: Dict[str, Optional[Tuple[int, Optional[str]]]] = {}


def resolve_tv_series_tmdb_id(show: str, year: Optional[str]) -> Optional[int]:
    """
    Resolve a TV series to its TMDB id by name + first-air year.

    Used when TheTVDB cannot identify a show at all — regional series are often
    on TMDB only (a regional series may have no TheTVDB entry at all), and
    FileBot's fuzzy search would otherwise substitute a same-named show.
    """
    if not CFG.TMDB_API_KEY or not show or not year:
        return None
    key = f"{show.strip().lower()}|{year}"
    with _TV_SERIES_ID_LOCK:
        if key in _TV_SERIES_ID_CACHE:
            return _TV_SERIES_ID_CACHE[key]

    tmdb_id: Optional[int] = None
    try:
        url = (f"https://api.themoviedb.org/3/search/tv?api_key={CFG.TMDB_API_KEY}"
               f"&query={urllib.parse.quote(show)}&first_air_date_year={year}")
        data = _http_get_json(url)
        for r in (data or {}).get("results") or []:
            if (str(r.get("first_air_date") or "")[:4] == str(year)) and r.get("id"):
                tmdb_id = int(r["id"])
                logging.debug("TMDB series resolved: %r (%s) -> %s (%s)",
                              show, year, tmdb_id, r.get("name"))
                break
    except Exception as e:
        logging.debug("TMDB series lookup failed for %r (%s): %s", show, year, e)

    with _TV_SERIES_ID_LOCK:
        _TV_SERIES_ID_CACHE[key] = tmdb_id
    return tmdb_id


def _normalise_title(text: str) -> str:
    """Casefold and drop punctuation so titles compare on their words alone."""
    return re.sub(r"[^0-9a-z]+", " ", (text or "").lower()).strip()


def resolve_tv_series_by_name(show: str) -> Optional[Tuple[int, Optional[str]]]:
    """
    Resolve a series on TMDB by name alone, for releases whose filenames carry
    no year. Returns (tmdb_id, first_air_year) or None.

    An unconstrained search cannot be trusted on ranking — that is how 'Show Name'
    finds 'Show Name Extended' — so only an EXACT title match counts, and only when
    exactly one result matches. Two same-named series with no year to separate
    them is not something this can answer, and it says so rather than picking.
    """
    if not CFG.TMDB_API_KEY or not show:
        return None
    want = _normalise_title(show)
    if not want:
        return None
    key = f"name|{want}"
    with _TV_SERIES_ID_LOCK:
        if key in _TV_SERIES_BY_NAME_CACHE:
            return _TV_SERIES_BY_NAME_CACHE[key]

    found: Optional[Tuple[int, Optional[str]]] = None
    try:
        url = (f"https://api.themoviedb.org/3/search/tv?api_key={CFG.TMDB_API_KEY}"
               f"&query={urllib.parse.quote(show)}")
        results = (_http_get_json(url) or {}).get("results") or []
        exact = [r for r in results
                 if r.get("id") and want in (_normalise_title(r.get("name")),
                                             _normalise_title(r.get("original_name")))]
        if len(exact) == 1:
            air = str(exact[0].get("first_air_date") or "")[:4]
            found = (int(exact[0]["id"]), air if air.isdigit() else None)
            logging.debug("TMDB series resolved by name: %r -> %s (%s)", show, found[0], found[1])
        elif len(exact) > 1:
            logging.info("%d series are titled %r and the filename carries no year — "
                         "not guessing between them.", len(exact), show)
    except Exception as e:
        logging.debug("TMDB series name lookup failed for %r: %s", show, e)

    with _TV_SERIES_ID_LOCK:
        _TV_SERIES_BY_NAME_CACHE[key] = found
    return found


def _filebot_tmdb_tv_cmd(base_cmd: List[str], show: str, year: Optional[str]) -> Optional[List[str]]:
    """
    Build a FileBot command pinned to an exact TMDB series id, for shows
    TheTVDB cannot find. Passing the bare numeric id as --q makes FileBot use
    that series instead of searching by name (a --filter cannot steer the
    search, it only drops candidates the search already produced).
    """
    tmdb_id = resolve_tv_series_tmdb_id(show, year) if year else None
    if not tmdb_id and not year:
        # No year in the filename — fall back to an exact-title match, which is
        # the only unconstrained lookup that can be trusted.
        by_name = resolve_tv_series_by_name(show)
        tmdb_id = by_name[0] if by_name else None
    if not tmdb_id:
        return None
    return [("TheMovieDB::TV" if a == "TheTVDB" else a) for a in base_cmd] + ["--q", str(tmdb_id)]


def _title_with_year_query(query: Optional[str]) -> Optional[str]:
    """
    Reinterpret 'Title (Year)' as a title that ENDS in that year — 'The Film
    (1984)' -> 'The Film 1984'. Returns None when there is no year to fold in.
    """
    if not query:
        return None
    m_year = re.search(r"^(.*?)\s*\((\d{4})\)\s*$", query)
    if not m_year or not m_year.group(1).strip():
        return None
    return f"{m_year.group(1).strip()} {m_year.group(2)}"


def _verified_title_year_retry(query: Optional[str]) -> Optional[Tuple[str, List[str]]]:
    """
    For files whose name carries no release year, the parsed 'year' may really be
    the end of the title ('The.Film.1984.1080p...'). Confirm that reading
    against TMDB before acting on it: the film it finds must itself carry the
    year in its title. Returns (query, year_filter) pinned to that film's real
    year, or None when the reading is wrong.

    The verification matters — an unconstrained search for such a title makes
    FileBot answer with a different entry in the same series.
    """
    merged = _title_with_year_query(query)
    if not merged or not (_FETCH_TAGS_ENABLED and CFG.TMDB_API_KEY):
        return None
    year_token = merged.rsplit(" ", 1)[-1]
    try:
        meta = _get_meta_fetcher().movie_metadata(merged, None, None)
    except Exception:
        return None
    if not meta or year_token not in str(meta.get("title") or ""):
        return None
    real_year = meta.get("year")
    logging.info("Year is part of the title: %r is %s (%s)", merged, meta.get("title"), real_year)
    return merged, _filebot_year_filter(None, CFG.FILEBOT_DB, year=real_year)


def _filebot_year_filter(query: Optional[str], db: str, year: Optional[str] = None) -> List[str]:
    """
    Build a FileBot --filter constraining the match to the title's year (±1 for
    release-date drift). For TV the year is the series' first-air year, which is
    exactly what distinguishes same-named shows.

    Without this, a failed lookup can silently match a same-title film or series
    from a different year (a 2026 film matched as its 1984 namesake, or a
    2026 series matched as a same-named 2024 one).
    """
    y_str = year
    if not y_str and query:
        m_year = re.search(r"\((\d{4})\)", query)
        y_str = m_year.group(1) if m_year else None
    if not y_str:
        return []
    try:
        y = int(y_str)
    except ValueError:
        return []
    return ["--filter", f"y >= {y - 1} && y <= {y + 1}"]


def _normalise_for_match(text: str) -> str:
    """Reduce a title to its letters and digits, so punctuation and case cannot
    make two spellings of the same name look different."""
    return "".join(ch for ch in (text or "") if ch.isalnum()).lower()



# --- Movie identity: pin the rename to one film, or refuse ------------------
# A title search alone cannot identify a film. A common one-word title can
# match a dozen releases of the same year, and the year filter excludes none, so
# whichever the database happens to rank first wins — silently, and the wrong
# answer overwrites the tags too. The IMDB id is the only unambiguous signal,
# so it is resolved here and handed to FileBot as a direct lookup.

# Set by --imdb: identifies the single film in scope, for a title too ambiguous
# to resolve. Applies to whatever the run is scoped to, so the run must be
# narrowed to one film with --filter/--input.
_IMDB_OVERRIDE: Optional[str] = None

# Films a run could not identify, numbered so the choice can be made by number
# instead of by pasting an id. The numbers are WRITTEN DOWN and read back rather
# than recomputed: a later search could rank differently, and then the same
# number would silently mean a different film.
PENDING_IDENTITY_CSV = _SCRIPT_DIR / "logs" / "pending_identity.csv"
_PENDING_IDENTITY: List[Dict[str, Any]] = []
_PENDING_LOCK = threading.Lock()
# Populated from that file by --pick: 'title|year' -> imdb id.
_PICK_SELECTION: Dict[str, str] = {}


def _pending_key(kind: str, title: str, year: Optional[str]) -> str:
    """
    Identify a pending title by what was searched for and its kind, not by path
    — the file that finally gets renamed may be a remux output living somewhere
    else, and 'kind' keeps a film and a show of the same name from colliding.
    """
    if kind == "tv":
        # A show is identified by title alone — its filename year is the season's
        # air year and changes when the file is renamed ('Show' -> 'Show (2026)'),
        # so keying on it would make a pick vanish partway through a run.
        year = None
    return f"{kind}|{(title or '').strip().lower()}|{year or ''}"


def _already_listed(kind: str, title: str, year: Optional[str]) -> List[int]:
    """Numbers already assigned to this title earlier in the run, if any."""
    key = _pending_key(kind, title, year)
    with _PENDING_LOCK:
        return [r["n"] for r in _PENDING_IDENTITY if r["key"] == key]


def _register_pending_candidates(kind: str, src_label: str, title: str, year: Optional[str],
                                 candidates: List[Dict[str, Any]]) -> List[int]:
    """
    Record this title's candidates and return the number shown against each.

    A title already registered this run (its episode 2 hit the same ambiguous
    show as episode 1, say) is not re-added — the numbers already assigned to
    it are returned instead, so the same show does not get renumbered mid-run.
    """
    key = _pending_key(kind, title, year)
    with _PENDING_LOCK:
        existing = [r["n"] for r in _PENDING_IDENTITY if r["key"] == key]
        if existing:
            return existing
        first = len(_PENDING_IDENTITY) + 1
        for c in candidates:
            _PENDING_IDENTITY.append({
                "n": len(_PENDING_IDENTITY) + 1,
                "kind": kind,
                "key": key,
                "file": src_label,
                "id": c.get("id") or "",
                "title": c.get("title") or "",
                "year": c.get("year") or "",
            })
        return list(range(first, first + len(candidates)))


def write_pending_identity() -> int:
    """Persist the numbered candidate list; returns how many films need a choice."""
    if not _PENDING_IDENTITY:
        try:
            PENDING_IDENTITY_CSV.unlink(missing_ok=True)   # nothing outstanding
        except OSError:
            pass
        return 0
    try:
        PENDING_IDENTITY_CSV.parent.mkdir(parents=True, exist_ok=True)
        with open(PENDING_IDENTITY_CSV, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["n", "kind", "key", "file", "id", "title", "year"])
            for row in _PENDING_IDENTITY:
                w.writerow([row["n"], row["kind"], row["key"], row["file"],
                           row["id"], row["title"], row["year"]])
    except OSError as e:
        logging.debug("Could not write %s: %s", PENDING_IDENTITY_CSV.name, e)
    return len({r["key"] for r in _PENDING_IDENTITY})


def load_pick_selection(numbers: List[int]) -> Tuple[Dict[str, str], List[str]]:
    """
    Turn chosen numbers into 'kind|title|year' -> id, using the list as written.

    Returns (selection, problems); problems is empty when every number resolved.
    """
    rows: Dict[int, Dict[str, str]] = {}
    try:
        with open(PENDING_IDENTITY_CSV, "r", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                try:
                    rows[int(row["n"])] = row
                except (TypeError, ValueError):
                    continue
    except OSError:
        return {}, [f"no saved list — run with --dry-run first to produce {PENDING_IDENTITY_CSV.name}"]

    selection: Dict[str, str] = {}
    problems: List[str] = []
    for n in numbers:
        row = rows.get(n)
        if not row:
            problems.append(f"{n} is not in the list (it has {len(rows)} entries)")
            continue
        if not row.get("id"):
            problems.append(f"{n} ({row.get('title')}) has no id — pick another")
            continue
        if row["key"] in selection and selection[row["key"]] != row["id"]:
            problems.append(f"{n} picks a second title for {row.get('title')!r} — one per title")
            continue
        selection[row["key"]] = row["id"]
        logging.info("Pick %d: %s (%s) -> %s", n, row.get("title"), row.get("year"), row["id"])
    return selection, problems


_MOVIE_IMDB_CACHE: Dict[str, Tuple[Optional[str], List[Dict[str, Any]], bool]] = {}
_MOVIE_IMDB_LOCK = threading.Lock()


def _match_key(text: str) -> str:
    """
    Letters and digits only, lowercased, with '&' spelled out.

    Databases and release names disagree on the ampersand ('A & B' vs
    'A.And.B'), and on every kind of punctuation, so both are removed
    from the comparison rather than allowed to defeat it.
    """
    return "".join(ch for ch in (text or "").lower().replace("&", " and ") if ch.isalnum())


def _title_prefix_matches(candidate: str, query: str) -> bool:
    """
    True when a database title begins with the title we inferred, at a word
    boundary. A film's real title is often longer than the release name
    ('The Film' -> 'The Film: A Longer Subtitle'), so an exact comparison is
    wrong here — but the boundary keeps 'The Filmmaker' from matching 'The Film'.
    """
    q, c = _match_key(query), _match_key(candidate)
    if not q or not c.startswith(q):
        return False
    if c == q:
        return True
    # Walk the original title until the matched run ends; the next character
    # decides whether the query landed on a word or inside one.
    seen = 0
    for ch in (candidate or "").lower().replace("&", " and "):
        if ch.isalnum():
            seen += 1
        elif seen >= len(q):
            return True
        if seen == len(q):
            continue
        if seen > len(q):
            return False
    return seen == len(q)


def resolve_movie_imdb_id(title: str, year: Optional[str]
                           ) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """
    Resolve a film to one IMDB id, or report why it could not be.

    Returns (imdb_id, candidates). imdb_id is set only when exactly one film
    survives; otherwise it is None and candidates lists what remained, so the
    caller can show the user what to choose between instead of guessing.
    """
    imdb_id, candidates, _answered = _resolve_movie_tmdb(title, year)
    return imdb_id, candidates


def _resolve_movie_tmdb(title: str, year: Optional[str]
                        ) -> Tuple[Optional[str], List[Dict[str, Any]], bool]:
    """
    TMDB step of the film chain: (imdb_id, candidates, answered).

    'answered' is False when TMDB could not be asked at all (no key, no network).
    Nothing found and nothing asked look the same in (None, []), but only the
    first is evidence that the title is absent — the second must not be treated
    as permission to fall back to anything.
    """
    if not CFG.TMDB_API_KEY or not title:
        return None, [], False
    key = f"{title.strip().lower()}|{year or ''}"
    with _MOVIE_IMDB_LOCK:
        if key in _MOVIE_IMDB_CACHE:
            return _MOVIE_IMDB_CACHE[key]

    imdb_id: Optional[str] = None
    candidates: List[Dict[str, Any]] = []
    answered = False
    try:
        url = (f"https://api.themoviedb.org/3/search/movie?api_key={CFG.TMDB_API_KEY}"
               f"&query={urllib.parse.quote(title)}")
        if year:
            url += f"&year={year}"
        reply = _http_get_json(url)
        answered = reply is not None
        results = (reply or {}).get("results") or []

        # Year first: it is a hard constraint, not a ranking hint.
        if year and str(year).isdigit():
            want = int(year)
            in_year = []
            for r in results:
                ry = str(r.get("release_date") or "")[:4]
                if ry.isdigit() and abs(int(ry) - want) <= 1:
                    in_year.append(r)
            results = in_year

        exact = [r for r in results
                 if _match_key(r.get("title")) == _match_key(title)
                 or _match_key(r.get("original_title")) == _match_key(title)]
        prefix = [r for r in results if _title_prefix_matches(str(r.get("title") or ""), title)]

        chosen = exact[0] if len(exact) == 1 else (prefix[0] if len(prefix) == 1 else None)
        pool = exact if len(exact) > 1 else prefix
        # Carry each candidate's IMDB id: two films can share a title AND a year,
        # so a list of names alone would not tell the user which to pick.
        candidates = []
        for r in pool[:5]:
            ids = _http_get_json(f"https://api.themoviedb.org/3/movie/{r.get('id')}"
                                 f"/external_ids?api_key={CFG.TMDB_API_KEY}") or {}
            tt = str(ids.get("imdb_id") or "").strip()
            iso1 = str(r.get("original_language") or "").strip()
            resolved_tt = tt if re.fullmatch(r"tt\d{7,10}", tt) else ""
            candidates.append({
                "title": str(r.get("title") or "?"),
                "year": str(r.get("release_date") or "")[:4],
                "released": str(r.get("release_date") or ""),
                "imdb": resolved_tt,
                "id": resolved_tt,     # generic field the shared pending-list code reads
                "tmdb": r.get("id"),
                "lang": resolve_language(iso1) if iso1 else None,
                "original_title": str(r.get("original_title") or ""),
                "overview": " ".join(str(r.get("overview") or "").split()),
            })

        if chosen and chosen.get("id"):
            data = _http_get_json(
                f"https://api.themoviedb.org/3/movie/{chosen['id']}/external_ids"
                f"?api_key={CFG.TMDB_API_KEY}")
            got = str((data or {}).get("imdb_id") or "").strip()
            if re.fullmatch(r"tt\d{7,10}", got):
                imdb_id = got
                candidates = []
                logging.info("Identified %r (%s) as %s — %s", title, year or "no year",
                             chosen.get("title"), imdb_id)
    except Exception as e:
        logging.debug("Movie identity lookup failed for %r (%s): %s", title, year, e)

    # A failed lookup is not cached: the next file in the run may reach TMDB.
    if answered:
        with _MOVIE_IMDB_LOCK:
            _MOVIE_IMDB_CACHE[key] = (imdb_id, candidates, answered)
    return imdb_id, candidates, answered


def file_audio_languages(mkv: Path) -> Set[str]:
    """Canonical languages of a file's audio tracks, for narrowing candidates."""
    try:
        tracks = extract_tracks(mkv, mkvmerge_identify_json(mkv))
    except Exception:
        return set()
    langs: Set[str] = set()
    for t in tracks:
        if t.type != "audio":
            continue
        raw = (t.language or "").lower()
        canon = resolve_language(raw) if raw and raw != "und" else detect_language_canonical(t)
        if canon:
            langs.add(canon)
    return langs


def _report_movie_candidates(src: Path, title: str, year: Optional[str],
                             candidates: List[Dict[str, Any]], own_langs: Set[str]) -> List[int]:
    """
    Print the films a title matched, richest signal first.

    A list of names cannot be chosen between — two films share a title and a
    year often enough that it happens on an ordinary library. Everything shown
    here already came back with the search, so it costs nothing extra: the
    language a film was made in usually settles it on its own, especially when
    it matches a language the file itself carries.
    """
    earlier = _already_listed("movie", title, year)
    if earlier:
        # A film passes through several steps in one run (identity gate, cover
        # art, ...). Listing every candidate again each time buries the output.
        logging.warning("Cannot identify %s — same candidates as listed above: %s.",
                        src.name, ", ".join(f"[{n}]" for n in earlier))
        return earlier
    logging.warning("Cannot identify %s — %d films match %r (%s).",
                    src.name, len(candidates), title, year or "no year")
    if own_langs:
        logging.warning("    This file's audio: %s",
                        ", ".join(sorted(language_display(c) for c in own_langs)))
    numbers = _register_pending_candidates("movie", src.name, title, year, candidates)
    for i, c in zip(numbers, candidates):
        hit = " <- matches this file's audio" if c.get("lang") in own_langs else ""
        logging.warning("    [%d] %s (%s)  %s%s", i, c["title"], c["year"] or "?",
                        language_display(c["lang"]) if c.get("lang") else "language unknown", hit)
        link = (f"https://www.imdb.com/title/{c['imdb']}/" if c.get("imdb")
                else f"https://www.themoviedb.org/movie/{c.get('tmdb')}")
        logging.warning("       %-12s %s", c.get("imdb") or "(no IMDB id)", link)
        if c.get("original_title") and _match_key(c["original_title"]) != _match_key(c["title"]):
            logging.warning("       original title: %s", c["original_title"])
        if c.get("overview"):
            logging.warning("       %s", c["overview"][:120] + ("..." if len(c["overview"]) > 120 else ""))
    best = next((n for n, c in zip(numbers, candidates) if c.get("imdb")), numbers[0])
    logging.warning("    -> choose one of these with --pick, e.g. --pick %d", best)
    return numbers


# OMDb's free tier allows about a thousand requests a day, and one film can be
# identified several times in a run (rename, tags, cover art), so answers are kept.
_OMDB_SEARCH_CACHE: Dict[str, List[Dict[str, Any]]] = {}
_OMDB_SEARCH_LOCK = threading.Lock()


def _omdb_search_movies(title: str, year: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    """
    Films OMDb lists under a title, or None when OMDb could not be asked.

    OMDb's year filter is exact, so a release-date drift of one year (the same
    tolerance the TMDB step allows) takes three small queries instead of one.
    """
    if not CFG.OMDB_API_KEY or not title:
        return None
    key = f"{title.strip().lower()}|{year or ''}"
    with _OMDB_SEARCH_LOCK:
        if key in _OMDB_SEARCH_CACHE:
            return _OMDB_SEARCH_CACHE[key]
    years: List[Optional[str]] = [None]
    if year and str(year).isdigit():
        years = [str(int(year) + d) for d in (0, -1, 1)]
    found: Dict[str, Dict[str, Any]] = {}
    answered = False
    for y in years:
        url = (f"https://www.omdbapi.com/?s={urllib.parse.quote(title)}&type=movie"
               f"&apikey={CFG.OMDB_API_KEY}" + (f"&y={y}" if y else ""))
        reply = _http_get_json(url)
        if reply is None:
            continue
        answered = True
        for r in reply.get("Search") or []:
            tt = str(r.get("imdbID") or "")
            if re.fullmatch(r"tt\d{7,10}", tt):
                found[tt] = r
    if not answered:
        return None        # not cached: the next film may reach OMDb
    result = list(found.values())
    with _OMDB_SEARCH_LOCK:
        _OMDB_SEARCH_CACHE[key] = result
    return result


def _resolve_movie_omdb(title: str, year: Optional[str]
                        ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], bool]:
    """
    OMDb step of the film chain: (film, candidates, answered).

    Held to the same standard as the TMDB step: the year must be within one, and
    exactly one film must carry the title — exactly, or as a whole-word prefix.
    'film' carries OMDb's own title and year, which the rename then uses.
    """
    rows = _omdb_search_movies(title, year)
    if rows is None:
        return None, [], False
    if year and str(year).isdigit():
        want = int(year)
        rows = [r for r in rows
                if str(r.get("Year") or "")[:4].isdigit()
                and abs(int(str(r["Year"])[:4]) - want) <= 1]
    exact = [r for r in rows if _match_key(r.get("Title")) == _match_key(title)]
    prefix = [r for r in rows if _title_prefix_matches(str(r.get("Title") or ""), title)]
    if len(exact) == 1:
        return exact[0], [], True
    if not exact and len(prefix) == 1:
        return prefix[0], [], True
    pool = exact if len(exact) > 1 else prefix
    candidates = [{
        "title": str(r.get("Title") or "?"),
        "year": str(r.get("Year") or "")[:4],
        "imdb": str(r["imdbID"]),
        "id": str(r["imdbID"]),
        "tmdb": None,
        "lang": None,
        "original_title": "",
        "overview": "",
    } for r in pool[:5]]
    return None, candidates, True


@dataclasses.dataclass
class MovieIdentity:
    """
    The outcome of identifying a film.

    status: 'found' (imdb is set), 'ambiguous' (several films fit — a person must
    choose), 'none' (every source that could be asked found nothing) or
    'unavailable' (no source could be asked at all). Only 'none' may lead to a
    name built from the file alone; the others leave the file as it is.
    """
    imdb: Optional[str] = None
    source: str = ""          # TMDB | OMDb | file | pick | command line
    status: str = "none"
    reason: str = ""
    title: Optional[str] = None   # the database's own title (OMDb results only)
    year: Optional[str] = None


def movie_identity_chain(src: Path, title: str, year: Optional[str],
                         known_imdb: Optional[str],
                         own_langs: Optional[Set[str]] = None) -> MovieIdentity:
    """
    Identify a film through the source chain: TMDB, then OMDb.

    A source is passed over only when it found NOTHING. If it found several films
    the chain stops there and asks — another database would only add more
    guesses. An id already carried by the filename, folder or tags is trusted
    as-is: it costs nothing and is exactly what a previous run established.
    """
    if _IMDB_OVERRIDE:
        logging.info("Using the IMDB id given on the command line for %s: %s",
                     src.name, _IMDB_OVERRIDE)
        return MovieIdentity(imdb=_IMDB_OVERRIDE, source="command line", status="found")
    picked = _PICK_SELECTION.get(_pending_key("movie", title, year))
    if picked:
        logging.info("Using your pick for %s: %s", src.name, picked)
        return MovieIdentity(imdb=picked, source="pick", status="found")
    if known_imdb and re.fullmatch(r"tt\d{7,10}", known_imdb):
        logging.debug("Using IMDB id from the file itself: %s", known_imdb)
        return MovieIdentity(imdb=known_imdb, source="file", status="found")

    tmdb_imdb, candidates, tmdb_answered = _resolve_movie_tmdb(title, year)
    if tmdb_imdb:
        return MovieIdentity(imdb=tmdb_imdb, source="TMDB", status="found")

    sources = ["TMDB"] if tmdb_answered else []
    if not candidates:
        film, candidates, omdb_answered = _resolve_movie_omdb(title, year)
        if omdb_answered:
            sources.append("OMDb")
        if film:
            logging.info("Identified %r (%s) as %s (%s) — %s, via OMDb (TMDB has no match)",
                         title, year or "no year", film.get("Title"), film.get("Year"),
                         film.get("imdbID"))
            return MovieIdentity(imdb=str(film["imdbID"]), source="OMDb", status="found",
                                 title=str(film.get("Title") or "") or None,
                                 year=str(film.get("Year") or "")[:4] or None)

    if candidates:
        langs = own_langs if own_langs is not None else file_audio_languages(src)
        # Films made in a language this file actually carries come first: that is
        # the strongest hint available, but it only ORDERS the list — the choice
        # stays with the user, because a dubbed release would defeat it.
        candidates = sorted(candidates, key=lambda c: 0 if c.get("lang") in langs else 1)
        numbers = _report_movie_candidates(src, title, year, candidates, langs)
        # The table is what most people read, and the numbers are the actionable
        # part — lead with them rather than leaving them only in the log above.
        listed = "; ".join(
            f"[{n}] {c['title']} ({c['year']})"
            + (f" {language_display(c['lang'])}" if c.get("lang") else "")
            for n, c in list(zip(numbers, candidates))[:4])
        return MovieIdentity(status="ambiguous", reason=f"pick one — {listed}")

    if not sources:
        why = "no database could be reached (check the API keys and the network)"
        logging.warning("Cannot identify %s: %s.", src.name, why)
        return MovieIdentity(status="unavailable", reason=why)

    tried = " and ".join(sources)
    logging.warning("Cannot identify %s: nothing matches %r (%s) on %s.",
                    src.name, title, year or "no year", tried)
    return MovieIdentity(status="none",
                         reason=f"no film matches {title!r} ({year or 'no year'}) on {tried}")


def movie_identity_for_rename(src: Path, title: str, year: Optional[str],
                              known_imdb: Optional[str],
                              own_langs: Optional[Set[str]] = None) -> Tuple[Optional[str], str]:
    """The IMDB id to pin this film's rename to, or a reason it cannot be renamed."""
    ident = movie_identity_chain(src, title, year, known_imdb, own_langs)
    return ident.imdb, ("" if ident.imdb else ident.reason)


def _filebot_series_name_filter(year_filter: List[str], show: str, db: str) -> List[str]:
    """
    Extend a FileBot --filter so the matched SERIES must be the one we asked for.

    FileBot's fuzzy search happily answers a query for 'Show Name' with 'Show Name Extended'
    — a different 2026 series, so the year constraint cannot separate them — and
    the rename then succeeds with the wrong show's episode titles. A --filter
    cannot steer the search, but it drops candidates the search produced: with
    no candidate left the attempt fails and the TMDB series-id fallback takes
    over, which resolves the series by exact title.

    TheTVDB's own name may carry a disambiguating suffix ('Show Name (2024)',
    'Some Show (US)'), so a trailing parenthetical is stripped before
    comparing. TV only — this is about series identity.
    """
    if db not in ("TheTVDB", "TVmaze"):
        return year_filter
    want = _normalise_for_match(re.sub(r"\s*\([^)]*\)\s*$", "", show or ""))
    if not want:
        return year_filter
    name_expr = (r"(n ?: '').replaceAll(/\s*\([^)]*\)\s*$/, '')"
                 r".replaceAll(/[^\p{L}\p{N}]/, '').toLowerCase() == '" + want + "'")
    if year_filter:
        return ["--filter", f"({year_filter[1]}) && {name_expr}"]
    return ["--filter", name_expr]


def _filebot_skipped_as_already_correct(out_txt: str) -> bool:
    """
    True when FileBot's only "failure" was that the file already carries the
    name it would be renamed to.

    FileBot reports `[MOVE] Skipped [X] because [X] already exists` and exits
    non-zero, which is indistinguishable from a real failure by return code —
    but source and destination being the same path means the work was already
    done, not that it could not be done.
    """
    m = re.search(r"Skipped \[(.+)\] because \[(.+)\] already exists", out_txt or "")
    if not m:
        return False
    return os.path.normcase(m.group(1).strip()) == os.path.normcase(m.group(2).strip())


def _filebot_unreachable(*texts: str) -> bool:
    """
    True when FileBot's output says it could not reach a database at all.

    'Found nothing' and 'could not ask' both end in a failed lookup, but only the
    first is evidence that a title is absent. Treating a network outage as
    absence would hand every file in the run a name built from itself.
    """
    blob = "\n".join(t or "" for t in texts)
    return bool(re.search(
        r"(?i)unknownhost|connectexception|connect(?:ion)? (?:refused|timed out|reset)|"
        r"unable to establish|socketexception|sockettimeout|sslhandshake|no route to host|"
        r"network is unreachable|http(?:s)? (?:response )?code:? ?(?:5\d\d|429)|"
        r"server returned http response code: (?:5\d\d|429)", blob))


def _filebot_failure_reason(out_txt: str, err_txt: str, rc: Optional[int], db: str) -> str:
    """Condense FileBot's output into one line fit for the summary table."""
    blob = "\n".join((out_txt or "", err_txt or ""))
    for pattern, message in (
        (r"(?i)Invalid Lookup: TVDB ID not found \[(\d+)\]", "{db} entry is broken (id {0})"),
        (r"(?i)No episode data: \[(.+?)\]", "{db} has no episode data for '{0}'"),
        (r"(?i)because \[.+?\] already exists", "target name already in use"),
        (r"(?i)bundled java runtime environment", "FileBot's bundled Java is missing or corrupted"),
    ):
        m = re.search(pattern, blob)
        if m:
            return message.format(*m.groups(), db=db)
    return f"{db} lookup failed (rc={rc})"


def _with_rename_outcome(details: Dict[str, Any], outcome: Dict[str, Any]) -> Dict[str, Any]:
    """Attach a failed rename's reason — or a name built from the file alone — to a task's details."""
    if outcome.get("ok") is False:
        details = {**details, "rename_failed": outcome.get("reason") or "rename failed"}
    elif outcome.get("local"):
        details = {**details, "local_named": outcome.get("local_name") or "yes"}
    return details


def run_filebot_rename_final_mkv(
    mkv: Path,
    *,
    db: str,
    filebot_format: str,
    dry_run: bool,
    query: Optional[str] = None,
    imdb_id: Optional[str] = None,
    outcome: Optional[Dict[str, Any]] = None,
) -> Path:
    """
    Run FileBot rename for a SINGLE MKV, writing result into the same directory.
    Best-effort: returns original path on failure.

    query:   clean movie/show title passed as --query to FileBot so it doesn't try to
             parse the (potentially noisy) release filename for the DB lookup.
    outcome: optional dict filled in with {'ok': bool, 'reason': str}. The return
             value alone cannot tell "renamed to the same name" from "rename
             failed", which used to let a failed rename be reported as OK.
    """
    def _record(ok: bool, reason: str = "") -> None:
        if outcome is not None:
            outcome["ok"] = ok
            outcome["reason"] = reason
    if dry_run or not mkv or not mkv.exists():
        return mkv
    if not CFG.FILEBOT_EXE.exists():
        return mkv

    global _FILEBOT_DISABLED
    if _FILEBOT_DISABLED:
        return mkv

    out_dir = mkv.parent

    try:
        before_size = mkv.stat().st_size
    except Exception:
        before_size = None

    # Plain str() paths — FileBot's launcher breaks on \\?\-prefixed paths.
    filebot_format = _pin_resolution_in_format(filebot_format, mkv)
    base_cmd = [
        str(CFG.FILEBOT_EXE),
        "-rename", str(mkv),
        "--db", db,
        "--format", filebot_format,
        "--output", str(out_dir),
        "--action", "move",
        "--conflict", "override",
        "-non-strict",
    ]
    # For TV the query carries the series year ('Show Name (2026)'): search on the
    # bare name and use the year as a constraint instead.
    is_tv_db = (db == "TheTVDB")
    show_year: Optional[str] = None
    search_q = query
    if is_tv_db and query:
        # Handles 'Show (2026)' and a bare 'Show 2026' alike — missing the
        # second form left the lookup unconstrained and unrescuable.
        bare, show_year = split_show_year(query)
        search_q = bare or query

    # Year constraint: stops a same-title film/series from another year winning
    # when the title match is imperfect. ±1 absorbs release-date drift.
    # Pass the year we resolved above: re-parsing `query` here would miss a bare
    # 'Show 2026' label and leave the attempt unconstrained by year.
    year_filter = _filebot_year_filter(query, db, year=show_year if is_tv_db else None)

    # A series must be identified before it may be renamed. A title search —
    # even with a year and a name filter — can still land on a different show
    # (the name filter ignores punctuation, so 'Name!' passes for 'Name', and a
    # filename with no year has no year to filter on). When more than one series
    # shares the exact title the file is left alone; otherwise the series id is
    # handed to FileBot as a direct lookup.
    tv_pin: Optional[int] = None
    if is_tv_db and search_q:
        tv_pin, tv_blocked = tv_identity_for_rename(mkv.name, search_q, show_year)
        if tv_blocked:
            logging.warning("Not renaming %s — %s", mkv.name, tv_blocked)
            _record(False, tv_blocked)
            return mkv

    # Override FileBot's filename-based search with a clean title so junk
    # in the original filename doesn't corrupt the DB lookup result.
    # An IMDB id identifies the title outright: FileBot resolves 'ttNNNNNNN' as a
    # direct lookup rather than a search, so no filter and no fallback can apply
    # — and none should, since a fallback could only substitute a different film.
    pinned = (bool(imdb_id) and not is_tv_db) or bool(tv_pin)
    if tv_pin:
        logging.debug("FileBot pinned to series tmdb:%s: %s", tv_pin, mkv.name)
        r = None
        for n, cmd in enumerate(pinned_tv_commands(base_cmd, tv_pin)):
            if n:
                logging.info("TheTVDB could not serve the series — using the TMDB entry "
                             "instead: %s", mkv.name)
            r = run_cmd(cmd, timeout_sec=1200)
            # 'already named' exits non-zero but is a success; a second source
            # would only say the same thing.
            if r.ok or _filebot_skipped_as_already_correct(r.out or ""):
                break
    elif pinned:
        logging.debug("FileBot pinned to %s: %s", imdb_id, mkv.name)
        r = run_cmd(base_cmd + ["--q", str(imdb_id)], timeout_sec=1200)
    else:
        # The name constraint goes only on the attempt that carries our query. The
        # later "retry without query" exists for when our inferred title is wrong,
        # so constraining it by that same title would defeat it.
        match_filter = _filebot_series_name_filter(year_filter, search_q or "", db)
        cmd = base_cmd + (["--q", search_q] if search_q else []) + match_filter
        if search_q:
            logging.debug("FileBot query override: %s", search_q)
        r = run_cmd(cmd, timeout_sec=1200)

    if not r.ok and not pinned and mkv.exists():
        tmdb_cmd = (_filebot_tmdb_tv_cmd(base_cmd, search_q or "", show_year)
                    if is_tv_db and search_q else None)
        if tmdb_cmd:
            # TheTVDB could not identify the series, or holds a broken entry for
            # it. Resolve it on TMDB and pin FileBot to that exact series id.
            logging.info("TheTVDB could not identify %s (%s) — using the TMDB series entry "
                         "instead: %s", search_q, show_year or "no year", mkv.name)
            r = run_cmd(tmdb_cmd, timeout_sec=1200)
        elif query:
            # The 'year' may actually be part of the title ('The Film 1984')
            # when the filename carries no release year. Try that reading before
            # giving up — the constrained attempt has already failed, so this
            # cannot mask a wrong-year match.
            retry = _verified_title_year_retry(query)
            if retry:
                merged_q, merged_filter = retry
                logging.info("Retrying as %r: %s", merged_q, mkv.name)
                r = run_cmd(base_cmd + ["--q", merged_q] + merged_filter, timeout_sec=1200)

            if not r.ok and not is_tv_db:
                # Our inferred title can itself be wrong (odd release naming), and
                # then the query is what blocks the match. Retry once letting FileBot
                # parse the filename — still year-constrained, so a wrong-year title
                # is never chosen silently.
                #
                # Never for a series: with no name to hold it to, FileBot's own parse
                # of a title nothing matches lands on whichever show it finds
                # ('Some.Unknown.Show.S01E01' became an unrelated 2024 series). A
                # series that cannot be identified is left unrenamed instead.
                logging.info("FileBot found no match for query %r — retrying without query%s: %s",
                             query, " (year-constrained)" if year_filter else "", mkv.name)
                r = run_cmd(base_cmd + year_filter, timeout_sec=1200)

    # Third source for a series: TVmaze, held to the same series-name check as
    # TheTVDB. Only when the earlier sources found nothing — not when they could
    # not be reached.
    if (not r.ok and not pinned and is_tv_db and search_q and mkv.exists()
            and not _filebot_unreachable(r.out, r.err)):
        logging.info("TheTVDB and TMDB could not identify %s — trying TVmaze: %s",
                     search_q, mkv.name)
        tvmaze_cmd = ([("TVmaze" if a == "TheTVDB" else a) for a in base_cmd]
                      + ["--q", search_q]
                      + _filebot_series_name_filter(year_filter, search_q, "TVmaze"))
        r = run_cmd(tvmaze_cmd, timeout_sec=1200)

    out_txt = (r.out or "").strip()
    err_txt = (r.err or "").strip()

    if (not r.ok and not pinned and is_tv_db and CFG.LOCAL_NAME_FALLBACK and mkv.exists()
            and not _filebot_skipped_as_already_correct(out_txt)
            and not _filebot_unreachable(out_txt, err_txt)
            and "lookup failed" in _filebot_failure_reason(out_txt, err_txt, r.rc, db)):
        # Every source found nothing: name the episode from its own file.
        local = rename_tv_from_file(
            mkv, f"no database knows {search_q!r} (TheTVDB, TMDB, TVmaze)",
            outcome if outcome is not None else {})
        if local is not None:
            return local

    if not r.ok:
        logging.warning("FileBot rename failed (db=%s, rc=%s).", db, r.rc)
        if out_txt:
            logging.warning("FileBot STDOUT: %s", out_txt)
        if err_txt:
            logging.warning("FileBot STDERR: %s", err_txt)

        # Disable further attempts if FileBot itself cannot run due to bundled JRE missing
        if "bundled java runtime environment" in out_txt.lower() and ("missing" in out_txt.lower() or "corrupted" in out_txt.lower()):
            _FILEBOT_DISABLED = True
        if _filebot_skipped_as_already_correct(out_txt):
            logging.info("Already named as the database would name it: %s", mkv.name)
            _record(True)
        else:
            _record(False, _filebot_failure_reason(out_txt, err_txt, r.rc, db))
        return mkv

    # Log what FileBot actually did so the user can see it
    if out_txt:
        logging.info("FileBot (db=%s): %s", db, out_txt)

    # Find resulting MKV (best-effort: same size, most recent)
    try:
        candidates = sorted(out_dir.glob("*.mkv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if before_size is not None:
            candidates = [p for p in candidates if p.exists() and p.stat().st_size == before_size]
        if candidates:
            _record(True)
            return candidates[0]
    except Exception:
        pass

    _record(True)
    return mkv

def mkvmerge_identify_json(mkv_path: Path) -> Dict[str, Any]:
    cmd = [win_long_path(CFG.MKVMERGE_EXE), "-J", win_long_path(mkv_path)]
    r = run_cmd(cmd, timeout_sec=300)
    if not r.ok:
        raise RuntimeError(f"mkvmerge -J failed rc={r.rc}: {r.err.strip()}")
    try:
        return json.loads(r.out)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse mkvmerge JSON for {mkv_path}: {e}")


# =========================
# Hashing & in-place remux helpers
# =========================

def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _container_duration_s(meta: Dict[str, Any]) -> Optional[float]:
    dur = ((meta.get("container") or {}).get("properties") or {}).get("duration")
    try:
        return float(dur) / 1_000_000_000.0 if dur else None  # mkvmerge reports ns
    except (TypeError, ValueError):
        return None


def verify_remux_output(out_tmp: Path, ref_file: Path,
                        expected_audio: int, expected_subs: int) -> Tuple[bool, str]:
    """
    Safety gate before an --inplace swap: the freshly-merged output must contain
    exactly the selected tracks and match the reference video source's duration
    (±2% or ±2s). On any doubt the caller keeps the sources and discards the tmp.
    """
    try:
        if not out_tmp.exists() or out_tmp.stat().st_size < 4096:
            return False, "output missing or implausibly small"
        meta = mkvmerge_identify_json(out_tmp)
        kinds = [str(t.get("type")) for t in meta.get("tracks", [])]
        n_video, n_audio, n_subs = kinds.count("video"), kinds.count("audio"), kinds.count("subtitles")
        if n_video != 1 or n_audio != expected_audio or n_subs != expected_subs:
            return False, (f"track mismatch: got video={n_video} audio={n_audio} subs={n_subs}, "
                           f"expected video=1 audio={expected_audio} subs={expected_subs}")
        out_dur = _container_duration_s(meta)
        ref_dur = _container_duration_s(mkvmerge_identify_json(ref_file))
        if out_dur and ref_dur:
            if abs(out_dur - ref_dur) > max(2.0, ref_dur * 0.02):
                return False, f"duration mismatch: output {out_dur:.1f}s vs source {ref_dur:.1f}s"
        return True, "ok"
    except Exception as e:
        return False, f"verification error: {e}"


def finalize_inplace(sources: List[Path], out_tmp: Path, out_final: Path, backup: bool) -> None:
    """
    Complete an --inplace remux: back up (as *.original.mkv) or delete every
    consumed source, then move the verified output onto its final name.
    Only called AFTER verify_remux_output has passed.
    """
    for s in sources:
        if not s.exists():
            continue
        if backup:
            b = s.with_suffix(".original.mkv")
            if b.exists():
                b.unlink()  # stale backup from an earlier run
            os.replace(win_long_path(s), win_long_path(b))
            logging.info("Original backed up: %s", b.name)
        else:
            s.unlink()
            logging.info("Original deleted (consumed by merge): %s", s.name)
    out_final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(win_long_path(out_tmp), win_long_path(out_final))


# =========================
# Scanning & grouping
# =========================

def scan_mkvs(root: Path) -> List[Path]:
    if not root.exists():
        logging.warning("Root not found (skipping): %s", root)
        return []
    out: List[Path] = []
    for p in root.rglob("*.mkv"):
        # *.original.mkv are --inplace --backup safety copies — never process them.
        if p.is_file() and not p.name.lower().endswith(".original.mkv"):
            out.append(p)
    return out


def matches_filters(mkv: Path, root: Path, patterns: Optional[List[str]]) -> bool:
    """
    Case-insensitive glob match for --filter. A file is included when ANY
    pattern matches its filename OR its first folder component under the scan
    root (movie folder / show folder). No patterns -> everything matches.
    """
    if not patterns:
        return True
    candidates = [mkv.name.lower()]
    try:
        rel = mkv.relative_to(root)
        if len(rel.parts) > 1:
            candidates.append(rel.parts[0].lower())
    except ValueError:
        pass
    return any(fnmatch.fnmatchcase(c, pat.lower()) for pat in patterns for c in candidates)


def apply_scan_filters(files: List[Path], root: Path,
                       patterns: Optional[List[str]], mode: str) -> List[Path]:
    """Apply --filter patterns to a scan result, logging how many survived."""
    if not patterns:
        return files
    kept = [f for f in files if matches_filters(f, root, patterns)]
    logging.info("%s - filter %s: %d of %d MKV(s) match.", mode, patterns, len(kept), len(files))
    return kept


_MOVIE_NOISE_TOKENS = re.compile(
    r"(?i)\b(2160p|1440p|1080p|720p|480p|x265|x264|hevc|h265|h264|avc|hdr10\+?|dv|dolby\.?vision|remux|bluray|brrip|webrip|web[- ]dl|hdr|aac|ac3|eac3|dts|truehd|atmos)\b"
)

_YEAR_RE = re.compile(r"\((19\d{2}|20\d{2})\)|\b(19\d{2}|20\d{2})\b")
# Accepts compact and separated forms: S01E02, S01.E02, S01 E02, S01-E02
_SEASON_EP_RE = re.compile(r"(?i)\bS(\d{1,2})\s*[.\-_ ]?\s*E(\d{1,2})\b")


def normalize_for_similarity(name: str) -> str:
    """
    Normalize movie filenames for similarity grouping.

    Goals:
    - Group multi-audio variants together (e.g., [Telugu] vs [Hindi + Malayalam + Kannada]).
    - Ignore bracketed language/metadata, IMDb ids, and common release tokens.
    """
    base = Path(name).stem
    base = base.replace(".", " ").replace("_", " ")

    # Drop bracket groups: [ ... ] (languages, tags, groups)
    base = re.sub(r"\[[^\]]*\]", " ", base)

    # Drop IMDb ids like tt1234567
    base = re.sub(r"(?i)\btt\d{6,9}\b", " ", base)

    # Remove common noise tokens & year tokens
    base = _MOVIE_NOISE_TOKENS.sub(" ", base)
    base = _YEAR_RE.sub(" ", base)

    # Remove language words (helps grouping when brackets weren't present)
    base = re.sub(r"(?i)\b(telugu|telegu|tamil|hindi|english|malayalam|kannada|multi)\b", " ", base)

    base = re.sub(r"\s+", " ", base).strip().lower()
    return base



def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


# Persistent movie identity cache: path -> resolved IMDB/TMDB id. Lets repeat
# runs group variant releases without paying for database lookups again.
MOVIE_IDENTITY_CSV = _SCRIPT_DIR / "logs" / "movie_identity.csv"


class IdentityCache:
    """Thread-safe path -> (size, identity key) store, persisted as CSV."""

    def __init__(self, csv_path: Path = MOVIE_IDENTITY_CSV) -> None:
        self._csv_path = csv_path
        self._lock = threading.Lock()
        self._entries: Dict[str, Tuple[int, str]] = {}
        self._dirty = False
        self._load()

    def _load(self) -> None:
        import csv
        if not self._csv_path.exists():
            return
        try:
            with self._csv_path.open("r", newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    try:
                        self._entries[str(row["path"]).lower()] = (int(row["size"]), str(row["identity"]))
                    except (KeyError, TypeError, ValueError):
                        continue
            logging.debug("Identity cache loaded: %d entries", len(self._entries))
        except Exception as e:
            logging.warning("Could not read identity cache (starting fresh): %s", e)

    def get(self, mkv: Path) -> Optional[str]:
        with self._lock:
            entry = self._entries.get(str(mkv).lower())
        if not entry:
            return None
        try:
            return entry[1] if mkv.stat().st_size == entry[0] else None
        except OSError:
            return None

    def add(self, mkv: Path, identity: str) -> None:
        try:
            size = mkv.stat().st_size
        except OSError:
            return
        with self._lock:
            self._entries[str(mkv).lower()] = (size, identity)
            self._dirty = True

    def save(self) -> None:
        import csv
        with self._lock:
            if not self._dirty:
                return
            entries = dict(self._entries)
        kept = {p: v for p, v in entries.items() if Path(p).exists()}
        try:
            self._csv_path.parent.mkdir(parents=True, exist_ok=True)
            with self._csv_path.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["path", "size", "identity"])
                for p, (size, ident) in sorted(kept.items()):
                    w.writerow([p, size, ident])
            logging.debug("Identity cache saved: %d entries", len(kept))
        except Exception as e:
            logging.warning("Could not save identity cache (non-fatal): %s", e)


def resolve_movie_identity(mkv: Path, cache: Optional[IdentityCache],
                           allow_lookup: bool) -> Optional[str]:
    """
    Resolve a stable identity key ('tt1234567' or 'tmdb:123456') for a movie.

    Staged, cheapest first:
      1. cache hit (size-verified)
      2. IMDB id already in the filename, a parent folder, or the MKV's tags — free
      3. TMDB lookup by inferred title+year — only when allow_lookup
    Returns None when the film cannot be identified.
    """
    if cache is not None:
        cached = cache.get(mkv)
        if cached:
            return cached

    ident: Optional[str] = None
    imdb = extract_imdb_id_from_movie_path(mkv)
    if not imdb:
        try:
            imdb = extract_imdb_from_mkv_tags(mkv)
        except Exception:
            imdb = None
    if imdb:
        ident = imdb.lower()

    if ident is None and allow_lookup and CFG.TMDB_API_KEY:
        try:
            title, year = infer_movie_name_year_from_path(mkv)
            if title:
                meta = _get_meta_fetcher().movie_metadata(title, year, None)
                if meta and meta.get("tmdb_id"):
                    ident = f"tmdb:{meta['tmdb_id']}"
        except Exception as e:
            logging.debug("Identity lookup failed for %s: %s", mkv.name, e)

    if ident and cache is not None:
        cache.add(mkv, ident)
    return ident


def _probe_duration_s(mkv: Path) -> Optional[float]:
    try:
        return _container_duration_s(mkvmerge_identify_json(mkv))
    except Exception:
        return None


def split_group_by_duration(group: List[Path], tolerance: float = 0.01) -> List[List[Path]]:
    """
    Split a merge candidate into cohorts of compatible runtime.

    Merging audio from releases of different length (alternate cut, extra
    distributor logos, PAL speed-up) yields a file whose extra language is out
    of sync for the whole movie — so only same-runtime files may be merged.
    Files whose duration cannot be read are never merged blindly.
    """
    if len(group) < 2:
        return [group]

    cohorts: List[Tuple[Optional[float], List[Path]]] = []
    for p in group:
        d = _probe_duration_s(p)
        placed = False
        if d is not None:
            for anchor, members in cohorts:
                if anchor is not None and abs(d - anchor) <= max(2.0, anchor * tolerance):
                    members.append(p)
                    placed = True
                    break
        if not placed:
            cohorts.append((d, [p]))

    if len(cohorts) > 1:
        logging.warning(
            "Runtime mismatch — not merging %s (durations: %s). Same-runtime files are "
            "still merged; the rest are processed separately.",
            [p.name for p in group],
            ", ".join(f"{(d if d is not None else float('nan')):.0f}s" for d, _ in cohorts))
    return [members for _anchor, members in cohorts]


def group_movies_in_folder(folder_mkvs: List[Path], threshold: float,
                           identity_cache: Optional[IdentityCache] = None,
                           allow_lookup: bool = False) -> List[List[Path]]:
    """
    Group variant releases of the same movie (same folder only), in stages:

      1. Inferred title + year — fuzzy title match (>= threshold) with a year
         guard, so a remake never merges with the original.
      2/3. Identity — groups still separate are merged when they resolve to the
         same IMDB/TMDB id (free signals first, database lookup only when
         allow_lookup and the folder holds more than one candidate).
      4. Runtime guard — a group is split into same-duration cohorts, because
         merging different cuts would desync the added audio.
    """
    if not folder_mkvs:
        return []

    items = sorted(folder_mkvs, key=lambda p: p.name.lower())
    info: Dict[Path, Tuple[str, Optional[str]]] = {p: infer_movie_name_year_from_path(p) for p in items}

    # --- Stage 1: inferred title + year -------------------------------------
    groups: List[List[Path]] = []
    used: set[Path] = set()
    for p in items:
        if p in used:
            continue
        group = [p]
        used.add(p)
        tp, yp = info[p]
        for q in items:
            if q in used:
                continue
            tq, yq = info[q]
            if not tp or not tq:
                continue
            if yp and yq and yp != yq:
                continue  # same title, different year -> different film
            s = similarity(tp.lower(), tq.lower())
            if s >= threshold:
                logging.info("Movie grouping: '%s' ~ '%s' | title='%s' (%s) vs '%s' (%s) | ratio=%.3f",
                             p.name, q.name, tp, yp, tq, yq, s)
                group.append(q)
                used.add(q)
        groups.append(group)

    # --- Stages 2/3: merge groups sharing a database identity ---------------
    if identity_cache is not None and len(groups) > 1:
        by_ident: Dict[str, List[Path]] = {}
        merged: List[List[Path]] = []
        for g in groups:
            ident = next((i for i in (resolve_movie_identity(p, identity_cache, allow_lookup) for p in g) if i), None)
            if ident is None:
                merged.append(g)
            elif ident in by_ident:
                logging.info("Movie grouping by identity %s: merging %s into %s",
                             ident, [p.name for p in g], [p.name for p in by_ident[ident]])
                by_ident[ident].extend(g)  # same list object already in `merged`
            else:
                by_ident[ident] = g
                merged.append(g)
        groups = merged

    # --- Stage 4: runtime guard ---------------------------------------------
    final: List[List[Path]] = []
    for g in groups:
        final.extend(split_group_by_duration(g))
    return final


# =========================
# Track extraction & scoring
# =========================

@dataclasses.dataclass
class Track:
    file: Path
    id: int
    type: str  # "video"|"audio"|"subtitles"
    codec_id: str
    codec: str
    language: str
    name: str
    default: bool
    forced: bool
    width: Optional[int] = None
    height: Optional[int] = None
    channels: Optional[int] = None
    bitrate: Optional[int] = None  # may be missing
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)


def _get_prop(props: Dict[str, Any], key: str, default=None):
    return props.get(key, default)


def _effective_track_language(props: Dict[str, Any]) -> str:
    """Track language: legacy ISO 639-2 field first; if und/empty, the BCP-47
    language_ietf primary subtag ('zh-Hans' -> 'zh'). Lowercased; 'und' fallback."""
    lang = str(props.get("language", "") or "").lower().strip()
    if lang and lang != "und":
        return lang
    ietf = str(props.get("language_ietf", "") or "").lower().strip()
    if ietf and ietf != "und":
        primary = re.split(r"[-_]", ietf)[0]
        if primary:
            return primary
    return "und"


def extract_tracks(mkv_path: Path, meta: Dict[str, Any]) -> List[Track]:
    tracks: List[Track] = []
    for t in meta.get("tracks", []):
        props = t.get("properties", {}) or {}

        # mkvmerge JSON fields vary by version. Prefer explicit pixel_width/height,
        # but fall back to parsing pixel_dimensions like "1280x720" when needed.
        w = _get_prop(props, "pixel_width", None)
        h = _get_prop(props, "pixel_height", None)
        if (not w or not h):
            dim = _get_prop(props, "pixel_dimensions", None) or _get_prop(props, "display_dimensions", None)
            if isinstance(dim, str) and "x" in dim:
                try:
                    a, b = dim.lower().split("x", 1)
                    w = int(a.strip())
                    h = int(re.sub(r"[^0-9]", "", b))
                except Exception:
                    pass

        tr = Track(
            file=mkv_path,
            id=int(t.get("id")),
            type=str(t.get("type", "")),
            codec_id=str(t.get("codec_id", "")),
            codec=str(t.get("codec", "")),
            # Modern mkvmerge also writes a BCP-47 tag (language_ietf, e.g.
            # 'zh-Hans'); when the legacy field is und/missing, fall back to
            # the IETF tag's primary subtag so detection still works.
            language=_effective_track_language(props),
            name=str(_get_prop(props, "track_name", "") or ""),
            default=bool(_get_prop(props, "default_track", False)),
            forced=bool(_get_prop(props, "forced_track", False)),
            width=w,
            height=h,
            channels=_get_prop(props, "audio_channels", None),
            bitrate=_get_prop(props, "bit_rate", None),
            extra={"properties": props},
        )
        tracks.append(tr)
    return tracks


def detect_language_canonical(track: Track) -> Optional[str]:
    """
    Returns canonical language label: 'Tel'|'Hin'|'Eng' or None.
    Uses ISO + fuzzy token checks in track name.
    """
    lang = (track.language or "und").lower()
    name = (track.name or "").lower()

    # ISO first
    for canon, codes in CFG.LANG_ISO_CODES.items():
        if lang in codes:
            return canon

    # Some files use und but have track_name
    for canon, toks in CFG.LANG_NAME_TOKENS.items():
        for tok in toks:
            if tok and tok in name:
                return canon

    return None


def is_excluded_audio(track: Track) -> bool:
    n = (track.name or "").lower()
    for tok in CFG.AUDIO_EXCLUDE_TOKENS:
        if tok in n:
            return True
    return False


def apply_track_lang_overrides(
    tracks: List[Track],
    audio_overrides: Dict[int, str],
    sub_overrides: Dict[int, str],
) -> None:
    """
    Patch Track objects in-place so downstream detection uses the forced language.
    Also sets track.language to the ISO code so mkvmerge --language picks it up.
    """
    for t in tracks:
        overrides = audio_overrides if t.type == "audio" else (sub_overrides if t.type == "subtitles" else {})
        if t.id in overrides:
            canon = overrides[t.id]  # canonical == ISO 639-2 code
            logging.info("Force-lang override: track %d (%s) %r -> %s", t.id, t.type, t.language, canon)
            t.language = canon
            if not t.name or t.name.strip().lower() in ("", "und", "2 channels", "stereo", "5.1"):
                t.name = language_display(canon)


def fix_track_langs_inplace(
    mkv_path: Path,
    tracks: List[Track],
    audio_overrides: Dict[int, str],
    sub_overrides: Dict[int, str],
) -> None:
    """
    Use mkvpropedit to write forced language tags directly into a file
    (used in the skip-remux path where we don't remux but still need correct tags).
    """
    if not CFG.MKVPROPEDIT_EXE.exists():
        logging.warning("mkvpropedit not found — cannot fix language tags in-place.")
        return
    cmd = [str(CFG.MKVPROPEDIT_EXE), str(mkv_path)]
    audio_idx = 0
    sub_idx = 0
    any_change = False
    for t in sorted(tracks, key=lambda x: x.id):
        if t.type == "audio":
            audio_idx += 1
            if t.id in audio_overrides:
                canon = audio_overrides[t.id]  # canonical == ISO 639-2 code
                name = language_display(canon)
                cmd += ["--edit", f"track:a{audio_idx}", "--set", f"language={canon}", "--set", f"name={name}"]
                any_change = True
        elif t.type == "subtitles":
            sub_idx += 1
            if t.id in sub_overrides:
                canon = sub_overrides[t.id]
                name = language_display(canon)
                cmd += ["--edit", f"track:s{sub_idx}", "--set", f"language={canon}", "--set", f"name={name}"]
                any_change = True
    if any_change:
        r = run_cmd(cmd, timeout_sec=120)
        if r.ok:
            logging.info("fix_track_langs_inplace OK: %s", mkv_path.name)
        else:
            logging.warning("fix_track_langs_inplace failed (non-fatal): %s", r.err)


def is_sdh_subtitle(track: Track) -> bool:
    """Return True if the subtitle track is SDH / hearing-impaired."""
    n = (track.name or "").lower()
    if any(tok in n for tok in ("sdh", "hearing impaired", "hearing-impaired", "hi subtitles", "for the deaf")):
        return True
    props = track.extra.get("properties", {}) or {}
    return bool(props.get("hearing_impaired_flag", False))



def language_display(canon: str) -> str:
    """English display name for a canonical code, target or not."""
    name = CFG.LANG_DISPLAY_MAP.get(canon) if CFG else None
    if name:
        return name
    entry = _LANGUAGE_TABLE.get(canon)
    return entry[1] if entry else canon


_ORIG_LANG_CACHE: Dict[str, Optional[str]] = {}
_ORIG_LANG_LOCK = threading.Lock()


def split_show_year(show: str) -> Tuple[str, Optional[str]]:
    """
    Split a show label into (title, year). infer_tv_components may return either
    'Show Name (2026)' or a bare 'Show Name 2026' depending on how the release was named,
    and leaving the year glued to the title turns the lookup into an
    unconstrained search — which is how 'Show Name 2026' once resolved to the French
    series 'Show Name Extended'.
    """
    text = (show or "").strip()
    m = re.search(r"^(.*?)\s*\((\d{4})\)\s*$", text)
    if not m:
        m = re.search(r"^(.*?)\s+(\d{4})$", text)
    if m and m.group(1).strip():
        return m.group(1).strip(), m.group(2)
    return text, None



# --- TV show identity: resolve a series to one TMDB id, for language and
# metadata only — the FileBot rename keeps its own existing mechanism. -------
# A renewed show's release year is the SEASON's air year, not the series'
# first-air year (a show that debuted in 2023 still has its season 3 release
# tagged '(2026)' three years later), so year cannot be used as a hard
# constraint here the way it is for movies. An EXACT, unambiguous
# title match is the safety net instead — the same rule resolve_tv_series_by_name
# already uses safely for the rename fallback.

_TV_IDENTITY_CACHE: Dict[str, Tuple[Optional[int], List[Dict[str, Any]]]] = {}
_TV_IDENTITY_LOCK = threading.Lock()


def resolve_tv_show_tmdb_id(show: str, year: Optional[str] = None
                            ) -> Tuple[Optional[int], List[Dict[str, Any]]]:
    """
    Resolve a series to one TMDB id, or report why it could not be.

    Returns (tmdb_id, candidates). tmdb_id is set only when exactly one series
    has this exact title; otherwise it is None and candidates lists every
    series with that exact title (year-agnostic — a genuine same-titled show
    from another era is rare, and this is the case that needs a human).
    """
    if not CFG.TMDB_API_KEY or not show:
        return None, []
    key = f"{show.strip().lower()}"
    with _TV_IDENTITY_LOCK:
        if key in _TV_IDENTITY_CACHE:
            return _TV_IDENTITY_CACHE[key]

    tmdb_id: Optional[int] = None
    candidates: List[Dict[str, Any]] = []
    try:
        url = (f"https://api.themoviedb.org/3/search/tv?api_key={CFG.TMDB_API_KEY}"
               f"&query={urllib.parse.quote(show)}")
        results = (_http_get_json(url) or {}).get("results") or []
        exact = [r for r in results
                 if _match_key(r.get("name")) == _match_key(show)
                 or _match_key(r.get("original_name")) == _match_key(show)]

        if len(exact) == 1 and exact[0].get("id"):
            tmdb_id = int(exact[0]["id"])
            logging.debug("TV series resolved: %r -> %s (%s)", show, tmdb_id, exact[0].get("name"))
        elif len(exact) > 1:
            for r in exact[:5]:
                iso1 = str(r.get("original_language") or "").strip()
                candidates.append({
                    "title": str(r.get("name") or "?"),
                    "year": str(r.get("first_air_date") or "")[:4],
                    "id": str(r.get("id") or ""),
                    "lang": resolve_language(iso1) if iso1 else None,
                    "original_title": str(r.get("original_name") or ""),
                    "overview": " ".join(str(r.get("overview") or "").split()),
                    "origin_country": ", ".join(r.get("origin_country") or []),
                })
    except Exception as e:
        logging.debug("TV series lookup failed for %r: %s", show, e)

    with _TV_IDENTITY_LOCK:
        _TV_IDENTITY_CACHE[key] = (tmdb_id, candidates)
    return tmdb_id, candidates


def _report_tv_candidates(src_label: str, title: str, year: Optional[str],
                          candidates: List[Dict[str, Any]], own_langs: Set[str]) -> List[int]:
    """Print the series a title matched, same shape as the movie report."""
    earlier = _already_listed("tv", title, year)
    if earlier:
        return earlier
    logging.warning("Cannot identify the show %r — %d series share that exact title.",
                    title, len(candidates))
    if own_langs:
        logging.warning("    This file's audio: %s",
                        ", ".join(sorted(language_display(c) for c in own_langs)))
    numbers = _register_pending_candidates("tv", src_label, title, year, candidates)
    for i, c in zip(numbers, candidates):
        hit = " <- matches this file's audio" if c.get("lang") in own_langs else ""
        where = f"  {c['origin_country']}" if c.get("origin_country") else ""
        logging.warning("    [%d] %s (%s)  %s%s%s", i, c["title"], c["year"] or "?",
                        language_display(c["lang"]) if c.get("lang") else "language unknown",
                        where, hit)
        logging.warning("       https://www.themoviedb.org/tv/%s", c.get("id") or "")
        if c.get("original_title") and _match_key(c["original_title"]) != _match_key(c["title"]):
            logging.warning("       original title: %s", c["original_title"])
        if c.get("overview"):
            logging.warning("       %s", c["overview"][:120] + ("..." if len(c["overview"]) > 120 else ""))
    best = next((n for n, c in zip(numbers, candidates) if c.get("id")), numbers[0])
    logging.warning("    -> choose one of these with --pick, e.g. --pick %d", best)
    return numbers


_TV_EXT_IDS_CACHE: Dict[int, Dict[str, Any]] = {}
_TV_EXT_IDS_LOCK = threading.Lock()


def tmdb_tv_external_ids(tmdb_id: int) -> Dict[str, Any]:
    """TheTVDB / IMDB ids of a series, from its TMDB id (cached)."""
    with _TV_EXT_IDS_LOCK:
        if tmdb_id in _TV_EXT_IDS_CACHE:
            return _TV_EXT_IDS_CACHE[tmdb_id]
    data: Dict[str, Any] = {}
    try:
        data = _http_get_json(f"https://api.themoviedb.org/3/tv/{tmdb_id}/external_ids"
                              f"?api_key={CFG.TMDB_API_KEY}") or {}
    except Exception as e:
        logging.debug("Could not fetch external ids for tmdb:%s: %s", tmdb_id, e)
    with _TV_EXT_IDS_LOCK:
        _TV_EXT_IDS_CACHE[tmdb_id] = data
    return data


def tv_identity_for_rename(src_label: str, title: str, year: Optional[str],
                           known_imdb: Optional[str] = None,
                           own_langs: Optional[Set[str]] = None) -> Tuple[Optional[int], str]:
    """
    The TMDB series id to pin a TV rename to, or why it must not be renamed.

    Returns (tmdb_id, "") when the series is identified, (None, reason) when
    more than one series shares the exact title and none was picked — the
    caller must then leave the file alone — and (None, "") when TMDB does not
    know the title at all, in which case the existing TheTVDB search still
    applies, since a show only TheTVDB carries is not ambiguous, merely absent.
    """
    tv_id = tv_show_identity(src_label, title, year, known_imdb, own_langs)
    if tv_id:
        return tv_id, ""
    _none, candidates = resolve_tv_show_tmdb_id(title)
    if not candidates:
        return None, ""
    nums = _already_listed("tv", title, year)
    listed = "; ".join(
        f"[{n}] {c['title']} ({c['year']})"
        + (f" {language_display(c['lang'])}" if c.get("lang") else "")
        for n, c in list(zip(nums, candidates))[:4])
    return None, f"pick one — {listed}" if listed else "pick one — several series share this title"


def pinned_tv_commands(base_cmd: List[str], tmdb_id: int) -> List[List[str]]:
    """
    FileBot commands that look the series up BY ID instead of searching.

    TheTVDB stays the first source, addressed by the series' TheTVDB id; the
    TMDB entry is the fallback for a series TheTVDB lacks or holds broken. An id
    is a direct lookup, so no name or year filter applies and no fuzzy retry can
    substitute a different show — which is the failure a title search had.
    base_cmd must already carry '--db TheTVDB'.
    """
    cmds: List[List[str]] = []
    tvdb = tmdb_tv_external_ids(tmdb_id).get("tvdb_id")
    if tvdb:
        cmds.append(base_cmd + ["--q", str(tvdb)])
    cmds.append([("TheMovieDB::TV" if a == "TheTVDB" else a) for a in base_cmd]
                + ["--q", str(tmdb_id)])
    return cmds


_TV_ORIG_LANG_CACHE: Dict[int, Optional[str]] = {}
_TV_ORIG_LANG_LOCK = threading.Lock()


def tv_original_language_from_id(tmdb_id: int) -> Optional[str]:
    """The language a series was made in, from an ALREADY-resolved TMDB id."""
    with _TV_ORIG_LANG_LOCK:
        if tmdb_id in _TV_ORIG_LANG_CACHE:
            return _TV_ORIG_LANG_CACHE[tmdb_id]
    canon: Optional[str] = None
    try:
        data = _http_get_json(f"https://api.themoviedb.org/3/tv/{tmdb_id}?api_key={CFG.TMDB_API_KEY}")
        iso1 = str((data or {}).get("original_language") or "").strip()
        canon = resolve_language(iso1) if iso1 else None
    except Exception as e:
        logging.debug("Could not fetch original_language for tmdb:%s: %s", tmdb_id, e)
    with _TV_ORIG_LANG_LOCK:
        _TV_ORIG_LANG_CACHE[tmdb_id] = canon
    return canon


def tv_show_identity(src_label: str, title: str, year: Optional[str],
                     known_imdb: Optional[str] = None,
                     own_langs: Optional[Set[str]] = None) -> Optional[int]:
    """
    The TMDB series id to use for language/metadata, or None when it cannot be
    determined — in which case the caller leaves the affected data alone
    rather than guessing (an und track stays und; metadata is skipped).

    Scope: language resolution and metadata tagging only. The FileBot rename
    keeps using its own existing TheTVDB-first, TMDB-fallback mechanism —
    unrelated to this function on purpose, so that path is not touched here.
    """
    if not title:
        return None
    picked = _PICK_SELECTION.get(_pending_key("tv", title, year))
    if picked:
        logging.debug("Using your pick for the show %r: tmdb:%s", title, picked)
        try:
            return int(picked)
        except (TypeError, ValueError):
            return None

    if known_imdb and re.fullmatch(r"tt\d{7,10}", known_imdb):
        try:
            data = _http_get_json(f"https://api.themoviedb.org/3/find/{known_imdb}"
                                  f"?api_key={CFG.TMDB_API_KEY}&external_source=imdb_id")
            shows = (data or {}).get("tv_results") or []
            if shows and shows[0].get("id"):
                return int(shows[0]["id"])
        except Exception as e:
            logging.debug("IMDB->TMDB lookup failed for %s: %s", known_imdb, e)

    tmdb_id, candidates = resolve_tv_show_tmdb_id(title)
    if tmdb_id:
        return tmdb_id
    if candidates:
        _report_tv_candidates(src_label, title, year, candidates, own_langs or set())
    return None


def tmdb_original_language(title: str, year: Optional[str], is_tv: bool) -> Optional[str]:
    """
    The language a title was made in, as a canonical ISO 639-2 code.

    Used to label a lone 'und' audio track: a release stripped of track metadata
    still almost always carries the original audio, and TMDB knows what that is.
    Returns None when the title cannot be resolved, so the track stays 'und'.
    """
    if not CFG.TMDB_API_KEY or not title:
        return None
    if not year:
        # An unconstrained search returns whatever is most popular under that
        # name, whose language is not necessarily this title's.
        logging.debug("No year for %r — skipping original-language lookup.", title)
        return None
    key = f"{'tv' if is_tv else 'movie'}|{title.strip().lower()}|{year}"
    with _ORIG_LANG_LOCK:
        if key in _ORIG_LANG_CACHE:
            return _ORIG_LANG_CACHE[key]

    canon: Optional[str] = None
    try:
        tmdb_id = _tmdb_search_best(title, year, is_tv)
        if tmdb_id:
            kind = "tv" if is_tv else "movie"
            data = _http_get_json(
                f"https://api.themoviedb.org/3/{kind}/{tmdb_id}?api_key={CFG.TMDB_API_KEY}")
            iso1 = str((data or {}).get("original_language") or "").strip()
            if iso1:
                canon = resolve_language(iso1)
                if canon:
                    logging.debug("TMDB original language for %r (%s): %s -> %s",
                                  title, year, iso1, canon)
    except Exception as e:
        logging.debug("TMDB original-language lookup failed for %r: %s", title, e)

    with _ORIG_LANG_LOCK:
        _ORIG_LANG_CACHE[key] = canon
    return canon


def _extract_subtitle_text(mkv: Path, track_ids: List[int], max_bytes: int = 65536) -> Dict[int, str]:
    """
    Pull the text of the given subtitle tracks out of an MKV (read-only).
    Returns {track_id: text}; tracks that fail to extract are simply absent.
    """
    if not track_ids or not CFG.MKVEXTRACT_EXE.exists():
        return {}
    import tempfile
    out: Dict[int, str] = {}
    with tempfile.TemporaryDirectory(prefix="mclang_") as tmpdir:
        tmp = Path(tmpdir)
        cmd = [str(CFG.MKVEXTRACT_EXE), "tracks", str(mkv)]
        cmd += [f"{tid}:{tmp / f'{tid}.sub'}" for tid in track_ids]
        r = run_cmd(cmd, timeout_sec=600)
        if not r.ok:
            logging.debug("mkvextract for language detection failed (rc=%s): %s", r.rc, r.err)
        for tid in track_ids:
            f = tmp / f"{tid}.sub"
            if not f.exists():
                continue
            try:
                with open(f, "rb") as fh:
                    raw = fh.read(max_bytes)
                out[tid] = raw.decode("utf-8", errors="replace")
            except OSError as e:
                logging.debug("Could not read extracted track %d: %s", tid, e)
    return out


def _track_codec_id(track: Track) -> str:
    """
    The Matroska codec id ('S_TEXT/UTF8'). mkvmerge reports it under the track's
    'properties' object; Track.codec_id reads the track root, where this version
    does not put it, so go to properties first and fall back to the root.
    """
    props = track.extra.get("properties", {}) or {}
    return str(props.get("codec_id") or track.codec_id or "").upper()


def resolve_undetermined_track_languages(
    mkv: Path,
    tracks: List[Track],
    title: Optional[str],
    year: Optional[str],
    is_tv: bool,
    audio_overrides: Dict[int, str],
    sub_overrides: Dict[int, str],
) -> Tuple[Dict[int, str], Dict[int, str]]:
    """
    Work out the language of tracks tagged 'und', without guessing from position.

    Audio: a release stripped of metadata carries the original audio, so a
    single unlabelled audio track takes the title's TMDB original language.
    With two or more we cannot tell which is which, and they stay 'und' —
    --force-audio-lang remains the answer there.

    Subtitles: identified from the subtitle text itself (see
    identify_text_language), which finds every language present rather than
    hoping the wanted one was muxed first.

    Returns (audio_map, sub_map) of track id -> canonical code, for tracks that
    were resolved. Explicit --force-* overrides are never touched.
    """
    resolved_audio: Dict[int, str] = {}
    resolved_subs: Dict[int, str] = {}

    def undetermined(t: Track, forced: Dict[int, str]) -> bool:
        return (t.id not in forced
                and (t.language or "und").lower() in ("", "und")
                and detect_language_canonical(t) is None)

    # --- audio: the title's original language, only when unambiguous ---------
    audio = [t for t in tracks if t.type == "audio" and not is_excluded_audio(t)]
    unlabelled_audio = [t for t in audio if undetermined(t, audio_overrides)]
    if unlabelled_audio:
        if len(audio) > 1:
            logging.info("%d audio tracks are unlabelled in %s — cannot tell them apart; "
                         "use --force-audio-lang to set them.", len(unlabelled_audio), mkv.name)
        elif title:
            # TV: a renewed show's release year is the SEASON's air year, not
            # the series' first-air year, so year cannot gate this lookup the
            # way it does for movies — tv_show_identity() matches on an exact,
            # unambiguous title instead (auto-resolves; asks via --pick only
            # when more than one series shares that exact title).
            canon: Optional[str] = None
            if is_tv:
                tv_id = tv_show_identity(mkv.name, title, year)
                if tv_id:
                    canon = tv_original_language_from_id(tv_id)
            else:
                canon = tmdb_original_language(title, year, False)
            if canon:
                resolved_audio[unlabelled_audio[0].id] = canon
                logging.info("Audio track %d in %s is unlabelled — %s is in %s per TMDB, using that.",
                             unlabelled_audio[0].id, mkv.name, title,
                             language_display(canon))
            else:
                logging.info("Audio track %d in %s is unlabelled and TMDB has no original "
                             "language for %r — leaving it undetermined.",
                             unlabelled_audio[0].id, mkv.name, title)

    # --- subtitles: read the text and identify it ----------------------------
    candidates = [t for t in tracks
                  if t.type == "subtitles"
                  and _track_codec_id(t) in _TEXT_SUB_CODECS
                  and undetermined(t, sub_overrides)]
    if candidates:
        texts = _extract_subtitle_text(mkv, [t.id for t in candidates])
        named: List[str] = []
        for t in candidates:
            text = texts.get(t.id)
            if not text:
                continue
            canon, conf = identify_text_language(text)
            if canon:
                resolved_subs[t.id] = canon
                named.append(f"{t.id}={language_display(canon)}({conf})")
        if named:
            logging.info("Identified %d of %d unlabelled subtitle tracks in %s: %s",
                         len(resolved_subs), len(candidates), mkv.name, ", ".join(named))
        unresolved = len(candidates) - len(resolved_subs)
        if unresolved:
            logging.info("%d subtitle track(s) in %s could not be identified — left undetermined.",
                         unresolved, mkv.name)

    return resolved_audio, resolved_subs


def codec_family_video(track: Track) -> str:
    # mkvmerge JSON may provide codec hints in either codec_id or codec.
    # Some versions may return null -> "None" after str(). Include filename fallback.
    cid = (track.codec_id or "")
    cc  = (track.codec or "")
    c = f"{cid} {cc}".lower()

    # Normalize common patterns
    if any(x in c for x in ("hevc", "hvc1", "hev1", "h.265", "h265", "x265")):
        return "hevc"
    if any(x in c for x in ("avc", "h.264", "h264", "x264")):
        return "avc"

    # Fallback: infer from filename when metadata is missing
    fn = (track.file.name or "").lower()
    if any(x in fn for x in ("hevc", "h265", "h.265", "x265")):
        return "hevc"
    if any(x in fn for x in ("avc", "h264", "h.264", "x264")):
        return "avc"

    # Last resort
    c2 = (cid or cc or "").lower()
    return c2 or "unknown"


def codec_tag_video(track: Track) -> str:
    fam = codec_family_video(track)
    if fam == "hevc":
        return "x265"
    if fam == "avc":
        return "x264"
    if "vp9" in fam:
        return "vp9"
    if "av1" in fam:
        return "av1"
    return sanitize_filename(fam)[:12] or "video"


def normalize_audio_codec_rank(codec_id: str) -> str:
    c = (codec_id or "").lower()
    # Common MKV codec_id examples:
    # A_AAC, A_AC3, A_EAC3, A_DTS, A_TRUEHD, A_OPUS, A_VORBIS
    if "truehd" in c:
        return "a_truehd"
    if "dts-hd" in c or "dtshd" in c:
        return "dts-hd"
    if "dts" in c:
        return "dts"
    if "eac3" in c:
        return "eac3"
    if "ac3" in c:
        return "ac3"
    if "aac" in c:
        return "aac"
    if "mp3" in c:
        return "mp3"
    if "opus" in c:
        return "opus"
    if "vorbis" in c:
        return "vorbis"
    return c or "other"


def normalize_sub_codec(codec_id: str) -> str:
    return (codec_id or "").lower()


def resolution_value(track: Track) -> Optional[int]:
    # Prefer height if present
    if track.height:
        try:
            return int(track.height)
        except Exception:
            return None
    return None


def nearest_target_rank(h: int) -> Tuple[int, int]:
    """
    Returns (target_index, delta) where target_index is lower is better:
      0 -> nearest 2160
      1 -> nearest 1080
      2 -> nearest 720
    delta is abs difference.
    """
    best_idx, best_delta = 0, 10**9
    for i, t in enumerate(CFG.RES_TARGETS):
        d = abs(h - t)
        if d < best_delta:
            best_delta = d
            best_idx = i
    return (best_idx, best_delta)


def score_video(track: Track, file_size: int) -> Tuple:
    fam = codec_family_video(track)
    # codec preference
    codec_rank = 9
    if fam == "hevc":
        codec_rank = 0
    elif fam == "avc":
        codec_rank = 1
    else:
        codec_rank = 5

    w = track.width or 0
    h = resolution_value(track) or 0
    if w:
        target_idx, delta = _nearest_by_dim(w, CFG.RES_WIDTH_TARGETS)
    elif h:
        target_idx, delta = _nearest_by_dim(h, CFG.RES_TARGETS)
    else:
        target_idx, delta = 9, 10**9
    pixels = (track.width or 0) * (track.height or 0)

    # bitrate may be None; file size acts as final tie breaker
    br = track.bitrate or 0

    # Lower tuple is better for ranks; for pixels/br/size use negative for higher-is-better.
    return (codec_rank, target_idx, delta, -pixels, -br, -file_size, track.id)


def score_audio(track: Track) -> Tuple:
    # Higher channels preferred
    ch = int(track.channels or 0)
    c_rank_key = normalize_audio_codec_rank(track.codec_id)
    try:
        c_rank = CFG.AUDIO_CODEC_RANK.index(c_rank_key)
    except ValueError:
        c_rank = len(CFG.AUDIO_CODEC_RANK) + 5

    br = int(track.bitrate or 0)
    # Prefer default track as small tie-break
    default_rank = 0 if track.default else 1

    # Lower is better; use negative for higher-is-better values
    return (-ch, c_rank, -br, default_rank, track.id)


def score_sub(track: Track, include_forced: bool) -> Tuple:
    cid = normalize_sub_codec(track.codec_id)
    try:
        c_rank = CFG.SUB_CODEC_RANK.index(cid)
    except ValueError:
        c_rank = len(CFG.SUB_CODEC_RANK) + 5

    # Prefer non-forced by default; if include_forced is enabled, we allow forced but do not
    # automatically prefer it unless no non-forced exists.
    forced_rank = 1 if track.forced else 0
    default_rank = 0 if track.default else 1
    return (c_rank, forced_rank, default_rank, track.id)


# =========================
# Filename inference helpers
# =========================

# Distributor / website prefixes glued onto downloaded filenames, e.g.
#   'www.example-site.net_-_The.Film.2024_...'
#   'www.example-site.org - Movie Name (2024) ...'
#   '[www.example-site.com] - Some.Film.2019...'
# Left in place they poison the DB lookup query, so they are stripped before
# any title inference. The TLD list + the (?![.\w]) guard keep legitimate
# dotted titles safe (a title whose second token is a TLD word such as
# 'in' or 'to' is never treated as a domain).
_SITE_TLDS = (
    "com|net|org|info|biz|co|io|me|tv|cc|ws|se|is|in|la|mx|sx|ph|to|ru|ua|eu|uk|us|ag|gd|gl|tw|"
    "party|promo|link|life|xyz|club|space|site|online|store|fun|icu|pro|app|unblockit|wtf|cam|"
    "lol|bar|cfd|mom|now|rest|sbs|vip|wiki|work|blue|red|green|digital|website|tel|cyou|lat|boo"
)
# At most three labels before the TLD: a real domain is short, and letting this
# span further swallows dotted titles ('The.Film.Name...WEB-DL.Hindi.TV').
_DOMAIN_LABELS = r"[A-Za-z0-9][\w-]*(?:\.[A-Za-z0-9][\w-]*){0,2}?"
_SITE_PREFIX_RX = re.compile(
    r"^\s*[\[\(]?\s*"
    r"(?:"
    # 'www.' is proof of a domain, so a dot may follow the TLD:
    # 'www.example-site.org.The.Film.2014...' -> 'The.Film.2014...'
    r"www\." + _DOMAIN_LABELS + r"\.(?:" + _SITE_TLDS + r")\b"
    # 'www.' with an unknown TLD, but clearly separated from the title by a dash
    r"|www\.\S+(?=\s*[-–—])"
    # bare domain: strict — the TLD must NOT be followed by more of a dotted
    # title ('Some.in.Title') nor by a hyphen ('...Hindi.TV-DL'), so
    # neither is ever mistaken for a domain
    r"|" + _DOMAIN_LABELS + r"\.(?:" + _SITE_TLDS + r")(?![-.\w])"
    r")"
    r"\s*[\]\)]?\s*(?:[-–—]+\s*|\.)?",
    re.IGNORECASE,
)


# Configured distributor names, stripped even when the trailing part is not a
# recognizable TLD ('SiteName.Foo.The.Film.2026...' -> 'The.Film.2026...').
# A distributor/tracker label after a configured prefix may be an unusual TLD
# ('SiteName.foo'), so a wider list is allowed here than for bare-domain
# detection — it must still look like a TLD, or 'SiteName.Some.Short.Title'
# would lose its first word.
_SITE_LABEL_TLDS = _SITE_TLDS + (
    "|foo|dad|day|esq|fyi|ing|mov|new|phd|prof|rsvp|soy|zip|moi|run|ltd|art|top|men|win|"
    "pw|su|nl|de|fr|es|jp|kr|br|ar|cl|pe|ec|za|ng|ke|pk|bd|lk|np|my|sg|th|vn|id|tr|ir|ae"
)

# Extra filename prefixes to strip, supplied by the user via
# [naming] strip_prefixes in MediaCleanup.toml (empty by default). Some
# distributors stamp their own name onto filenames without a valid domain
# suffix, which the generic domain rule above cannot catch.
_PREFIX_RX_CACHE: Dict[Tuple[str, ...], Tuple[Optional["re.Pattern[str]"], Optional["re.Pattern[str]"]]] = {}
_PREFIX_RX_LOCK = threading.Lock()


def _configured_prefix_patterns() -> Tuple[Optional["re.Pattern[str]"], Optional["re.Pattern[str]"]]:
    """Compile (with-label, name-only) matchers for the configured prefixes."""
    names = tuple(CFG.STRIP_PREFIXES) if CFG is not None else ()
    if not names:
        return None, None
    with _PREFIX_RX_LOCK:
        if names in _PREFIX_RX_CACHE:
            return _PREFIX_RX_CACHE[names]
        # Longest first so a longer prefix wins over a shorter one that is its
        # leading substring (regex alternation is first-match).
        alt = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
        with_label = re.compile(
            r"^\s*[\[\(]?\s*(?:" + alt + r")(?:\.(?:" + _SITE_LABEL_TLDS + r")\b)?"
            r"\s*[\]\)]?\s*(?:[-–—]+\s*|\.)?", re.IGNORECASE)
        name_only = re.compile(
            r"^\s*[\[\(]?\s*(?:" + alt + r")\s*[\]\)]?\s*(?:[-–—]+\s*|\.)?", re.IGNORECASE)
        _PREFIX_RX_CACHE[names] = (with_label, name_only)
        return with_label, name_only


def strip_site_prefix(stem: str) -> str:
    """
    Remove a leading distributor/domain prefix from a filename stem.
    Underscores are normalized to spaces first (so the domain becomes a
    space-delimited token) while dots stay intact for domain matching.
    Returns the original stem when nothing is stripped or nothing would remain.
    """
    def _starts_with_year(text: str) -> bool:
        return bool(re.match(r"^(?:19|20)\d{2}\b", text.strip(" .-")))

    s = stem.replace("_", " ")
    cleaned = _SITE_PREFIX_RX.sub("", s, count=1)

    # Configured prefixes can be chained ('SiteA.SiteB.The.Film.2014...').
    with_label, name_only = _configured_prefix_patterns()
    for _ in range(3):
        if with_label is None or name_only is None:
            break
        candidate = with_label.sub("", cleaned, count=1)
        if candidate == cleaned:
            break
        # Guard against over-stripping: if the result now starts with the year,
        # the trailing label was actually the film's title
        # ('SiteName.Up.2009' must not become '2009').
        if _starts_with_year(candidate):
            candidate = name_only.sub("", cleaned, count=1)
            if candidate == cleaned or _starts_with_year(candidate):
                break
        cleaned = candidate

    cleaned = re.sub(r"^[\s.\-–—]+", "", cleaned)
    if not cleaned.strip():
        return s
    if cleaned != s:
        logging.debug("Stripped site prefix: %r -> %r", stem, cleaned)
    return cleaned


def infer_movie_name_year_from_path(p: Path) -> Tuple[str, Optional[str]]:
    """
    Best-effort inference of Movie Title + Year from a filename.

    Goals:
    - Extract a 4-digit year (prefer (YYYY), else standalone token).
    - Remove typical release/quality clutter from the *title* (languages, codecs, sizes, bracketed groups).
    - Keep the human movie title clean, even when the source name is extremely noisy.

    Note: Source tags like WEB-DL/HDRip/BluRay are NOT kept in the title; they are inferred separately.
    """
    stem = strip_site_prefix(p.stem)

    # Normalize separators early
    s = stem.replace(".", " ").replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip()

    # Remove bracketed groups that commonly contain junk: [ ... ]
    # (Languages, groups, tags, etc.)
    s = re.sub(r"\[[^\]]*\]", " ", s)

    # Remove non-year parentheses groups that often contain audio/bitrate/size info.
    # Keep (YYYY) if present.
    s = re.sub(r"\((?!19\d{2}\)|20\d{2}\))[^\)]*\)", " ", s)

    # Extract year. Scene convention is 'Title.Year.Quality.Source.Lang.Tags' —
    # when there is title text BEFORE the year, everything AFTER it is release
    # junk (e.g. 'The.Film.Name.2026.1080p.WEB-DL.Hindi.ESubs'), so truncate.
    year = None
    m = re.search(r"\((19\d{2}|20\d{2})\)", s)
    if m:
        year = m.group(1)
        before = s[:m.start()].strip()
        s = before if before else s.replace(m.group(0), " ")
    else:
        # A title can END in a year, or be nothing but a year, which puts TWO
        # year tokens side by side: 'The.Film.1984.2020.1080p'. The last of an
        # adjacent run is the release year; earlier ones belong to the title.
        m2 = re.search(r"\b(19\d{2}|20\d{2})(?:[\s._\-]+(19\d{2}|20\d{2}))*\b", s)
        if m2:
            year = m2.group(2) or m2.group(1)
            cut = m2.end() - len(year)          # keep any earlier year in the title
            before = s[:cut].strip(" .-_")
            s = before if before else re.sub(r"\b" + re.escape(year) + r"\b", " ", s)

    # Remove common "release junk" tokens from title
    # (we intentionally do NOT remove plain words that could be part of title)
    junk = re.compile(
        r"(?i)\b("
        r"2160p|1440p|1080p|720p|480p|"
        r"x265|x264|h265|h264|hevc|avc|"
        r"hdr10\+?|hdr|dv|dolby\s*vision|"
        r"webrip|web[- ]?dl|bluray|b[dr]rip|remux|"
        r"hdtv|cam|ts|tc|dvdrip|"
        r"esubs?|msubs?|subbed|multi|dubbed|dual\s*audio|uncut|org|hq|"
        r"ddp?\+?\s*\d\.\d|dd\s*\d\.\d|"
        r"eac3|ac3|aac|dts(?:-hd)?|truehd|atmos|"
        r"(?:8|10)\s*-?\s*bit|"
        r"\d+\s*kbps|\d+\s*mbps|"
        r"\d+(?:\.\d+)?\s*(?:gb|mb)"
        r")\b"
    )
    s = junk.sub(" ", s)

    # Release-group debris left behind after codec removal (e.g. 'HEVC-GRP' -> '-GRP')
    s = re.sub(r"(?:^|\s)-[A-Za-z0-9]+\b", " ", s)

    # Collapse repeated hyphens / separators
    s = re.sub(r"[\-–—]{2,}", " ", s)
    s = re.sub(r"\s+", " ", s).strip()

    # Final sanitize
    title = sanitize_filename(s)
    if not title:
        # Fallback to folder name if filename was too noisy
        title = sanitize_filename(p.parent.name) or sanitize_filename(stem)

    return title, year


def extract_imdb_id_from_path(p: Path) -> Optional[str]:
    """Extract IMDb id (tt1234567) from filename, if present."""
    m = re.search(r"(?i)\btt\d{6,9}\b", p.stem)
    return m.group(0) if m else None


def extract_imdb_id_from_movie_path(p: Path) -> Optional[str]:
    """
    Extract IMDb id for a movie file.
    Checks the filename first, then walks up parent folder names —
    movie folders are often named 'Movie Title (Year) - tt1234567'.
    """
    imdb = extract_imdb_id_from_path(p)
    if imdb:
        return imdb
    for parent in p.parents:
        if len(parent.parts) <= 1:
            break
        m = re.search(r"(?i)\btt\d{6,9}\b", parent.name)
        if m:
            return m.group(0)
    return None


def extract_imdb_from_mkv_tags(mkv_path: Path) -> Optional[str]:
    """
    Read the IMDB tag already embedded in the MKV file's Matroska tags.
    Used as a fallback when the filename/folder doesn't carry an IMDB ID —
    FileBot writes the IMDB ID into the tags even when the filename format
    doesn't include it.

    Runs mkvextract to dump the tags XML, then parses for <Name>IMDB</Name>.
    Returns the first tt-prefixed ID found, or None.
    """
    if not CFG.MKVEXTRACT_EXE.exists():
        return None
    import tempfile as _tf
    fd, tmp = _tf.mkstemp(prefix="mkvtags_read_", suffix=".xml")
    tmp_path = Path(tmp)
    try:
        os.close(fd)
        mkvextract_exe = CFG.MKVEXTRACT_EXE
        r = run_cmd([str(mkvextract_exe), str(mkv_path), "tags", str(tmp_path)], timeout_sec=60)
        if not tmp_path.exists() or tmp_path.stat().st_size == 0:
            return None
        xml_text = tmp_path.read_text(encoding="utf-8", errors="replace")
        # Find <Name>IMDB</Name> ... <String>ttNNN</String>
        m = re.search(r"<Name>IMDB</Name>\s*<String>(tt\d{6,9})</String>", xml_text, re.IGNORECASE)
        return m.group(1) if m else None
    except Exception:
        return None
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def extract_imdb_id_from_tv_path(p: Path) -> Optional[str]:
    """
    Extract IMDb id for a TV file.
    Checks the filename first, then walks up parent folder names —
    TV show folders commonly carry the IMDb id (e.g. 'Show Name (2008) - tt0000000').
    """
    imdb = extract_imdb_id_from_path(p)
    if imdb:
        return imdb
    for parent in p.parents:
        if len(parent.parts) <= 1:
            break
        m = re.search(r"(?i)\btt\d{6,9}\b", parent.name)
        if m:
            return m.group(0)
    return None


def _nearest_by_dim(value: int, targets: Tuple[int, ...]) -> Tuple[int, int]:
    """Return (index, delta) of the closest target to value, picking by smallest delta."""
    best_idx, best_delta = 0, 10**9
    for i, t in enumerate(targets):
        d = abs(value - t)
        if d < best_delta:
            best_delta = d
            best_idx = i
    return (best_idx, best_delta)


# Standard frame heights, largest first.
_STD_HEIGHTS: Tuple[int, ...] = (4320, 2160, 1440, 1080, 720, 576, 480, 360, 240)
# Widths of the common masters, mapped to the height their releases are named for.
_WIDTH_CLASS: Tuple[Tuple[int, int], ...] = (
    (7680, 4320), (3840, 2160), (2560, 1440), (1920, 1080),
    (1280, 720), (1024, 576), (854, 480), (640, 360),
)


def infer_resolution_tag_from_video(track: Track, fallback_filename: Optional[str] = None, **_ignored) -> str:
    """
    Infer the resolution tag ('1080p') a release is named for.

    Height decides it whenever the frame has a standard height, within 5% so
    coded padding still lands right (an encoder rounds 1080 up to 1088). This is
    what keeps an ultra-wide 2582x1080 scope encode at **1080p**: it has exactly
    1080 rows, and naming it for its 2582 width would claim vertical detail that
    is not there.

    A letterboxed frame has no standard height (1920x804), and there its width
    says which master it came from, so the width class is used instead.

    Falls back to a resolution written in the filename, then 'UnknownRes'.
    """
    h = resolution_value(track)
    if h:
        try:
            h = int(h)
            for std in _STD_HEIGHTS:
                if std * 0.95 <= h <= std * 1.05:
                    return f"{std}p"
        except (TypeError, ValueError):
            pass

    w = track.width
    if w:
        try:
            return f"{min(_WIDTH_CLASS, key=lambda wc: abs(wc[0] - int(w)))[1]}p"
        except (TypeError, ValueError):
            pass

    if fallback_filename:
        m = re.search(r"(?i)\b(4320|2160|1440|1080|720|576|480|360|240)p\b", fallback_filename)
        if m:
            return f"{m.group(1)}p"

    return "UnknownRes"


def _resolution_tag_for_file(mkv: Path) -> Optional[str]:
    """The resolution tag for a file on disk, read from its own video track."""
    try:
        video = next((t for t in extract_tracks(mkv, mkvmerge_identify_json(mkv))
                      if t.type == "video"), None)
    except Exception as e:
        logging.debug("Could not read video track of %s: %s", mkv.name, e)
        return None
    return infer_resolution_tag_from_video(video, fallback_filename=mkv.name) if video else None


def _pin_resolution_in_format(fmt: str, mkv: Path) -> str:
    """
    Replace FileBot's {vf} with the tag this script computed.

    {vf} normalises to a 16:9-equivalent height, so FileBot would write 1440p
    for a 2582x1080 frame while every preview and every other part of the script
    says 1080p. Substituting a literal makes this script the single source of
    truth for the tag, and the two can no longer disagree. If the tag cannot be
    determined, {vf} is left in place and FileBot decides as before.
    """
    if "{vf}" not in fmt:
        return fmt
    tag = _resolution_tag_for_file(mkv)
    return fmt.replace("{vf}", tag) if tag and tag != "UnknownRes" else fmt


_SOURCE_TAGS = [
    ("WEB-DL", re.compile(r"(?i)\bweb[ ._-]?dl\b")),
    ("WEBRip", re.compile(r"(?i)\bweb[ ._-]?rip\b")),
    ("BluRay", re.compile(r"(?i)\bblu[ ._-]?ray\b|\bbd\b")),
    ("BRRip", re.compile(r"(?i)\bbrrip\b|\bb[dr]rip\b")),
    ("HDRip", re.compile(r"(?i)\bhdrip\b")),
    ("HDTV", re.compile(r"(?i)\bhdtv\b")),
    ("DVDRip", re.compile(r"(?i)\bdvdrip\b")),
    ("REMUX", re.compile(r"(?i)\bremux\b")),
]

def infer_source_tag_from_filename(filename: str) -> Optional[str]:
    """
    Infer a source tag (e.g., WEB-DL, WEBRip, BluRay, HDRip) from the filename stem.
    Returns None if not detected.
    """
    s = filename.replace(".", " ").replace("_", " ")
    for tag, rx in _SOURCE_TAGS:
        if rx.search(s):
            return tag
    return None


def infer_codec_tag_from_filename(filename: str) -> Optional[str]:
    s = filename.lower()
    if re.search(r"\b(x265|h265|hevc)\b", s):
        return "x265"
    if re.search(r"\b(x264|h264|avc)\b", s):
        return "x264"
    if re.search(r"\b(av1)\b", s):
        return "av1"
    if re.search(r"\b(vp9)\b", s):
        return "vp9"
    return None

def parse_force_lang_overrides(pairs: Optional[List[List[str]]]) -> Dict[int, str]:
    """
    Parse repeated --force-audio-lang / --force-sub-lang TRACK_ID LANG pairs
    into {track_id: canonical} dict.  LANG accepts same values as --audio-langs.
    """
    if not pairs:
        return {}
    result: Dict[int, str] = {}
    for tid_str, lang_str in pairs:
        try:
            tid = int(tid_str)
        except ValueError:
            raise ValueError(f"Track ID must be an integer, got: {tid_str!r}")
        resolved = parse_audio_lang_filter([lang_str])
        if not resolved:
            raise ValueError(f"Could not resolve language: {lang_str!r}")
        result[tid] = resolved[0]
    return result


def parse_audio_lang_filter(raw: List[str]) -> Optional[List[str]]:
    """
    Parse user-supplied language names/codes into canonical keys.
    Accepts full names (Telugu, Hindi, English) or ISO codes (tel, hin, eng).
    Returns ordered list of canonical keys, or None if input is empty/None.
    Raises ValueError for unrecognised tokens.
    """
    if not raw:
        return None

    # Build a lookup: lower token -> canonical key
    lookup: Dict[str, str] = {}
    for canon, codes in CFG.LANG_ISO_CODES.items():
        for c in codes:
            lookup[c.lower()] = canon
    for canon, tokens in CFG.LANG_NAME_TOKENS.items():
        for tok in tokens:
            if tok:
                lookup[tok.lower()] = canon
    # Also accept canonical keys themselves (Tel, Hin, Eng)
    for canon in CFG.LANG_CANONICAL_ORDER:
        lookup[canon.lower()] = canon

    resolved: List[str] = []
    for token in raw:
        key = token.strip().lower()
        canon = lookup.get(key)
        if canon is None:
            accepted = ", ".join(f"{CFG.LANG_DISPLAY_MAP[c]}/{c}" for c in CFG.LANG_CANONICAL_ORDER)
            raise ValueError(
                f"Unrecognised language '{token}'. Configured targets ([languages] in "
                f"{CONFIG_FILE.name}): {accepted}"
            )
        if canon not in resolved:
            resolved.append(canon)

    # Return in canonical order
    return [c for c in CFG.LANG_CANONICAL_ORDER if c in resolved]


def build_audio_bracket(selected_langs: List[str]) -> str:
    """
    Build bracket string using FULL language names in fixed order.
    Example: [Telugu + Hindi + English]
    """
    if not selected_langs:
        return "NoAudioMatch"
    ordered = [x for x in CFG.LANG_CANONICAL_ORDER if x in selected_langs]
    ordered_display = [CFG.LANG_DISPLAY_MAP.get(x, x) for x in ordered]
    return " + ".join(ordered_display)


# =========================
# mkvmerge command builder
# =========================

def mkvmerge_build_and_run(
    output_tmp: Path,
    parts: List[Tuple[Path, Dict[str, Any]]],
    dry_run: bool,
    segment_title: Optional[str] = None,
    timeout_sec: int = 3600,
) -> CmdResult:
    """
    parts: list of (input_file, options_dict) where options_dict contains:
      - video_tracks: List[int] | None
      - audio_tracks: List[int] | None
      - sub_tracks: List[int] | None
      - track_names: Dict[int,str] track_id->name
      - languages: Dict[int,str] track_id->iso (optional)
      - no_attachments: bool
      - no_chapters: bool
    Each part's options apply to that file and are placed immediately before it.
    """
    cmd: List[str] = [win_long_path(CFG.MKVMERGE_EXE), "-o", win_long_path(output_tmp)]

    # Global safety: no chapters / tags unless desired
    cmd += ["--no-chapters", "--no-global-tags"]

    if segment_title:
        cmd += ["--title", segment_title]

    for in_file, opt in parts:
        # Attachments can carry fonts; default keep them unless explicitly disabled.
        if opt.get("no_attachments", False):
            cmd += ["--no-attachments"]

        v = opt.get("video_tracks", None)
        a = opt.get("audio_tracks", None)
        s = opt.get("sub_tracks", None)

        if v is None:
            cmd += ["--no-video"]
        else:
            cmd += ["--video-tracks", ",".join(str(x) for x in v)]

        if a is None:
            cmd += ["--no-audio"]
        else:
            cmd += ["--audio-tracks", ",".join(str(x) for x in a)]

        if s is None:
            cmd += ["--no-subtitles"]
        else:
            cmd += ["--subtitle-tracks", ",".join(str(x) for x in s)]

        # track names
        tnames: Dict[int, str] = opt.get("track_names", {}) or {}
        for tid, tname in tnames.items():
            cmd += ["--track-name", f"{tid}:{tname}"]

        # languages (optional)
        tlang: Dict[int, str] = opt.get("languages", {}) or {}
        for tid, iso in tlang.items():
            cmd += ["--language", f"{tid}:{iso}"]

        cmd += [win_long_path(in_file)]

    if dry_run:
        logging.info("[DRY] mkvmerge command: %s", " ".join(cmd))
        return CmdResult(ok=True, rc=0, out="", err="", cmd=cmd)

    return run_cmd(cmd, timeout_sec=timeout_sec)


def file_has_all_target_langs(
    src: Path,
    audios_found: Dict[str, Any],
    audio_lang_filter: Optional[List[str]],
) -> bool:
    """
    Return True if a SINGLE source file already contains every target audio language
    so that remuxing is unnecessary.

    target_langs = audio_lang_filter if specified, else all three canonical languages
    that are present in the file (we only require the ones the user asked for, not all
    three unconditionally — if user asked for Telugu+Hindi only, English being absent is fine).

    Additionally the file must be a single-file group (caller is responsible for checking
    len(group) == 1 for movies).
    """
    target = set(audio_lang_filter) if audio_lang_filter else set(CFG.LANG_CANONICAL_ORDER)
    found  = set(audios_found.keys())
    return target.issubset(found)


def atomic_move(src_tmp: Path, dst_final: Path, overwrite: bool) -> None:
    dst_final.parent.mkdir(parents=True, exist_ok=True)
    if dst_final.exists():
        if not overwrite:
            raise FileExistsError(f"Output exists and overwrite disabled: {dst_final}")
        # Try remove first to reduce cross-volume rename issues
        dst_final.unlink()
    os.replace(win_long_path(src_tmp), win_long_path(dst_final))


# =========================
# Tag cleaning (--cleantags mode)
# =========================

def _build_tags_xml(imdb_id: Optional[str] = None) -> str:
    """
    Build a Matroska tags XML string.
    If imdb_id is provided, includes an IMDB tag at movie level (TargetTypeValue 50).
    Otherwise returns an empty tags document (clears all existing tags).
    """
    if imdb_id:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE Tags SYSTEM "matroskatags.dtd">\n'
            "<Tags>\n"
            "  <Tag>\n"
            "    <Targets>\n"
            "      <TargetTypeValue>50</TargetTypeValue>\n"
            "    </Targets>\n"
            "    <Simple>\n"
            "      <Name>IMDB</Name>\n"
            f"      <String>{imdb_id}</String>\n"
            "    </Simple>\n"
            "  </Tag>\n"
            "</Tags>\n"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE Tags SYSTEM "matroskatags.dtd">\n'
        "<Tags>\n"
        "</Tags>\n"
    )


def _write_tags_xml(imdb_id: Optional[str] = None, xml_text: Optional[str] = None) -> Path:
    """Write a Matroska tags XML to a temp file and return its path.
    xml_text overrides the default minimal (IMDB-only) document."""
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".xml", prefix="mkvtags_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(xml_text if xml_text is not None else _build_tags_xml(imdb_id))
    except Exception:
        try:
            os.close(fd)
        except Exception:
            pass
        raise
    return Path(tmp)


def _xml_esc(s: Any) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _simple_tag(name: str, value: Any, indent: str = "    ", nested: str = "") -> str:
    """One Matroska <Simple> element, or empty string when value is empty."""
    if value is None or str(value).strip() == "":
        return ""
    return (f"{indent}<Simple>\n"
            f"{indent}  <Name>{_xml_esc(name)}</Name>\n"
            f"{indent}  <String>{_xml_esc(str(value).strip())}</String>\n"
            f"{nested}"
            f"{indent}</Simple>\n")


def _actor_tags(cast: List[Tuple[str, str]], indent: str = "    ") -> str:
    """ACTOR Simple tags with nested CHARACTER sub-tags."""
    out = []
    for actor, character in cast:
        if not actor:
            continue
        nested = ""
        if character:
            nested = (f"{indent}  <Simple>\n"
                      f"{indent}    <Name>CHARACTER</Name>\n"
                      f"{indent}    <String>{_xml_esc(character)}</String>\n"
                      f"{indent}  </Simple>\n")
        out.append(_simple_tag("ACTOR", actor, indent=indent, nested=nested))
    return "".join(out)


def _open_tag(ttv: int) -> str:
    return ("  <Tag>\n"
            "    <Targets>\n"
            f"      <TargetTypeValue>{ttv}</TargetTypeValue>\n"
            "    </Targets>\n")


def _build_rich_tags_xml(meta: Dict[str, Any], is_tv: bool, imdb_id: Optional[str]) -> str:
    """
    Build a full Matroska tags document from fetched metadata.

    Movies : TargetTypeValue 50 (TITLE, DATE_RELEASED, GENRE, DIRECTOR, WRITTEN_BY,
             DESCRIPTION, SYNOPSIS, LAW_RATING, RATING, IMDB, TMDB, ACTOR+CHARACTER)
             + TargetTypeValue 70 collection tag when the movie belongs to one.
    TV     : TargetTypeValue 70 show (TITLE, GENRE, NETWORK, LAW_RATING, ACTORs, ids)
             + 60 season (TITLE, PART_NUMBER)
             + 50 episode (TITLE, PART_NUMBER, DATE_RELEASED, DIRECTOR, DESCRIPTION,
               SYNOPSIS, RATING).
    """
    parts: List[str] = ['<?xml version="1.0" encoding="UTF-8"?>\n'
                        '<!DOCTYPE Tags SYSTEM "matroskatags.dtd">\n<Tags>\n']

    if not is_tv:
        parts.append(_open_tag(50))
        parts.append(_simple_tag("TITLE", meta.get("title")))
        parts.append(_simple_tag("DATE_RELEASED", meta.get("date") or meta.get("year")))
        parts.append(_simple_tag("GENRE", ", ".join(meta.get("genres") or [])))
        for d in meta.get("directors") or []:
            parts.append(_simple_tag("DIRECTOR", d))
        for w in meta.get("writers") or []:
            parts.append(_simple_tag("WRITTEN_BY", w))
        parts.append(_actor_tags(meta.get("cast") or []))
        parts.append(_simple_tag("DESCRIPTION", meta.get("description")))
        parts.append(_simple_tag("SYNOPSIS", meta.get("synopsis")))
        parts.append(_simple_tag("LAW_RATING", meta.get("law_rating")))
        parts.append(_simple_tag("RATING", meta.get("rating")))
        parts.append(_simple_tag("IMDB", imdb_id))
        parts.append(_simple_tag("TMDB", meta.get("tmdb_id")))
        parts.append("  </Tag>\n")
        if meta.get("collection"):
            parts.append(_open_tag(70))
            parts.append(_simple_tag("TITLE", meta.get("collection")))
            parts.append("  </Tag>\n")
    else:
        # Show level
        parts.append(_open_tag(70))
        parts.append(_simple_tag("TITLE", meta.get("show")))
        parts.append(_simple_tag("DATE_RELEASED", meta.get("show_year")))
        parts.append(_simple_tag("GENRE", ", ".join(meta.get("genres") or [])))
        parts.append(_simple_tag("NETWORK", meta.get("network")))
        parts.append(_simple_tag("LAW_RATING", meta.get("law_rating")))
        parts.append(_actor_tags(meta.get("cast") or []))
        parts.append(_simple_tag("IMDB", imdb_id))
        parts.append(_simple_tag("TMDB", meta.get("tmdb_id")))
        parts.append("  </Tag>\n")
        # Season level
        if meta.get("season") is not None:
            parts.append(_open_tag(60))
            parts.append(_simple_tag("TITLE", meta.get("season_name")))
            parts.append(_simple_tag("PART_NUMBER", meta.get("season")))
            parts.append("  </Tag>\n")
        # Episode level
        if meta.get("episode") is not None:
            parts.append(_open_tag(50))
            parts.append(_simple_tag("TITLE", meta.get("ep_title")))
            parts.append(_simple_tag("PART_NUMBER", meta.get("episode")))
            parts.append(_simple_tag("DATE_RELEASED", meta.get("airdate")))
            for d in meta.get("directors") or []:
                parts.append(_simple_tag("DIRECTOR", d))
            parts.append(_simple_tag("DESCRIPTION", meta.get("description")))
            parts.append(_simple_tag("SYNOPSIS", meta.get("synopsis")))
            parts.append(_simple_tag("RATING", meta.get("rating")))
            parts.append("  </Tag>\n")

    parts.append("</Tags>\n")
    return "".join(parts)


def clear_mkv_tags(mkv_path: Path, dry_run: bool) -> Result:
    """
    Strip a file bare: replace the global tags with an empty document and
    delete the segment title and every track name. Nothing is written back —
    not even the IMDB id — and no database is consulted (fully offline).
    Embedded cover art is left alone; use --coverart --clear to remove that.
    """
    kind = "tag_clear"
    try:
        meta = mkvmerge_identify_json(mkv_path)
        tracks = extract_tracks(mkv_path, meta)
        attachments: List[Dict[str, Any]] = meta.get("attachments", []) or []

        cmd: List[str] = [str(CFG.MKVPROPEDIT_EXE), str(mkv_path)]
        tags_xml: Optional[Path] = None
        if not dry_run:
            tags_xml = _write_tags_xml(None)          # empty <Tags/> document
            cmd += ["--tags", f"all:{tags_xml}"]
        else:
            cmd += ["--tags", "all:<empty.xml>"]

        cmd += ["--edit", "info", "--delete", "title"]

        # Junk attachments go; cover art is the other mode's business.
        for att in attachments:
            att_id = att.get("id")
            if str(att.get("file_name", "")).lower() in _COVER_ATTACHMENT_NAMES:
                continue
            if att_id is not None:
                cmd += ["--delete-attachment", str(att_id)]

        video_idx = audio_idx = sub_idx = 0
        for t in tracks:
            if t.type == "video":
                video_idx += 1
                cmd += ["--edit", f"track:v{video_idx}", "--delete", "name"]
            elif t.type == "audio":
                audio_idx += 1
                cmd += ["--edit", f"track:a{audio_idx}", "--delete", "name"]
            elif t.type == "subtitles":
                sub_idx += 1
                cmd += ["--edit", f"track:s{sub_idx}", "--delete", "name"]

        if dry_run:
            logging.info("[DRY] Would clear ALL tags, title and track names: %s", mkv_path.name)
            return Result(kind=kind, source_items=[mkv_path], output_path=mkv_path,
                          ok=True, reason="dry-run")

        try:
            r = run_cmd(cmd, timeout_sec=300)
        finally:
            if tags_xml and tags_xml.exists():
                try:
                    tags_xml.unlink()
                except Exception:
                    pass

        if not r.ok and r.rc > 1:
            return Result(kind=kind, source_items=[mkv_path], output_path=None, ok=False,
                          reason=f"mkvpropedit rc={r.rc}: {(r.out or r.err).strip()}")
        logging.info("Tags cleared: %s", mkv_path.name)
        return Result(kind=kind, source_items=[mkv_path], output_path=mkv_path, ok=True)

    except Exception as e:
        logging.exception("Tag clear failed: %s", mkv_path.name)
        return Result(kind=kind, source_items=[mkv_path], output_path=None, ok=False, reason=str(e))


def clean_mkv_tags(mkv_path: Path, dry_run: bool, is_tv: bool = False) -> Result:
    """
    Clean promotional/advertising tags from an MKV in-place using mkvpropedit.

    Changes made:
      Segment info  : title → movie 'Title (Year)'  or  TV 'Show (Year) - S01E01 - Episode Title'
      Global tags   : all cleared; IMDB tag written back if ID found in filename/folder
      Attachments   : all deleted (advertising images, stray fonts)
      Video track   : name → same as segment title
      Audio tracks  : name → '<N> channels'  (e.g. '6 channels')
      Subtitle tracks: name → '' (cleared)

    is_tv=True  uses TV naming conventions (infer_tv_components).
    is_tv=False uses movie naming conventions (default).
    """
    kind = "tag_clean"
    try:
        # --- Identify tracks and attachments ---
        meta = mkvmerge_identify_json(mkv_path)
        tracks = extract_tracks(mkv_path, meta)
        attachments: List[Dict[str, Any]] = meta.get("attachments", []) or []

        # --- Build segment title and extract IMDb ID ---
        if is_tv:
            show_name, season_str, ep_str, ep_title = infer_tv_components(mkv_path)
            # infer_tv_components may leave trailing " - -" artifacts when noise tokens
            # (codec/resolution) were removed from the episode title before space normalization.
            if ep_title:
                ep_title = re.sub(r"[\s.\-–—]+$", "", ep_title).strip() or None
            parts_title: List[str] = [show_name]
            if season_str and ep_str:
                parts_title.append(f"{season_str}{ep_str}")
            if ep_title:
                parts_title.append(ep_title)
            segment_title = " - ".join(parts_title)
            imdb_id = extract_imdb_id_from_tv_path(mkv_path)
            if not imdb_id:
                imdb_id = extract_imdb_from_mkv_tags(mkv_path)
                if imdb_id:
                    logging.debug("IMDB tag read from existing MKV tags (TV): %s -> %s", mkv_path.name, imdb_id)
        else:
            title, year, imdb_id = parse_title_year_imdb_from_filename(mkv_path)
            if not title:
                title, year = infer_movie_name_year_from_path(mkv_path)
            if not imdb_id:
                # Walk filename + parent folder names — folder may carry the IMDB ID even
                # when the filename alone does not (e.g. 'Movie (2026) - tt1234567\file.mkv')
                imdb_id = extract_imdb_id_from_movie_path(mkv_path)
            if not imdb_id:
                # Last resort: read the IMDB tag already embedded in the file's Matroska tags.
                # FileBot writes it there even when the filename format doesn't include it.
                imdb_id = extract_imdb_from_mkv_tags(mkv_path)
                if imdb_id:
                    logging.debug("IMDB tag read from existing MKV tags: %s -> %s", mkv_path.name, imdb_id)
            segment_title = f"{title} ({year})" if year else (title or mkv_path.stem)

        # --- Fetch rich metadata (TMDB primary, OMDb supplement) ---
        # Enabled whenever API keys are configured; --no-fetch-tags disables it.
        # Failures fall back to the basic (IMDB-only) tags — never fatal, and
        # dry runs stay offline.
        rich_xml_text: Optional[str] = None
        rich: Optional[Dict[str, Any]] = None
        if not dry_run and _FETCH_TAGS_ENABLED and (CFG.TMDB_API_KEY or CFG.OMDB_API_KEY):
            try:
                if is_tv:
                    s_num = int(season_str[1:]) if season_str else None
                    e_num = int(ep_str[1:]) if ep_str else None
                    rich = _get_meta_fetcher().episode_metadata(show_name, imdb_id, s_num, e_num)
                else:
                    if not imdb_id:
                        # No id on the file yet. A film is tagged only once it is one
                        # verified film — never with whatever a title search ranks
                        # first, which for an unidentified (or LOCAL) film would be
                        # another film's cast and synopsis.
                        imdb_id, _cands = resolve_movie_imdb_id(title, year)
                    rich = (_get_meta_fetcher().movie_metadata(title, year, imdb_id,
                                                               allow_title_search=False)
                            if imdb_id else None)
                if rich:
                    rich_xml_text = _build_rich_tags_xml(rich, is_tv=is_tv, imdb_id=imdb_id)
                    logging.info("Tags enriched: %s | genre=%s | director=%s | actors=%d",
                                 mkv_path.name,
                                 ", ".join((rich.get("genres") or [])[:3]) or "-",
                                 ", ".join(rich.get("directors") or []) or "-",
                                 len(rich.get("cast") or []))
                else:
                    logging.debug("No rich metadata found for: %s", mkv_path.name)
            except Exception as e:
                logging.warning("Metadata fetch failed (non-fatal, basic tags used): %s | %s",
                                mkv_path.name, e)

        if imdb_id:
            logging.info("Cleaning tags [%s]: %s -> title='%s'  imdb=%s",
                         "tv" if is_tv else "movie", mkv_path.name, segment_title, imdb_id)
        else:
            logging.info("Cleaning tags [%s]: %s -> title='%s'  (no IMDb ID found)",
                         "tv" if is_tv else "movie", mkv_path.name, segment_title)

        # --- Build mkvpropedit command ---
        # Use plain str() for paths — mkvpropedit doesn't accept the \\?\ prefix.
        cmd: List[str] = [str(CFG.MKVPROPEDIT_EXE), str(mkv_path)]

        # 1. Replace ALL global tags with a clean XML.
        #    Clears promotional tags (AUTHOR, SUMMARY, WEBSITE, Comment, etc.)
        #    and writes back the IMDb tag if the ID was found in the filename.
        tags_xml: Optional[Path] = None
        if not dry_run:
            tags_xml = _write_tags_xml(imdb_id, xml_text=rich_xml_text)
            cmd += ["--tags", f"all:{tags_xml}"]
        else:
            placeholder = f"tags_imdb={imdb_id}" if imdb_id else "tags_empty"
            cmd += ["--tags", f"all:<{placeholder}.xml>"]

        # 2. Set segment title only. Description/Copyright/Comment are tags,
        #    not segment-info properties — they are already wiped by step 1.
        #    Only 'title' and 'date' are valid --edit info properties.
        cmd += [
            "--edit", "info",
            "--set", f"title={segment_title}",
        ]

        # 3. Delete all attachments (advertising images, stray fonts, etc.).
        #    Selector is plain numeric ID from mkvmerge -J (0-based per mkvpropedit docs).
        #    Embedded cover art (cover.jpg etc., per Matroska convention) is legitimate
        #    metadata written by the --coverart mode — never delete it.
        for att in attachments:
            att_id = att.get("id")
            att_name = str(att.get("file_name", "")).lower()
            if att_name in _COVER_ATTACHMENT_NAMES:
                continue
            if att_id is not None:
                cmd += ["--delete-attachment", str(att_id)]

        # 4. Set per-track names — and fix the video track language, which
        #    encoders usually leave as 'und'. A --force-video-lang value wins;
        #    otherwise the title's original language from TMDB is used.
        video_lang: Optional[str] = _FORCE_VIDEO_LANG
        if video_lang is None and rich and rich.get("orig_lang"):
            video_lang = iso1_to_iso2(str(rich["orig_lang"]))

        video_idx = audio_idx = sub_idx = 0
        for t in tracks:
            if t.type == "video":
                video_idx += 1
                cmd += ["--edit", f"track:v{video_idx}",
                        "--set", f"name={segment_title}"]
                if video_lang:
                    cmd += ["--set", f"language={video_lang}"]

            elif t.type == "audio":
                audio_idx += 1
                ch = int(t.channels or 0)
                ch_label = f"{ch} channels" if ch else "audio"
                cmd += ["--edit", f"track:a{audio_idx}",
                        "--set", f"name={ch_label}"]

            elif t.type == "subtitles":
                sub_idx += 1
                cmd += ["--edit", f"track:s{sub_idx}",
                        "--set", "name="]

        if dry_run:
            logging.info("[DRY] mkvpropedit command: %s", " ".join(cmd))
            return Result(kind=kind, source_items=[mkv_path], output_path=mkv_path,
                          ok=True, reason="dry-run")

        try:
            r = run_cmd(cmd, timeout_sec=300)
        finally:
            # Always clean up the temp XML regardless of outcome
            if tags_xml and tags_xml.exists():
                try:
                    tags_xml.unlink()
                except Exception:
                    pass

        if not r.ok:
            # mkvpropedit writes errors to stdout, not stderr.
            detail = (r.out or r.err or "").strip()
            # rc=1 means warnings only — operation still applied; treat as non-fatal.
            if r.rc > 1:
                return Result(kind=kind, source_items=[mkv_path], output_path=None,
                              ok=False, reason=f"mkvpropedit rc={r.rc}: {detail}")
            logging.warning("mkvpropedit warning (rc=1, continuing): %s", detail)

        logging.info("Tags cleaned OK: %s", mkv_path.name)
        return Result(kind=kind, source_items=[mkv_path], output_path=mkv_path, ok=True)

    except Exception as e:
        logging.exception("Tag clean failed: %s", mkv_path.name)
        return Result(kind=kind, source_items=[mkv_path], output_path=None,
                      ok=False, reason=str(e))


def _insert_imdb_into_filename(p: Path, imdb_id: str) -> Path:
    """
    Rename a file in-place to add the IMDB ID after 'Title (Year)' in the filename.

    Input:  The Sequel (2022) - BRRip.1080p.x265 - [Hindi + English].mkv
    Output: The Sequel (2022) - tt1234567 - BRRip.1080p.x265 - [Hindi + English].mkv

    If the IMDB ID is already present, the file is left untouched.
    Returns the new Path (or the original if nothing changed / rename failed).
    """
    stem = p.stem
    # Already has it — nothing to do
    if re.search(r"\btt\d{6,9}\b", stem, re.IGNORECASE):
        return p

    # Insert after 'Title (Year)' — find the first ' - ' separator
    m = re.match(r"^(.+?\(\d{4}\))(.*)", stem)
    if not m:
        # No year found — append before the first ' - '
        idx = stem.find(" - ")
        if idx == -1:
            new_stem = f"{stem} - {imdb_id}"
        else:
            new_stem = f"{stem[:idx]} - {imdb_id}{stem[idx:]}"
    else:
        title_year = m.group(1)        # "The Sequel (2022)"
        rest       = m.group(2)        # " - BRRip.1080p.x265 - [Hindi + English]"
        # Drop an existing leading ' - ' from rest so we can re-join cleanly
        rest_clean = re.sub(r"^\s*-\s*", "", rest)
        new_stem   = f"{title_year} - {imdb_id} - {rest_clean}" if rest_clean else f"{title_year} - {imdb_id}"

    new_stem = re.sub(r"\s+-\s+-\s+", " - ", new_stem)   # collapse double separators
    new_name = sanitize_filename(new_stem) + p.suffix
    new_path = p.parent / new_name
    if new_path == p:
        return p
    try:
        p.rename(new_path)
        logging.info("Inserted IMDB into filename: %s -> %s", p.name, new_path.name)
        return new_path
    except Exception as exc:
        logging.warning("Failed to rename for IMDB insert (%s): %s", p.name, exc)
        return p


def _cleantags_one(
    mkv_path: Path,
    is_tv: bool,
    dry_run: bool,
    skip_filebot: bool = False,
    clear_all: bool = False,
) -> Result:
    """
    Full cleantags sequence for a single file:
      1. clean_mkv_tags        — strip junk tags, write clean segment title + IMDB tag
      2. FileBot rename        — identify via DB using clean title as --query, rename in-place
         Fallback (no FileBot) — insert IMDB ID directly into the filename via Python rename
      3. clean_mkv_tags        — update segment title to match the final filename
    """
    kind = "tag_clean"

    # --clear: strip everything and stop — no metadata, no FileBot rename.
    if clear_all:
        return clear_mkv_tags(mkv_path, dry_run=dry_run)

    # Step 1: clean tags — also resolves the clean title / IMDB we'll need below
    ct = clean_mkv_tags(mkv_path, dry_run=dry_run, is_tv=is_tv)
    if not ct.ok:
        return ct

    current = mkv_path  # will be updated if the file gets renamed
    # False when a film could not be pinned to one IMDB id. A follow-on step such
    # as cover art must not then guess by title: the poster of whichever film the
    # database happened to rank first is as wrong as a wrong rename would be.
    identified = True
    outcome: Dict[str, Any] = {}     # what the rename step did (see _with_rename_outcome)

    if not skip_filebot and not dry_run:
        # Extract clean title and IMDB so we can use them whether FileBot runs or not
        if is_tv:
            show_name, _s, _e, _t = infer_tv_components(mkv_path)
            query    = show_name
            db       = "TheTVDB"
            fmt      = TV_FILEBOT_FORMAT
            imdb_id  = extract_imdb_id_from_tv_path(mkv_path) or extract_imdb_from_mkv_tags(mkv_path)
        else:
            title, year, imdb_id = parse_title_year_imdb_from_filename(mkv_path)
            if not title:
                title, year = infer_movie_name_year_from_path(mkv_path)
            if not imdb_id:
                imdb_id = extract_imdb_id_from_movie_path(mkv_path) or extract_imdb_from_mkv_tags(mkv_path)
            query = f"{title} ({year})" if year else (title or mkv_path.stem)
            db    = CFG.FILEBOT_DB
            fmt   = MOVIE_FILEBOT_FORMAT

        filebot_ok = False
        if is_tv:
            if CFG.FILEBOT_EXE.exists() and not _FILEBOT_DISABLED:
                logging.info("cleantags FileBot rename: %s  (query=%s)", mkv_path.name, query)
                fb = run_filebot_rename_final_mkv(mkv_path, db=db, filebot_format=fmt,
                                                  dry_run=False, query=query, outcome=outcome)
                if fb and fb.exists() and fb != mkv_path:
                    logging.info("cleantags FileBot renamed -> %s", fb.name)
                    current    = fb
                    filebot_ok = True
        else:
            # A film must be pinned to one IMDB id before it may be renamed; several
            # releases can share a title and a year, and the wrong pick rewrites
            # tags. One that no database knows is named from its own file instead.
            ident = movie_identity_chain(mkv_path, title or mkv_path.stem, year, imdb_id)
            identified = bool(ident.imdb)
            logging.info("cleantags rename: %s  (query=%s)", mkv_path.name, query)
            fb = rename_movie_when_identified(mkv_path, query, title or mkv_path.stem, year,
                                              imdb_id, outcome, ident=ident)
            if fb and fb.exists() and fb != mkv_path:
                logging.info("cleantags renamed -> %s", fb.name)
                current    = fb
                filebot_ok = True
            elif not ident.imdb and not outcome.get("local"):
                logging.warning("cleantags: leaving %s unrenamed — %s", mkv_path.name,
                                outcome.get("reason") or ident.reason)

        if not filebot_ok and not is_tv and imdb_id:
            # FileBot unavailable or failed — insert the IMDB ID into the filename directly
            logging.info("FileBot unavailable; inserting IMDB ID into filename: %s", mkv_path.name)
            current = _insert_imdb_into_filename(current, imdb_id)

        # Step 3: re-run cleantags so segment title matches the final filename
        if current.exists():
            ct2 = clean_mkv_tags(current, dry_run=False, is_tv=is_tv)
            if not ct2.ok:
                logging.warning("cleantags (post-rename) failed (non-fatal): %s", ct2.reason)

    elif not skip_filebot and dry_run and not is_tv:
        # A dry run renames nothing, but it must still report which films the real
        # run would refuse — that is where the numbered candidates come from, and
        # without it "dry run, read the numbers, then --pick" cannot work. The
        # lookups are read-only, so G3 still holds.
        p_title, p_year, p_imdb = parse_title_year_imdb_from_filename(mkv_path)
        if not p_title:
            p_title, p_year = infer_movie_name_year_from_path(mkv_path)
        if not p_imdb:
            p_imdb = extract_imdb_id_from_movie_path(mkv_path) or extract_imdb_from_mkv_tags(mkv_path)
        ident = movie_identity_chain(mkv_path, p_title or mkv_path.stem, p_year, p_imdb)
        if not ident.imdb:
            identified = False
            local_name = ""
            if ident.status == "none" and CFG.LOCAL_NAME_FALLBACK:
                local_name, problem = local_movie_name(mkv_path, p_title or mkv_path.stem, p_year)
                if local_name:
                    outcome["local"], outcome["local_name"] = True, local_name
                    logging.info("[DRY] cleantags: no database knows %s — would name it from the "
                                 "file alone (LOCAL): %s", mkv_path.name, local_name)
                else:
                    logging.warning("[DRY] cleantags would leave %s unrenamed — %s; %s",
                                    mkv_path.name, ident.reason, problem)
            else:
                logging.warning("[DRY] cleantags would leave %s unrenamed — %s",
                                mkv_path.name, ident.reason)

    details: Dict[str, Any] = {"is_tv": is_tv, "identified": identified}
    if outcome.get("local"):
        details["local_named"] = outcome.get("local_name") or "yes"
    return Result(kind=kind, source_items=[mkv_path], output_path=current, ok=True,
                  details=details)


def run_cleantags_pipeline(
    do_movies: bool,
    do_tv: bool,
    dry_run: bool,
    workers: int,
    movies_root: Optional[Path] = None,
    tv_root: Optional[Path] = None,
    skip_filebot: bool = False,
    filters: Optional[List[str]] = None,
    clear_all: bool = False,
) -> List[Result]:
    """Scan Movies/TV roots, clean tags, and rename via FileBot on every MKV found
    (or, with clear_all, strip every tag and leave the file bare)."""
    movies_root = movies_root or CFG.MOVIES_ROOT
    tv_root     = tv_root     or CFG.TV_ROOT
    targets: List[Path] = []
    if do_movies:
        found = apply_scan_filters(scan_mkvs(movies_root), movies_root, filters, "cleantags")
        logging.info("cleantags - Movies: %d MKV(s) found in %s.", len(found), movies_root)
        targets.extend(found)
    if do_tv:
        found = apply_scan_filters(scan_mkvs(tv_root), tv_root, filters, "cleantags")
        logging.info("cleantags - TV: %d MKV(s) found in %s.", len(found), tv_root)
        targets.extend(found)

    # Build (path, is_tv) pairs
    tagged_targets: List[Tuple[Path, bool]] = []
    for p in targets:
        try:
            p.relative_to(tv_root or CFG.TV_ROOT)
            is_tv = True
        except ValueError:
            is_tv = False
        tagged_targets.append((p, is_tv))

    results: List[Result] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(_cleantags_one, p, is_tv, dry_run, skip_filebot, clear_all): p
            for p, is_tv in tagged_targets
        }
        for fut in concurrent.futures.as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as e:
                p = futs[fut]
                logging.exception("cleantags worker crashed: %s", p)
                results.append(Result(kind="tag_clean", source_items=[p],
                                      output_path=None, ok=False,
                                      reason=f"Worker exception: {e}"))
    return results


# =========================
# Cover art (--coverart mode)
# =========================

# Matroska cover-art attachment names (spec convention; "cover.jpg" is the front cover).
# Used both to detect existing covers and to protect them from cleantags deletion.
_COVER_ATTACHMENT_NAMES = (
    "cover.jpg", "cover.png", "cover.webp",
    "cover_land.jpg", "cover_land.png",
    "small_cover.jpg", "small_cover.png",
)

# Local poster files checked next to the MKV (first match wins).
_LOCAL_POSTER_NAMES = ("poster", "cover", "folder")
_LOCAL_POSTER_EXTS = (".jpg", ".jpeg", ".png")

# TMDB pre-sized poster (780x1170 for 2:3 posters) — no local image resize needed.
_TMDB_IMG_BASE = "https://image.tmdb.org/t/p/w780"

_HTTP_USER_AGENT = "MediaCleanup/1.0"


def mkv_cover_attachments(meta: Dict[str, Any]) -> Tuple[List[int], bool]:
    """
    Return (cover_attachment_ids, written_by_us).
    written_by_us is True when any cover attachment carries the description
    'Cover art' — the marker this script sets when embedding. Covers without
    it came with the file (third-party) and are fair game for replacement.
    """
    ids: List[int] = []
    ours = False
    for att in meta.get("attachments", []) or []:
        name = str(att.get("file_name", "")).lower()
        if name in _COVER_ATTACHMENT_NAMES:
            aid = att.get("id")
            if aid is not None:
                ids.append(int(aid))
            if str(att.get("description", "")).strip().lower() == "cover art":
                ours = True
    return ids, ours


# Ledger of files whose cover art this script has embedded. Default --coverart
# runs skip ledger entries instantly (no mkvmerge/API calls); --coverart-overwrite
# ignores it and re-embeds. Stale rows (file gone) are pruned on save.
COVERART_LEDGER_CSV = _SCRIPT_DIR / "logs" / "coverart_done.csv"


class CoverartLedger:
    """Thread-safe persistent record: path -> (size, date, source)."""

    def __init__(self, csv_path: Path = COVERART_LEDGER_CSV) -> None:
        self._csv_path = csv_path
        self._lock = threading.Lock()
        self._entries: Dict[str, Tuple[int, str, str]] = {}  # lower path -> (size, date, source)
        self._load()

    def _load(self) -> None:
        import csv
        if not self._csv_path.exists():
            return
        try:
            with self._csv_path.open("r", newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    try:
                        self._entries[str(row["path"]).lower()] = (
                            int(row["size"]), str(row.get("date", "")), str(row.get("source", "")))
                    except (KeyError, TypeError, ValueError):
                        continue
            logging.debug("Coverart ledger loaded: %d entries", len(self._entries))
        except Exception as e:
            logging.warning("Could not read coverart ledger (starting fresh): %s", e)

    def has(self, mkv: Path) -> bool:
        """True when the file is recorded AND its size still matches (a remux/replace invalidates it)."""
        with self._lock:
            entry = self._entries.get(str(mkv).lower())
        if entry is None:
            return False
        try:
            return mkv.stat().st_size == entry[0]
        except OSError:
            return False

    def add(self, mkv: Path, source: str) -> None:
        try:
            size = mkv.stat().st_size
        except OSError:
            return
        with self._lock:
            self._entries[str(mkv).lower()] = (
                size, _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), source)

    def remove(self, mkv: Path) -> None:
        """Forget a file so a later --coverart run fetches it again."""
        with self._lock:
            self._entries.pop(str(mkv).lower(), None)

    def save(self) -> None:
        """Rewrite the CSV, pruning rows whose files no longer exist."""
        import csv
        with self._lock:
            entries = dict(self._entries)
        kept = {p: v for p, v in entries.items() if Path(p).exists()}
        pruned = len(entries) - len(kept)
        try:
            self._csv_path.parent.mkdir(parents=True, exist_ok=True)
            with self._csv_path.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["path", "size", "date", "source"])
                for p, (size, date, source) in sorted(kept.items()):
                    w.writerow([p, size, date, source])
            logging.debug("Coverart ledger saved: %d entries (%d stale pruned)", len(kept), pruned)
        except Exception as e:
            logging.warning("Could not save coverart ledger (non-fatal): %s", e)


def find_local_poster(mkv_path: Path, is_tv: bool) -> Optional[Path]:
    """
    Look for a manual poster file next to the MKV: poster/cover/folder + .jpg/.jpeg/.png.
    Movies: same folder only (a poster in a shared folder applies to every MKV in it).
    TV: episode's folder, then one level up (Season xx -> show folder).
    """
    dirs = [mkv_path.parent]
    if is_tv and mkv_path.parent.parent != mkv_path.parent:
        dirs.append(mkv_path.parent.parent)
    for d in dirs:
        for base in _LOCAL_POSTER_NAMES:
            for ext in _LOCAL_POSTER_EXTS:
                p = d / f"{base}{ext}"
                if p.is_file():
                    return p
    return None


def _http_get_json(url: str, timeout: int = 30) -> Optional[Dict[str, Any]]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _HTTP_USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:
        logging.debug("HTTP GET failed: %s | %s", url, e)
        return None


def _public_https_url(url: str) -> bool:
    """
    True for an https URL that points at a public host. Image and subtitle links come from
    third-party API answers, so they are not trusted blindly: plain http, localhost and
    private, loopback or link-local addresses (anything on the user's own network) are refused.
    """
    import ipaddress
    import socket
    try:
        parts = urllib.parse.urlparse(url)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return False
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)]
        except (OSError, ValueError):
            return True               # it will not resolve for the request either, so that fails on its own
    return not any(a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast
                   or a.is_unspecified for a in addresses)


class _PublicHttpsRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only if it still points at a public https host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _public_https_url(newurl):
            raise urllib.error.URLError(f"refused a redirect to a non-public or non-https address: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_PUBLIC_OPENER = urllib.request.build_opener(_PublicHttpsRedirects())


def _http_get_bytes(url: str, timeout: int = 60) -> Optional[bytes]:
    if not _public_https_url(url):
        logging.warning("Not downloading %s: only public https addresses are fetched.", redact_secrets(url))
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _HTTP_USER_AGENT})
        with _PUBLIC_OPENER.open(req, timeout=timeout) as resp:
            data = resp.read()
        return data if data else None
    except Exception as e:
        logging.debug("HTTP download failed: %s | %s", url, e)
        return None


def poster_lang_preference(audio_canon_langs: List[str]) -> List[str]:
    """
    Poster language priority: English always first, then the file's own audio
    languages (Hindi/Telugu as detected), then textless posters ('null' at TMDB).
    """
    pref = ["en"]
    for canon in audio_canon_langs:
        iso1 = iso2_to_iso1(canon)
        if iso1 and iso1 not in pref:
            pref.append(iso1)
    pref.append("null")
    return pref


def _maybe_downscale_poster(data: bytes, max_width: int = 1000) -> bytes:
    """
    Downscale oversized posters (e.g. full-res local files) to ~1000px wide JPEG.
    Pillow is an OPTIONAL dependency: if it isn't installed, the image is embedded
    as-is. TMDB w780 images never need this.
    """
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return data
    try:
        import io
        img = Image.open(io.BytesIO(data))
        if img.width <= max_width:
            return data
        new_h = max(1, int(img.height * max_width / img.width))
        img = img.convert("RGB").resize((max_width, new_h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88)
        out = buf.getvalue()
        logging.debug("Poster downscaled: %d KB -> %d KB", len(data) // 1024, len(out) // 1024)
        return out
    except Exception as e:
        logging.debug("Poster downscale skipped: %s", e)
        return data


class CoverArtFetcher:
    """
    Fetches poster images via the source chain: TMDB -> fanart.tv -> OMDb.
    (Local poster files are handled by the caller before this runs.)

    Thread-safe; results are cached per movie/show for the run, so every episode
    of a series reuses one downloaded show poster (and repeated failures are not
    retried). Sources with an empty API key are skipped.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # cache: key -> (image_bytes | None, source_label)
        self._cache: Dict[str, Tuple[Optional[bytes], str]] = {}

    # ---------- TMDB ----------

    def _tmdb_find_by_imdb(self, imdb_id: str) -> Tuple[Optional[int], Optional[int]]:
        """Resolve an IMDB id to TMDB ids. Returns (movie_id, tv_id)."""
        url = (f"https://api.themoviedb.org/3/find/{urllib.parse.quote(imdb_id)}"
               f"?api_key={CFG.TMDB_API_KEY}&external_source=imdb_id")
        data = _http_get_json(url)
        if not data:
            return None, None
        movies = data.get("movie_results") or []
        shows = data.get("tv_results") or []
        return (movies[0].get("id") if movies else None,
                shows[0].get("id") if shows else None)

    def _tmdb_search(self, title: str, year: Optional[str], is_tv: bool) -> Optional[int]:
        return _tmdb_search_best(title, year, is_tv)

    def _tmdb_pick_poster_url(self, tmdb_id: int, is_tv: bool, lang_pref: List[str]) -> Optional[str]:
        """Pick the best poster by language preference, then TMDB vote score."""
        kind = "tv" if is_tv else "movie"
        url = f"https://api.themoviedb.org/3/{kind}/{tmdb_id}/images?api_key={CFG.TMDB_API_KEY}"
        data = _http_get_json(url)
        posters = (data or {}).get("posters") or []
        if not posters:
            return None

        def rank(p: Dict[str, Any]) -> Tuple[int, float]:
            lang = p.get("iso_639_1") or "null"
            try:
                li = lang_pref.index(lang)
            except ValueError:
                li = len(lang_pref) + 1  # language not in preference list: last resort
            return (li, -float(p.get("vote_average") or 0.0))

        best = min(posters, key=rank)
        fp = best.get("file_path")
        if fp:
            logging.debug("TMDB poster picked: lang=%s votes=%s %s",
                          best.get("iso_639_1"), best.get("vote_average"), fp)
            return f"{_TMDB_IMG_BASE}{fp}"
        return None

    def _tmdb_tv_tvdb_id(self, tmdb_tv_id: int) -> Optional[int]:
        """fanart.tv keys TV shows by TheTVDB id; TMDB can translate."""
        url = f"https://api.themoviedb.org/3/tv/{tmdb_tv_id}/external_ids?api_key={CFG.TMDB_API_KEY}"
        data = _http_get_json(url)
        return (data or {}).get("tvdb_id") or None

    # ---------- fanart.tv ----------

    @staticmethod
    def _fanart_rank(items: List[Dict[str, Any]], lang_pref: List[str]) -> Optional[str]:
        if not items:
            return None

        def rank(p: Dict[str, Any]) -> Tuple[int, int]:
            lang = (p.get("lang") or "00").lower()
            if lang == "00":  # fanart.tv's code for textless
                lang = "null"
            try:
                li = lang_pref.index(lang)
            except ValueError:
                li = len(lang_pref) + 1
            try:
                likes = int(p.get("likes") or 0)
            except (TypeError, ValueError):
                likes = 0
            return (li, -likes)

        return min(items, key=rank).get("url")

    def _fanarttv_movie_poster_url(self, movie_id: str, lang_pref: List[str]) -> Optional[str]:
        """movie_id: IMDB id (ttNNN) or TMDB id — fanart.tv accepts both."""
        url = (f"https://webservice.fanart.tv/v3/movies/{urllib.parse.quote(movie_id)}"
               f"?api_key={CFG.FANARTTV_API_KEY}")
        data = _http_get_json(url)
        return self._fanart_rank((data or {}).get("movieposter") or [], lang_pref)

    def _fanarttv_show_poster_url(self, tvdb_id: int, lang_pref: List[str]) -> Optional[str]:
        url = f"https://webservice.fanart.tv/v3/tv/{tvdb_id}?api_key={CFG.FANARTTV_API_KEY}"
        data = _http_get_json(url)
        return self._fanart_rank((data or {}).get("tvposter") or [], lang_pref)

    # ---------- OMDb ----------

    def _omdb_poster_url(self, imdb_id: str) -> Optional[str]:
        url = f"https://www.omdbapi.com/?i={urllib.parse.quote(imdb_id)}&apikey={CFG.OMDB_API_KEY}"
        data = _http_get_json(url)
        poster = (data or {}).get("Poster")
        return poster if poster and poster != "N/A" else None

    # ---------- public API ----------

    def fetch_movie_poster(
        self, title: Optional[str], year: Optional[str], imdb_id: Optional[str],
        lang_pref: List[str],
    ) -> Tuple[Optional[bytes], str]:
        cache_key = f"movie:{(imdb_id or f'{title}|{year}' or '').lower()}"
        with self._lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

        img: Optional[bytes] = None
        source = "none"
        tmdb_id: Optional[int] = None

        if CFG.TMDB_API_KEY:
            # By id only. This used to fall back to a title search and take the top
            # hit, which for a title shared by several films embedded the wrong
            # film's poster; callers must now pin the film to an IMDB id first.
            if imdb_id:
                tmdb_id, _tv = self._tmdb_find_by_imdb(imdb_id)
            if tmdb_id is not None:
                purl = self._tmdb_pick_poster_url(tmdb_id, is_tv=False, lang_pref=lang_pref)
                if purl:
                    img = _http_get_bytes(purl)
                    source = "TMDB"

        if img is None and CFG.FANARTTV_API_KEY and (imdb_id or tmdb_id is not None):
            purl = self._fanarttv_movie_poster_url(imdb_id or str(tmdb_id), lang_pref)
            if purl:
                img = _http_get_bytes(purl)
                source = "fanart.tv"

        if img is None and CFG.OMDB_API_KEY and imdb_id:
            purl = self._omdb_poster_url(imdb_id)
            if purl:
                img = _http_get_bytes(purl)
                source = "OMDb"

        result = (img, source if img is not None else "none")
        with self._lock:
            self._cache[cache_key] = result
        return result

    def fetch_show_poster(
        self, show_name: str, imdb_id: Optional[str], lang_pref: List[str],
        tmdb_tv_id: Optional[int] = None,
    ) -> Tuple[Optional[bytes], str]:
        """
        One show poster per series per run (cached), embedded into every episode.

        By id only. A series is identified by the caller (tv_show_identity) and
        passed in; this method used to search by title itself — year-strict, so a
        renewed show got no poster, and unconstrained when no year was parsed, so
        a title shared by several series got whichever the database ranked first.
        """
        cache_key = f"tv:{(imdb_id or (str(tmdb_tv_id) if tmdb_tv_id else show_name) or '').lower()}"
        with self._lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

        img: Optional[bytes] = None
        source = "none"

        if CFG.TMDB_API_KEY:
            if tmdb_tv_id is None and imdb_id:
                _mv, tmdb_tv_id = self._tmdb_find_by_imdb(imdb_id)
            if tmdb_tv_id is not None:
                purl = self._tmdb_pick_poster_url(tmdb_tv_id, is_tv=True, lang_pref=lang_pref)
                if purl:
                    img = _http_get_bytes(purl)
                    source = "TMDB"

        if img is None and CFG.FANARTTV_API_KEY and CFG.TMDB_API_KEY and tmdb_tv_id is not None:
            tvdb_id = self._tmdb_tv_tvdb_id(tmdb_tv_id)
            if tvdb_id:
                purl = self._fanarttv_show_poster_url(tvdb_id, lang_pref)
                if purl:
                    img = _http_get_bytes(purl)
                    source = "fanart.tv"

        if img is None and CFG.OMDB_API_KEY and imdb_id:
            purl = self._omdb_poster_url(imdb_id)
            if purl:
                img = _http_get_bytes(purl)
                source = "OMDb"

        result = (img, source if img is not None else "none")
        with self._lock:
            self._cache[cache_key] = result
        return result


# =========================
# Metadata fetching (rich MKV tags) & API key validation
# =========================

# Rich tag fetching is on by default when API keys are configured;
# --no-fetch-tags sets this to False in main().
_FETCH_TAGS_ENABLED: bool = True

# --force-video-lang: canonical ISO 639-2 code to stamp on video tracks during
# tag cleaning, overriding the TMDB original_language. Set in main().
_FORCE_VIDEO_LANG: Optional[str] = None


def _http_get_json_status(url: str, timeout: int = 30) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    """Like _http_get_json but also returns the HTTP status (for key validation)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _HTTP_USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        logging.debug("HTTP GET failed: %s | %s", url, e)
        return None, None


def validate_api_keys() -> Dict[str, str]:
    """
    Check each configured [coverart] API key with one cheap call.
    Returns {source: 'ok' | 'invalid' | 'network error' | 'not configured'}.
    Uses tt0063350 (a public-domain film) as an always-existing probe title.
    """
    status: Dict[str, str] = {}

    if not CFG.TMDB_API_KEY:
        status["TMDB"] = "not configured"
    else:
        code, _ = _http_get_json_status(
            f"https://api.themoviedb.org/3/configuration?api_key={CFG.TMDB_API_KEY}")
        status["TMDB"] = "ok" if code == 200 else ("invalid" if code == 401 else "network error")

    if not CFG.FANARTTV_API_KEY:
        status["fanart.tv"] = "not configured"
    else:
        code, _ = _http_get_json_status(
            f"https://webservice.fanart.tv/v3/movies/tt0063350?api_key={CFG.FANARTTV_API_KEY}")
        status["fanart.tv"] = "ok" if code == 200 else ("invalid" if code == 401 else "network error")

    if not CFG.OMDB_API_KEY:
        status["OMDb"] = "not configured"
    else:
        code, data = _http_get_json_status(
            f"https://www.omdbapi.com/?i=tt0063350&apikey={CFG.OMDB_API_KEY}")
        if code == 200 and data and data.get("Response") == "True":
            status["OMDb"] = "ok"
        elif code == 401 or (data and "invalid api key" in str(data.get("Error", "")).lower()):
            status["OMDb"] = "invalid"
        else:
            status["OMDb"] = "network error"

    # Only the API key is needed for OpenSubtitles; the login is optional (see check_opensubtitles).
    status["OpenSubs"] = check_opensubtitles()

    return status


def disable_invalid_api_keys() -> None:
    """
    Validate configured keys once at run start; blank out definitively-invalid
    ones (HTTP 401) in CFG so every worker doesn't fail per-file. Network errors
    are transient — sources are left enabled.
    """
    global CFG
    status = validate_api_keys()
    replace: Dict[str, str] = {}
    key_field = {"TMDB": "TMDB_API_KEY", "fanart.tv": "FANARTTV_API_KEY",
                 "OMDb": "OMDB_API_KEY", "OpenSubs": "OS_API_KEY"}
    for source, st in status.items():
        if st == "invalid":
            logging.warning("API key/credentials for %s are INVALID — source disabled for this run. "
                            "Fix them in %s (verify with --validate-keys).",
                            source, CONFIG_FILE.name)
            field = key_field.get(source)
            if field:
                replace[field] = ""
        elif st == "network error":
            logging.warning("API key check for %s hit a network error — leaving the source enabled.", source)
    if replace:
        CFG = dataclasses.replace(CFG, **replace)


class MetadataFetcher:
    """
    Fetches movie/TV metadata for rich MKV tagging (cleantags enrichment).

    TMDB is the primary source (details + credits + certifications in one call);
    OMDb supplements the US certification (LAW_RATING) and IMDB rating (RATING)
    when TMDB lacks them. Thread-safe; every lookup is cached for the run, so a
    full season costs one show call + one season call regardless of episode count.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: Dict[str, Any] = {}

    def _cached(self, key: str, fetch) -> Any:
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        val = fetch()
        with self._lock:
            self._cache[key] = val
        return val

    # ---------- shared TMDB lookups ----------

    def _tmdb_ids_for_imdb(self, imdb_id: str) -> Tuple[Optional[int], Optional[int]]:
        url = (f"https://api.themoviedb.org/3/find/{urllib.parse.quote(imdb_id)}"
               f"?api_key={CFG.TMDB_API_KEY}&external_source=imdb_id")
        data = _http_get_json(url)
        if not data:
            return None, None
        movies = data.get("movie_results") or []
        shows = data.get("tv_results") or []
        return (movies[0].get("id") if movies else None,
                shows[0].get("id") if shows else None)

    def _tmdb_search_id(self, title: str, year: Optional[str], is_tv: bool) -> Optional[int]:
        return _tmdb_search_best(title, year, is_tv)

    @staticmethod
    def _top_cast(credits: Dict[str, Any], limit: int = 10) -> List[Tuple[str, str]]:
        cast = (credits or {}).get("cast") or []
        return [(str(c.get("name") or ""), str(c.get("character") or "")) for c in cast[:limit]]

    # ---------- movies ----------

    @staticmethod
    def _omdb_movie_metadata(imdb_id: str, title: Optional[str],
                             year: Optional[str]) -> Optional[Dict[str, Any]]:
        """
        Tags for a film TMDB does not carry, from OMDb's record of its IMDB id.

        Thinner than TMDB's (no collection, no original language), and only ever
        asked for by id: what OMDb returns here is the film itself, not a guess.
        """
        rec = _omdb_movie_by_id(imdb_id)
        if not rec:
            return None

        def listed(key: str) -> List[str]:
            return [x.strip() for x in str(rec.get(key) or "").split(",")
                    if x.strip() and x.strip() != "N/A"]

        def value(key: str) -> Optional[str]:
            v = str(rec.get(key) or "").strip()
            return None if v in ("", "N/A") else v

        plot = value("Plot") or ""
        return {
            "title": rec.get("Title") or title,
            "year": str(rec.get("Year") or "")[:4] or year,
            "date": None,
            "genres": listed("Genre"),
            "directors": listed("Director")[:5],
            "writers": listed("Writer")[:5],
            "cast": [(n, "") for n in listed("Actors")[:10]],
            "description": (plot[:250] + "…" if len(plot) > 250 else plot) or None,
            "synopsis": plot or None,
            "law_rating": value("Rated"),
            "rating": value("imdbRating"),
            "collection": None,
            "orig_lang": None,
            "imdb_id": imdb_id,
            "tmdb_id": None,
        }

    def movie_metadata(self, title: Optional[str], year: Optional[str],
                       imdb_id: Optional[str],
                       allow_title_search: bool = True) -> Optional[Dict[str, Any]]:
        """
        Rich metadata for a film.

        With an id, the film is looked up by it — on TMDB, then on OMDb — and
        never by title: if no database carries the id, there is no metadata,
        because a title search could only return a different film.
        allow_title_search=False refuses the title search when there is no id too,
        for callers that must not tag a film they could not identify.
        """
        if not CFG.TMDB_API_KEY and not (CFG.OMDB_API_KEY and imdb_id):
            return None
        cache_key = (f"movie:{(imdb_id or f'{title}|{year}' or '').lower()}"
                     + ("" if allow_title_search else ":id"))

        def fetch() -> Optional[Dict[str, Any]]:
            tmdb_id: Optional[int] = None
            if CFG.TMDB_API_KEY:
                if imdb_id:
                    tmdb_id, _tv = self._tmdb_ids_for_imdb(imdb_id)
                elif title and allow_title_search:
                    tmdb_id = self._tmdb_search_id(title, year, is_tv=False)
            if tmdb_id is None:
                return self._omdb_movie_metadata(imdb_id, title, year) if imdb_id else None

            data = _http_get_json(
                f"https://api.themoviedb.org/3/movie/{tmdb_id}"
                f"?api_key={CFG.TMDB_API_KEY}&append_to_response=credits,release_dates")
            if not data:
                return None

            crew = (data.get("credits") or {}).get("crew") or []
            directors = [c.get("name") for c in crew if c.get("job") == "Director" and c.get("name")]
            writers: List[str] = []
            for c in crew:
                if c.get("department") == "Writing" and c.get("name") and c["name"] not in writers:
                    writers.append(c["name"])
            overview = str(data.get("overview") or "").strip()
            tagline = str(data.get("tagline") or "").strip()

            # US certification from TMDB release_dates
            law_rating: Optional[str] = None
            for entry in (data.get("release_dates") or {}).get("results") or []:
                if entry.get("iso_3166_1") == "US":
                    for rel in entry.get("release_dates") or []:
                        cert = str(rel.get("certification") or "").strip()
                        if cert:
                            law_rating = cert
                            break
                    break

            rating: Optional[str] = None
            if CFG.OMDB_API_KEY and imdb_id:
                od = _http_get_json(
                    f"https://www.omdbapi.com/?i={urllib.parse.quote(imdb_id)}&apikey={CFG.OMDB_API_KEY}")
                if od and od.get("Response") == "True":
                    if not law_rating and od.get("Rated") not in (None, "", "N/A"):
                        law_rating = str(od["Rated"])
                    if od.get("imdbRating") not in (None, "", "N/A"):
                        rating = str(od["imdbRating"])
            if rating is None and data.get("vote_average"):
                rating = f"{float(data['vote_average']):.1f}"

            return {
                "title": data.get("title") or title,
                "year": (data.get("release_date") or "")[:4] or year,
                "date": data.get("release_date") or None,
                "genres": [g.get("name") for g in data.get("genres") or [] if g.get("name")],
                "directors": directors[:5],
                "writers": writers[:5],
                "cast": self._top_cast(data.get("credits") or {}),
                "description": tagline or (overview[:250] + "…" if len(overview) > 250 else overview) or None,
                "synopsis": overview or None,
                "law_rating": law_rating,
                "rating": rating,
                "collection": ((data.get("belongs_to_collection") or {}).get("name") or None),
                "orig_lang": data.get("original_language") or None,  # ISO 639-1
                "imdb_id": data.get("imdb_id") or None,
                "tmdb_id": tmdb_id,
            }

        return self._cached(cache_key, fetch)

    # ---------- TV ----------

    def _show_metadata(self, show_name: str, imdb_id: Optional[str]) -> Optional[Dict[str, Any]]:
        cache_key = f"show:{(imdb_id or show_name or '').lower()}"

        def fetch() -> Optional[Dict[str, Any]]:
            # Keep the year as a constraint: a bare one-word search ranks by
            # popularity and can return a same-named show from another
            # decade, whose tags would then be embedded into this file.
            # Handles 'Show (2026)' and bare 'Show 2026' alike — parsing only the
            # parenthesised form left the search unconstrained, which is how a
            # 'Show Name 2026' episode was previewed as 'Show Name Extended'.
            search_name, show_year = split_show_year(show_name or "")

            tv_id: Optional[int] = None
            if imdb_id:
                _mv, tv_id = self._tmdb_ids_for_imdb(imdb_id)
            if tv_id is None and search_name:
                # A renewed show's release year is the SEASON's air year, not the
                # series' first-air year, so year cannot gate this the way it does
                # for movies. tv_show_identity() matches on an exact, unambiguous
                # title instead — the same safety rule, without the year trap.
                tv_id = tv_show_identity(f"{search_name} metadata", search_name, show_year, imdb_id)
                if tv_id is None:
                    logging.info("Cannot identify the series %r — skipping metadata rather "
                                 "than tagging with a different show's.", search_name)
            if tv_id is None:
                return None

            data = _http_get_json(
                f"https://api.themoviedb.org/3/tv/{tv_id}"
                f"?api_key={CFG.TMDB_API_KEY}&append_to_response=credits,content_ratings")
            if not data:
                return None

            law_rating: Optional[str] = None
            for entry in (data.get("content_ratings") or {}).get("results") or []:
                if entry.get("iso_3166_1") == "US" and str(entry.get("rating") or "").strip():
                    law_rating = str(entry["rating"]).strip()
                    break

            networks = data.get("networks") or []
            return {
                "tv_id": tv_id,
                "show": data.get("name") or show_name,
                "show_year": (data.get("first_air_date") or "")[:4] or None,
                "genres": [g.get("name") for g in data.get("genres") or [] if g.get("name")],
                "network": networks[0].get("name") if networks else None,
                "cast": self._top_cast(data.get("credits") or {}),
                "law_rating": law_rating,
                "orig_lang": data.get("original_language") or None,  # ISO 639-1
                "tmdb_id": tv_id,
            }

        return self._cached(cache_key, fetch)

    def _season_json(self, tv_id: int, season: int) -> Optional[Dict[str, Any]]:
        cache_key = f"season:{tv_id}:{season}"

        def fetch() -> Optional[Dict[str, Any]]:
            return _http_get_json(
                f"https://api.themoviedb.org/3/tv/{tv_id}/season/{season}?api_key={CFG.TMDB_API_KEY}")

        return self._cached(cache_key, fetch)

    def episode_metadata(self, show_name: str, imdb_id: Optional[str],
                         season: Optional[int], episode: Optional[int]) -> Optional[Dict[str, Any]]:
        if not CFG.TMDB_API_KEY:
            return None
        show = self._show_metadata(show_name, imdb_id)
        if not show:
            return None

        meta: Dict[str, Any] = dict(show)
        meta.update({"season": season, "episode": episode,
                     "season_name": None, "ep_title": None, "airdate": None,
                     "directors": [], "description": None, "synopsis": None, "rating": None})

        if season is None:
            return meta

        sdata = self._season_json(show["tv_id"], season)
        if not sdata:
            return meta
        meta["season_name"] = sdata.get("name") or f"Season {season}"

        if episode is None:
            return meta
        ep = next((e for e in sdata.get("episodes") or []
                   if e.get("episode_number") == episode), None)
        if not ep:
            return meta

        overview = str(ep.get("overview") or "").strip()
        meta["ep_title"] = ep.get("name") or None
        meta["airdate"] = ep.get("air_date") or None
        meta["directors"] = [c.get("name") for c in ep.get("crew") or []
                             if c.get("job") == "Director" and c.get("name")][:5]
        meta["description"] = (overview[:250] + "…" if len(overview) > 250 else overview) or None
        meta["synopsis"] = overview or None
        if ep.get("vote_average"):
            meta["rating"] = f"{float(ep['vote_average']):.1f}"
        return meta


_META_FETCHER: Optional[MetadataFetcher] = None
_META_FETCHER_LOCK = threading.Lock()


def _get_meta_fetcher() -> MetadataFetcher:
    global _META_FETCHER
    with _META_FETCHER_LOCK:
        if _META_FETCHER is None:
            _META_FETCHER = MetadataFetcher()
        return _META_FETCHER


def embed_cover_into_mkv(
    mkv_path: Path,
    image_bytes: bytes,
    delete_attachment_ids: List[int],
    dry_run: bool,
) -> bool:
    """
    Embed image as the Matroska front cover via mkvpropedit.
    delete_attachment_ids: existing cover attachment IDs to replace (overwrite mode).
    """
    is_png = image_bytes[:4] == b"\x89PNG"
    att_name = "cover.png" if is_png else "cover.jpg"
    mime = "image/png" if is_png else "image/jpeg"

    if dry_run:
        logging.info("[DRY] Would embed %s (%d KB) into: %s", att_name, len(image_bytes) // 1024, mkv_path.name)
        return True

    import tempfile
    fd, tmp = tempfile.mkstemp(prefix="mkvcover_", suffix=".png" if is_png else ".jpg")
    tmp_path = Path(tmp)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(image_bytes)

        cmd: List[str] = [str(CFG.MKVPROPEDIT_EXE), str(mkv_path)]
        for aid in delete_attachment_ids:
            cmd += ["--delete-attachment", str(aid)]
        cmd += [
            "--attachment-name", att_name,
            "--attachment-mime-type", mime,
            "--attachment-description", "Cover art",
            "--add-attachment", str(tmp_path),
        ]
        r = run_cmd(cmd, timeout_sec=300)
        if not r.ok and r.rc > 1:  # rc=1 is warnings-only, operation still applied
            logging.warning("Cover embed failed rc=%s: %s", r.rc, (r.out or r.err).strip())
            return False
        return True
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def _save_review_copy(review_dir: Path, mkv_path: Path, image_bytes: bytes) -> Optional[str]:
    """
    Save an audit copy of the embedded poster into the review folder, named after
    the MKV so a wrong poster is immediately obvious in Explorer / the HTML report.
    Returns the saved filename (relative to review_dir), or None on failure.
    """
    ext = ".png" if image_bytes[:4] == b"\x89PNG" else ".jpg"
    base = sanitize_filename(mkv_path.stem) or "cover"
    name = f"{base}{ext}"
    try:
        review_dir.mkdir(parents=True, exist_ok=True)  # lazy — pipeline runs create it on first use
    except Exception:
        return None
    target = review_dir / name
    if target.exists():
        # Same stem from another folder (rare): disambiguate with a short path hash.
        suffix = hashlib.sha1(str(mkv_path).encode("utf-8", "replace")).hexdigest()[:6]
        name = f"{base}_{suffix}{ext}"
        target = review_dir / name
    try:
        target.write_bytes(image_bytes)
        return name
    except Exception as e:
        logging.warning("Could not save review copy for %s: %s", mkv_path.name, e)
        return None


def process_coverart_one(
    mkv_path: Path,
    is_tv: bool,
    fetcher: CoverArtFetcher,
    dry_run: bool,
    overwrite_cover: bool,
    review_dir: Optional[Path] = None,
    ledger: Optional[CoverartLedger] = None,
    clear_only: bool = False,
) -> Result:
    """
    Full cover-art sequence for one MKV:
      1. Ledger hit (already embedded by this script, size unchanged) -> instant skip.
      2. Cover WE embedded found in the file (description 'Cover art') -> skip,
         self-heal the ledger. Foreign covers from the release get REPLACED.
      3. Detect audio languages -> poster language preference (English first).
      4. Source chain: local poster file -> TMDB -> fanart.tv -> OMDb.
      5. Embed as cover.jpg/cover.png via mkvpropedit (in-place, no remux).
      6. Save an audit copy into review_dir; record the file in the ledger.
    --coverart-overwrite skips steps 1-2 and re-embeds unconditionally.
    """
    kind = "coverart"
    try:
        if clear_only:
            meta = mkvmerge_identify_json(mkv_path)
            existing, _ours = mkv_cover_attachments(meta)
            if not existing:
                if ledger is not None and not dry_run:
                    ledger.remove(mkv_path)
                return Result(kind=kind, source_items=[mkv_path], output_path=mkv_path,
                              ok=True, reason="no_cover")
            if dry_run:
                logging.info("[DRY] Would remove embedded cover art: %s", mkv_path.name)
                return Result(kind=kind, source_items=[mkv_path], output_path=mkv_path,
                              ok=True, reason="dry-run")
            cmd = [str(CFG.MKVPROPEDIT_EXE), str(mkv_path)]
            for aid in existing:
                cmd += ["--delete-attachment", str(aid)]
            r = run_cmd(cmd, timeout_sec=300)
            if not r.ok and r.rc > 1:
                return Result(kind=kind, source_items=[mkv_path], output_path=None, ok=False,
                              reason=f"cover removal failed: {(r.out or r.err).strip()}")
            if ledger is not None:
                ledger.remove(mkv_path)  # so a later run fetches it again
            logging.info("Cover art removed: %s", mkv_path.name)
            return Result(kind=kind, source_items=[mkv_path], output_path=mkv_path,
                          ok=True, details={"source": "cleared"})

        if not overwrite_cover and ledger is not None and ledger.has(mkv_path):
            logging.debug("Ledger: cover already done, skipping: %s", mkv_path.name)
            return Result(kind=kind, source_items=[mkv_path], output_path=mkv_path,
                          ok=True, reason="ledger_skip")

        meta = mkvmerge_identify_json(mkv_path)
        existing, ours = mkv_cover_attachments(meta)
        if existing and ours and not overwrite_cover:
            # Our cover is in the file but the ledger didn't know (renamed file,
            # rebuilt ledger, ...) — record it and move on.
            if ledger is not None and not dry_run:
                ledger.add(mkv_path, "self-heal")
            logging.debug("Own cover already embedded, skipping: %s", mkv_path.name)
            return Result(kind=kind, source_items=[mkv_path], output_path=mkv_path,
                          ok=True, reason="already_has_cover")

        tracks = extract_tracks(mkv_path, meta)
        detected = {detect_language_canonical(t) for t in tracks if t.type == "audio"}
        audio_langs = [c for c in CFG.LANG_CANONICAL_ORDER if c in detected]
        lang_pref = poster_lang_preference(audio_langs)

        img: Optional[bytes] = None
        source = "none"

        # Tier 1: local poster file (manual override always wins)
        local = find_local_poster(mkv_path, is_tv=is_tv)
        if local:
            try:
                img = local.read_bytes()
                source = f"local:{local.name}"
            except Exception as e:
                logging.warning("Could not read local poster %s: %s", local, e)

        # Tier 2-4: online sources. Dry-run stays offline by design.
        if img is None:
            if is_tv:
                show_name, _s, _e, _t = infer_tv_components(mkv_path)
                imdb_id = extract_imdb_id_from_tv_path(mkv_path) or extract_imdb_from_mkv_tags(mkv_path)
                if dry_run:
                    logging.info("[DRY] Would fetch show poster: show=%r imdb=%s langs=%s | %s",
                                 show_name, imdb_id, lang_pref, mkv_path.name)
                    return Result(kind=kind, source_items=[mkv_path], output_path=mkv_path,
                                  ok=True, reason="dry-run")
                # Pin the series first. A show is identified by an exact title match
                # (not by year: a renewed show's filename carries the SEASON's air
                # year, not the year it debuted). When more than one series shares
                # the title nothing is guessed — the file is left exactly as it is
                # and the candidates are listed for --pick.
                bare_show, show_year = split_show_year(show_name or "")
                tv_id = tv_show_identity(mkv_path.name, bare_show or show_name, show_year, imdb_id,
                                         own_langs={c for c in detected if c})
                if tv_id is None and not imdb_id:
                    logging.warning("No cover art embedded (show not identified): %s", mkv_path.name)
                    return Result(kind=kind, source_items=[mkv_path], output_path=mkv_path,
                                  ok=True, reason="show_unidentified",
                                  details={"note": "not identified — more than one series shares "
                                                   "this title, or none matches; use --pick"})
                img, source = fetcher.fetch_show_poster(show_name, imdb_id, lang_pref, tmdb_tv_id=tv_id)
            else:
                title, year, imdb_id = parse_title_year_imdb_from_filename(mkv_path)
                if not title:
                    title, year = infer_movie_name_year_from_path(mkv_path)
                if not imdb_id:
                    imdb_id = extract_imdb_id_from_movie_path(mkv_path) or extract_imdb_from_mkv_tags(mkv_path)
                if dry_run:
                    logging.info("[DRY] Would fetch movie poster: title=%r year=%s imdb=%s langs=%s | %s",
                                 title, year, imdb_id, lang_pref, mkv_path.name)
                    return Result(kind=kind, source_items=[mkv_path], output_path=mkv_path,
                                  ok=True, reason="dry-run")
                # A poster found by title alone is whichever film the database ranked
                # first — as wrong as a wrong rename, and just as silent. Pin the film
                # to one IMDB id first; if that cannot be done, leave the file exactly
                # as it is rather than embed another film's artwork.
                pinned, why = movie_identity_for_rename(mkv_path, title or mkv_path.stem, year, imdb_id)
                if not pinned:
                    logging.warning("No cover art embedded (film not identified): %s", mkv_path.name)
                    return Result(kind=kind, source_items=[mkv_path], output_path=mkv_path,
                                  ok=True, reason="film_unidentified",
                                  details={"note": f"not identified — {why}"})
                img, source = fetcher.fetch_movie_poster(title, year, pinned, lang_pref)

        if img is None:
            logging.warning("No cover art found for: %s", mkv_path.name)
            return Result(kind=kind, source_items=[mkv_path], output_path=None,
                          ok=False, reason="no_poster_found")

        img = _maybe_downscale_poster(img)

        # Said here, not earlier: a film that cannot be identified, or a title with
        # no poster, keeps the cover it came with, so nothing is being replaced yet.
        if existing and not ours and not overwrite_cover:
            logging.info("Third-party cover found (came with the file) — replacing: %s", mkv_path.name)

        # Any pre-existing cover attachments are replaced by the new embed.
        if embed_cover_into_mkv(mkv_path, img, existing, dry_run):
            logging.info("%sCover embedded (%s, %d KB): %s",
                         "[DRY] " if dry_run else "", source, len(img) // 1024, mkv_path.name)
            review_name: Optional[str] = None
            if not dry_run:
                if review_dir is not None:
                    review_name = _save_review_copy(review_dir, mkv_path, img)
                if ledger is not None:
                    ledger.add(mkv_path, source)
            return Result(kind=kind, source_items=[mkv_path], output_path=mkv_path,
                          ok=True, details={"source": source, "langs": audio_langs,
                                            "review_image": review_name})
        return Result(kind=kind, source_items=[mkv_path], output_path=None,
                      ok=False, reason="mkvpropedit_embed_failed")

    except Exception as e:
        logging.exception("Cover art failed: %s", mkv_path.name)
        return Result(kind=kind, source_items=[mkv_path], output_path=None,
                      ok=False, reason=str(e))


def _write_coverart_report(review_dir: Path, results: List[Result]) -> Optional[Path]:
    """
    Write a self-contained HTML gallery (coverart_report.html) into the review folder:
    failures listed first, then a thumbnail grid of every embedded poster with the
    MKV name and source underneath, then the list of files skipped (already covered).
    """
    import html as _html

    embedded = [r for r in results if r.ok and r.details.get("review_image")]
    embedded_no_img = [r for r in results if r.ok and r.reason not in ("already_has_cover", "dry-run")
                       and not r.details.get("review_image")]
    skipped = [r for r in results if r.ok and r.reason == "already_has_cover"]
    failed = [r for r in results if not r.ok]

    def _name(r: Result) -> str:
        return r.source_items[0].name if r.source_items else "?"

    rows: List[str] = []
    rows.append("<!DOCTYPE html><html><head><meta charset='utf-8'>")
    rows.append("<title>MediaCleanup cover art report</title><style>")
    rows.append(
        "body{font-family:Segoe UI,Arial,sans-serif;margin:20px;background:#1b1b1f;color:#ddd}"
        "h1,h2{color:#fff} a{color:#7ab7ff}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px}"
        "figure{margin:0;background:#26262c;border-radius:8px;padding:10px}"
        "figure img{width:100%;height:300px;object-fit:contain;background:#000;border-radius:4px}"
        "figcaption{font-size:12px;margin-top:8px;word-break:break-word}"
        ".src{color:#8fc98f} .fail{color:#ff8484} details{margin:10px 0}"
        "li{font-size:13px;margin:2px 0}"
    )
    rows.append("</style></head><body>")
    rows.append("<h1>Cover art report</h1>")
    rows.append(f"<p>Run: {_html.escape(_dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))} &nbsp;|&nbsp; "
                f"embedded: <b>{len(embedded) + len(embedded_no_img)}</b> &nbsp;|&nbsp; "
                f"already had cover: <b>{len(skipped)}</b> &nbsp;|&nbsp; "
                f"failed: <b class='fail'>{len(failed)}</b></p>")

    if failed:
        rows.append("<h2 class='fail'>Failures — needs attention</h2><ul>")
        for r in failed:
            rows.append(f"<li class='fail'>{_html.escape(_name(r))} — {_html.escape(r.reason)}</li>")
        rows.append("</ul>")
        rows.append("<p>Fix: drop a <code>poster.jpg</code> into the movie's folder and re-run "
                    "<code>--coverart</code> for it.</p>")

    if embedded:
        rows.append("<h2>Embedded posters — verify visually</h2>")
        rows.append("<p>Wrong poster? Drop the correct <code>poster.jpg</code> into that movie's folder and "
                    "re-run with <code>--coverart-overwrite</code> (scoped via <code>--input</code>).</p>")
        rows.append("<div class='grid'>")
        for r in sorted(embedded, key=_name):
            img = _html.escape(str(r.details["review_image"]))
            src = _html.escape(str(r.details.get("source", "?")))
            langs = ", ".join(r.details.get("langs") or []) or "-"
            rows.append(
                f"<figure><img src='{img}' loading='lazy'>"
                f"<figcaption>{_html.escape(_name(r))}<br>"
                f"<span class='src'>source: {src} | audio: {_html.escape(langs)}</span>"
                f"</figcaption></figure>"
            )
        rows.append("</div>")

    if skipped:
        rows.append(f"<details><summary>Skipped — already had a cover ({len(skipped)})</summary><ul>")
        for r in sorted(skipped, key=_name):
            rows.append(f"<li>{_html.escape(_name(r))}</li>")
        rows.append("</ul></details>")

    rows.append("</body></html>")

    report = review_dir / "coverart_report.html"
    try:
        report.write_text("\n".join(rows), encoding="utf-8")
        return report
    except Exception as e:
        logging.warning("Could not write cover art report: %s", e)
        return None


def run_coverart_pipeline(
    do_movies: bool,
    do_tv: bool,
    dry_run: bool,
    workers: int,
    movies_root: Optional[Path] = None,
    tv_root: Optional[Path] = None,
    overwrite_cover: bool = False,
    filters: Optional[List[str]] = None,
    clear_only: bool = False,
    only_files: Optional[List[Tuple[Path, bool]]] = None,
) -> List[Result]:
    """Scan Movies/TV roots and embed cover art into every MKV missing one
    (or, with clear_only, remove embedded cover art).

    only_files: (path, is_tv) pairs to process INSTEAD of scanning. A step that
    has just renamed files must pass them explicitly — rescanning with --filter
    would test the new names against a pattern written for the old ones."""
    movies_root = movies_root or CFG.MOVIES_ROOT
    tv_root = tv_root or CFG.TV_ROOT

    if not clear_only and not (CFG.TMDB_API_KEY or CFG.FANARTTV_API_KEY or CFG.OMDB_API_KEY):
        logging.warning("coverart: no API keys in [coverart] section of %s — "
                        "only local poster files (poster.jpg/cover.jpg/folder.jpg) will be used.",
                        CONFIG_FILE.name)

    if only_files is not None:
        movie_set: set[Path] = set()
        tv_set: set[Path] = set()
    else:
        movie_set = set(apply_scan_filters(scan_mkvs(movies_root), movies_root,
                                           filters, "coverart")) if do_movies else set()
        tv_set = set(apply_scan_filters(scan_mkvs(tv_root), tv_root,
                                        filters, "coverart")) if do_tv else set()
    if do_movies:
        logging.info("coverart - Movies: %d MKV(s) found in %s.", len(movie_set), movies_root)
    if do_tv:
        logging.info("coverart - TV: %d MKV(s) found in %s.", len(tv_set), tv_root)

    # Dedupe (both pipelines may scan the same --input root). For files seen by
    # both, classify by SxxEyy episode pattern in the filename.
    tagged_targets: List[Tuple[Path, bool]] = []
    if only_files is not None:
        tagged_targets = [(p, tv) for p, tv in only_files if p.exists()]
        logging.info("coverart - %d file(s) handed over from the previous step.", len(tagged_targets))
    for p in sorted(movie_set | tv_set):
        if p in movie_set and p in tv_set:
            is_tv = bool(_SEASON_EP_RE.search(p.stem))
        else:
            is_tv = p in tv_set
        tagged_targets.append((p, is_tv))

    # Audit trail: every embedded poster is copied here, plus an HTML gallery
    # report, so wrong matches can be spotted at a glance. Dry runs are offline
    # (no images to show), so no review folder is created.
    review_dir: Optional[Path] = None
    if not dry_run and tagged_targets and not clear_only:
        review_dir = _SCRIPT_DIR / "logs" / "coverart_review" / _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            review_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logging.warning("Could not create review folder %s: %s", review_dir, e)
            review_dir = None

    fetcher = CoverArtFetcher()
    ledger = CoverartLedger()
    results: List[Result] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(process_coverart_one, p, is_tv, fetcher, dry_run,
                      overwrite_cover, review_dir, ledger, clear_only): p
            for p, is_tv in tagged_targets
        }
        for fut in concurrent.futures.as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as e:
                p = futs[fut]
                logging.exception("coverart worker crashed: %s", p)
                results.append(Result(kind="coverart", source_items=[p], output_path=None,
                                      ok=False, reason=f"Worker exception: {e}"))

    if not dry_run:
        ledger.save()

    if review_dir is not None:
        report = _write_coverart_report(review_dir, results)
        if report:
            logging.info("Cover art review: %s", review_dir)
            logging.info("Open in a browser to verify posters: %s", report)

    return results


# Shared cover art context for the MAIN pipeline: cover embedding runs as the
# final finishing step of --movies/--tv (after the FileBot rename) unless
# --skip-coverart is set. Initialized in main(); ledger keeps re-runs cheap.
_PIPELINE_COVERART: Dict[str, Any] = {
    "enabled": False, "fetcher": None, "ledger": None,
    "review_dir": None, "results": [], "lock": threading.Lock(),
}


def pipeline_embed_cover(mkv: Optional[Path], is_tv: bool, dry_run: bool) -> None:
    """Best-effort cover embed for a pipeline-finished file. Never fatal."""
    ctx = _PIPELINE_COVERART
    if not ctx["enabled"] or mkv is None:
        return
    if dry_run:
        logging.info("[DRY] Would embed cover art: %s", mkv.name)
        return
    if not mkv.exists():
        return
    try:
        res = process_coverart_one(mkv, is_tv, ctx["fetcher"], dry_run=False,
                                   overwrite_cover=False,
                                   review_dir=ctx["review_dir"], ledger=ctx["ledger"])
        with ctx["lock"]:
            ctx["results"].append(res)
        if not res.ok:
            logging.warning("Cover art failed (non-fatal): %s | %s", mkv.name, res.reason)
    except Exception as e:
        logging.warning("Cover art step failed (non-fatal): %s | %s", mkv.name, e)


# =========================
# Rename mode (--rename / --rename-undo)
# =========================

RENAME_HISTORY_CSV = _SCRIPT_DIR / "logs" / "rename_history.csv"

# Library-organizing formats for --rename-into (folder structure prepended).
# The show folder de-duplicates the year the same way the filename does.
MOVIE_FILEBOT_FORMAT_DIR = "{n} ({y})/" + MOVIE_FILEBOT_FORMAT
TV_FILEBOT_FORMAT_DIR = (r"{n.replaceAll(/\s*\(\d{4}\)$/, '')} ({y})/Season {s.pad(2)}/"
                         + TV_FILEBOT_FORMAT)


def _append_rename_history(batch_id: str, pairs: List[Tuple[Path, Path]]) -> None:
    """Append old->new mappings to logs/rename_history.csv (creates it if missing)."""
    if not pairs:
        return
    import csv
    RENAME_HISTORY_CSV.parent.mkdir(parents=True, exist_ok=True)
    new_file = not RENAME_HISTORY_CSV.exists()
    try:
        with RENAME_HISTORY_CSV.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["batch", "old", "new"])
            for old, new in pairs:
                w.writerow([batch_id, str(old), str(new)])
        logging.info("Rename history: %d entries appended to %s (batch %s)",
                     len(pairs), RENAME_HISTORY_CSV, batch_id)
    except Exception as e:
        logging.warning("Could not write rename history (non-fatal): %s", e)


def run_rename_undo() -> int:
    """
    Revert the most recent --rename batch recorded in logs/rename_history.csv.
    Files that moved or changed since are skipped with a warning. The undone
    batch is removed from the history so a further undo targets the batch before.
    """
    import csv
    if not RENAME_HISTORY_CSV.exists():
        logging.error("No rename history found at %s — nothing to undo.", RENAME_HISTORY_CSV)
        return 1

    with RENAME_HISTORY_CSV.open("r", newline="", encoding="utf-8") as f:
        rows = [r for r in csv.reader(f) if r]
    if len(rows) <= 1:
        logging.error("Rename history is empty — nothing to undo.")
        return 1

    header, entries = rows[0], rows[1:]
    last_batch = entries[-1][0]
    batch_rows = [r for r in entries if r[0] == last_batch]
    keep_rows = [r for r in entries if r[0] != last_batch]

    logging.info("Undoing rename batch %s (%d file(s))...", last_batch, len(batch_rows))
    reverted = skipped = 0
    for _b, old_s, new_s in reversed(batch_rows):
        old, new = Path(old_s), Path(new_s)
        if not new.exists():
            logging.warning("Skip undo (renamed file no longer exists): %s", new)
            skipped += 1
            continue
        if old.exists():
            logging.warning("Skip undo (original path is occupied): %s", old)
            skipped += 1
            continue
        try:
            old.parent.mkdir(parents=True, exist_ok=True)
            os.replace(win_long_path(new), win_long_path(old))
            logging.info("Reverted: %s -> %s", new.name, old)
            reverted += 1
            # Prune empty folders --rename-into may have created
            d = new.parent
            while d != d.parent:
                try:
                    d.rmdir()
                except OSError:
                    break
                d = d.parent
        except Exception as e:
            logging.warning("Undo failed for %s: %s", new, e)
            skipped += 1

    try:
        with RENAME_HISTORY_CSV.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(keep_rows)
    except Exception as e:
        logging.warning("Could not rewrite rename history (non-fatal): %s", e)

    logging.info("Undo complete: reverted=%d skipped=%d", reverted, skipped)
    return 0 if skipped == 0 else 1


def _rename_one_via_omdb(mkv: Path, ident: MovieIdentity, title: str, year: Optional[str],
                         target_root: Optional[Path], dry_run: bool) -> Result:
    """--rename for a film that only OMDb identified: the script's own template, no FileBot."""
    kind = "rename"
    facts = _local_file_facts(mkv)
    if not facts:
        return Result(kind=kind, source_items=[mkv], output_path=None, ok=False,
                      reason="could not read the file's video")
    name_title = ident.title or title
    name_year = ident.year or year
    dest_dir = mkv.parent
    if target_root:
        folder = sanitize_filename(f"{name_title} ({name_year})" if name_year else name_title)
        dest_dir = target_root / folder
    dest = dest_dir / build_movie_output_name(name_title, name_year, ident.imdb, facts["res"],
                                              facts["source"], facts["codec"], [],
                                              bracket=facts["bracket"])
    if dry_run:
        logging.info("[DRY] %s -> %s (identified via OMDb)", mkv.name, dest)
        return Result(kind=kind, source_items=[mkv], output_path=mkv, ok=True,
                      reason="dry-run", details={"proposed": str(dest)})
    outcome: Dict[str, Any] = {}
    new = rename_movie_from_omdb(mkv, ident.imdb or "", ident.title, ident.year, title, year,
                                 outcome, dest_dir=dest_dir)
    if new is None:
        return Result(kind=kind, source_items=[mkv], output_path=None, ok=False,
                      reason=outcome.get("reason") or "rename failed")
    if new == mkv:
        return Result(kind=kind, source_items=[mkv], output_path=mkv, ok=True, reason="already_named")
    return Result(kind=kind, source_items=[mkv], output_path=new, ok=True,
                  details={"old": str(mkv), "new": str(new)})


def process_rename_one(
    mkv: Path,
    is_tv: bool,
    target_root: Optional[Path],
    dry_run: bool,
    force_audio_langs: Optional[Dict[int, str]] = None,
    force_sub_langs: Optional[Dict[int, str]] = None,
) -> Result:
    """
    Rename a single MKV via FileBot into the canonical naming format.

    target_root=None  -> rename in place (same folder).
    target_root=Path  -> organize into the library structure under that root
                         (Movies: 'Title (Year)/...'; TV: 'Show (Year)/Season XX/...').

    When --force-audio-lang/--force-sub-lang are given, language tags are fixed
    via mkvpropedit BEFORE FileBot runs so the [language] bracket comes out right.
    Dry runs use FileBot's native test action, which prints the actual proposed name.
    """
    kind = "rename"
    try:
        if not CFG.FILEBOT_EXE.exists():
            return Result(kind=kind, source_items=[mkv], output_path=None, ok=False,
                          reason=f"FileBot not found at {CFG.FILEBOT_EXE}")
        if _FILEBOT_DISABLED:
            return Result(kind=kind, source_items=[mkv], output_path=None, ok=False,
                          reason="FileBot disabled for this run (bundled JRE problem)")

        # Fix mislabeled language tags first so FileBot reads correct languages.
        if force_audio_langs or force_sub_langs:
            if dry_run:
                logging.info("[DRY] Would fix language tags before rename: %s", mkv.name)
            else:
                meta = mkvmerge_identify_json(mkv)
                tracks = extract_tracks(mkv, meta)
                fix_track_langs_inplace(mkv, tracks, force_audio_langs or {}, force_sub_langs or {})

        # Clean query so filename noise doesn't corrupt the DB lookup.
        tv_year: Optional[str] = None
        if is_tv:
            show_name, _s, _e, _t = infer_tv_components(mkv)
            _bare, tv_year = split_show_year(show_name or "")
            query = _bare or None
            db = "TheTVDB"
            fmt = TV_FILEBOT_FORMAT_DIR if target_root else TV_FILEBOT_FORMAT
            # A series must be identified before it may be renamed — see
            # tv_identity_for_rename. Ambiguous means leave the file alone.
            tv_pin: Optional[int] = None
            if query:
                tv_pin, tv_blocked = tv_identity_for_rename(mkv.name, query, tv_year)
                if tv_blocked:
                    return Result(kind=kind, source_items=[mkv], output_path=None, ok=False,
                                  reason=tv_blocked)
        else:
            tv_pin = None
            title, year, _imdb = parse_title_year_imdb_from_filename(mkv)
            if not title:
                title, year = infer_movie_name_year_from_path(mkv)
            query = f"{title} ({year})" if title and year else (title or None)
            db = CFG.FILEBOT_DB
            fmt = MOVIE_FILEBOT_FORMAT_DIR if target_root else MOVIE_FILEBOT_FORMAT
            if not _imdb:
                _imdb = extract_imdb_id_from_movie_path(mkv) or extract_imdb_from_mkv_tags(mkv)
            # A film must be pinned to one id before it may be renamed — a title
            # and a year are shared by too many releases to identify one.
            ident = movie_identity_chain(mkv, title or mkv.stem, year, _imdb)
            if not ident.imdb:
                return Result(kind=kind, source_items=[mkv], output_path=None, ok=False,
                              reason=ident.reason)
            pinned_imdb = ident.imdb
            if ident.source == "OMDb":
                return _rename_one_via_omdb(mkv, ident, title or mkv.stem, year,
                                            target_root, dry_run)

        out_dir = target_root if target_root else mkv.parent
        action = "test" if dry_run else "move"

        try:
            before_size = mkv.stat().st_size
        except Exception:
            before_size = None

        fmt = _pin_resolution_in_format(fmt, mkv)
        # Plain str() paths — FileBot's launcher breaks on \\?\-prefixed paths
        # ("bundled JRE missing or corrupted" error).
        cmd = [
            str(CFG.FILEBOT_EXE),
            "-rename", str(mkv),
            "--db", db,
            "--format", fmt,
            "--output", str(out_dir),
            "--action", action,
            "--conflict", "skip",
            "-non-strict",
        ]
        # Year constraint so a same-title film/series from another year can
        # never win a fuzzy match (TV uses the series' first-air year).
        plain_cmd = list(cmd)
        year_filter = _filebot_year_filter(query, db, year=tv_year if is_tv else year)
        base_cmd = plain_cmd + year_filter
        if not is_tv:
            # Direct lookup by id: no filter can improve on it, and no fallback
            # should apply, since a fallback could only find a different film.
            cmd += ["--q", str(pinned_imdb)]
        elif tv_pin:
            pass    # the pinned commands below are built from plain_cmd
        elif query:
            cmd += ["--q", query]
            cmd += _filebot_series_name_filter(year_filter, query, db)
        else:
            cmd += year_filter

        # (In --action test, rc is 1 even on success — judge by the output.)
        def _matched(res: CmdResult, text: str) -> bool:
            return ("[TEST]" in text or "skipped" in text.lower()) if dry_run else res.ok

        if tv_pin:
            # By id, TheTVDB first then the TMDB entry; no search, so no filter
            # and no fuzzy retry that could substitute a different show.
            for n, pcmd in enumerate(pinned_tv_commands(plain_cmd, tv_pin)):
                if n:
                    logging.info("TheTVDB could not serve the series — using the TMDB entry "
                                 "instead: %s", mkv.name)
                r = run_cmd(pcmd, timeout_sec=600)
                out_txt = (r.out or "").strip()
                if _matched(r, out_txt) or _filebot_skipped_as_already_correct(out_txt):
                    break
        else:
            r = run_cmd(cmd, timeout_sec=600)
            out_txt = (r.out or "").strip()

        if not tv_pin and not _matched(r, out_txt) and is_tv and mkv.exists():
            tmdb_cmd = (_filebot_tmdb_tv_cmd(plain_cmd, query or "", tv_year)
                        if is_tv and query else None)
            if tmdb_cmd:
                # Series absent from TheTVDB, or its entry is broken: resolve it
                # on TMDB and pin FileBot to that exact series id.
                logging.info("TheTVDB could not identify %s (%s) — using the TMDB series entry "
                             "instead: %s", query, tv_year or "no year", mkv.name)
                r = run_cmd(tmdb_cmd, timeout_sec=600)
                out_txt = (r.out or "").strip()
            elif query:
                # The 'year' may be part of the title ('The Film 1984') when
                # the filename carries no release year. Try that reading first —
                # the constrained attempt already failed, so this cannot mask a
                # wrong-year match.
                retry = _verified_title_year_retry(query)
                if retry:
                    merged_q, merged_filter = retry
                    logging.info("Retrying as %r: %s", merged_q, mkv.name)
                    r = run_cmd(plain_cmd + ["--q", merged_q] + merged_filter, timeout_sec=600)
                    out_txt = (r.out or "").strip()

                # No "retry without query" here: this branch is TV-only, and with no
                # name to hold it to FileBot's own parse of a title nothing matches
                # lands on whichever show it finds. A series that cannot be
                # identified is reported as not renamed instead.

        if dry_run:
            # FileBot prints '[TEST] from [old] to [new]' — surface it verbatim.
            # NOTE: --action test exits with rc=1 even on success (no files were
            # actually renamed), so success is judged from the output, not rc.
            for line in out_txt.splitlines():
                if "[TEST]" in line or "Skipped" in line or "Failed" in line:
                    logging.info("[DRY] %s", line.strip())
            if "[TEST]" in out_txt or "skipped" in out_txt.lower():
                mt = re.search(r"\[TEST\] from \[.+?\] to \[(.+?)\]\s*$", out_txt, flags=re.M)
                details = {"proposed": mt.group(1)} if mt else {}
                return Result(kind=kind, source_items=[mkv], output_path=mkv, ok=True,
                              reason="dry-run", details=details)
            tail = out_txt.splitlines()[-1].strip() if out_txt else f"rc={r.rc}"
            return Result(kind=kind, source_items=[mkv], output_path=None, ok=False,
                          reason=f"FileBot found no match: {tail}")

        if "skipped" in out_txt.lower() and mkv.exists():
            logging.info("Rename skipped (already named / destination exists): %s", mkv.name)
            return Result(kind=kind, source_items=[mkv], output_path=mkv, ok=True,
                          reason="already_named")

        if not r.ok and mkv.exists():
            tail = out_txt.splitlines()[-1].strip() if out_txt else f"rc={r.rc}"
            return Result(kind=kind, source_items=[mkv], output_path=None, ok=False,
                          reason=f"FileBot no match: {tail}")

        # File was moved — locate the result (same size, newest, under out_dir).
        new_path: Optional[Path] = None
        if not mkv.exists():
            try:
                candidates = [p for p in out_dir.rglob("*.mkv")
                              if before_size is None or (p.exists() and p.stat().st_size == before_size)]
                candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                if candidates:
                    new_path = candidates[0]
            except Exception:
                pass

        if new_path is None:
            if mkv.exists():
                return Result(kind=kind, source_items=[mkv], output_path=mkv, ok=True,
                              reason="unchanged")
            return Result(kind=kind, source_items=[mkv], output_path=None, ok=False,
                          reason="renamed but result file not found")

        logging.info("Renamed: %s -> %s", mkv.name, new_path)
        return Result(kind=kind, source_items=[mkv], output_path=new_path, ok=True,
                      details={"old": str(mkv), "new": str(new_path)})

    except Exception as e:
        logging.exception("Rename failed: %s", mkv)
        return Result(kind=kind, source_items=[mkv], output_path=None, ok=False, reason=str(e))


def run_rename_pipeline(
    is_tv: bool,
    scan_root: Path,
    rename_into: bool,
    dry_run: bool,
    workers: int,
    force_audio_langs: Optional[Dict[int, str]] = None,
    force_sub_langs: Optional[Dict[int, str]] = None,
    filters: Optional[List[str]] = None,
) -> List[Result]:
    """FileBot-rename every MKV under scan_root. In-place unless rename_into."""
    targets = apply_scan_filters(scan_mkvs(scan_root), scan_root, filters, "rename")
    logging.info("rename - %s: %d MKV(s) found in %s.%s",
                 "TV" if is_tv else "Movies", len(targets), scan_root,
                 " (organizing into library)" if rename_into else " (in-place)")

    target_root: Optional[Path] = None
    if rename_into:
        target_root = CFG.TV_ROOT if is_tv else CFG.MOVIES_ROOT

    results: List[Result] = []
    # FileBot holds a per-invocation lock on its cache; parallel invocations can
    # contend. Cap rename concurrency at 2 regardless of --workers.
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(2, max(1, workers))) as ex:
        futs = {
            ex.submit(process_rename_one, p, is_tv, target_root, dry_run,
                      force_audio_langs, force_sub_langs): p
            for p in targets
        }
        for fut in concurrent.futures.as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as e:
                p = futs[fut]
                logging.exception("rename worker crashed: %s", p)
                results.append(Result(kind="rename", source_items=[p], output_path=None,
                                      ok=False, reason=f"Worker exception: {e}"))

    if not dry_run:
        pairs = [(Path(r.details["old"]), Path(r.details["new"]))
                 for r in results if r.ok and r.details.get("old") and r.details.get("new")]
        batch_id = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        _append_rename_history(batch_id, pairs)
        if pairs:
            logging.info("Undo this batch anytime with: --rename-undo")

    return results


# =========================
# Subtitle downloading (--subtitles mode, OpenSubtitles.com REST API)
# =========================




def compute_oshash(path: Path) -> Optional[str]:
    """
    Classic OpenSubtitles moviehash: filesize + 64-bit sums of the first and
    last 64 KiB. The strongest match signal — it identifies the exact release.
    """
    try:
        chunk = 65536
        size = path.stat().st_size
        if size < chunk * 2:
            return None
        h = size
        with path.open("rb") as f:
            for _ in range(chunk // 8):
                h = (h + int.from_bytes(f.read(8), "little")) & 0xFFFFFFFFFFFFFFFF
            f.seek(size - chunk)
            for _ in range(chunk // 8):
                h = (h + int.from_bytes(f.read(8), "little")) & 0xFFFFFFFFFFFFFFFF
        return f"{h:016x}"
    except Exception as e:
        logging.debug("oshash failed for %s: %s", path, e)
        return None


def subtitle_sidecar_path(mkv: Path, lang_iso1: str) -> Path:
    """
    Sidecar naming: with a single configured language (or for English), the
    sidecar is '<mkv stem>.srt' exactly. Additional languages get an ISO 639-2
    suffix so they can coexist: '<stem>.hin.srt'.
    """
    single = len(CFG.SUB_LANGS) == 1
    if single or lang_iso1 == "en":
        return mkv.with_suffix(".srt")
    iso2 = iso1_to_iso2(lang_iso1) or lang_iso1
    return mkv.with_suffix(f".{iso2}.srt")


def missing_subtitle_langs(mkv: Path, tracks: List[Track]) -> List[str]:
    """
    Return configured languages not already covered by an embedded subtitle
    track or an existing sidecar file.
    """
    embedded: set[str] = set()
    for t in tracks:
        if t.type == "subtitles":
            code = subtitle_lang_iso1(t.language)       # 'ger' -> 'de', not 'ge'
            if code:
                embedded.add(code)

    missing: List[str] = []
    for lang in CFG.SUB_LANGS:
        if lang in embedded:
            continue
        if subtitle_sidecar_path(mkv, lang).exists():
            continue
        missing.append(lang)
    return missing


# --- OpenSubtitles.com REST API -------------------------------------------------------
# What the manual (opensubtitles.stoplight.io, "Getting started") requires, and what this
# client therefore does:
#   * Api-Key is the ONLY credential needed to search (unlimited) and to download a few
#     subtitles a day per IP. A user login (JWT) just raises the download quota. So
#     username/password are optional here, and a failed login never stops the run.
#   * The username is the account USERNAME - an email address is refused.
#   * Every request carries 'User-Agent: AppName vX.Y'.
#   * Requests should use sorted, lowercase parameters with no default values and no
#     leading zeros in ids, otherwise every search is answered with a redirect.
#   * TV episodes are searched with parent_imdb_id + season_number + episode_number.
#   * After login, later requests must go to the returned base_url, with the token.
#   * Rate limit: about 5 requests a second (HTTP 429 says when to retry); login is
#     limited to 1/second, 10/minute, 30/hour and must not be retried after a refusal.

_OS_DEFAULT_HOST = "api.opensubtitles.com"
_OS_HOSTS = frozenset({"api.opensubtitles.com", "vip-api.opensubtitles.com"})
_OS_MIN_INTERVAL_S = 0.25            # at most four requests a second, under the documented five
_OS_MAX_RETRY_WAIT_S = 10.0


def _os_user_agent() -> str:
    return f"MediaCleanup v{__version__}"


def os_digits(imdb_id: Optional[str]) -> Optional[str]:
    """'tt0063350' -> '63350': the API wants the number alone, without leading zeros."""
    digits = re.sub(r"\D", "", str(imdb_id or ""))
    return str(int(digits)) if digits else None


def build_subtitle_searches(imdb_id: Optional[str], oshash: Optional[str], lang: str, *,
                            tmdb_id: Optional[int] = None, is_tv: bool = False,
                            season: Optional[int] = None,
                            episode: Optional[int] = None) -> List[Dict[str, str]]:
    """
    The searches to try, most precise first (at most three), as parameter dicts.

    A moviehash identifies the exact release, an id identifies the title; both are
    filters, so when the combination finds nothing the looser one is tried. A TV
    episode is searched by its series (parent id) with season and episode. There is
    deliberately no search by title: a title is not an identity, and the top hit of a
    title search can be another film. A hash-only search asks for exact matches only.
    """
    lang = (lang or "en").lower()
    num = os_digits(imdb_id)
    h = (oshash or "").lower() or None
    out: List[Dict[str, str]] = []

    def add(**params: Any) -> None:
        clean = {k: str(v) for k, v in params.items() if v not in (None, "")}
        if clean not in out:
            out.append(clean)

    if is_tv:
        parent = ({"parent_imdb_id": num} if num else
                  ({"parent_tmdb_id": tmdb_id} if tmdb_id else {}))
        ep = ({"season_number": season, "episode_number": episode}
              if season is not None and episode is not None else {})
        if parent and ep:
            add(languages=lang, moviehash=h, **parent, **ep)
            add(languages=lang, **parent, **ep)
    elif num:
        add(imdb_id=num, languages=lang, moviehash=h)
        add(imdb_id=num, languages=lang)
    if h:
        add(languages=lang, moviehash=h, moviehash_match="only")
    return out[:3]


def search_query_string(params: Dict[str, str]) -> str:
    """Parameters sorted by name and URL-encoded - the form that is not redirected."""
    return urllib.parse.urlencode(sorted(params.items()), quote_via=urllib.parse.quote)


def os_login_reason(code: Optional[int], data: Optional[Dict[str, Any]], username: str) -> str:
    """Why a login failed, in the server's own words plus the commonest mistake."""
    msg = str((data or {}).get("message") or "").strip()
    parts = []
    if code is None:
        parts.append("OpenSubtitles could not be reached")
    else:
        parts.append(f"HTTP {code}" + (f": {msg}" if msg else ""))
    if "@" in (username or ""):
        parts.append("the username in [subtitles] looks like an email address - OpenSubtitles needs "
                     "your username, not your email")
    return "; ".join(parts)


# --- Choosing a subtitle that fits the video --------------------------------------------
# The search results say nothing about how LONG a subtitle is, so the choice is made in
# two stages. Before downloading, candidates are scored on what the results do carry
# (exact-release hash, source, edition, frame rate, a runtime in the release text, ...).
# After downloading, the subtitle's last cue is compared with the video's duration; if it
# clearly does not fit, the next-best candidate is tried ONCE (it costs one more download).

# Editions that can change what is on screen or how long it runs. Framing and packaging
# words (open matte, IMAX, Criterion, 3D) do not change timing, so they are not listed.
_EDITION_PATTERNS: Dict[str, str] = {
    "colorized": r"colou?riz?s?ed",
    "remastered": r"remaster(?:ed)?",
    "extended": r"extended",
    "unrated": r"unrated",
    "directors cut": r"director'?s?[ ._-]?cut",
    "uncut": r"uncut",
    "theatrical": r"theatrical",
    "anniversary": r"anniversary",
    "restored": r"restor(?:ed|ation)",
}
_SOURCE_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("bluray", r"blu[ ._-]?ray|\bbrrip\b|\bbdrip\b|\bbd\b|\bremux\b"),
    ("web", r"\bweb[ ._-]?(?:dl|rip)?\b|\bamzn\b|\bnf\b"),
    ("hdtv", r"\bhdtv\b|\bpdtv\b"),
    ("dvd", r"\bdvd(?:rip|scr)?\b"),
)
_SUB_MIN_COVERAGE = 0.70        # a full subtitle's last cue is near the end of the video
_SUB_MAX_FIRST_CUE = 0.35       # ...and its first cue is not past a third of it


def edition_words(text: str) -> Set[str]:
    low = (text or "").lower()
    return {name for name, pat in _EDITION_PATTERNS.items() if re.search(pat, low)}


def release_source(text: str) -> Optional[str]:
    low = (text or "").lower()
    for name, pat in _SOURCE_PATTERNS:
        if re.search(pat, low):
            return name
    return None


def release_group(text: str) -> Optional[str]:
    """The release group after the last hyphen ('...X264-AMIABLE' -> 'amiable')."""
    m = re.search(r"-\s*([A-Za-z0-9]{2,15})\s*(?:\.[A-Za-z0-9]{2,4})?\s*$", (text or "").strip())
    return m.group(1).lower() if m else None


def runtime_hint(text: str) -> Optional[float]:
    """A film-length runtime written in a release text ('... 1:35:08') in seconds, if any."""
    for m in re.finditer(r"\b(\d{1,2}):([0-5]\d):([0-5]\d)\b", text or ""):
        secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        if 20 * 60 <= secs <= 6 * 3600:
            return float(secs)
    return None


def fmt_hms(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


@dataclasses.dataclass
class SubtitleTarget:
    """What the video in hand looks like, for choosing a subtitle that fits it."""
    name: str = ""
    duration_s: Optional[float] = None
    fps: Optional[float] = None


@dataclasses.dataclass
class SubtitleCandidate:
    file_id: int
    score: float
    release: str = ""
    fps: float = 0.0
    hash_match: bool = False
    reasons: List[str] = dataclasses.field(default_factory=list)


def score_subtitle_candidate(attrs: Dict[str, Any], target: SubtitleTarget
                             ) -> Tuple[Optional[float], List[str]]:
    """
    Score one search result against the video. Returns (score, reasons); a score of
    None means the result is excluded outright. Only fields the search returns are used.
    """
    why: List[str] = []
    if int(attrs.get("nb_cd") or 1) > 1:
        return None, ["split over several discs"]
    if attrs.get("machine_translated"):
        return None, ["machine-translated"]
    if attrs.get("foreign_parts_only"):
        return None, ["foreign parts only"]

    release = str(attrs.get("release") or "")
    score = 0.0

    def add(points: float, reason: str) -> None:
        nonlocal score
        score += points
        why.append(f"{points:+.0f} {reason}")

    if attrs.get("moviehash_match"):
        add(1000, "exact release (hash)")

    # source: WEB / BluRay / HDTV / DVD
    want_src, have_src = release_source(target.name), release_source(release)
    if want_src and have_src:
        add(20 if want_src == have_src else -12, f"source {have_src} vs {want_src}")

    # release group
    want_grp, have_grp = release_group(target.name), release_group(release)
    if want_grp and have_grp and want_grp == have_grp:
        add(15, f"same release group {have_grp}")

    # editions: a Colorized or Remastered subtitle is for another cut of the film
    want_ed, have_ed = edition_words(target.name), edition_words(release)
    for ed in sorted(have_ed - want_ed):
        add(-25, f"edition '{ed}' is not in your file")
    for ed in sorted(have_ed & want_ed):
        add(20, f"edition '{ed}' matches")
    for ed in sorted(want_ed - have_ed):
        add(-10, f"your file is '{ed}'")

    # frame rate: a different rate drifts steadily over the film
    sub_fps = float(attrs.get("fps") or 0.0)
    if sub_fps > 0 and target.fps:
        diff = abs(sub_fps - target.fps)
        if diff <= 0.01:
            add(25, f"frame rate {sub_fps:g} matches")
        elif diff > 0.05:
            add(-35, f"frame rate {sub_fps:g} vs {target.fps:g}")

    # a runtime written in the release text
    hint = runtime_hint(release)
    if hint and target.duration_s:
        gap = abs(hint - target.duration_s)
        if gap <= 60:
            add(30, f"runtime {fmt_hms(hint)} matches")
        elif gap > target.duration_s * 0.05:
            add(-40, f"runtime {fmt_hms(hint)} vs {fmt_hms(target.duration_s)}")

    if attrs.get("hearing_impaired"):
        add(-10, "hearing-impaired")
    if attrs.get("ai_translated"):
        add(-15, "AI-translated")
    if attrs.get("from_trusted"):
        add(8, "trusted uploader")
    try:
        rating = float(attrs.get("ratings") or 0.0)
        if rating > 0:
            add(min(10.0, rating), "rating")
        downloads = int(attrs.get("download_count") or 0)
        if downloads > 0:
            add(min(10.0, 3.0 * math.log10(1 + downloads)), f"{downloads} downloads")
    except (TypeError, ValueError):
        pass
    return score, why


def verify_subtitle_fit(raw: bytes, duration_s: Optional[float]) -> Tuple[bool, str, str]:
    """
    Does this subtitle fit a video of this length? Returns (fits, reason, cleaned SRT).

    The advertising cues the release injected at the start and end are stripped first,
    because they can run past the end of the video. A subtitle fits when its last cue
    is near the end of the video, not far beyond it, and its first cue is not late.
    It catches a wrong cut, a wrong film or a truncated file; a small frame-rate drift
    is caught earlier, by comparing frame rates before downloading.
    """
    text, _charset = _decode_subtitle_bytes(raw)
    cleaned, _removed = clean_srt_advertisements(text, duration_s)
    blocks = parse_srt(cleaned)
    if not blocks:
        return False, "not a readable SRT file", ""
    starts = [b[0] for b in blocks if b[0] is not None]
    ends = [b[1] for b in blocks if b[1] is not None]
    if not starts or not ends:
        return False, "its timing lines could not be read", ""
    if not duration_s:
        return True, "length not checked (the video's duration is unknown)", cleaned
    min_cues = int(min(20, max(5, duration_s / 120)))
    if len(blocks) < min_cues:
        return False, f"only {len(blocks)} lines for a {fmt_hms(duration_s)} video", ""
    last_end, first_start = max(ends), min(starts)
    tolerance = max(30.0, duration_s * 0.01)
    if last_end > duration_s + tolerance:
        return False, f"runs to {fmt_hms(last_end)} but the video is only {fmt_hms(duration_s)}", ""
    if last_end < duration_s * _SUB_MIN_COVERAGE:
        return False, (f"ends at {fmt_hms(last_end)}, only {last_end / duration_s:.0%} of the "
                       f"video's {fmt_hms(duration_s)}"), ""
    if first_start > duration_s * _SUB_MAX_FIRST_CUE:
        return False, f"its first line is at {fmt_hms(first_start)}", ""
    return True, (f"fits: ends at {fmt_hms(last_end)} of {fmt_hms(duration_s)} "
                  f"({last_end / duration_s:.0%})"), cleaned


def video_fps(meta: Dict[str, Any]) -> Optional[float]:
    """The first video track's frame rate, from its default frame duration."""
    for t in meta.get("tracks") or []:
        if t.get("type") == "video":
            dd = (t.get("properties") or {}).get("default_duration")
            try:
                return round(1e9 / float(dd), 3) if dd else None
            except (TypeError, ValueError, ZeroDivisionError):
                return None
    return None


def subtitle_lang_iso1(code: str) -> Optional[str]:
    """A track's language as the two-letter code the settings use ('ger' -> 'de', 'eng' -> 'en')."""
    c = (code or "").lower().strip()
    if not c or c == "und":
        return None
    if len(c) == 2:
        return c
    return iso2_to_iso1(c)


def subtitle_identity(mkv: Path, is_tv: bool, show_title: Optional[str],
                      show_year: Optional[str]) -> Tuple[Optional[str], Optional[int], str]:
    """
    Which title is this, for the subtitle search? Returns (imdb id, TMDB series id, problem).

    An id already on the file (name, folder or tags) is used as-is. Otherwise the title
    is identified the same way a rename identifies it; one that cannot be pinned to a
    single title yields no id and the reason, never a guess.
    """
    known = (extract_imdb_id_from_tv_path(mkv) if is_tv else extract_imdb_id_from_movie_path(mkv)) \
        or extract_imdb_from_mkv_tags(mkv)
    if known:
        return known, None, ""
    if is_tv:
        tid = tv_show_identity(mkv.name, show_title or "", show_year, None)
        if tid:
            imdb = str(tmdb_tv_external_ids(tid).get("imdb_id") or "")
            return (imdb if re.fullmatch(r"tt\d{7,10}", imdb) else None), tid, ""
        return None, None, "the show could not be identified, so no subtitle search was made by title"
    title, year = infer_movie_name_year_from_path(mkv)
    ident = movie_identity_chain(mkv, title, year, None)
    if ident.imdb:
        return ident.imdb, None, ""
    return None, None, ident.reason


class SubtitleFetcher:
    """
    OpenSubtitles.com REST client. Thread-safe and paced. Searches with the Api-Key
    alone; logs in (once) only when a username and password are configured, to raise
    the download quota; stops the run gracefully when the quota is used up.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()          # login state
        self._pace_lock = threading.Lock()     # request spacing
        self._last_request = 0.0
        self._token: Optional[str] = None
        self._host = _OS_DEFAULT_HOST
        self._login_tried = False
        self.login_problem = ""                # why the login failed, if it did
        self.quota_exhausted = False
        self.stop_reason = ""                  # why downloads stopped (quota, key refused)
        self.remaining: Optional[int] = None
        self._noted: Set[str] = set()

    # -- plumbing --------------------------------------------------------------------

    def _note_once(self, level: int, msg: str) -> None:
        with self._lock:
            if msg in self._noted:
                return
            self._noted.add(msg)
        logging.log(level, "%s", msg)

    def _headers(self) -> Dict[str, str]:
        h = {"Api-Key": CFG.OS_API_KEY, "User-Agent": _os_user_agent(),
             "Content-Type": "application/json", "Accept": "*/*"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"      # the manual: send it with every request
        return h

    def _pace(self) -> None:
        with self._pace_lock:
            wait = self._last_request + _OS_MIN_INTERVAL_S - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None
                 ) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
        """(status, parsed JSON) - the JSON of an error answer too, since it holds the reason."""
        url = f"https://{self._host}/api/v1{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        for attempt in range(4):
            self._pace()
            try:
                req = urllib.request.Request(url, data=data, method=method, headers=self._headers())
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return resp.status, json.loads(resp.read().decode("utf-8", errors="replace"))
            except urllib.error.HTTPError as e:
                body: Optional[Dict[str, Any]] = None
                try:
                    parsed = json.loads(e.read().decode("utf-8", errors="replace"))
                    body = parsed if isinstance(parsed, dict) else None
                except Exception:
                    pass
                logging.debug("OpenSubtitles %s %s -> %s %s", method, path, e.code, body)
                if e.code == 429 and attempt < 3:
                    try:
                        wait = float(e.headers.get("Retry-After") or e.headers.get("ratelimit-reset") or 2)
                    except ValueError:
                        wait = 2.0
                    logging.debug("OpenSubtitles rate limit - waiting %.0fs", wait)
                    time.sleep(min(max(wait, 1.0), _OS_MAX_RETRY_WAIT_S))
                    continue
                return e.code, body
            except Exception as e:
                logging.debug("OpenSubtitles %s %s failed: %s", method, path, e)
                return None, None
        return 429, None

    # -- login (optional) -------------------------------------------------------------

    def _ensure_login(self) -> bool:
        """True when logged in. Never needed: the Api-Key alone still searches and downloads a few a day."""
        with self._lock:
            if self._token:
                return True
            if self._login_tried or not (CFG.OS_USERNAME and CFG.OS_PASSWORD):
                return False
            self._login_tried = True       # a refused login is not retried: it is the "expensive" call
        code, data = self._request("POST", "/login",
                                   {"username": CFG.OS_USERNAME, "password": CFG.OS_PASSWORD})
        if code == 200 and data and data.get("token"):
            with self._lock:
                self._token = str(data["token"])
                host = str(data.get("base_url") or "")
                if host in _OS_HOSTS:
                    self._host = host       # the manual: continue on the host the login names
            user = data.get("user") or {}
            logging.info("OpenSubtitles login OK (level=%s, allowed downloads/day=%s)",
                         user.get("level", "?"), user.get("allowed_downloads"))
            return True
        self.login_problem = os_login_reason(code, data, CFG.OS_USERNAME)
        self._note_once(logging.WARNING,
                        f"OpenSubtitles login failed ({self.login_problem}). Carrying on with the API "
                        "key alone: searches work, but only a few downloads a day are allowed. "
                        "Fix username/password in [subtitles] to raise that.")
        return False

    # -- search ------------------------------------------------------------------------

    def search_candidates(self, mkv: Path, imdb_id: Optional[str], lang_iso1: str,
                          target: SubtitleTarget, *, tmdb_id: Optional[int] = None,
                          is_tv: bool = False, season: Optional[int] = None,
                          episode: Optional[int] = None) -> List[SubtitleCandidate]:
        """Every subtitle that could fit, best first. Searching costs no download quota."""
        searches = build_subtitle_searches(imdb_id, compute_oshash(mkv), lang_iso1, tmdb_id=tmdb_id,
                                           is_tv=is_tv, season=season, episode=episode)
        if not searches:
            return []
        self._ensure_login()        # before searching: a VIP host only answers with the token
        found: Dict[int, SubtitleCandidate] = {}
        for params in searches:
            _code, data = self._request("GET", "/subtitles?" + search_query_string(params))
            for it in (data or {}).get("data") or []:
                attrs = it.get("attributes") or {}
                files = attrs.get("files") or []
                if not files or not files[0].get("file_id"):
                    continue
                file_id = int(files[0]["file_id"])
                if file_id in found:
                    continue
                score, why = score_subtitle_candidate(attrs, target)
                if score is None:
                    logging.debug("Subtitle %s left out: %s", file_id, why[0])
                    continue
                found[file_id] = SubtitleCandidate(
                    file_id=file_id, score=score, release=str(attrs.get("release") or ""),
                    fps=float(attrs.get("fps") or 0.0), hash_match=bool(attrs.get("moviehash_match")),
                    reasons=why)
            if len(found) >= 2:      # enough to pick from, and to fall back on once
                break
        return sorted(found.values(), key=lambda c: -c.score)

    # -- download ----------------------------------------------------------------------

    def _stop(self, reason: str) -> None:
        self.quota_exhausted = True
        self.stop_reason = reason
        self._note_once(logging.WARNING, f"OpenSubtitles: {reason} - the remaining files are skipped.")

    def download(self, file_id: int) -> Optional[bytes]:
        """Download one subtitle; tracks the remaining quota from the answer."""
        if self.quota_exhausted:
            return None
        self._ensure_login()
        code, data = self._request("POST", "/download", {"file_id": file_id})
        msg = str((data or {}).get("message") or "").strip()
        if code in (401, 403, 500) and self._token and "invalid" in msg.lower():
            # The login token lasts 24 hours; a long run can outlive it. Log in once more.
            with self._lock:
                self._token, self._login_tried = None, False
            if self._ensure_login():
                code, data = self._request("POST", "/download", {"file_id": file_id})
                msg = str((data or {}).get("message") or "").strip()
        if code == 406 or (data and isinstance(data.get("remaining"), int) and data["remaining"] < 0):
            tail = "" if self._token else " Logging in (username and password in [subtitles]) raises the daily limit."
            self._stop(f"daily download quota used up ({msg or 'HTTP 406'}).{tail}")
            return None
        if code in (401, 403):
            if self._token:
                self._stop(f"the download was refused (HTTP {code}{': ' + msg if msg else ''})")
            else:
                self._stop(f"the download was refused with the API key alone (HTTP {code}"
                           f"{': ' + msg if msg else ''}) - either the key is wrong or its few free "
                           "downloads for this IP today are used up")
            return None
        if not data or not data.get("link"):
            logging.warning("OpenSubtitles download gave no link (HTTP %s%s)", code, f": {msg}" if msg else "")
            return None
        if isinstance(data.get("remaining"), int):
            self.remaining = data["remaining"]
            if self.remaining <= 0:
                self.quota_exhausted, self.stop_reason = True, "daily download quota used up"
        link = str(data["link"])
        host = (urllib.parse.urlparse(link).hostname or "").lower()
        if host != "opensubtitles.com" and not host.endswith(".opensubtitles.com"):
            logging.warning("OpenSubtitles gave a download link on an unexpected host (%s) - not following it.", host or "?")
            return None
        return _http_get_bytes(link)


def check_opensubtitles() -> str:
    """
    The status line for --validate-keys / --self-check.

    Search and the info endpoints answer even to a made-up key, so a key can only
    be confirmed by a login (which needs the username and password) or by a real
    download. Without a login this says so plainly instead of claiming "ok".
    """
    if not CFG.OS_API_KEY:
        return "not configured"
    if not (CFG.OS_USERNAME and CFG.OS_PASSWORD):
        return ("ok - API key only (no login set): search is unlimited and a few downloads a day work; "
                "the key itself can only be confirmed by a download. Add username/password to log in")
    f = SubtitleFetcher()
    if f._ensure_login():
        return "ok"
    msg = f.login_problem
    low = msg.lower()
    if "api key" in low or "api-key" in low:
        return "invalid"
    if "could not be reached" in msg:
        return "network error"
    return f"ok - API key only: the login was refused ({msg}); fix username/password to raise the download limit"


def process_subtitles_one(mkv: Path, is_tv: bool, fetcher: SubtitleFetcher, dry_run: bool) -> Result:
    """
    Download missing subtitles for one MKV as sidecar .srt files.
      1. Skip languages already covered (embedded track or existing sidecar).
      2. Identify the title (an id on the file, or the same identification a rename uses).
      3. Search, score the candidates against the video, download the best.
      4. Check it against the video's duration. If it clearly does not fit, try the
         next-best candidate ONCE; if that fails too, save nothing and say why.
      5. Strip advertising cues and save '<mkv stem>.srt' (extra languages: .<iso2>.srt).
    """
    kind = "subtitles"

    def blocked() -> Result:
        return Result(kind=kind, source_items=[mkv], output_path=None, ok=False,
                      reason=fetcher.stop_reason or "quota_exhausted", details={"blocked": True})

    try:
        meta = mkvmerge_identify_json(mkv)
        tracks = extract_tracks(mkv, meta)
        missing = missing_subtitle_langs(mkv, tracks)
        if not missing:
            logging.debug("Subtitles already covered, skipping: %s", mkv.name)
            return Result(kind=kind, source_items=[mkv], output_path=mkv, ok=True,
                          reason="already_covered")

        if dry_run:
            logging.info("[DRY] Would search subtitles for %s: langs=%s", mkv.name, missing)
            return Result(kind=kind, source_items=[mkv], output_path=mkv, ok=True, reason="dry-run")

        if fetcher.quota_exhausted:
            return blocked()

        duration = _container_duration_s(meta)
        target = SubtitleTarget(name=mkv.stem, duration_s=duration, fps=video_fps(meta))

        # An episode is searched by its series id with season and episode numbers; the
        # series id alone would only find the show's own entry, not this episode.
        season = episode = None
        show_title: Optional[str] = None
        show_year: Optional[str] = None
        if is_tv:
            show_label, s_str, e_str, _ep_title = infer_tv_components(mkv)
            season = int(s_str[1:]) if s_str else None
            episode = int(e_str[1:]) if e_str else None
            show_title, show_year = split_show_year(show_label or "")
        imdb_id, tmdb_id, problem = subtitle_identity(mkv, is_tv, show_title or None, show_year)

        got: List[str] = []
        notes: List[str] = []
        for lang in missing:
            cands = fetcher.search_candidates(mkv, imdb_id, lang, target, tmdb_id=tmdb_id, is_tv=is_tv,
                                              season=season, episode=episode)
            if not cands:
                why = problem or f"no {lang} subtitle found"
                logging.info("No %s subtitle for %s: %s", lang, mkv.name, why)
                notes.append(why)
                continue
            rejected: List[str] = []
            saved = False
            for attempt, cand in enumerate(cands[:2]):          # the best, then the next-best ONCE
                if fetcher.quota_exhausted:
                    break
                if attempt:
                    logging.info("Trying the next-best %s subtitle (uses one more download): %s",
                                 lang, mkv.name)
                logging.debug("Subtitle candidate %s score %.0f: %s | %s", cand.file_id, cand.score,
                              cand.release, "; ".join(cand.reasons))
                data = fetcher.download(cand.file_id)
                if data is None:
                    if fetcher.quota_exhausted:
                        break
                    rejected.append("the download failed")
                    continue
                fits, why, cleaned = verify_subtitle_fit(data, duration)
                if not fits:
                    logging.warning("%s subtitle for %s does not fit the video (%s): %s",
                                    lang, mkv.name, why, cand.release or cand.file_id)
                    rejected.append(why)
                    continue
                dst = subtitle_sidecar_path(mkv, lang)
                dst.write_text(cleaned, encoding="utf-8", newline="\n")
                got.append(lang)
                saved = True
                logging.info("Subtitle saved (%s%s%s): %s", lang,
                             f", quota left: {fetcher.remaining}" if fetcher.remaining is not None else "",
                             f", {why}" if why else "", dst.name)
                break
            if not saved and not fetcher.quota_exhausted:
                notes.append(f"no {lang} subtitle fit the video ({'; '.join(rejected)})")

        if got:
            return Result(kind=kind, source_items=[mkv], output_path=mkv, ok=True,
                          details={"langs": got, **({"notes": notes} if notes else {})})
        if fetcher.quota_exhausted:
            return blocked()
        return Result(kind=kind, source_items=[mkv], output_path=None, ok=False,
                      reason="; ".join(notes) or f"no subtitles found ({', '.join(missing)})")

    except Exception as e:
        logging.exception("Subtitles failed: %s", mkv.name)
        return Result(kind=kind, source_items=[mkv], output_path=None, ok=False, reason=str(e))


def run_subtitles_pipeline(
    do_movies: bool,
    do_tv: bool,
    dry_run: bool,
    workers: int,
    movies_root: Optional[Path] = None,
    tv_root: Optional[Path] = None,
    filters: Optional[List[str]] = None,
) -> List[Result]:
    """Scan Movies/TV roots and download missing sidecar subtitles."""
    movies_root = movies_root or CFG.MOVIES_ROOT
    tv_root = tv_root or CFG.TV_ROOT

    # Only the API key is required. A username and password are optional: they log in,
    # which raises the daily download limit, but searching and a few downloads a day
    # work with the key alone.
    if not dry_run and not CFG.OS_API_KEY:
        logging.error("--subtitles requires api_key in the [subtitles] section of %s "
                      "(a free consumer key from opensubtitles.com/en/consumers).", CONFIG_FILE.name)
        return [Result(kind="subtitles", source_items=[], output_path=None, ok=False,
                       reason="missing OpenSubtitles api_key")]
    if not dry_run and not (CFG.OS_USERNAME and CFG.OS_PASSWORD):
        logging.info("No username/password in [subtitles]: using the API key alone (search is "
                     "unlimited, but only a few downloads a day are allowed). Add them to log in "
                     "and raise that limit.")
    elif not dry_run and "@" in CFG.OS_USERNAME:
        logging.warning("The [subtitles] username looks like an email address. OpenSubtitles needs "
                        "your username, not your email - the login will be refused until it is fixed "
                        "(the API key alone still works meanwhile).")

    movie_set: set[Path] = set(apply_scan_filters(scan_mkvs(movies_root), movies_root,
                                                  filters, "subtitles")) if do_movies else set()
    tv_set: set[Path] = set(apply_scan_filters(scan_mkvs(tv_root), tv_root,
                                               filters, "subtitles")) if do_tv else set()
    if do_movies:
        logging.info("subtitles - Movies: %d MKV(s) found in %s.", len(movie_set), movies_root)
    if do_tv:
        logging.info("subtitles - TV: %d MKV(s) found in %s.", len(tv_set), tv_root)

    tagged: List[Tuple[Path, bool]] = []
    for p in sorted(movie_set | tv_set):
        if p in movie_set and p in tv_set:
            is_tv = bool(_SEASON_EP_RE.search(p.stem))
        else:
            is_tv = p in tv_set
        tagged.append((p, is_tv))

    fetcher = SubtitleFetcher()
    results: List[Result] = []
    # Keep concurrency low: the API rate-limits, and quota is a shared resource.
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(2, max(1, workers))) as ex:
        futs = {ex.submit(process_subtitles_one, p, is_tv, fetcher, dry_run): p
                for p, is_tv in tagged}
        for fut in concurrent.futures.as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as e:
                p = futs[fut]
                logging.exception("subtitles worker crashed: %s", p)
                results.append(Result(kind="subtitles", source_items=[p], output_path=None,
                                      ok=False, reason=f"Worker exception: {e}"))
    return results


# =========================
# Movie processing - ENHANCED
# =========================

def choose_best_video_across_files(metas: Dict[Path, Tuple[List[Track], int]]) -> Tuple[Path, Track]:
    """
    Choose the best video track across all files, preferring x265/HEVC.
    """
    best: Optional[Tuple[Tuple, Path, Track]] = None
    for f, (tracks, fsize) in metas.items():
        for t in tracks:
            if t.type != "video":
                continue
            sc = score_video(t, fsize)
            cand = (sc, f, t)
            if best is None or cand[0] < best[0]:
                best = cand
    if best is None:
        raise RuntimeError("No video track found across candidates.")
    return best[1], best[2]


def collect_all_audio_by_language(metas: Dict[Path, Tuple[List[Track], int]]) -> Dict[str, List[Tuple[Path, Track]]]:
    """
    ENHANCED: Collect ALL audio tracks for Hindi, Telugu, and English ONLY from all files.
    Returns Dict[canonical_lang, List[Tuple[file, track]]]
    
    This allows merging multiple audio tracks of the same language from different files.
    Tracks from other languages are completely excluded.
    Each list is sorted by quality (best first).
    """
    audio_collections: Dict[str, List[Tuple[Tuple, Path, Track]]] = {}
    
    for f, (tracks, _fsize) in metas.items():
        for t in tracks:
            if t.type != "audio":
                continue
            if is_excluded_audio(t):
                continue
            
            # Detect language
            canon = detect_language_canonical(t)
            
            # ONLY include Hindi, Telugu, and English (skip all other languages)
            if canon not in CFG.LANG_CANONICAL_ORDER:
                logging.debug("Skipping audio track (unsupported language): %s | track=%d lang=%s name=%s", 
                            f.name, t.id, t.language, t.name)
                continue
            
            sc = score_audio(t)
            if canon not in audio_collections:
                audio_collections[canon] = []
            audio_collections[canon].append((sc, f, t))
    
    # Sort each language's tracks by score (best first) and convert to final format
    result: Dict[str, List[Tuple[Path, Track]]] = {}
    for canon, track_list in audio_collections.items():
        track_list.sort(key=lambda x: x[0])  # Sort by score
        result[canon] = [(f, t) for (_, f, t) in track_list]
    
    return result


def choose_best_audio_by_language(metas: Dict[Path, Tuple[List[Track], int]]) -> Dict[str, Tuple[Path, Track]]:
    """
    Original function: Choose only the BEST audio track for each language.
    Kept for backward compatibility with TV processing.
    """
    chosen: Dict[str, Tuple[Path, Track]] = {}
    for f, (tracks, _fsize) in metas.items():
        for t in tracks:
            if t.type != "audio":
                continue
            if is_excluded_audio(t):
                continue
            canon = detect_language_canonical(t)
            if canon not in CFG.LANG_CANONICAL_ORDER:
                continue
            sc = score_audio(t)
            if canon not in chosen:
                chosen[canon] = (f, t)
            else:
                _, cur = chosen[canon]
                if sc < score_audio(cur):
                    chosen[canon] = (f, t)
    return chosen


def choose_best_english_sub(metas: Dict[Path, Tuple[List[Track], int]], include_forced: bool) -> Optional[Tuple[Path, Track]]:
    """Kept for reference; collect_all_subtitles is used in the pipeline instead."""
    candidates_normal: List[Tuple[Tuple, Path, Track]] = []
    candidates_forced: List[Tuple[Tuple, Path, Track]] = []
    for f, (tracks, _fsize) in metas.items():
        for t in tracks:
            if t.type != "subtitles":
                continue
            canon = detect_language_canonical(t)
            if canon != "eng":
                continue
            sc = score_sub(t, include_forced=include_forced)
            if t.forced:
                candidates_forced.append((sc, f, t))
            else:
                candidates_normal.append((sc, f, t))

    if candidates_normal:
        candidates_normal.sort(key=lambda x: x[0])
        return (candidates_normal[0][1], candidates_normal[0][2])

    if include_forced and candidates_forced:
        candidates_forced.sort(key=lambda x: x[0])
        return (candidates_forced[0][1], candidates_forced[0][2])

    return None


def collect_all_subtitles(
    metas: Dict[Path, Tuple[List[Track], int]]
) -> Dict[Path, List[Track]]:
    """
    Collect subtitle tracks from all source files, grouped by file.

    Rules applied:
    - Only keep tracks whose language is Hindi, Telugu, or English (target langs).
    - Keep BOTH regular AND SDH/hearing-impaired tracks for all three languages.
    - Strip commentary/SDH-excluded subtitle tracks (non-SDH exclusions only).
    - When the same (language, codec, sdh_flag) combination appears in more than
      one source file, keep only the best-scoring one to avoid duplicates.

    Returns Dict[file_path, List[Track]] sorted by original track id within each file.
    """
    target_langs = set(CFG.LANG_CANONICAL_ORDER)

    # key: (canonical_lang, codec_id, is_sdh) -> (score, file, track)
    best_by_key: Dict[Tuple[str, str, bool], Tuple[Tuple, Path, Track]] = {}

    for f, (tracks, _fsize) in metas.items():
        for t in tracks:
            if t.type != "subtitles":
                continue
            canon = detect_language_canonical(t)
            if canon not in target_langs:
                logging.debug("Dropping subtitle track (non-target language): file=%s track=%d lang=%s name=%r",
                              f.name, t.id, t.language, t.name)
                continue
            sdh = is_sdh_subtitle(t)
            codec_key = (t.codec_id or "").lower()
            dedup_key = (canon, codec_key, sdh)
            sc = score_sub(t, include_forced=True)
            if dedup_key not in best_by_key or sc < best_by_key[dedup_key][0]:
                best_by_key[dedup_key] = (sc, f, t)

    result: Dict[Path, List[Track]] = {}
    for (_lang, _codec, _sdh), (sc, f, t) in best_by_key.items():
        result.setdefault(f, []).append(t)

    for f in result:
        result[f].sort(key=lambda t: t.id)

    return result


def compute_relpath_under_root(p: Path, root: Path) -> Path:
    try:
        return p.relative_to(root)
    except ValueError:
        # Should not happen; fallback
        return Path(p.name)


def output_path_for_item(src_item: Path, root: Path, new_filename: str) -> Path:
    rel = compute_relpath_under_root(src_item, root)
    return CFG.OUTPUT_ROOT / rel.parent / new_filename


def build_movie_output_name(
    movie_name: str,
    year: Optional[str],
    imdb_id: Optional[str],
    res_tag: str,
    source_tag: Optional[str],
    codec_tag: str,
    audio_langs: List[str],
    bracket: Optional[str] = None,
) -> str:
    """
    Movies naming (requested):
      Movie Name (Year) - imdbID - RipType.Resolution.VideoCodec - [Lang1 + Lang2 + Lang3].mkv

    Example:
      The Film (2026) - tt1234567 - HDRip.1080p.x265 - [Telugu + Hindi].mkv

    'bracket' overrides the language list when the caller has already worked out
    what the file really carries (a name built from the file alone must not say
    'NoAudioMatch' about a language that merely is not a configured target).
    """
    base = sanitize_filename(movie_name)
    title = f"{base} ({year})" if year else base

    bracket = bracket or build_audio_bracket(audio_langs)

    # Rip (source) is first; fall back to WebRip if unknown/missing
    rip = sanitize_filename(source_tag) if source_tag else "WebRip"
    mid = f"{rip}.{res_tag}.{codec_tag}"

    imdb_part = f"{sanitize_filename(imdb_id)}" if imdb_id else None
    if imdb_part:
        fn = f"{title} - {imdb_part} - {mid} - [{bracket}].mkv"
    else:
        fn = f"{title} - {mid} - [{bracket}].mkv"

    return fn


# --preview-exact: ask FileBot itself for the dry-run name instead of predicting
# it from the database. Authoritative but costs a JVM launch per item.
_PREVIEW_EXACT: bool = False


def _filebot_preview_name(sample: Path, db: str, fmt: str, query: Optional[str],
                          year: Optional[str], langs: List[str]) -> Optional[str]:
    """
    Ask FileBot what it would name this file (`--action test`, writes nothing).

    The merged output does not exist yet during a dry run, so the probe runs
    against the source that supplies the video — its resolution, codec and
    source tag are the ones the output will carry. Only the audio set differs
    after a merge, so the language bracket is substituted with the merged one.
    """
    if not CFG.FILEBOT_EXE.exists() or _FILEBOT_DISABLED or not sample.exists():
        return None
    fmt = _pin_resolution_in_format(fmt, sample)
    cmd = [str(CFG.FILEBOT_EXE), "-rename", str(sample),
           "--db", db, "--format", fmt, "--output", str(sample.parent),
           "--action", "test", "--conflict", "skip", "-non-strict"]
    if query:
        cmd += ["--q", query]
    cmd += _filebot_year_filter(query, db, year=year)

    r = run_cmd(cmd, timeout_sec=600)
    m_name = re.search(r"\[TEST\] from \[.+?\] to \[(.+?)\]\s*$", (r.out or ""), flags=re.M)
    if not m_name:
        return None
    name = Path(m_name.group(1)).name
    if langs:
        name = re.sub(r"\[[^\]]*\](?=\.mkv$)", f"[{build_audio_bracket(langs)}]", name)
    return name


def predict_movie_final_name(sample: Path, title: str, year: Optional[str], imdb_id: Optional[str],
                             res_tag: str, source_tag: Optional[str], codec_tag: str,
                             langs: List[str], exact: bool) -> Optional[str]:
    """Best estimate of the filename a real run would end up with, for --dry-run."""
    if exact:
        name = _filebot_preview_name(
            sample, CFG.FILEBOT_DB, MOVIE_FILEBOT_FORMAT,
            f"{title} ({year})" if title and year else (title or None), year, langs)
        if name:
            return name
    # Database prediction: the canonical title and IMDB id are the parts the
    # rename adds; resolution/codec/source/languages we already computed.
    if _FETCH_TAGS_ENABLED and CFG.TMDB_API_KEY and imdb_id:
        try:
            meta = _get_meta_fetcher().movie_metadata(title, year, imdb_id)
            if meta:
                return build_movie_output_name(
                    meta.get("title") or title, meta.get("year") or year,
                    imdb_id or meta.get("imdb_id"), res_tag, source_tag, codec_tag, langs)
        except Exception as e:
            logging.debug("Name prediction failed for %s: %s", sample.name, e)
    return None


def predict_tv_final_name(sample: Path, show: str, season_str: Optional[str], ep_str: Optional[str],
                          ep_title: Optional[str], res_tag: str, codec_tag: str,
                          langs: List[str], exact: bool) -> Optional[str]:
    """Best estimate of the episode filename a real run would produce, for --dry-run."""
    bare, show_year = split_show_year(show or "")
    search = bare or None

    if exact:
        name = _filebot_preview_name(sample, "TheTVDB", TV_FILEBOT_FORMAT, search, show_year, langs)
        if name:
            return name
    if _FETCH_TAGS_ENABLED and CFG.TMDB_API_KEY and season_str and ep_str:
        try:
            meta = _get_meta_fetcher().episode_metadata(
                show, None, int(season_str[1:]), int(ep_str[1:]))
            if meta:
                show_disp = meta.get("show") or show
                if meta.get("show_year") and "(" not in show_disp:
                    show_disp = f"{show_disp} ({meta['show_year']})"
                return build_tv_output_name(show_disp, season_str, ep_str,
                                            meta.get("ep_title") or ep_title,
                                            res_tag, codec_tag, langs)
        except Exception as e:
            logging.debug("Name prediction failed for %s: %s", sample.name, e)
    return None



# =========================
# MP4 -> MKV conversion (--mp4tomkv)
# =========================
# MP4 carries no Matroska tags and usually leaves every track 'und', so a
# converted file relies on the same identification the rest of the tool uses.
# mkvmerge reads MP4 natively, so this is a lossless remux, never a re-encode.

VIDEO_CONVERT_EXTS: Tuple[str, ...] = (".mp4", ".m4v")
SIDECAR_SUB_EXTS: Tuple[str, ...] = (".srt",)

# Cues and chapter names that advertise rather than translate. Releases inject
# these at the very start or end of a subtitle, where they play over the film.
#
# Only STRUCTURAL patterns ship here — web addresses and the stock phrasings of
# an advert. Specific distributor or site names are not in the source: they live
# in [naming] strip_prefixes in the user's own config, the same list already used
# to strip those names from filenames, and are folded in at runtime below.
_AD_PATTERNS = re.compile(
    r"(?i)(?:"
    r"\bwww\.[a-z0-9-]+\.[a-z]{2,}"          # bare web addresses
    r"|\b[a-z0-9-]+\.(?:com|net|org|tv|cat|bz|gg|me|to|in|xyz|top|club|site)\b"
    r"|downloaded\s+from|please\s+visit|visit\s+(?:us|our)"
    r"|subtitles?\s+by\s+\S+|advertise\s+your|support\s+us"
    r"|official\s+\S+\s+(?:movies?|site)"
    r")"
)


def _looks_like_advertising(text: str) -> bool:
    """
    True when a subtitle cue or chapter name advertises rather than belongs to
    the film. Combines the built-in structural patterns with whatever site names
    the user configured in [naming] strip_prefixes.
    """
    if _AD_PATTERNS.search(text):
        return True
    for name in (CFG.STRIP_PREFIXES if CFG else ()):
        if name and name.lower() in text.lower():
            return True
    return False


# How far into a subtitle an advertisement is still plausibly an advertisement.
_AD_WINDOW_S = 60.0
# Below this many cues per minute a subtitle only covers foreign dialogue.
_FORCED_CUES_PER_MIN = 2.0


def _decode_subtitle_bytes(raw: bytes) -> Tuple[str, str]:
    """
    Decode subtitle bytes, returning (text, charset). Sidecar files come in
    UTF-8 with or without a BOM, and in legacy single-byte encodings; guessing
    wrong turns accented text into mojibake inside the muxed file.
    """
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace"), "UTF-8"
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc), ("UTF-8" if enc == "utf-8" else enc.upper())
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "UTF-8"


def _srt_timestamp_seconds(stamp: str) -> Optional[float]:
    m = re.match(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})", stamp.strip())
    if not m:
        return None
    h, mi, s, ms = (int(g) for g in m.groups())
    return h * 3600 + mi * 60 + s + ms / 1000.0


def parse_srt(text: str) -> List[Tuple[Optional[float], Optional[float], str, str]]:
    """
    Split an SRT into (start_s, end_s, timing_line, body) blocks.
    Returns [] when the text does not look like SRT at all.
    """
    blocks: List[Tuple[Optional[float], Optional[float], str, str]] = []
    text = text.lstrip("﻿")   # mkvextract writes a BOM; it must not hide cue 1
    for chunk in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n")):
        lines = [ln for ln in chunk.split("\n") if ln.strip()]
        if not lines:
            continue
        if lines[0].strip().isdigit():
            lines = lines[1:]
        if not lines or "-->" not in lines[0]:
            continue
        timing = lines[0]
        start_raw, _, end_raw = timing.partition("-->")
        blocks.append((_srt_timestamp_seconds(start_raw), _srt_timestamp_seconds(end_raw),
                       timing.strip(), "\n".join(lines[1:])))
    return blocks


def clean_srt_advertisements(text: str, duration_s: Optional[float]) -> Tuple[str, List[str]]:
    """
    Remove advertising cues from an SRT, returning (cleaned_text, removed).

    Only cues inside the first or last minute are eligible: that is where
    releases inject them, and dialogue mentioning a web address mid-film is
    real dialogue. Renumbers what remains so the result is a valid SRT.
    """
    blocks = parse_srt(text)
    if not blocks:
        return text, []

    end_zone = (duration_s - _AD_WINDOW_S) if duration_s else None
    kept: List[Tuple[str, str]] = []
    removed: List[str] = []
    for start, _end, timing, body in blocks:
        in_window = (start is not None
                     and (start <= _AD_WINDOW_S or (end_zone is not None and start >= end_zone)))
        if in_window and _looks_like_advertising(body):
            removed.append(f"{timing.split('-->')[0].strip()} {' / '.join(body.split(chr(10)))[:60]}")
            continue
        kept.append((timing, body))

    if not removed:
        return text, []
    rebuilt = "\n\n".join(f"{i}\n{timing}\n{body}" for i, (timing, body) in enumerate(kept, 1))
    return rebuilt + "\n", removed


def subtitle_looks_forced(text: str, duration_s: Optional[float]) -> bool:
    """
    True when a subtitle only covers foreign dialogue rather than everything.

    A full subtitle runs to roughly ten cues a minute; a forced one carries a
    few dozen for a whole film. Flagging it matters because players show forced
    subtitles automatically over untranslated speech.
    """
    blocks = parse_srt(text)
    if not blocks or not duration_s or duration_s <= 0:
        return False
    return (len(blocks) / (duration_s / 60.0)) < _FORCED_CUES_PER_MIN


def find_sidecar_subtitles(video: Path) -> List[Path]:
    """Sidecar subtitles belonging to a video: '<stem>.srt', '<stem>.<tag>.srt'."""
    stem = video.stem.lower()
    found: List[Path] = []
    for p in sorted(video.parent.glob("*")):
        if not p.is_file() or p.suffix.lower() not in SIDECAR_SUB_EXTS:
            continue
        name = p.stem.lower()
        if name == stem or name.startswith(stem + "."):
            found.append(p)
    return found


def sanitize_mkv_chapter_names(mkv: Path, dry_run: bool = False) -> int:
    """
    Rewrite advertising chapter names in place, keeping every timestamp.

    Chapters are genuine navigation data worth keeping, but a release can rename
    them into advertising. Names that advertise become a plain 'Chapter NN';
    nothing else is touched. Returns how many names were rewritten.
    """
    if not CFG.MKVEXTRACT_EXE.exists() or not CFG.MKVPROPEDIT_EXE.exists():
        return 0
    r = run_cmd([str(CFG.MKVEXTRACT_EXE), str(mkv), "chapters", "-s"], timeout_sec=120)
    if not r.ok or not (r.out or "").strip():
        return 0

    lines = (r.out or "").splitlines()
    changed = 0
    out_lines: List[str] = []
    for line in lines:
        m = re.match(r"(CHAPTER(\d+)NAME)=(.*)$", line.strip())
        if m and _looks_like_advertising(m.group(3)):
            out_lines.append(f"{m.group(1)}=Chapter {m.group(2)}")
            logging.info("Chapter name advertised (%s) — renaming to 'Chapter %s': %s",
                         m.group(3).strip()[:50], m.group(2), mkv.name)
            changed += 1
        else:
            out_lines.append(line)
    if not changed or dry_run:
        return changed

    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".txt", prefix="mcchap_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(out_lines) + "\n")
        w = run_cmd([str(CFG.MKVPROPEDIT_EXE), str(mkv), "--chapters", tmp], timeout_sec=120)
        if not w.ok:
            logging.warning("Could not rewrite chapter names (non-fatal): %s", w.err.strip()[:160])
            return 0
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return changed


MP4TOMKV_LEDGER_CSV = _SCRIPT_DIR / "logs" / "mp4tomkv_done.csv"


def _mp4_ledger_path() -> Path:
    return MP4TOMKV_LEDGER_CSV


def _mp4_ledger_load() -> Dict[str, str]:
    """Sources already converted, keyed by 'path|size' so a re-download redoes it."""
    done: Dict[str, str] = {}
    p = _mp4_ledger_path()
    if not p.exists():
        return done
    try:
        with open(p, "r", encoding="utf-8", newline="") as fh:
            for row in csv.reader(fh):
                if len(row) >= 2:
                    done[row[0]] = row[1]
    except OSError as e:
        logging.debug("Could not read %s: %s", p.name, e)
    return done


def _mp4_ledger_add(key: str, produced: str) -> None:
    p = _mp4_ledger_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        new = not p.exists()
        with open(p, "a", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(["source", "produced", "when"])
            w.writerow([key, produced, _dt.datetime.now().isoformat(timespec="seconds")])
    except OSError as e:
        logging.debug("Could not update %s: %s", p.name, e)


def _ledger_key(src: Path) -> str:
    try:
        return f"{src}|{src.stat().st_size}"
    except OSError:
        return str(src)


def scan_convertible(root: Path) -> List[Path]:
    """Video files that are not Matroska and can be remuxed into it."""
    if not root.exists():
        logging.warning("Root not found (skipping): %s", root)
        return []
    return sorted(p for p in root.rglob("*")
                  if p.is_file() and p.suffix.lower() in VIDEO_CONVERT_EXTS)


def _prepare_sidecars(video: Path, tmpdir: Path, dry_run: bool) -> List[Dict[str, Any]]:
    """
    Read, clean and describe each sidecar subtitle belonging to a video.

    Returns one entry per usable subtitle with its cleaned file, language and
    forced flag. Advertising cues are removed here, before anything is muxed.
    """
    prepared: List[Dict[str, Any]] = []
    for idx, sub in enumerate(find_sidecar_subtitles(video)):
        try:
            raw = sub.read_bytes()
        except OSError as e:
            logging.warning("Cannot read subtitle %s: %s", sub.name, e)
            continue
        text, charset = _decode_subtitle_bytes(raw)

        blocks = parse_srt(text)
        if not blocks:
            logging.warning("Not a usable SRT, skipping: %s", sub.name)
            continue
        # The film's runtime is unknown for MP4, so use the subtitle's own last
        # cue: it tracks the end of the film closely enough for both decisions.
        duration_s = max((b[1] or b[0] or 0.0) for b in blocks) or None

        cleaned, removed = clean_srt_advertisements(text, duration_s)
        if removed:
            logging.info("Removed %d advertising cue(s) from %s:", len(removed), sub.name)
            for r in removed:
                logging.info("    %s", r)

        canon, conf = identify_text_language(cleaned)
        forced = subtitle_looks_forced(cleaned, duration_s)
        logging.info("Subtitle %s: %s%s, %d cues%s, charset %s",
                     sub.name,
                     language_display(canon) if canon else "undetermined",
                     f" ({conf})" if canon else "",
                     len(parse_srt(cleaned)),
                     " — forced/foreign-parts only" if forced else "",
                     charset)

        out = tmpdir / f"{idx}_{sub.stem[:40]}.srt"
        if not dry_run:
            out.write_text(cleaned, encoding="utf-8", newline="\n")
        prepared.append({"path": out, "source": sub, "lang": canon,
                         "forced": forced, "removed": len(removed)})
    return prepared


def convert_one_to_mkv(src: Path, dry_run: bool, overwrite: bool) -> Tuple[Optional[Path], str]:
    """
    Remux one MP4/M4V (plus any sidecar subtitles) into MKV beside the source.

    The source is only ever READ — it is kept whatever else happens. Returns
    (output path, reason); output is None when nothing was produced.
    """
    target = src.with_suffix(".mkv")
    if target.exists() and not overwrite:
        return None, f"an MKV of that name already exists: {target.name}"

    import tempfile
    with tempfile.TemporaryDirectory(prefix="mcmp4_") as td:
        tmpdir = Path(td)
        subs = _prepare_sidecars(src, tmpdir, dry_run)

        out_tmp = target.with_suffix(".mkv.tmp")
        cmd = [win_long_path(CFG.MKVMERGE_EXE), "-o", win_long_path(out_tmp),
               "--no-global-tags",            # MP4 metadata is not worth carrying over
               win_long_path(src)]            # chapters are kept deliberately
        for s in subs:
            if s["lang"]:
                cmd += ["--language", f"0:{s['lang']}",
                        "--track-name", f"0:{language_display(s['lang'])}"]
            cmd += ["--forced-track", f"0:{'yes' if s['forced'] else 'no'}",
                    "--sub-charset", "0:UTF-8", win_long_path(s["path"])]

        if dry_run:
            logging.info("[DRY] mkvmerge command: %s", " ".join(cmd))
            return target, "dry-run"

        r = run_cmd(cmd, timeout_sec=3600)
        if not r.ok:
            for leftover in (out_tmp,):
                try:
                    leftover.unlink(missing_ok=True)
                except OSError:
                    pass
            return None, f"mkvmerge failed rc={r.rc}: {(r.err or r.out or '').strip()[:200]}"

        # Sanity: the output must carry the video plus every subtitle we passed.
        try:
            meta = mkvmerge_identify_json(out_tmp)
            kinds = [str(t.get("type")) for t in meta.get("tracks", [])]
            if kinds.count("video") != 1 or kinds.count("subtitles") != len(subs):
                out_tmp.unlink(missing_ok=True)
                return None, (f"unexpected output tracks: video={kinds.count('video')} "
                              f"subs={kinds.count('subtitles')} (expected 1 and {len(subs)})")
        except Exception as e:
            out_tmp.unlink(missing_ok=True)
            return None, f"could not verify output: {e}"

        os.replace(out_tmp, target)

    renamed = sanitize_mkv_chapter_names(target, dry_run=False)
    if renamed:
        logging.info("Sanitized %d advertising chapter name(s): %s", renamed, target.name)
    return target, "converted"


def _predict_converted_final_name(src: Path, is_tv: bool) -> Optional[str]:
    """
    The name a converted file would end up with, for --dry-run.

    Everything is read from the MP4 itself except the audio language, which the
    source leaves 'und' — that comes from the title's TMDB original language,
    exactly as the real run resolves it.
    """
    try:
        tracks = extract_tracks(src, mkvmerge_identify_json(src))
    except Exception:
        return None
    video = next((t for t in tracks if t.type == "video"), None)
    if video is None:
        return None

    res_tag = infer_resolution_tag_from_video(video, fallback_filename=src.name)
    codec_tag = codec_tag_video(video)
    if codec_tag in ("unknown", "video"):
        codec_tag = infer_codec_tag_from_filename(src.name) or codec_tag
    source_tag = infer_source_tag_from_filename(src.name)

    if is_tv:
        show, season, ep, ep_title = infer_tv_components(src)
        bare, year = split_show_year(show or "")
        langs = _converted_audio_langs(tracks, bare or show, year, True)
        return predict_tv_final_name(src, show, season, ep, ep_title,
                                     res_tag, codec_tag, langs, exact=False)

    title, year = infer_movie_name_year_from_path(src)
    langs = _converted_audio_langs(tracks, title, year, False)
    return predict_movie_final_name(src, title, year, None, res_tag, source_tag,
                                    codec_tag, langs, exact=False)


def _converted_audio_langs(tracks: List[Track], title: str, year: Optional[str],
                           is_tv: bool) -> List[str]:
    """Audio languages the converted file will carry, resolving a lone 'und'."""
    audio = [t for t in tracks if t.type == "audio" and not is_excluded_audio(t)]
    langs: List[str] = []
    for t in audio:
        canon = detect_language_canonical(t)
        if canon is None and len(audio) == 1 and title:
            canon = tmdb_original_language(title, year, is_tv)
        if canon and canon not in langs:
            langs.append(canon)
    return [c for c in CFG.LANG_CANONICAL_ORDER if c in langs] or langs


def run_mp4tomkv_pipeline(
    do_movies: bool,
    do_tv: bool,
    movies_root: Path,
    tv_root: Path,
    dry_run: bool,
    overwrite: bool,
    filters: Optional[List[str]],
    include_forced_subs: bool,
    audio_lang_filter: Optional[List[str]],
    skip_cleantags: bool,
    force_audio_langs: Optional[Dict[int, str]],
    force_sub_langs: Optional[Dict[int, str]],
) -> List[Result]:
    """
    Convert MP4/M4V files to MKV and finish them completely.

    Each source is remuxed beside itself (never re-encoded, never deleted), any
    sidecar subtitle is cleaned of advertising and muxed in, then the finished
    MKV goes through the ordinary per-item pipeline — tag cleaning, metadata,
    language resolution, cover art and the database rename — so nothing about
    the finishing behaviour is duplicated here.
    """
    targets: List[Tuple[Path, bool, Path]] = []
    if do_movies:
        found = apply_scan_filters(scan_convertible(movies_root), movies_root, filters, "mp4tomkv")
        logging.info("mp4tomkv - Movies: %d convertible file(s) in %s.", len(found), movies_root)
        targets += [(p, False, movies_root) for p in found]
    if do_tv:
        found = apply_scan_filters(scan_convertible(tv_root), tv_root, filters, "mp4tomkv")
        logging.info("mp4tomkv - TV: %d convertible file(s) in %s.", len(found), tv_root)
        targets += [(p, True, tv_root) for p in found]

    if not targets:
        logging.info("mp4tomkv: nothing to convert.")
        return []

    ledger = _mp4_ledger_load()
    results: List[Result] = []

    for src, is_tv, root in targets:
        key = _ledger_key(src)
        if key in ledger and not overwrite:
            logging.info("Already converted (ledger), skipping: %s", src.name)
            results.append(Result(kind="mp4tomkv", source_items=[src], output_path=None,
                                  ok=True, reason="already converted",
                                  details={"produced": ledger[key]}))
            continue

        logging.info("Converting to MKV: %s", src.name)
        produced, why = convert_one_to_mkv(src, dry_run=dry_run, overwrite=overwrite)
        if produced is None:
            logging.warning("mp4tomkv failed: %s — %s", src.name, why)
            results.append(Result(kind="mp4tomkv", source_items=[src], output_path=None,
                                  ok=False, reason=why))
            continue

        if dry_run:
            logging.info("[DRY] Would convert %s -> %s (source kept)", src.name, produced.name)
            final_name = _predict_converted_final_name(src, is_tv)
            if final_name:
                logging.info("[DRY] Final name would be: %s", final_name)
            results.append(Result(kind="mp4tomkv", source_items=[src], output_path=produced,
                                  ok=True, reason="dry-run",
                                  details={"predicted": final_name or produced.name}))
            continue

        logging.info("Converted -> %s (source kept)", produced.name)

        # Finish the new MKV with the ordinary pipeline. inplace=True keeps it in
        # this folder if it needs a further remux; the MP4 is untouched either way.
        try:
            if is_tv:
                res = process_tv_file(
                    produced, root, dry_run=False, overwrite=True,
                    include_forced_subs=include_forced_subs,
                    audio_lang_filter=audio_lang_filter, skip_cleantags=skip_cleantags,
                    force_audio_langs=force_audio_langs, force_sub_langs=force_sub_langs,
                    inplace=True, backup=False)
            else:
                res = process_movie_group(
                    [produced], root, dry_run=False, overwrite=True,
                    include_forced_subs=include_forced_subs,
                    audio_lang_filter=audio_lang_filter, skip_cleantags=skip_cleantags,
                    force_audio_langs=force_audio_langs, force_sub_langs=force_sub_langs,
                    inplace=True, backup=False)
        except Exception as e:
            logging.exception("Finishing failed for %s", produced.name)
            results.append(Result(kind="mp4tomkv", source_items=[src], output_path=produced,
                                  ok=False, reason=f"converted, but finishing failed: {e}"))
            continue

        final = res.output_path or produced
        _mp4_ledger_add(key, final.name)
        results.append(Result(kind="mp4tomkv", source_items=[src], output_path=final,
                              ok=res.ok, reason=res.reason,
                              details={**(res.details or {}), "converted_from": src.name}))

    return results

# --- Names built from the file alone ----------------------------------------
# When every database that could be asked found nothing, the file is still named
# and tagged — but only from facts that are in the file: the title and year its
# own filename states, and the resolution, codec and audio languages read from
# the video and its tracks. No id, no poster, no synopsis, no cast is invented,
# and the result is reported as LOCAL and written to a ledger so a name that no
# database confirmed can always be told apart from one that was.

LOCAL_NAMED_CSV = _SCRIPT_DIR / "logs" / "local_named.csv"
_LOCAL_LEDGER_LOCK = threading.Lock()
_LOWER_WORDS = frozenset("a an and as at but by for from in of on or the to with".split())


def _tidy_title(title: str) -> str:
    """
    Capitalise a title written entirely in lower case ('some film' -> 'Some Film').

    A title that already has any capital letter is left exactly as written: that
    is information (an acronym, a stylised name) the script cannot reconstruct.
    """
    t = (title or "").strip()
    if not t or t != t.lower():
        return t
    return " ".join(w if (i and w in _LOWER_WORDS) else w[:1].upper() + w[1:]
                    for i, w in enumerate(t.split(" ")))


def _local_title_usable(title: Optional[str], year: Optional[str], *, need_year: bool) -> bool:
    """A name built from the file needs a real title, and for a film a plausible year."""
    t = (title or "").strip()
    if not t or not re.search(r"[^\W_]", t) or t.lower() == "unknownshow":
        return False
    if need_year:
        if not (year and str(year).isdigit()):
            return False
        return 1888 <= int(year) <= _dt.date.today().year + 1
    return True


def _local_audio_bracket(tracks: List[Track]) -> str:
    """
    The languages a file's audio really carries, configured targets first.

    Unlike build_audio_bracket this does not drop a language just because it is
    not a configured target: the name describes the file, it does not select.
    """
    found: List[str] = []
    for t in tracks:
        if t.type != "audio" or is_excluded_audio(t):
            continue
        raw = (t.language or "und").lower()
        canon = resolve_language(raw) if raw != "und" else detect_language_canonical(t)
        if canon and canon not in found:
            found.append(canon)
    order = {c: i for i, c in enumerate(CFG.LANG_CANONICAL_ORDER)}
    found.sort(key=lambda c: order.get(c, len(order)))     # stable: file order otherwise
    return " + ".join(language_display(c) for c in found) or "Unknown"


def _local_file_facts(src: Path) -> Optional[Dict[str, Any]]:
    """Resolution, codec, source and audio languages as read from the file itself."""
    try:
        tracks = extract_tracks(src, mkvmerge_identify_json(src))
    except Exception as e:
        logging.debug("Could not read %s: %s", src.name, e)
        return None
    video = next((t for t in tracks if t.type == "video"), None)
    if video is None:
        return None
    codec = codec_tag_video(video)
    if codec in ("unknown", "video"):
        codec = infer_codec_tag_from_filename(src.name) or codec
    return {
        "res": infer_resolution_tag_from_video(video, fallback_filename=src.name),
        "codec": codec,
        "source": infer_source_tag_from_filename(src.name),
        "bracket": _local_audio_bracket(tracks),
    }


def _local_ledger_add(kind: str, old: Path, new: Path, why: str) -> None:
    try:
        LOCAL_NAMED_CSV.parent.mkdir(parents=True, exist_ok=True)
        with _LOCAL_LEDGER_LOCK:
            fresh = not LOCAL_NAMED_CSV.exists()
            with open(LOCAL_NAMED_CSV, "a", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                if fresh:
                    w.writerow(["when", "kind", "old_path", "new_path", "why"])
                w.writerow([_dt.datetime.now().isoformat(timespec="seconds"),
                            kind, str(old), str(new), why])
    except OSError as e:
        logging.debug("Could not write %s: %s", LOCAL_NAMED_CSV.name, e)


def _rename_file_to(src: Path, dest: Path, outcome: Dict[str, Any]) -> Optional[Path]:
    """
    Rename src to dest, refusing to overwrite. Records the result in outcome and
    returns the file's path afterwards (src itself when it already has that name).
    """
    if os.path.normcase(str(dest)) == os.path.normcase(str(src)):
        outcome["ok"], outcome["reason"] = True, ""
        return src
    if dest.exists():
        outcome["ok"], outcome["reason"] = False, f"target name already in use: {dest.name}"
        return None
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dest)
    except OSError as e:
        outcome["ok"], outcome["reason"] = False, f"could not rename: {e}"
        return None
    outcome["ok"], outcome["reason"] = True, ""
    return dest


def _finish_local_rename(src: Path, new_name: str, kind: str, why: str,
                         outcome: Dict[str, Any]) -> Optional[Path]:
    """Rename a file to a name built from itself, and say so everywhere it is seen."""
    result = _rename_file_to(src, src.with_name(new_name), outcome)
    if result is None:
        return None
    outcome["local"], outcome["local_name"] = True, new_name
    if result != src:
        logging.info("Named from the file alone (%s): %s -> %s", why, src.name, result.name)
        _local_ledger_add(kind, src, result, why)
    return result


def local_movie_name(src: Path, movie_name: str, year: Optional[str]) -> Tuple[Optional[str], str]:
    """The name a film would get from its own file, or why it cannot get one."""
    if not _local_title_usable(movie_name, year, need_year=True):
        return None, "the filename gives no usable title and year"
    facts = _local_file_facts(src)
    if not facts or facts["res"] == "UnknownRes" or facts["codec"] in ("unknown", "video"):
        return None, "the video's resolution or codec could not be read"
    return build_movie_output_name(_tidy_title(movie_name), year, None, facts["res"],
                                   facts["source"], facts["codec"], [],
                                   bracket=facts["bracket"]), ""


def rename_movie_from_file(src: Path, movie_name: str, year: Optional[str],
                           why: str, outcome: Dict[str, Any]) -> Optional[Path]:
    name, problem = local_movie_name(src, movie_name, year)
    if not name:
        outcome["ok"], outcome["reason"] = False, f"{why}; {problem}, so it was left as it is"
        return None
    return _finish_local_rename(src, name, "movie", why, outcome)


def tv_local_name(src: Path) -> Tuple[Optional[str], str]:
    """The name an episode would get from its own file, or why it cannot get one."""
    show, season, ep, ep_title = infer_tv_components(src)
    bare, _year = split_show_year(show or "")
    if not _local_title_usable(bare, None, need_year=False):
        return None, "the filename gives no usable show title"
    if not (season and ep):
        return None, "the filename gives no season and episode number"
    facts = _local_file_facts(src)
    if not facts or facts["res"] == "UnknownRes" or facts["codec"] in ("unknown", "video"):
        return None, "the video's resolution or codec could not be read"
    return build_tv_output_name(_tidy_title(show), season, ep, ep_title, facts["res"],
                                facts["codec"], [], bracket=facts["bracket"]), ""


def rename_tv_from_file(src: Path, why: str, outcome: Dict[str, Any]) -> Optional[Path]:
    name, problem = tv_local_name(src)
    if not name:
        outcome["ok"], outcome["reason"] = False, f"{why}; {problem}, so it was left as it is"
        return None
    return _finish_local_rename(src, name, "tv", why, outcome)


def _omdb_movie_by_id(imdb_id: str) -> Optional[Dict[str, Any]]:
    """OMDb's record for an IMDB id, when it is a film."""
    if not CFG.OMDB_API_KEY or not imdb_id:
        return None
    data = _http_get_json(f"https://www.omdbapi.com/?i={urllib.parse.quote(imdb_id)}"
                          f"&apikey={CFG.OMDB_API_KEY}")
    if data and data.get("Response") == "True" and str(data.get("Type") or "") == "movie":
        return data
    return None


def rename_movie_from_omdb(src: Path, imdb_id: str, omdb_title: Optional[str],
                           omdb_year: Optional[str], fallback_name: str,
                           fallback_year: Optional[str], outcome: Dict[str, Any],
                           dest_dir: Optional[Path] = None) -> Optional[Path]:
    """
    Rename a film that OMDb identified, using this script's own name template.

    The film is already pinned to an id, so nothing here guesses. FileBot is not
    involved: it would need its own OMDb access, and the template is the same
    one the rest of the tool uses to name a film.
    """
    facts = _local_file_facts(src)
    if not facts:
        outcome["ok"], outcome["reason"] = False, "could not read the file's video"
        return None
    name = build_movie_output_name(omdb_title or fallback_name, omdb_year or fallback_year,
                                   imdb_id, facts["res"], facts["source"], facts["codec"],
                                   [], bracket=facts["bracket"])
    dest = (dest_dir or src.parent) / name
    result = _rename_file_to(src, dest, outcome)
    if result is not None and result != src:
        logging.info("OMDb rename: %s -> %s", src.name, result.name)
    return result


def rename_movie_when_identified(src_file: Path, movie_title: str, movie_name: str,
                                 year: Optional[str], imdb_id: Optional[str],
                                 outcome: Dict[str, Any],
                                 ident: Optional[MovieIdentity] = None) -> Optional[Path]:
    """
    Rename a film only once it is pinned to a single IMDB id.

    A title search cannot identify a film on its own — several releases share a
    name and a year — so when the id cannot be established the file is left
    alone and the reason recorded, rather than renamed to whichever film the
    database ranked first. That rename would also overwrite the tags, and a
    later run would then trust the wrong id.

    The one exception is a film that every database found nothing about. It has
    no wrong answer to be given, so it is named from its own file (LOCAL); see
    rename_movie_from_file. A film with SEVERAL possible matches never is.
    """
    ident = ident or movie_identity_chain(src_file, movie_name, year, imdb_id)
    if ident.imdb and ident.source == "OMDb":
        return rename_movie_from_omdb(src_file, ident.imdb, ident.title, ident.year,
                                      movie_name, year, outcome)
    if ident.imdb:
        renamed = run_filebot_rename_final_mkv(src_file, db=CFG.FILEBOT_DB,
                                               filebot_format=MOVIE_FILEBOT_FORMAT,
                                               dry_run=False, query=movie_title,
                                               imdb_id=ident.imdb, outcome=outcome)
        if outcome.get("ok") is False:
            # TMDB may simply not carry this id (a film chosen with --imdb or
            # --pick that only OMDb lists). The id is still certain, so OMDb can
            # supply the name.
            rec = _omdb_movie_by_id(ident.imdb)
            if rec:
                logging.info("FileBot could not serve %s — naming it from OMDb instead: %s",
                             ident.imdb, src_file.name)
                return rename_movie_from_omdb(src_file, ident.imdb, rec.get("Title"),
                                              str(rec.get("Year") or "")[:4] or None,
                                              movie_name, year, outcome)
        return renamed
    if ident.status == "none" and CFG.LOCAL_NAME_FALLBACK:
        return rename_movie_from_file(src_file, movie_name, year, ident.reason, outcome)
    outcome["ok"] = False
    outcome["reason"] = ident.reason
    return None


def process_movie_group(
    group: List[Path],
    movies_root: Path,
    dry_run: bool,
    overwrite: bool,
    include_forced_subs: bool,
    audio_lang_filter: Optional[List[str]] = None,
    skip_cleantags: bool = False,
    force_audio_langs: Optional[Dict[int, str]] = None,
    force_sub_langs: Optional[Dict[int, str]] = None,
    inplace: bool = False,
    backup: bool = False,
) -> Result:
    """
    Process a group of similar movie files.

    When multiple files are found:
    - Select the best x265/HEVC video track from any file
    - Collect ALL target-language audio tracks from ALL files (others excluded)
    - Keep target-language subtitles (regular + SDH)
    - Merge everything into a single optimized MKV file

    Sources are READ directly (mkvmerge never modifies its inputs). Output goes
    to OUTPUT_ROOT, or — with inplace=True — replaces the sources in their own
    folder after verification (backup=True keeps them as *.original.mkv).
    """
    kind = "movie_cleanup" if len(group) == 1 else "movie_merge"
    _rename_outcome: Dict[str, Any] = {}
    try:
        # Identify tracks (reading sources directly — identification is read-only)
        metas: Dict[Path, Tuple[List[Track], int]] = {}
        for src in group:
            # Use source size for tie-break
            fsize = src.stat().st_size if src.exists() else 0
            meta = mkvmerge_identify_json(src)

            tracks = extract_tracks(src, meta)
            # Apply forced language overrides before any detection runs
            apply_track_lang_overrides(tracks, force_audio_langs or {}, force_sub_langs or {})
            metas[src] = (tracks, fsize)

        # Determine movie name/year/imdb
        movie_name: str
        year: Optional[str]
        imdb_id: Optional[str]

        movie_name = ""
        year = None
        imdb_id = None

        # Prefer parsing from canonically-named files: 'Name (Year) - tt1234567'
        for wf in metas.keys():
            t, y, imdb = parse_title_year_imdb_from_filename(wf)
            if t and y:
                movie_name, year = t, y
                imdb_id = imdb_id or imdb
                break

        # Fallback: derive from original path(s)
        if not movie_name:
            movie_name, year = infer_movie_name_year_from_path(group[0])

        if not imdb_id:
            imdb_id = next((extract_imdb_id_from_movie_path(p) for p in group if extract_imdb_id_from_movie_path(p)), None)

        movie_title = f"{movie_name} ({year})" if year else movie_name

        # Work out what 'und' tracks actually are before any selection runs,
        # so releases stripped of track metadata are not written off as having
        # no target languages.
        if CFG.DETECT_UNDETERMINED_LANGS:
            for _src_file, (_tracks, _sz) in metas.items():
                _ra, _rs = resolve_undetermined_track_languages(
                    _src_file, _tracks, movie_name, year, False,
                    force_audio_langs or {}, force_sub_langs or {})
                if _ra or _rs:
                    force_audio_langs = {**(force_audio_langs or {}), **_ra}
                    force_sub_langs = {**(force_sub_langs or {}), **_rs}
                    apply_track_lang_overrides(_tracks, _ra, _rs)

        # Best video (prefer x265/HEVC)
        best_video_file, best_video = choose_best_video_across_files(metas)

        # Keep ALL audio tracks per target language across all files (Hindi/English/Telugu only)
        audios = collect_all_audio_by_language(metas)

        # Apply user-supplied language filter if provided
        if audio_lang_filter is not None:
            audios = {k: v for k, v in audios.items() if k in audio_lang_filter}
            logging.info("Audio language filter applied: keeping %s", audio_lang_filter)

        # Collect subtitle tracks: Hindi + Telugu + English only, regular + SDH both kept
        all_subs: Dict[Path, List[Track]] = collect_all_subtitles(metas)

        selected_audio_langs = [k for k in CFG.LANG_CANONICAL_ORDER if k in audios]

        res_tag = infer_resolution_tag_from_video(best_video, fallback_filename=group[0].name)
        codec_tag = codec_tag_video(best_video)
        if codec_tag in ("unknown", "video"):
            codec_tag = infer_codec_tag_from_filename(group[0].name) or codec_tag

        source_tag = infer_source_tag_from_filename(group[0].name)

        # Dry runs skip the whole finishing chain, so the remux target name says
        # nothing about the database rename that follows. Predict the real one.
        predicted_name: Optional[str] = None
        if dry_run:
            # Preview the identification too: a film the real run would refuse
            # to rename must not be previewed as though it had a name.
            _ident = movie_identity_chain(group[0], movie_name, year, imdb_id)
            if _ident.imdb and _ident.source == "OMDb":
                predicted_name = build_movie_output_name(
                    _ident.title or movie_name, _ident.year or year, _ident.imdb, res_tag,
                    source_tag, codec_tag, selected_audio_langs)
                logging.info("[DRY] Final name would be (identified via OMDb): %s", predicted_name)
            elif _ident.imdb:
                predicted_name = predict_movie_final_name(
                    best_video_file, movie_name, year, _ident.imdb, res_tag, source_tag,
                    codec_tag, selected_audio_langs, exact=_PREVIEW_EXACT)
                if predicted_name:
                    logging.info("[DRY] Final name would be: %s", predicted_name)
            elif _ident.status == "none" and CFG.LOCAL_NAME_FALLBACK:
                # Same rule as the real run: nothing found anywhere means a name
                # built from the file alone — but never when the title is only
                # ambiguous or no database could be asked.
                if not _local_title_usable(movie_name, year, need_year=True):
                    _why = "the filename gives no usable title and year"
                    logging.warning("[DRY] Would NOT rename %s — %s; %s", group[0].name,
                                    _ident.reason, _why)
                    _rename_outcome["ok"] = False
                    _rename_outcome["reason"] = f"{_ident.reason}; {_why}"
                else:
                    _bracket = (build_audio_bracket(selected_audio_langs) if selected_audio_langs
                                else _local_audio_bracket([t for tr, _s in metas.values() for t in tr]))
                    predicted_name = build_movie_output_name(
                        _tidy_title(movie_name), year, None, res_tag, source_tag, codec_tag,
                        [], bracket=_bracket)
                    _rename_outcome["local"] = True
                    _rename_outcome["local_name"] = predicted_name
                    logging.info("[DRY] No database knows %r — would name it from the file alone "
                                 "(LOCAL): %s", movie_title, predicted_name)
            else:
                logging.warning("[DRY] Would NOT rename %s — %s", group[0].name, _ident.reason)
                predicted_name = None
                _rename_outcome["ok"] = False
                _rename_outcome["reason"] = _ident.reason

        # ── SKIP-REMUX / RULE-7 CHECKS (single-file groups only) ─────────────
        if len(group) == 1:
            _all_tracks_single = metas[list(metas.keys())[0]][0]
            _actual_audio_count = sum(1 for t in _all_tracks_single if t.type == "audio" and not is_excluded_audio(t))
            _total_target_audio_count = sum(len(v) for v in audios.values())

            # Rule 7: no target languages found — keep all tracks, just rename/tag
            if _actual_audio_count > 0 and _total_target_audio_count == 0:
                logging.warning("movie: no target audio languages (%s) found in %s — skipping remux, renaming only.",
                                "/".join(CFG.LANG_DISPLAY_MAP.values()), group[0].name)
                src_file = group[0]
                out_done = src_file
                if not dry_run:
                    _single_tracks = metas[list(metas.keys())[0]][0]
                    fix_track_langs_inplace(src_file, _single_tracks, force_audio_langs or {}, force_sub_langs or {})
                    if not skip_cleantags and CFG.MKVPROPEDIT_EXE.exists():
                        ct = clean_mkv_tags(src_file, dry_run=False)
                        if not ct.ok:
                            logging.warning("Auto-cleantags failed (non-fatal): %s", ct.reason)
                    fb_path = rename_movie_when_identified(src_file, movie_title, movie_name, year,
                                                                 imdb_id, _rename_outcome)
                    if fb_path and fb_path.exists() and fb_path != src_file:
                        out_done = fb_path
                    if not skip_cleantags and CFG.MKVPROPEDIT_EXE.exists() and out_done.exists():
                        ct = clean_mkv_tags(out_done, dry_run=False)
                        if not ct.ok:
                            logging.warning("Auto-cleantags (post-FileBot) failed (non-fatal): %s", ct.reason)
                else:
                    logging.info("[DRY] Would rename/tag in-place (no target langs): %s", src_file.name)
                pipeline_embed_cover(out_done, is_tv=False, dry_run=dry_run)
                logging.info("movie_no_target_langs OK -> %s", out_done)
                return Result(kind="movie_no_target_langs", source_items=group, output_path=out_done, ok=True,
                              details=_with_rename_outcome({"reason": "no_target_languages_found", "predicted": predicted_name}, _rename_outcome))

            # Rules 1,2,5,6: all audio tracks are target languages — no remux needed
            if _actual_audio_count == _total_target_audio_count:
                src_file = group[0]
                logging.info("movie_skip_remux: %s has %d audio track(s) %s, all target langs — skipping remux.",
                             src_file.name, _actual_audio_count, selected_audio_langs)
                out_done = src_file
                if not dry_run:
                    _single_tracks = metas[list(metas.keys())[0]][0]
                    fix_track_langs_inplace(src_file, _single_tracks, force_audio_langs or {}, force_sub_langs or {})
                    if not skip_cleantags and CFG.MKVPROPEDIT_EXE.exists():
                        logging.info("Auto-cleantags (pre-FileBot, in-place) on: %s", src_file.name)
                        ct = clean_mkv_tags(src_file, dry_run=False)
                        if not ct.ok:
                            logging.warning("Auto-cleantags (pre-FileBot) failed (non-fatal): %s", ct.reason)
                    logging.info("FileBot identify+rename (in-place): %s", src_file.name)
                    fb_path = rename_movie_when_identified(src_file, movie_title, movie_name, year,
                                                                 imdb_id, _rename_outcome)
                    if fb_path and fb_path.exists() and fb_path != src_file:
                        logging.info("FileBot renamed -> %s", fb_path.name)
                        out_done = fb_path
                    if not skip_cleantags and CFG.MKVPROPEDIT_EXE.exists() and out_done.exists():
                        logging.info("Auto-cleantags (post-FileBot, in-place) on: %s", out_done.name)
                        ct = clean_mkv_tags(out_done, dry_run=False)
                        if not ct.ok:
                            logging.warning("Auto-cleantags (post-FileBot) failed (non-fatal): %s", ct.reason)
                else:
                    logging.info("[DRY] Would run FileBot + cleantags in-place on: %s", src_file.name)
                pipeline_embed_cover(out_done, is_tv=False, dry_run=dry_run)
                logging.info("movie_skip_remux OK -> %s", out_done)
                return Result(kind="movie_skip_remux", source_items=group, output_path=out_done, ok=True,
                              details=_with_rename_outcome({"audio_langs": selected_audio_langs, "reason": "already_has_required_tracks",
                                       "predicted": predicted_name}, _rename_outcome))

            # Rules 3,4: has target langs + extra languages — remux to strip extras
            logging.info("movie: file has %d audio tracks total, %d are target langs — remuxing to strip extras.",
                         _actual_audio_count, _total_target_audio_count)
        # ─────────────────────────────────────────────────────────────────────

        # SAFETY (multi-file groups): if the sources have audio but NONE of it was
        # detected as a target language, a merge would produce a video-only file.
        # Refuse instead — mislabeled 'und' tracks should be fixed with
        # --force-audio-lang first.
        if len(group) > 1:
            _any_audio = any(
                t.type == "audio" and not is_excluded_audio(t)
                for tracks_, _fs in metas.values() for t in tracks_
            )
            if _any_audio and not audios:
                return Result(
                    kind=kind, source_items=group, output_path=None, ok=False,
                    reason=("no target-language audio detected across group — merging would drop "
                            "ALL audio; fix language tags with --force-audio-lang and retry"))

        out_name = build_movie_output_name(movie_name, year, imdb_id, res_tag, source_tag, codec_tag, selected_audio_langs)

        # --inplace: the merged file lands in the sources' own folder (they are
        # co-located — grouping never crosses folders). Otherwise: OUTPUT_ROOT.
        if inplace:
            out_final = group[0].parent / out_name
            if out_final.exists() and out_final not in group and not overwrite:
                return Result(kind=kind, source_items=group, output_path=None, ok=False,
                              reason=f"in-place output name collides with an unrelated file: {out_final.name}")
        else:
            out_final = output_path_for_item(group[0], movies_root, out_name)

        out_done = out_final

        # Build mkvmerge parts: video + all audio tracks + all subtitle tracks
        parts: List[Tuple[Path, Dict[str, Any]]] = []

        # Video part (best video file only)
        v_opt = {
            "video_tracks": [best_video.id],
            "audio_tracks": None,
            "sub_tracks": None,
            "track_names": {best_video.id: sanitize_filename(movie_title)},
        }
        parts.append((best_video_file, v_opt))

        # Audio — output order: Hindi → English → Telugu (LANG_CANONICAL_ORDER)
        # All tracks per language kept (e.g. stereo + 5.1 both included)
        for canon in CFG.LANG_CANONICAL_ORDER:
            if canon not in audios:
                continue
            lang_full_name = CFG.LANG_DISPLAY_MAP.get(canon, canon)
            for (afile, atrack) in audios[canon]:
                a_opt = {
                    "video_tracks": None,
                    "audio_tracks": [atrack.id],
                    "sub_tracks": None,
                    "track_names": {atrack.id: lang_full_name},
                    "languages": {atrack.id: canon},
                }
                parts.append((afile, a_opt))
                logging.info("Adding audio track: %s from %s (track %d, codec=%s, channels=%s)",
                             lang_full_name, afile.name, atrack.id, atrack.codec_id, atrack.channels)

        # Add ALL subtitle tracks grouped by source file (tags cleaned later by mkvpropedit)
        total_subs = sum(len(v) for v in all_subs.values())
        logging.info("Subtitle tracks to include: %d", total_subs)
        for sfile, stracks in all_subs.items():
            s_opt = {
                "video_tracks": None,
                "audio_tracks": None,
                "sub_tracks": [t.id for t in stracks],
                "track_names": {},
                "languages": {t.id: t.language for t in stracks
                              if (t.language or "und").lower() != "und"},
            }
            parts.append((sfile, s_opt))
            for st in stracks:
                logging.info("  Sub track %d: lang=%s codec=%s forced=%s name=%r",
                             st.id, st.language, st.codec_id, st.forced, st.name)

        out_tmp = out_final.with_suffix(".mkv.tmp")
        if out_tmp.exists() and not dry_run:
            try:
                out_tmp.unlink()
            except Exception:
                pass

        r = mkvmerge_build_and_run(out_tmp, parts, dry_run=dry_run, segment_title=movie_title)
        if not r.ok:
            return Result(kind=kind, source_items=group, output_path=None, ok=False,
                          reason=f"mkvmerge failed rc={r.rc}", details={"stderr": r.err, "cmd": r.cmd})

        if dry_run and inplace:
            for s in group:
                logging.info("[DRY] Would %s source: %s", "back up as *.original.mkv" if backup else "DELETE", s.name)

        if not dry_run:
            if inplace:
                total_audio = sum(len(v) for v in audios.values())
                ok_v, why = verify_remux_output(out_tmp, ref_file=best_video_file,
                                                expected_audio=total_audio, expected_subs=total_subs)
                if not ok_v:
                    out_tmp.unlink(missing_ok=True)
                    return Result(kind=kind, source_items=group, output_path=None, ok=False,
                                  reason=f"in-place verification FAILED ({why}) — sources untouched")
                finalize_inplace(sources=group, out_tmp=out_tmp, out_final=out_final, backup=backup)
            else:
                atomic_move(out_tmp, out_final, overwrite=overwrite)

        out_done = out_final

        # Log selection details
        logging.info("%s OK -> %s", kind, out_done)
        logging.info("Selected video: %s | track=%d codec_id=%s %sx%s",
                     best_video_file.name, best_video.id, best_video.codec_id, best_video.width, best_video.height)

        # Log selected audio tracks
        total_audio_tracks = sum(len(v) for v in audios.values())
        logging.info("Audio tracks included: %d across %d language(s)", total_audio_tracks, len(selected_audio_langs))
        for canon in selected_audio_langs:
            for (afile, atrack) in audios[canon]:
                logging.info("  Audio %s: %s | track=%d codec_id=%s channels=%s",
                             canon, afile.name, atrack.id, atrack.codec_id, atrack.channels)

        if not dry_run:
            # Step 1: cleantags — strip junk tags and write a clean segment title.
            # This gives FileBot the best possible signal for DB lookup in step 2.
            if not skip_cleantags and CFG.MKVPROPEDIT_EXE.exists() and out_done.exists():
                logging.info("Auto-cleantags (pre-FileBot) on: %s", out_done.name)
                ct = clean_mkv_tags(out_done, dry_run=False)
                if not ct.ok:
                    logging.warning("Auto-cleantags (pre-FileBot) failed (non-fatal): %s", ct.reason)

            # Step 2: FileBot rename — identify movie via DB and apply canonical filename.
            logging.info("FileBot identify+rename: %s", out_done.name)
            fb_path = rename_movie_when_identified(out_done, movie_title, movie_name,
                                                   year, imdb_id, _rename_outcome)
            if fb_path and fb_path.exists() and fb_path != out_done:
                logging.info("FileBot renamed -> %s", fb_path.name)
                out_done = fb_path

            # Step 3: cleantags again on the final (possibly renamed) file so the segment
            # title matches the canonical FileBot-assigned filename.
            if not skip_cleantags and CFG.MKVPROPEDIT_EXE.exists() and out_done.exists():
                logging.info("Auto-cleantags (post-FileBot) on: %s", out_done.name)
                ct = clean_mkv_tags(out_done, dry_run=False)
                if not ct.ok:
                    logging.warning("Auto-cleantags (post-FileBot) failed (non-fatal): %s", ct.reason)

        # Step 4: cover art (final step — uses the canonical filename for lookup)
        pipeline_embed_cover(out_done, is_tv=False, dry_run=dry_run)

        return Result(kind=kind, source_items=group, output_path=out_done, ok=True,
                      details=_with_rename_outcome({"cmd": r.cmd, "audio_langs": selected_audio_langs,
                                                    "predicted": predicted_name}, _rename_outcome))

    except FileExistsError as e:
        return Result(kind=kind, source_items=group, output_path=None, ok=False, reason=str(e))
    except Exception as e:
        logging.exception("Movie group failed: %s", [p.name for p in group])
        return Result(kind=kind, source_items=group, output_path=None, ok=False, reason=str(e))


# =========================
# TV processing (unchanged from original)
# =========================

def infer_tv_components(p: Path) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
    """
    Infer TV components from path:
      returns (show_with_year, season_str, ep_str, episode_title)

    Tries hard to keep Plex/Jellyfin-friendly values:
      Show (Year) - SxxEyy - Title
    """
    stem = strip_site_prefix(p.stem).replace('.', ' ').replace('_', ' ')
    # Drop website/release-group junk in non-year parentheses, e.g.
    # '(SiteName Foo) Show Name S01 E02 ...' — keep '(YYYY)' groups.
    stem = re.sub(r"\((?!\s*(?:19|20)\d{2}\s*\))[^)]*\)", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()

    # Season/Episode
    m = _SEASON_EP_RE.search(stem)
    season_str = ep_str = None
    if m:
        season_str = f"S{int(m.group(1)):02d}"
        ep_str = f"E{int(m.group(2)):02d}"

    # Episode title heuristics: common pattern "Show - S01E01 - Title"
    episode_title: Optional[str] = None
    m2 = re.search(r"\s-\sS\d{1,2}E\d{1,2}\s-\s(.+)$", stem, flags=re.I)
    if m2:
        episode_title = m2.group(1).strip()
        # Strip trailing technical tags and language brackets
        episode_title = _MOVIE_NOISE_TOKENS.sub(" ", episode_title)
        episode_title = re.sub(r"\[[^\]]+\]", " ", episode_title)
        # Normalize spaces FIRST so multi-space gaps from removed tokens become single spaces.
        # Then strip any trailing junk: dashes, dots, spaces left behind after token removal
        # (e.g., "Title - . -" from "Title - 1080p.x264 - [langs]" -> "Title")
        episode_title = re.sub(r"\s+", " ", episode_title).strip()
        episode_title = re.sub(r"[\s.\-–—]+$", "", episode_title).strip()

    # Show (Year) from parent folder when available (best signal)
    parent = p.parent.name
    parent_clean = parent.replace('.', ' ').replace('_', ' ')
    parent_clean = re.sub(r"\s+", " ", parent_clean).strip()
    show_with_year = None
    pm = re.search(r"^(.+?\(\d{4}\))", parent_clean)
    if pm:
        show_with_year = pm.group(1).strip()
    else:
        # fallback: everything left of the SxxEyy marker (any separator style)
        m3 = re.search(r"^(.+?)[\s.\-_]+S\d{1,2}\s*[.\-_ ]?\s*E\d{1,2}\b", stem, flags=re.I)
        if m3:
            show_with_year = _MOVIE_NOISE_TOKENS.sub(" ", m3.group(1))
            show_with_year = re.sub(r"\s+", " ", show_with_year).strip()
            show_with_year = re.sub(r"[\s.\-–—]+$", "", show_with_year).strip()
        else:
            # fallback: remove SxxExx then clean
            tmp = stem
            if m:
                tmp = tmp[:m.start()] + tmp[m.end():]
            tmp = _MOVIE_NOISE_TOKENS.sub(" ", tmp)
            # Noisy no-marker names: also drop language/sub markers
            tmp = re.sub(r"(?i)\b(telugu|telegu|tamil|hindi|english|malayalam|kannada|multi|dual\s*audio|esubs?|msubs?)\b", " ", tmp)
            tmp = re.sub(r"\s+", " ", tmp).strip()
            show_with_year = tmp or parent_clean or "UnknownShow"

    show_with_year = sanitize_filename(show_with_year)

    if episode_title:
        episode_title = sanitize_filename(episode_title)

    return show_with_year, season_str, ep_str, episode_title



def build_tv_output_name(
    show_with_year: str,
    season_str: Optional[str],
    ep_str: Optional[str],
    episode_title: Optional[str],
    res_tag: str,
    codec_tag: str,
    audio_langs: List[str],
    bracket: Optional[str] = None,
) -> str:
    """
    Plex/Jellyfin-friendly TV naming (fallback when FileBot is unavailable):

      Show (Year) - SxxEyy - Episode Title - 1080p.x265 - [Telugu + Hindi].mkv
    """
    base = sanitize_filename(show_with_year) or "UnknownShow"

    se = ""
    if season_str and ep_str:
        se = f"{season_str}{ep_str}"
    elif season_str:
        se = season_str

    title = sanitize_filename(episode_title) if episode_title else None

    bracket = bracket or build_audio_bracket(audio_langs)

    parts = [base]
    if se:
        parts.append(se)
    if title:
        parts.append(title)

    prefix = " - ".join(parts)
    fn = f"{prefix} - {res_tag}.{codec_tag} - [{bracket}].mkv"
    # Collapse any consecutive " - " sequences that slipped through (e.g., "Title - - 1080p")
    fn = re.sub(r"(\s+-\s+){2,}", " - ", fn)
    return sanitize_filename(fn)



def process_tv_file(
    src: Path,
    tv_root: Path,
    dry_run: bool,
    overwrite: bool,
    include_forced_subs: bool,
    audio_lang_filter: Optional[List[str]] = None,
    skip_cleantags: bool = False,
    force_audio_langs: Optional[Dict[int, str]] = None,
    force_sub_langs: Optional[Dict[int, str]] = None,
    inplace: bool = False,
    backup: bool = False,
) -> Result:
    """
    Process a single TV episode file.

    The source is READ directly (mkvmerge never modifies its inputs). Output
    goes to OUTPUT_ROOT, or — with inplace=True — replaces the source in its
    own folder after verification (backup=True keeps it as *.original.mkv).
    """
    kind = "tv_cleanup"
    _rename_outcome: Dict[str, Any] = {}
    try:
        fsize = src.stat().st_size if src.exists() else 0
        meta = mkvmerge_identify_json(src)

        tracks = extract_tracks(src, meta)
        # Apply forced language overrides before any detection runs
        apply_track_lang_overrides(tracks, force_audio_langs or {}, force_sub_langs or {})
        metas = {src: (tracks, fsize)}

        show_name, season_str, ep_str, ep_title = infer_tv_components(src)

        # Same as the movie path: identify 'und' tracks before selection.
        if CFG.DETECT_UNDETERMINED_LANGS:
            _bare_show, _show_year = split_show_year(show_name or "")
            _ra, _rs = resolve_undetermined_track_languages(
                src, tracks, _bare_show or show_name, _show_year, True,
                force_audio_langs or {}, force_sub_langs or {})
            if _ra or _rs:
                force_audio_langs = {**(force_audio_langs or {}), **_ra}
                force_sub_langs = {**(force_sub_langs or {}), **_rs}
                apply_track_lang_overrides(tracks, _ra, _rs)

        best_video_file, best_v = choose_best_video_across_files(metas)
        # Keep ALL audio tracks per target language (supports duplicate tracks, e.g. stereo + 5.1)
        audios = collect_all_audio_by_language(metas)

        # Apply user-supplied language filter if provided
        if audio_lang_filter is not None:
            audios = {k: v for k, v in audios.items() if k in audio_lang_filter}
            logging.info("Audio language filter applied: keeping %s", audio_lang_filter)

        # Collect subtitle tracks: Hindi + Telugu + English only, regular + SDH both kept
        all_subs: Dict[Path, List[Track]] = collect_all_subtitles(metas)

        selected_audio_langs = [k for k in CFG.LANG_CANONICAL_ORDER if k in audios]
        res_tag = infer_resolution_tag_from_video(best_v, fallback_filename=str(src))
        codec_tag = codec_tag_video(best_v)
        if codec_tag in ("unknown", "video"):
            codec_tag = infer_codec_tag_from_filename(str(src)) or codec_tag

        # Dry runs skip the finishing chain, so predict the post-rename name.
        predicted_name: Optional[str] = None
        if dry_run:
            predicted_name = predict_tv_final_name(
                src, show_name, season_str, ep_str, ep_title, res_tag, codec_tag,
                selected_audio_langs, exact=_PREVIEW_EXACT)
            if predicted_name:
                logging.info("[DRY] Final name would be: %s", predicted_name)
            # Preview the identification too: a series the real run would refuse to
            # rename must not be previewed as though it had a name.
            _dry_bare, _dry_year = split_show_year(show_name or "")
            if _dry_bare and CFG.TMDB_API_KEY:
                _dry_id, _dry_why = tv_identity_for_rename(src.name, _dry_bare, _dry_year)
                if _dry_why:
                    logging.warning("[DRY] Would NOT rename %s — %s", src.name, _dry_why)
                    predicted_name = None
                    _rename_outcome["ok"] = False
                    _rename_outcome["reason"] = _dry_why
                elif not _dry_id and not predicted_name and CFG.LOCAL_NAME_FALLBACK:
                    # TMDB does not know the show. A real run asks FileBot's TheTVDB
                    # and TVmaze next — a dry run cannot (without --preview-exact),
                    # so say what happens if both also find nothing.
                    _local, _problem = tv_local_name(src)
                    logging.info("[DRY] TMDB has no match for %r — a real run tries TheTVDB, then "
                                 "TVmaze; if neither knows it: %s", _dry_bare,
                                 f"named from the file alone (LOCAL): {_local}" if _local
                                 else f"left as it is ({_problem})")

        # ── SKIP-REMUX / RULE-7 CHECKS ───────────────────────────────────────
        _actual_audio_count = sum(1 for t in tracks if t.type == "audio" and not is_excluded_audio(t))
        _total_target_audio_count = sum(len(v) for v in audios.values())

        # Rule 7: file has no target languages at all — keep as-is, just rename/tag
        if _actual_audio_count > 0 and _total_target_audio_count == 0:
            logging.warning("tv: no target audio languages (%s) found in %s — skipping remux, renaming only.",
                            "/".join(CFG.LANG_DISPLAY_MAP.values()), src.name)
            out_done = src
            if not dry_run:
                fix_track_langs_inplace(src, tracks, force_audio_langs or {}, force_sub_langs or {})
                if not skip_cleantags and CFG.MKVPROPEDIT_EXE.exists():
                    ct = clean_mkv_tags(src, dry_run=False, is_tv=True)
                    if not ct.ok:
                        logging.warning("Auto-cleantags failed (non-fatal): %s", ct.reason)
                fb_path = run_filebot_rename_final_mkv(src, db="TheTVDB", filebot_format=TV_FILEBOT_FORMAT,
                                                       dry_run=False, query=show_name,
                                                       outcome=_rename_outcome)
                if fb_path and fb_path.exists() and fb_path != src:
                    out_done = fb_path
                if not skip_cleantags and CFG.MKVPROPEDIT_EXE.exists() and out_done.exists():
                    ct = clean_mkv_tags(out_done, dry_run=False, is_tv=True)
                    if not ct.ok:
                        logging.warning("Auto-cleantags (post-FileBot) failed (non-fatal): %s", ct.reason)
            else:
                logging.info("[DRY] Would rename/tag in-place (no target langs): %s", src.name)
            pipeline_embed_cover(out_done, is_tv=True, dry_run=dry_run)
            logging.info("tv_no_target_langs OK -> %s", out_done)
            return Result(kind="tv_no_target_langs", source_items=[src], output_path=out_done, ok=True,
                          details=_with_rename_outcome({"reason": "no_target_languages_found", "predicted": predicted_name}, _rename_outcome))

        # Rules 1,2,5,6: all audio tracks in the file are already target languages — no remux needed
        _no_extra_tracks = _actual_audio_count == _total_target_audio_count
        if _no_extra_tracks:
            logging.info("tv_skip_remux: %s has %d audio track(s) %s, all target langs — skipping remux.",
                         src.name, _actual_audio_count, selected_audio_langs)
            out_done = src

            if not dry_run:
                fix_track_langs_inplace(src, tracks, force_audio_langs or {}, force_sub_langs or {})
                if not skip_cleantags and CFG.MKVPROPEDIT_EXE.exists():
                    logging.info("Auto-cleantags (pre-FileBot, in-place) on: %s", src.name)
                    ct = clean_mkv_tags(src, dry_run=False, is_tv=True)
                    if not ct.ok:
                        logging.warning("Auto-cleantags (pre-FileBot) failed (non-fatal): %s", ct.reason)
                logging.info("FileBot identify+rename (in-place): %s", src.name)
                fb_path = run_filebot_rename_final_mkv(src, db="TheTVDB", filebot_format=TV_FILEBOT_FORMAT, dry_run=False,
                                                       query=show_name, outcome=_rename_outcome)
                if fb_path and fb_path.exists() and fb_path != src:
                    logging.info("FileBot renamed -> %s", fb_path.name)
                    out_done = fb_path
                if not skip_cleantags and CFG.MKVPROPEDIT_EXE.exists() and out_done.exists():
                    logging.info("Auto-cleantags (post-FileBot, in-place) on: %s", out_done.name)
                    ct = clean_mkv_tags(out_done, dry_run=False, is_tv=True)
                    if not ct.ok:
                        logging.warning("Auto-cleantags (post-FileBot) failed (non-fatal): %s", ct.reason)
            else:
                logging.info("[DRY] Would run FileBot + cleantags in-place on: %s", src.name)

            pipeline_embed_cover(out_done, is_tv=True, dry_run=dry_run)
            logging.info("tv_skip_remux OK -> %s", out_done)
            return Result(kind="tv_skip_remux", source_items=[src], output_path=out_done, ok=True,
                          details=_with_rename_outcome({"audio_langs": selected_audio_langs, "reason": "already_has_required_tracks",
                                   "predicted": predicted_name}, _rename_outcome))

        # Rules 3,4: has target langs + extra languages — remux to strip extras
        logging.info("tv: file has %d audio tracks total, %d are target langs — remuxing to strip extras.",
                     _actual_audio_count, _total_target_audio_count)
        # ─────────────────────────────────────────────────────────────────────

        out_name = build_tv_output_name(show_name, season_str, ep_str, ep_title, res_tag, codec_tag, selected_audio_langs)

        # --inplace: output replaces the episode in its own folder; else OUTPUT_ROOT.
        if inplace:
            out_final = src.parent / out_name
            if out_final.exists() and out_final != src and not overwrite:
                return Result(kind=kind, source_items=[src], output_path=None, ok=False,
                              reason=f"in-place output name collides with an unrelated file: {out_final.name}")
        else:
            out_final = output_path_for_item(src, tv_root, out_name)

        parts: List[Tuple[Path, Dict[str, Any]]] = []

        # Video
        parts.append((src, {
            "video_tracks": [best_v.id],
            "audio_tracks": None,
            "sub_tracks": None,
            "track_names": {best_v.id: f"{show_name} - {season_str}{ep_str}" if season_str and ep_str else show_name},
        }))

        # Audio — output order follows the configured [languages] targets order.
        # All tracks per language are kept (e.g. stereo + 5.1 both included)
        for canon in CFG.LANG_CANONICAL_ORDER:
            if canon not in audios:
                continue
            title = CFG.LANG_DISPLAY_MAP.get(canon, canon)
            for (afile, t) in audios[canon]:
                parts.append((afile, {
                    "video_tracks": None,
                    "audio_tracks": [t.id],
                    "sub_tracks": None,
                    "track_names": {t.id: title},
                    "languages": {t.id: canon},
                }))

        # All subtitle tracks grouped by source file (tags cleaned later by mkvpropedit)
        total_subs = sum(len(v) for v in all_subs.values())
        logging.info("Subtitle tracks to include: %d", total_subs)
        for sfile, stracks in all_subs.items():
            parts.append((sfile, {
                "video_tracks": None,
                "audio_tracks": None,
                "sub_tracks": [t.id for t in stracks],
                "track_names": {},
                "languages": {t.id: t.language for t in stracks
                              if (t.language or "und").lower() != "und"},
            }))
            for st in stracks:
                logging.info("  Sub track %d: lang=%s codec=%s forced=%s name=%r",
                             st.id, st.language, st.codec_id, st.forced, st.name)

        out_tmp = out_final.with_suffix(".mkv.tmp")
        if out_tmp.exists() and not dry_run:
            try:
                out_tmp.unlink()
            except Exception:
                pass

        r = mkvmerge_build_and_run(out_tmp, parts, dry_run=dry_run)
        if not r.ok:
            return Result(kind=kind, source_items=[src], output_path=None, ok=False,
                          reason=f"mkvmerge failed rc={r.rc}", details={"stderr": r.err, "cmd": r.cmd})

        if dry_run and inplace:
            logging.info("[DRY] Would %s source: %s", "back up as *.original.mkv" if backup else "DELETE", src.name)

        if not dry_run:
            if inplace:
                total_audio = sum(len(v) for v in audios.values())
                ok_v, why = verify_remux_output(out_tmp, ref_file=src,
                                                expected_audio=total_audio, expected_subs=total_subs)
                if not ok_v:
                    out_tmp.unlink(missing_ok=True)
                    return Result(kind=kind, source_items=[src], output_path=None, ok=False,
                                  reason=f"in-place verification FAILED ({why}) — source untouched")
                finalize_inplace(sources=[src], out_tmp=out_tmp, out_final=out_final, backup=backup)
            else:
                atomic_move(out_tmp, out_final, overwrite=overwrite)

        out_done = out_final

        logging.info("%s OK -> %s", kind, out_done)
        logging.info("Selected video: track=%d codec_id=%s %sx%s", best_v.id, best_v.codec_id, best_v.width, best_v.height)
        for canon, track_list in audios.items():
            for (_f, t) in track_list:
                logging.info("Selected audio %s: track=%d codec_id=%s channels=%s", canon, t.id, t.codec_id, t.channels)

        if not dry_run:
            # Step 1: cleantags — strip junk tags and write clean segment title so
            # FileBot can identify the episode from clean metadata in step 2.
            if not skip_cleantags and CFG.MKVPROPEDIT_EXE.exists() and out_done.exists():
                logging.info("Auto-cleantags (pre-FileBot) on: %s", out_done.name)
                ct = clean_mkv_tags(out_done, dry_run=False, is_tv=True)
                if not ct.ok:
                    logging.warning("Auto-cleantags (pre-FileBot) failed (non-fatal): %s", ct.reason)

            # Step 2: FileBot rename — identify episode via TheTVDB and rename.
            logging.info("FileBot identify+rename: %s", out_done.name)
            fb_path = run_filebot_rename_final_mkv(
                out_done,
                db="TheTVDB",
                filebot_format=TV_FILEBOT_FORMAT,
                dry_run=dry_run,
                query=show_name,
                outcome=_rename_outcome,
            )
            if fb_path and fb_path.exists() and fb_path != out_done:
                logging.info("FileBot renamed -> %s", fb_path.name)
                out_done = fb_path

            # Step 3: cleantags again on final path so segment title reflects the
            # canonical FileBot-assigned episode name.
            if not skip_cleantags and CFG.MKVPROPEDIT_EXE.exists() and out_done.exists():
                logging.info("Auto-cleantags (post-FileBot) on: %s", out_done.name)
                ct = clean_mkv_tags(out_done, dry_run=False, is_tv=True)
                if not ct.ok:
                    logging.warning("Auto-cleantags (post-FileBot) failed (non-fatal): %s", ct.reason)

        # Step 4: cover art (final step — uses the canonical filename for lookup)
        pipeline_embed_cover(out_done, is_tv=True, dry_run=dry_run)

        return Result(kind=kind, source_items=[src], output_path=out_done, ok=True,
                      details=_with_rename_outcome({"cmd": r.cmd, "audio_langs": selected_audio_langs,
                                                    "predicted": predicted_name}, _rename_outcome))

    except FileExistsError as e:
        return Result(kind=kind, source_items=[src], output_path=None, ok=False, reason=str(e))
    except Exception as e:
        logging.exception("TV file failed: %s", src)
        return Result(kind=kind, source_items=[src], output_path=None, ok=False, reason=str(e))


# =========================
# Movies pipeline (per folder)
# =========================

def group_movies_by_folder(movies: List[Path]) -> Dict[Path, List[Path]]:
    folders: Dict[Path, List[Path]] = {}
    for p in movies:
        folders.setdefault(p.parent, []).append(p)
    return folders


# =========================
# Self-check
# =========================

def self_check() -> int:
    logging.info("Self-check: validating tools and folder access...")

    try:
        validate_tools()
    except Exception as e:
        logging.error("Self-check failed: tools: %s", e)
        return 2

    for d in (CFG.MOVIES_ROOT, CFG.TV_ROOT, CFG.OUTPUT_ROOT):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logging.error("Self-check failed: cannot access/create: %s | %s", d, e)
            return 3

    # Validate any configured API keys (same checks as --validate-keys)
    if CFG.TMDB_API_KEY or CFG.FANARTTV_API_KEY or CFG.OMDB_API_KEY:
        key_status = validate_api_keys()
        for source, st in key_status.items():
            logging.info("Self-check API key %-10s: %s", source, st.upper() if st == "invalid" else st)
        if any(st == "invalid" for st in key_status.values()):
            logging.error("Self-check failed: invalid API key(s) in [coverart] of %s", CONFIG_FILE)
            return 6

    # Attempt mkvmerge -J on a sample if any MKV exists
    sample = None
    for root in (CFG.MOVIES_ROOT, CFG.TV_ROOT):
        mkvs = scan_mkvs(root)
        if mkvs:
            sample = mkvs[0]
            break

    if not sample:
        logging.warning("Self-check: no MKV files found under Movies/TV roots; skipping JSON parse test.")
        return 0

    try:
        meta = mkvmerge_identify_json(sample)
        if "tracks" not in meta:
            logging.error("Self-check failed: mkvmerge JSON missing 'tracks'.")
            return 4
        logging.info("Self-check OK: mkvmerge JSON parsed: %s tracks=%d", sample.name, len(meta.get("tracks", [])))
        return 0
    except Exception as e:
        logging.error("Self-check failed: mkvmerge -J parse: %s", e)
        return 5


# =========================
# Version and update check
# =========================
# Looks at the latest PUBLISHED GitHub release — never a branch — so what it
# reports is what was actually released. It only reads: nothing is downloaded or
# installed here, and a check that fails (offline, rate-limited, private repo) is
# never an error for the tool. A repository that is private needs a read-only
# token in the MEDIACLEANUP_GITHUB_TOKEN environment variable.

UPDATE_CACHE_JSON = _SCRIPT_DIR / "logs" / "update_check.json"
_UPDATE_MAX_AGE_S = 24 * 3600        # a successful check is reused for a day
_UPDATE_RETRY_S = 3600               # a failed one is not retried for an hour
_UPDATE_TIMEOUT_S = 5
_UPDATE_THREAD: Optional[threading.Thread] = None
_UPDATE_NOTICES: bool = False        # set by main() once the notice is wanted


def parse_version(text: Optional[str]) -> Optional[Tuple[int, int, int]]:
    """'v1.11.0' or '1.11.0' -> (1, 11, 0); None when it is not a release version."""
    m = re.match(r"^\s*v?(\d+)\.(\d+)\.(\d+)", text or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


class _AuthStrippingRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect, but never carry the token to a different host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and (urllib.parse.urlparse(newurl).netloc
                                != urllib.parse.urlparse(req.full_url).netloc):
            new.headers.pop("Authorization", None)
            new.unredirected_hdrs.pop("Authorization", None)
        return new


_GITHUB_OPENER = urllib.request.build_opener(_AuthStrippingRedirects())


def _github_get(path: str, accept: str = "application/vnd.github+json",
                timeout: float = _UPDATE_TIMEOUT_S,
                max_bytes: int = 5_000_000) -> Tuple[Optional[int], bytes]:
    """GET from the GitHub API: (status, body), with status None when it could not be reached."""
    headers = {"User-Agent": f"MediaCleanup/{__version__}", "Accept": accept,
               "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("MEDIACLEANUP_GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"      # sent to api.github.com only
    url = f"https://api.github.com{path}"
    try:
        with _GITHUB_OPENER.open(urllib.request.Request(url, headers=headers),
                                 timeout=timeout) as resp:
            body = resp.read(max_bytes + 1)
            if len(body) > max_bytes:
                return 413, b""                           # larger than this call may return
            return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:
        logging.debug("GitHub request failed: %s | %s", url, e)
        return None, b""


def fetch_latest_release(timeout: float = _UPDATE_TIMEOUT_S) -> Tuple[Optional[Dict[str, Any]], str]:
    """The latest published release as {version, tag, url, published}, or (None, why not)."""
    status, body = _github_get(f"/repos/{GITHUB_REPO}/releases/latest", timeout=timeout)
    if status is None:
        return None, "GitHub could not be reached (offline, or blocked)"
    if status == 404:
        return None, ("GitHub shows no release here - the repository may be private (set "
                      "MEDIACLEANUP_GITHUB_TOKEN to a read-only token) or none is published yet")
    if status in (401, 403):
        return None, ("GitHub refused the request (rate limit, or the token is invalid) - "
                      "try again later")
    if status != 200:
        return None, f"GitHub answered HTTP {status}"
    try:
        data = json.loads(body.decode("utf-8", errors="replace"))
    except ValueError:
        return None, "GitHub's answer could not be read"
    ver = parse_version(str(data.get("tag_name") or ""))
    if not ver:
        return None, "the latest release has no version tag such as v1.2.3"
    return {"version": ".".join(str(n) for n in ver), "tag": str(data["tag_name"]),
            "url": str(data.get("html_url") or ""),
            "published": str(data.get("published_at") or "")[:10]}, ""


def _read_update_cache() -> Dict[str, Any]:
    try:
        data = json.loads(UPDATE_CACHE_JSON.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _record_update_attempt(info: Optional[Dict[str, Any]]) -> None:
    """Remember that a check was made, and what it found. Never raises."""
    cache = _read_update_cache()
    now = time.time()
    cache["attempted_at"] = now
    if info:
        cache.update(info)
        cache["checked_at"] = now
    try:
        UPDATE_CACHE_JSON.parent.mkdir(parents=True, exist_ok=True)
        tmp = UPDATE_CACHE_JSON.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        os.replace(tmp, UPDATE_CACHE_JSON)
    except OSError as e:
        logging.debug("Could not write %s: %s", UPDATE_CACHE_JSON.name, e)


def _update_refresh_due(now: Optional[float] = None) -> bool:
    """True when the cached answer is more than a day old and no attempt was made lately."""
    now = time.time() if now is None else now
    cache = _read_update_cache()

    def age(key: str) -> float:
        try:
            return now - float(cache.get(key, 0))
        except (TypeError, ValueError):
            return float("inf")

    return age("checked_at") >= _UPDATE_MAX_AGE_S and age("attempted_at") >= _UPDATE_RETRY_S


def update_notice_text() -> Optional[str]:
    """One line when the cached latest release is newer than this one."""
    cache = _read_update_cache()
    latest, current = parse_version(str(cache.get("version") or "")), parse_version(__version__)
    if latest and current and latest > current:
        return (f"MediaCleanup {cache['version']} is available (you have {__version__}) - "
                f"run: python MediaCleanup.py --check-update")
    return None


def start_background_update_check() -> None:
    """Refresh the cached answer without ever making the run wait for it."""
    global _UPDATE_THREAD
    if not _update_refresh_due():
        return

    def work() -> None:
        info, problem = fetch_latest_release(_UPDATE_TIMEOUT_S)
        if not info:
            logging.debug("Update check failed: %s", problem)
        _record_update_attempt(info)

    _UPDATE_THREAD = threading.Thread(target=work, name="update-check", daemon=True)
    _UPDATE_THREAD.start()


def finish_update_check() -> None:
    """At the end of a run: give a check that is still in flight a moment, then print any notice."""
    t = _UPDATE_THREAD
    if t is not None and t.is_alive():
        t.join(1.5)
    text = update_notice_text()
    if text:
        logging.info(text)


def parse_changelog_sections(text: str) -> List[Tuple[Tuple[int, int, int], str, str]]:
    """CHANGELOG.md -> [(version, heading, body)], newest first as written."""
    heads = list(re.finditer(r"(?m)^## \[(\d+\.\d+\.\d+)\][^\n]*$", text or ""))
    out: List[Tuple[Tuple[int, int, int], str, str]] = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        out.append((parse_version(m.group(1)) or (0, 0, 0), m.group(0)[3:].strip(),
                    text[m.end():end].strip()))
    return out


def changelog_between(current: str, tag: str) -> List[Tuple[str, str]]:
    """The changelog entries after `current`, up to and including release `tag`."""
    status, body = _github_get(
        f"/repos/{GITHUB_REPO}/contents/CHANGELOG.md?ref={urllib.parse.quote(tag)}",
        accept="application/vnd.github.raw+json", timeout=10)
    if status != 200:
        return []
    cur, new = parse_version(current), parse_version(tag)
    if not cur or not new:
        return []
    return [(head, b) for v, head, b in parse_changelog_sections(body.decode("utf-8", errors="replace"))
            if cur < v <= new]


_ASCII_PUNCT = str.maketrans({"—": "-", "–": "-", "‘": "'", "’": "'",
                              "“": '"', "”": '"', "…": "...", " ": " "})


def _console_safe(text: str) -> str:
    """Typographic punctuation printed to a Windows console becomes '?' — use plain ASCII."""
    return text.translate(_ASCII_PUNCT)


def _changelog_highlights(body: str, limit: int = 12) -> List[str]:
    """The section headings and top-level bullets of one entry, shortened to fit a terminal."""
    lines: List[str] = []
    for raw in body.splitlines():
        if raw.startswith("### ") or raw.startswith("- "):
            line = _console_safe(raw.replace("**", ""))
            lines.append(line if len(line) <= 140 else line[:137].rstrip() + "...")
    more = len(lines) - limit
    lines = lines[:limit]
    if more > 0:
        lines.append(f"... and {more} more - see CHANGELOG.md")
    return lines


def _first_line(text: str) -> str:
    return next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")


def _probe_tool(exe: Optional[Path], args: List[str], timeout: int = 30) -> str:
    """First line of a tool's version output, or why there is none."""
    if exe is None:
        return "not configured"
    if not exe.exists():
        return f"not found ({exe})"
    r = run_cmd([str(exe)] + args, timeout_sec=timeout)
    line = _first_line(r.out) or _first_line(r.err)
    return f"{line}   [{exe}]" if line else f"installed, version could not be read   [{exe}]"


def _find_optional_tool(name: str, root: Optional[Path] = None) -> Optional[Path]:
    """ffmpeg / x265: the project's own runtimes folder first, then the PATH."""
    for rel in (f"runtimes/{name}/bin/{name}.exe", f"runtimes/{name}/{name}.exe"):
        p = (root or _SCRIPT_DIR) / rel
        if p.exists():
            return p
    found = shutil.which(name)
    return Path(found) if found else None


def _package_version(name: str) -> str:
    try:
        from importlib import metadata
        return metadata.version(name)
    except Exception:
        return "not installed (optional)"


def print_version() -> int:
    """--version: this tool's version and what it is running on. Needs no valid config."""
    cfg: Optional[Config] = None
    config_problem = ""
    try:
        cfg = load_config()
    except Exception as e:
        config_problem = str(e)

    rows: List[Tuple[str, str]] = [
        ("Python", f"{platform.python_version()}   [{sys.executable}]"),
        ("Platform", platform.platform()),
    ]
    if cfg is not None:
        rows.append(("mkvmerge", _probe_tool(cfg.MKVMERGE_EXE, ["--version"])))
        rows.append(("mkvpropedit", _probe_tool(cfg.MKVPROPEDIT_EXE, ["--version"])))
        fb = cfg.FILEBOT_EXE
        rows.append(("FileBot", _probe_tool(fb, ["-version"], timeout=60) if fb.exists()
                     else "not installed (optional)"))
    else:
        for name in ("mkvmerge", "mkvpropedit", "FileBot"):
            rows.append((name, f"unknown - configuration not loaded ({config_problem})"))
    for name, flag in (("ffmpeg", "-version"), ("x265", "--version")):
        exe = _find_optional_tool(name)
        rows.append((name, _probe_tool(exe, [flag]) if exe else "not installed (optional, not used yet)"))
    rows.append(("rich", _package_version("rich")))
    rows.append(("Pillow", _package_version("pillow")))

    print(f"MediaCleanup {__version__}")
    width = max(len(k) for k, _ in rows)
    for k, v in rows:
        print(f"  {k:<{width}}  {v}")
    return 0


def run_check_update() -> int:
    """--check-update: compare with the latest release. Exit 0 current, 10 newer available, 1 unknown."""
    print(f"MediaCleanup {__version__} - checking {GITHUB_REPO} for a newer release...")
    info, problem = fetch_latest_release(timeout=10)
    _record_update_attempt(info)
    if not info:
        print(f"Could not check for updates: {problem}.")
        return 1
    latest, current = parse_version(info["version"]), parse_version(__version__)
    if current and latest and current >= latest:
        print(f"You have the latest release ({__version__}).")
        return 0
    when = f", published {info['published']}" if info.get("published") else ""
    print(f"A newer release is available: {info['version']}{when}")
    if info.get("url"):
        print(f"  {info['url']}")
    notes = changelog_between(__version__, info["tag"])
    if notes:
        print("\nWhat changed since your version:")
        for heading, body in notes:
            print(f"\n  {_console_safe(heading)}")
            for line in _changelog_highlights(body):
                print(f"    {line}")
    return 10


# =========================
# Updating the tool itself (--update)
# =========================
# A release is installed only after every file in it has been checked against the
# git blob hash GitHub lists for that tag, fetched over HTTPS — so what lands on
# disk is exactly what was published, for every release, with no separate
# checksum file to maintain. Only files the release itself contains are ever
# written: MediaCleanup.toml, logs\, backup\ and the runtimes are never touched.
# Everything replaced is copied to backup\ first, and a failure part-way puts it
# all back. A git clone is updated with git instead.

_UPDATE_PROTECTED_TOP = frozenset({"logs", "backup", ".git"})
_UPDATE_PROTECTED_FILES = frozenset({"MediaCleanup.toml"})
_UPDATE_MAX_ZIP_BYTES = 100_000_000
# path -> (git blob sha1, mode)
ReleaseTree = Dict[str, Tuple[str, str]]


def _safe_release_path(path: str) -> bool:
    """A path from a release that is safe to join onto the install folder."""
    if not path or path.startswith(("/", "\\")) or ":" in path or "\\" in path:
        return False
    return all(part not in ("", ".", "..") for part in path.split("/"))


def _is_protected_path(path: str) -> bool:
    return path in _UPDATE_PROTECTED_FILES or path.split("/", 1)[0] in _UPDATE_PROTECTED_TOP


def git_blob_sha1(data: bytes) -> str:
    """The id git gives a file's content — what GitHub's file list publishes."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _local_blob_shas(path: Path) -> Set[str]:
    """Hashes a local copy could legitimately have: as-is, and with Windows line endings undone."""
    try:
        data = path.read_bytes()
    except OSError:
        return set()
    return {git_blob_sha1(data), git_blob_sha1(data.replace(b"\r\n", b"\n"))}


def fetch_release_tree(tag: str) -> Tuple[Optional[ReleaseTree], str]:
    """Every file in a release with its published hash, or (None, why not)."""
    status, body = _github_get(
        f"/repos/{GITHUB_REPO}/git/trees/{urllib.parse.quote(tag)}?recursive=1", timeout=20)
    if status is None:
        return None, "GitHub could not be reached (offline, or blocked)"
    if status == 404:
        return None, f"GitHub has no release file list for {tag} (or the repository is private - see MEDIACLEANUP_GITHUB_TOKEN)"
    if status != 200:
        return None, f"GitHub answered HTTP {status} for the file list of {tag}"
    try:
        data = json.loads(body.decode("utf-8", errors="replace"))
    except ValueError:
        return None, "GitHub's file list could not be read"
    if data.get("truncated"):
        return None, f"the file list of {tag} is too large to verify"
    tree: ReleaseTree = {}
    for entry in data.get("tree") or []:
        mode = str(entry.get("mode") or "")
        if entry.get("type") != "blob" or mode not in ("100644", "100755"):
            continue                       # directories, symlinks and submodules are not installed
        p = str(entry.get("path") or "")
        if not _safe_release_path(p) or _is_protected_path(p):
            return None, f"{tag} lists a path this tool will not write: {p!r}"
        tree[p] = (str(entry.get("sha") or ""), mode)
    if not tree:
        return None, f"{tag} lists no files"
    return tree, ""


@dataclasses.dataclass
class UpdatePlan:
    add: List[str] = dataclasses.field(default_factory=list)
    replace: List[str] = dataclasses.field(default_factory=list)
    remove: List[str] = dataclasses.field(default_factory=list)
    unchanged: List[str] = dataclasses.field(default_factory=list)
    edited: List[str] = dataclasses.field(default_factory=list)     # changed locally since the old release

    @property
    def writes(self) -> List[str]:
        return self.add + self.replace

    @property
    def changes(self) -> bool:
        return bool(self.add or self.replace or self.remove)


def build_update_plan(root: Path, old: ReleaseTree, new: ReleaseTree) -> UpdatePlan:
    """What moving the install folder from the `old` release to `new` would do."""
    plan = UpdatePlan()
    for path, (sha, _mode) in sorted(new.items()):
        local = root / path
        have = _local_blob_shas(local) if local.is_file() else set()
        if sha in have:
            plan.unchanged.append(path)
            continue
        if not have:
            plan.add.append(path)
            continue
        plan.replace.append(path)
        # An edit is a local copy that matches neither release (nothing to compare
        # with at all when the installed version has no tag).
        if path not in old or old[path][0] not in have:
            plan.edited.append(path)
    for path in sorted(set(old) - set(new)):
        local = root / path
        if local.is_file():
            plan.remove.append(path)
            if old[path][0] not in _local_blob_shas(local):
                plan.edited.append(path)
    return plan


def download_release_zip(tag: str) -> Tuple[Optional[bytes], str]:
    status, body = _github_get(f"/repos/{GITHUB_REPO}/zipball/{urllib.parse.quote(tag)}",
                               accept="application/vnd.github+json", timeout=120,
                               max_bytes=_UPDATE_MAX_ZIP_BYTES)
    if status == 200 and body:
        return body, ""
    if status is None:
        return None, "the download could not be made (offline, or blocked)"
    return None, f"GitHub answered HTTP {status} for the download of {tag}"


def extract_verified(zip_bytes: bytes, tree: ReleaseTree, paths: List[str],
                     staging: Path) -> Optional[str]:
    """
    Unpack `paths` into `staging`, checking each against its published hash.
    Returns None when every file verified, or a description of the first problem.
    """
    import io
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        return "the download is not a valid zip file"
    names = {n for n in zf.namelist() if not n.endswith("/")}
    top = {n.split("/", 1)[0] for n in names}
    if len(top) != 1:
        return "the download has an unexpected layout"
    prefix = next(iter(top)) + "/"
    for path in paths:
        member = prefix + path
        if member not in names:
            return f"the download is missing {path}"
        data = zf.read(member)
        if git_blob_sha1(data) != tree[path][0]:
            return f"{path} does not match the file GitHub published for this release"
        target = staging / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return None


def apply_update(root: Path, plan: UpdatePlan, staging: Path, backup_dir: Path) -> None:
    """
    Put the staged files in place, backing up whatever they replace. If anything
    fails, everything already done is undone and the error is re-raised.
    """
    done: List[Tuple[str, bool]] = []          # (path, existed before)
    try:
        for path in plan.writes:
            target = root / path
            existed = target.is_file()
            if existed:
                dest = backup_dir / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, dest)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".updating")
            try:
                shutil.copyfile(staging / path, tmp)
                os.replace(tmp, target)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
            done.append((path, existed))
        for path in plan.remove:
            target = root / path
            dest = backup_dir / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, dest)
            target.unlink()
            done.append((path, True))
    except BaseException:
        for path, existed in reversed(done):
            target = root / path
            try:
                if existed:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(backup_dir / path, target)
                else:
                    target.unlink(missing_ok=True)
            except OSError as e:
                logging.error("Could not restore %s (a copy is in %s): %s", path, backup_dir, e)
        raise


def _flatten_toml(data: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for section, body in data.items():
        if isinstance(body, dict):
            for key, value in body.items():
                out[f"{section}.{key}"] = value
        else:
            out[section] = body
    return out


def new_config_settings(root: Path) -> List[str]:
    """Settings the example config now has that the user's own MediaCleanup.toml lacks."""
    try:
        example = _flatten_toml(tomllib.loads((root / "MediaCleanup.example.toml").read_text(encoding="utf-8")))
        mine = _flatten_toml(tomllib.loads((root / "MediaCleanup.toml").read_text(encoding="utf-8")))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    return [f"{k} = {json.dumps(v)}" for k, v in example.items() if k not in mine]


def _confirm(question: str, assume_yes: bool) -> bool:
    """Ask before changing anything. Without a terminal, only --yes can answer."""
    if assume_yes:
        return True
    if not sys.stdin or not sys.stdin.isatty():
        print(f"{question} - not asking without a terminal; re-run with --yes to proceed.")
        return False
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _print_plan(plan: UpdatePlan, backup_dir: Path) -> None:
    def show(label: str, items: List[str]) -> None:
        if items:
            print(f"  {label} ({len(items)}):")
            for p in items[:12]:
                print(f"    {p}")
            if len(items) > 12:
                print(f"    ... and {len(items) - 12} more")

    show("New files", plan.add)
    show("Replaced", plan.replace)
    show("Removed (no longer part of the release)", plan.remove)
    if plan.unchanged:
        print(f"  Already identical: {len(plan.unchanged)} file(s)")
    if plan.edited:
        print(f"\n  !! You have edited {len(plan.edited)} of these files since your release:")
        for p in plan.edited[:12]:
            print(f"     {p}")
        print("     Your versions are kept in the backup folder, but the release's replace them.")
    if plan.writes or plan.remove:
        print(f"\n  Everything replaced is copied to {backup_dir} first.")
    print("  MediaCleanup.toml, logs\\ and runtimes\\ are never touched.")


def _git(root: Path, *args: str, timeout: int = 120) -> CmdResult:
    return run_cmd(["git", "-C", str(root), *args], timeout_sec=timeout)


def _is_git_clone(root: Path) -> bool:
    return (root / ".git").exists() and shutil.which("git") is not None


def _update_via_git(root: Path, tag: str, dry_run: bool, assume_yes: bool) -> int:
    """Update a git clone with git: fetch the tags, then fast-forward (or check out) the release."""
    print(f"This folder is a git clone, so it is updated with git (to {tag}).")
    dirty = _git(root, "status", "--porcelain", "--untracked-files=no")
    if dirty.out.strip():
        print("You have uncommitted changes to tracked files - commit or stash them first:")
        for line in dirty.out.strip().splitlines()[:10]:
            print(f"    {line}")
        return 1
    fetched = _git(root, "fetch", "--tags", "--quiet", "origin")
    if not fetched.ok:
        print(f"git fetch failed: {_first_line(fetched.err) or fetched.rc}")
        return 1
    if not _git(root, "rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}").ok:
        print(f"git does not know the tag {tag} after fetching.")
        return 1
    branch = _first_line(_git(root, "symbolic-ref", "-q", "--short", "HEAD").out)
    head = _first_line(_git(root, "rev-parse", "HEAD").out)
    target = _first_line(_git(root, "rev-parse", f"{tag}^{{commit}}").out)
    if head and head == target:
        print(f"This checkout is already at {tag}.")
        return 0
    # A tag your checkout already contains is OLDER: merging it would do nothing and
    # report success, so moving there has to be an explicit checkout.
    older = _git(root, "merge-base", "--is-ancestor", tag, "HEAD").ok
    ahead = _first_line(_git(root, "rev-list", "--count", f"HEAD..{tag}").out) or "?"
    if older:
        how = f"check out {tag} (older than your checkout; this leaves {branch or 'HEAD'} behind)"
    elif branch:
        how = f"fast-forward {branch} to {tag} ({ahead} new commit(s))"
    else:
        how = f"check out {tag} ({ahead} new commit(s))"
    print(f"  Would {how}.")
    if dry_run:
        print("Dry run: nothing changed.")
        return 0
    if not _confirm(f"Proceed and {how.split(' (')[0]}?", assume_yes):
        return 5
    r = _git(root, "merge", "--ff-only", tag) if (branch and not older) else _git(root, "checkout", tag)
    if not r.ok:
        print(f"git could not do that: {_first_line(r.err) or _first_line(r.out)}")
        if branch and not older:
            print("  (your local history has diverged from the release - "
                  f"use git yourself, e.g. git checkout {tag})")
        return 1
    print(f"Updated to {tag}.")
    return 0


def install_release_files(root: Path, tag: str, tree: ReleaseTree, plan: UpdatePlan,
                          backup_dir: Path) -> str:
    """
    Download release `tag`, verify every file the plan writes against its published
    hash, and put them in place (backing up what they replace). Returns "" on
    success, or what went wrong — in which case nothing has been changed.
    """
    print(f"\nDownloading {tag}...")
    data, problem = download_release_zip(tag)
    if data is None:
        return problem
    with tempfile.TemporaryDirectory(prefix="mediacleanup-update-") as tmp:
        staging = Path(tmp)
        bad = extract_verified(data, tree, plan.writes, staging)
        if bad:
            return bad
        print(f"Verified {len(plan.writes)} file(s) against GitHub's published hashes.")
        try:
            apply_update(root, plan, staging, backup_dir)
        except Exception as e:
            return f"{e} (rolled back)"
    return ""


def run_update(root: Path = _SCRIPT_DIR, dry_run: bool = False, assume_yes: bool = False,
               to_tag: Optional[str] = None) -> int:
    """
    --update / --update-to TAG. Exit codes: 0 updated or already current,
    1 failed (nothing changed), 5 declined.
    """
    print(f"MediaCleanup {__version__} - looking for a release to install...")
    if to_tag:
        want = parse_version(to_tag)
        if not want:
            print(f"{to_tag!r} is not a release version such as v1.12.0.")
            return 1
        info: Dict[str, Any] = {"version": ".".join(map(str, want)),
                                "tag": "v" + ".".join(map(str, want))}
    else:
        found, problem = fetch_latest_release(timeout=10)
        _record_update_attempt(found)
        if not found:
            print(f"Could not look for updates: {problem}.")
            return 1
        info = found
    cur, new = parse_version(__version__), parse_version(info["version"])
    if cur == new:
        print(f"You already have {__version__}.")
        return 0
    if cur and new and new < cur:
        if not to_tag:
            print(f"The latest release ({info['version']}) is older than yours ({__version__}); nothing to do.")
            return 0
        print(f"Note: {info['tag']} is OLDER than {__version__} - installing it because you asked for it.")
    tag = info["tag"]
    print(f"Release {tag}" + (f", published {info['published']}" if info.get("published") else ""))

    notes = changelog_between(__version__, tag) if (cur and new and new > cur) else []
    for heading, body in notes:
        print(f"\n  {_console_safe(heading)}")
        for line in _changelog_highlights(body, limit=8):
            print(f"    {line}")
    print()

    if _is_git_clone(root):
        return _update_via_git(root, tag, dry_run, assume_yes)

    new_tree, why = fetch_release_tree(tag)
    if new_tree is None:
        print(f"Cannot verify {tag}: {why}.")
        return 1
    old_tree, why_old = fetch_release_tree("v" + __version__)
    if old_tree is None:
        print(f"Note: the installed version's file list is unavailable ({why_old}); every file that "
              "differs from the release will be treated as edited and backed up.")
        old_tree = {}
    plan = build_update_plan(root, old_tree, new_tree)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = _unique_path(root / "backup" / f"update-{__version__}-to-{info['version']}-{stamp}")
    _print_plan(plan, backup_dir)
    if not plan.changes:
        print(f"\nEvery file already matches {tag}.")
        return 0
    if dry_run:
        print("\nDry run: nothing changed.")
        return 0
    if not _confirm(f"\nInstall {tag}?", assume_yes):
        return 5

    problem = install_release_files(root, tag, new_tree, plan, backup_dir)
    if problem:
        print(f"Update failed, nothing was changed: {problem}.")
        return 1

    try:
        hist = root / "logs" / "update_history.csv"
        hist.parent.mkdir(parents=True, exist_ok=True)
        fresh = not hist.exists()
        with open(hist, "a", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            if fresh:
                w.writerow(["when", "from", "to", "files_written", "files_removed", "backup"])
            w.writerow([_dt.datetime.now().isoformat(timespec="seconds"), __version__, info["version"],
                        len(plan.writes), len(plan.remove), str(backup_dir)])
    except OSError:
        pass
    print(f"\nUpdated {__version__} -> {info['version']}: {len(plan.writes)} file(s) written, "
          f"{len(plan.remove)} removed. Previous versions are in {backup_dir}.")
    fresh_settings = new_config_settings(root)
    if fresh_settings:
        print("\nNew settings in MediaCleanup.example.toml that your MediaCleanup.toml does not have "
              "(the defaults apply until you add them):")
        for line in fresh_settings:
            print(f"    {line}")
    print("\nRun: python MediaCleanup.py --version")
    return 0


# =========================
# Runtimes: --update-runtimes, --install, --repair
# =========================
# The tools this one runs on, each handled the way it deserves:
#   MKVToolNix   updated automatically (official portable build, checksum verified)
#   ffmpeg       opt-in; once installed it is kept updated like MKVToolNix. It carries
#                libx265, so x265 comes with it
#   rich/Pillow  updated with pip when installed
#   x265, FileBot, Python   reported only — x265 binaries are third-party, FileBot is
#                licensed software and Python cannot replace the interpreter running it
# Only files from the hosts listed below are ever downloaded, each is checked
# against a SHA-256 published beside it, and the folder being replaced is kept in
# runtimes\_previous\ and put back if the new one does not run.

_RUNTIME_HOSTS = frozenset({"mkvtoolnix.download", "www.gyan.dev", "pypi.org"})
_PIP_PACKAGES = {"rich": "rich", "pillow": "Pillow"}        # the only packages pip is ever asked for
_MKV_LATEST_URL = "https://mkvtoolnix.download/latest-release.json"
_FFMPEG_BUILDS = "https://www.gyan.dev/ffmpeg/builds/"
_INSTALLABLE = ("mkvtoolnix", "ffmpeg", "rich", "pillow")


def _runtime_url_ok(url: str) -> bool:
    p = urllib.parse.urlparse(url)
    return p.scheme == "https" and (p.hostname or "") in _RUNTIME_HOSTS


def _fetch_text(url: str, timeout: float = 20, max_bytes: int = 5_000_000) -> Optional[str]:
    """A small text/JSON document from a trusted host, or None."""
    if not _runtime_url_ok(url):
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": f"MediaCleanup/{__version__}"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if not _runtime_url_ok(resp.geturl()):
                return None                      # redirected somewhere that is not listed
            data = resp.read(max_bytes + 1)
        return data.decode("utf-8", errors="replace") if len(data) <= max_bytes else None
    except Exception as e:
        logging.debug("Fetch failed: %s | %s", url, e)
        return None


def _download_file(url: str, dest: Path, max_bytes: int, timeout: float = 120) -> Tuple[Optional[str], str]:
    """Stream a file from a trusted host to disk. Returns (sha256 hex, "") or (None, problem)."""
    if not _runtime_url_ok(url):
        return None, f"{url} is not on a download host this tool trusts"
    digest, got, mark = hashlib.sha256(), 0, 25
    try:
        req = urllib.request.Request(url, headers={"User-Agent": f"MediaCleanup/{__version__}"})
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as fh:
            if not _runtime_url_ok(resp.geturl()):
                return None, "the download was redirected to a host this tool does not trust"
            total = int(resp.headers.get("Content-Length") or 0)
            if total > max_bytes:
                return None, "the download is larger than expected"
            while True:
                chunk = resp.read(262144)
                if not chunk:
                    break
                got += len(chunk)
                if got > max_bytes:
                    return None, "the download is larger than expected"
                digest.update(chunk)
                fh.write(chunk)
                while total and got * 100 // total >= mark and mark < 100:
                    print(f"    {mark}% of {total // 1_000_000} MB", flush=True)
                    mark += 25
    except Exception as e:
        return None, f"the download failed: {e}"
    return digest.hexdigest(), ""


def _parse_sha256(text: str, filename: Optional[str] = None) -> Optional[str]:
    """A SHA-256 from a '<hash>  <file>' listing, or a file holding only the hash."""
    for line in (text or "").splitlines():
        m = re.match(r"^\s*([0-9a-fA-F]{64})(?:\s+\*?(.+?))?\s*$", line)
        if m and (not filename or not m.group(2) or Path(m.group(2)).name == filename):
            return m.group(1).lower()
    return None


def _numeric_version(text: Optional[str]) -> Tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", text or "")[:4])


_TAR_CHECKED: Dict[str, bool] = {}
_NO_7Z = ("this archive is a .7z and nothing here can unpack it - install 7-Zip "
          "(winget install 7zip.7zip) or use Windows 10 1803 or newer, which has tar.exe")


def find_7z_extractor() -> Optional[Tuple[str, str]]:
    """('7z', path) or ('bsdtar', path) — either can unpack a .7z — else None."""
    for name in ("7z", "7za"):
        found = shutil.which(name)
        if found:
            return "7z", found
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
        p = Path(base) / "7-Zip" / "7z.exe"
        if p.exists():
            return "7z", str(p)
    tar = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
    if tar.exists():
        if str(tar) not in _TAR_CHECKED:
            _TAR_CHECKED[str(tar)] = "bsdtar" in (run_cmd([str(tar), "--version"], 15).out or "").lower()
        if _TAR_CHECKED[str(tar)]:
            return "bsdtar", str(tar)
    return None


def extract_archive(archive: Path, dest: Path) -> str:
    """Unpack a .zip or .7z into dest. Returns "" on success or what went wrong."""
    dest.mkdir(parents=True, exist_ok=True)
    if archive.suffix.lower() == ".zip":
        root = dest.resolve()
        try:
            with zipfile.ZipFile(archive) as zf:
                for info in zf.infolist():
                    target = (dest / info.filename).resolve()
                    if root != target and root not in target.parents:
                        return f"the archive tries to write outside its folder ({info.filename})"
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as src, open(target, "wb") as out:
                            shutil.copyfileobj(src, out)
        except (zipfile.BadZipFile, OSError) as e:
            return f"the archive could not be unpacked: {e}"
        return ""
    ext = find_7z_extractor()
    if ext is None:
        return _NO_7Z
    kind, path = ext
    cmd = ([path, "x", "-y", f"-o{dest}", str(archive)] if kind == "7z"
           else [path, "-xf", str(archive), "-C", str(dest)])
    r = run_cmd(cmd, timeout_sec=900)
    if not r.ok:
        return f"the archive could not be unpacked: {_first_line(r.err) or _first_line(r.out)}"
    # A link inside an archive could point outside the folder it was unpacked into, so none are accepted.
    for dirpath, dirnames, filenames in os.walk(dest):
        for name in dirnames + filenames:
            q = Path(dirpath) / name
            if q.is_symlink() or (hasattr(q, "is_junction") and q.is_junction()):
                return f"the archive contains a link ({q.name}), which is not accepted"
    return ""


def _find_dir_with(base: Path, marker: str, max_depth: int = 3) -> Optional[Path]:
    """The shallowest folder under base that contains `marker` (a relative file path)."""
    level = [base]
    for _ in range(max_depth + 1):
        for d in level:
            if (d / marker).is_file():
                return d
        level = [c for d in level if d.is_dir() for c in sorted(d.iterdir()) if c.is_dir()]
    return None


def _unique_path(path: Path) -> Path:
    """`path`, or `path-2`, `path-3`... when it is taken — two runs in the same second must not share a folder."""
    candidate, n = path, 1
    while candidate.exists():
        n += 1
        candidate = path.with_name(f"{path.name}-{n}")
    return candidate


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except (ValueError, OSError):
        return False


# --- what is installed, and what is newest -----------------------------------------

def mkvtoolnix_installed(exe: Path) -> Optional[str]:
    m = re.search(r"mkvmerge v([\d.]+)", _probe_tool(exe, ["--version"], timeout=30)) if exe.exists() else None
    return m.group(1) if m else None


def mkvtoolnix_latest() -> Optional[str]:
    text = _fetch_text(_MKV_LATEST_URL)
    try:
        v = str(json.loads(text or "")["mkvtoolnix-releases"]["latest-source"]["version"])
    except (ValueError, KeyError, TypeError):
        return None
    return v if re.fullmatch(r"\d+(\.\d+)+", v) else None


def mkvtoolnix_package(version: str, use_7z: bool) -> Tuple[str, str, str]:
    """(archive url, checksum url, file name) of the 64-bit portable build."""
    name = f"mkvtoolnix-64-bit-{version}.{'7z' if use_7z else 'zip'}"
    base = f"https://mkvtoolnix.download/windows/releases/{version}/"
    return base + name, base + name + ".sha256", name


def parse_ffmpeg_version(line: str) -> Dict[str, Any]:
    """'ffmpeg version 2026-01-12-git-21a3e44fbe-full_build-www.gyan.dev ...' -> channel, version, variant."""
    m = re.search(r"ffmpeg version (\S+)", line or "")
    token = m.group(1) if m else ""
    out: Dict[str, Any] = {"channel": None, "version": None, "variant": None, "gyan": "gyan.dev" in token}
    g = re.match(r"(\d{4}-\d{2}-\d{2}-git-[0-9a-f]+)", token)
    r = re.match(r"(\d+(?:\.\d+)+)", token)
    if g:
        out["channel"], out["version"] = "git", g.group(1)
    elif r:
        out["channel"], out["version"] = "release", r.group(1)
    out["variant"] = "full" if "full_build" in token else ("essentials" if "essentials_build" in token else None)
    return out


def ffmpeg_latest(channel: str) -> Optional[str]:
    text = (_fetch_text(_FFMPEG_BUILDS + ("git-version" if channel == "git" else "release-version")) or "").strip()
    ok = re.fullmatch(r"\d{4}-\d{2}-\d{2}-git-[0-9a-f]+", text) if channel == "git" else re.fullmatch(r"\d+(\.\d+)+", text)
    return text if ok else None


def ffmpeg_package(channel: str, variant: str) -> Tuple[str, str, str]:
    ext = "zip" if (channel == "release" and variant == "essentials") else "7z"
    name = f"ffmpeg-{channel}-{variant}.{ext}"
    return _FFMPEG_BUILDS + name, _FFMPEG_BUILDS + name + ".sha256", name


def ffmpeg_is_newer(info: Dict[str, Any], latest: str) -> bool:
    if info.get("channel") == "git":
        return latest[:10] > str(info.get("version") or "")[:10]       # ISO dates sort as text
    return _numeric_version(latest) > _numeric_version(info.get("version"))


def pypi_latest(package: str) -> Optional[str]:
    try:
        return str(json.loads(_fetch_text(f"https://pypi.org/pypi/{package}/json", max_bytes=8_000_000) or "")["info"]["version"])
    except (ValueError, KeyError, TypeError):
        return None


def _package_installed(name: str) -> Optional[str]:
    try:
        from importlib import metadata
        return metadata.version(name)
    except Exception:
        return None


@dataclasses.dataclass
class RuntimeStatus:
    key: str
    label: str
    installed: Optional[str] = None
    latest: Optional[str] = None
    action: str = "none"                 # 'update' when this tool can and should be updated
    note: str = ""
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)


def gather_runtime_status(root: Path, cfg: Optional[Config]) -> List[RuntimeStatus]:
    """Look at every tool this one runs on. Network lookups that fail leave 'latest' unknown."""
    runtimes = root / "runtimes"
    out: List[RuntimeStatus] = []

    # MKVToolNix
    exe = cfg.MKVMERGE_EXE if cfg else runtimes / "mkvtoolnix" / "mkvmerge.exe"
    st = RuntimeStatus("mkvtoolnix", "MKVToolNix", latest=mkvtoolnix_latest())
    st.extra["target"] = exe.parent
    managed = _inside(exe, runtimes)
    if not exe.exists():
        st.note = "not found" + (" - run: --repair" if managed else f" ({exe})")
    else:
        st.installed = mkvtoolnix_installed(exe)
        if st.latest is None:
            st.note = "could not check for a newer version"
        elif st.installed and _numeric_version(st.latest) > _numeric_version(st.installed):
            if managed:
                st.action, st.note = "update", "newer version available"
            else:
                st.note = "newer version available - installed outside runtimes\\, so update it with its own installer"
        else:
            st.note = "up to date"
    out.append(st)

    # ffmpeg (optional)
    fexe = _find_optional_tool("ffmpeg", root)
    st = RuntimeStatus("ffmpeg", "ffmpeg")
    if fexe is None:
        st.note = "not installed (optional) - add it with: --install ffmpeg"
    else:
        line = _first_line(run_cmd([str(fexe), "-version"], 30).out)
        info = parse_ffmpeg_version(line)
        st.installed = info["version"] or "version unknown"
        st.extra.update(info=info, target=runtimes / "ffmpeg")
        enc = run_cmd([str(fexe), "-hide_banner", "-encoders"], 30).out or ""
        x265 = " (includes libx265)" if "libx265" in enc else " (no libx265)"
        if not info["gyan"] or info["channel"] is None or not _inside(fexe, runtimes / "ffmpeg"):
            st.note = "not a gyan.dev build in runtimes\\ffmpeg, so it is not updated automatically" + x265
        else:
            st.latest = ffmpeg_latest(info["channel"])
            if st.latest is None:
                st.note = "could not check for a newer version" + x265
            elif ffmpeg_is_newer(info, st.latest):
                st.action, st.note = "update", f"newer {info['channel']} build available" + x265
            else:
                st.note = "up to date" + x265
    out.append(st)

    # x265 (standalone) - reported only
    xexe = _find_optional_tool("x265", root)
    st = RuntimeStatus("x265", "x265")
    if xexe is None:
        st.note = "not installed (optional); the ffmpeg build above carries libx265"
    else:
        r = run_cmd([str(xexe), "--version"], 30)
        m = re.search(r"version ([\w.+-]+)", (r.err or "") + (r.out or ""))
        st.installed = m.group(1) if m else "version unknown"
        st.note = "standalone builds are third-party, so it is not updated automatically"
    out.append(st)

    # FileBot - licensed, reported only
    fb = cfg.FILEBOT_EXE if cfg else runtimes / "FileBot" / "filebot.exe"
    st = RuntimeStatus("filebot", "FileBot")
    if fb.exists():
        m = re.search(r"FileBot ([\d.]+)", _first_line(run_cmd([str(fb), "-version"], 90).out))
        st.installed = m.group(1) if m else "version unknown"
        st.note = "licensed software - check https://www.filebot.net/ for a newer version"
    else:
        st.note = "not installed (optional) - https://www.filebot.net/"
    out.append(st)

    # Python - reported only
    st = RuntimeStatus("python", "Python", installed=platform.python_version())
    minor = sys.version_info.minor
    st.note = ("below the minimum, 3.11 - " if sys.version_info < (3, 11) else "") + \
              f"not updated by this tool; use: winget upgrade Python.Python.3.{minor}"
    out.append(st)

    # pip packages
    for key, pkg in _PIP_PACKAGES.items():
        st = RuntimeStatus(key, pkg, installed=_package_installed(pkg))
        if st.installed is None:
            st.note = f"not installed (optional) - add it with: --install {key}"
        else:
            st.latest = pypi_latest(pkg)
            if st.latest is None:
                st.note = "could not check for a newer version"
            elif _numeric_version(st.latest) > _numeric_version(st.installed):
                st.action, st.note = "update", "newer version available (pip)"
            else:
                st.note = "up to date"
        out.append(st)
    return out


def _print_runtime_table(statuses: List[RuntimeStatus]) -> None:
    rows = [("Component", "Installed", "Latest", "Status")] + [
        (s.label, s.installed or "-", s.latest or "-",
         ("UPDATE: " if s.action == "update" else "") + s.note) for s in statuses]
    widths = [max(len(r[i]) for r in rows) for i in range(3)]
    for i, r in enumerate(rows):
        print("  " + "  ".join(r[j].ljust(widths[j]) for j in range(3)) + "  " + r[3])
        if i == 0:
            print("  " + "  ".join("-" * widths[j] for j in range(3)) + "  " + "-" * 6)


# --- installing ---------------------------------------------------------------------

def install_archive_runtime(root: Path, key: str, target: Path, package: Tuple[str, str, str],
                            marker: str, sanity: List[Tuple[str, List[str]]],
                            max_bytes: int = 300_000_000) -> str:
    """
    Download, verify and unpack a portable tool, then swap it into `target`. The
    folder it replaces is kept in runtimes\\_previous\\ and put back if the new one
    does not run. Returns "" on success or what went wrong.
    """
    url, sha_url, filename = package
    runtimes = root / "runtimes"
    staging = runtimes / f"_staging-{key}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        expected = _parse_sha256(_fetch_text(sha_url) or "", filename)
        if not expected:
            return f"the published checksum could not be read ({sha_url})"
        archive = staging / filename
        print(f"  Downloading {filename}...", flush=True)
        got, problem = _download_file(url, archive, max_bytes)
        if got is None:
            return problem
        if got != expected:
            return f"{filename} does not match the SHA-256 published beside it - discarded"
        print("  Checksum verified.", flush=True)
        problem = extract_archive(archive, staging / "x")
        if problem:
            return problem
        archive.unlink(missing_ok=True)
        content = _find_dir_with(staging / "x", marker)
        if content is None:
            return f"the archive does not contain {marker}"
        previous: Optional[Path] = None
        if target.exists():
            keep = runtimes / "_previous"
            keep.mkdir(parents=True, exist_ok=True)
            previous = _unique_path(keep / f"{key}-{_dt.datetime.now().strftime('%Y%m%d-%H%M%S')}")
            try:
                shutil.move(str(target), str(previous))
            except OSError as e:
                return f"could not move the current {key} aside ({e}) - is it running?"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(content), str(target))
            for rel, args in sanity:
                if not run_cmd([str(target / rel), *args], 60).ok:
                    raise RuntimeError(f"{rel} does not run")
        except BaseException as e:
            shutil.rmtree(target, ignore_errors=True)
            if previous is not None:
                shutil.move(str(previous), str(target))
            return f"{e} - the previous version was put back"
        for old in sorted((runtimes / "_previous").glob(f"{key}-*"))[:-1]:
            shutil.rmtree(old, ignore_errors=True)         # keep only the newest rollback copy
        return ""
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def install_mkvtoolnix(root: Path, version: str, target: Path) -> str:
    # The .7z is a third the size of the .zip, so it is used whenever it can be unpacked.
    pkg = mkvtoolnix_package(version, use_7z=find_7z_extractor() is not None)
    return install_archive_runtime(root, "mkvtoolnix", target, pkg, "mkvmerge.exe",
                                   [("mkvmerge.exe", ["--version"]), ("mkvpropedit.exe", ["--version"])])


def install_ffmpeg(root: Path, channel: str = "release", variant: str = "full") -> str:
    pkg = ffmpeg_package(channel, variant)
    if pkg[2].endswith(".7z") and find_7z_extractor() is None:
        return _NO_7Z
    return install_archive_runtime(root, "ffmpeg", root / "runtimes" / "ffmpeg", pkg, "bin/ffmpeg.exe",
                                   [("bin/ffmpeg.exe", ["-version"])])


def pip_install(package_key: str, upgrade: bool) -> str:
    pkg = _PIP_PACKAGES.get(package_key)
    if pkg is None:
        return f"{package_key} is not a package this tool manages"
    cmd = [sys.executable, "-m", "pip", "install"] + (["--upgrade"] if upgrade else []) + [pkg]
    r = run_cmd(cmd, timeout_sec=600)
    return "" if r.ok else (_first_line(r.err) or _first_line(r.out) or f"pip exited {r.rc}")


def apply_runtime_update(root: Path, st: RuntimeStatus) -> str:
    if st.key == "mkvtoolnix":
        return install_mkvtoolnix(root, st.latest or "", st.extra["target"])
    if st.key == "ffmpeg":
        info = st.extra["info"]
        return install_ffmpeg(root, info["channel"], info["variant"] or "full")
    if st.key in _PIP_PACKAGES:
        return pip_install(st.key, upgrade=True)
    return f"{st.label} is not updated by this tool"


def _load_config_quietly(root: Path) -> Optional[Config]:
    try:
        return load_config(root / "MediaCleanup.toml")
    except Exception:
        return None


def run_update_runtimes(root: Path = _SCRIPT_DIR, dry_run: bool = False, assume_yes: bool = False) -> int:
    """--update-runtimes. Exit 0 when nothing failed, 1 when an update failed, 5 when declined."""
    print("Checking the tools MediaCleanup runs on...\n")
    statuses = gather_runtime_status(root, _load_config_quietly(root))
    _print_runtime_table(statuses)
    todo = [s for s in statuses if s.action == "update"]
    if not todo:
        print("\nNothing to update.")
        return 0
    names = ", ".join(s.label for s in todo)
    print(f"\nWould update: {names}.")
    print("  Each download is checked against a checksum published beside it; a replaced tool is "
          "kept in runtimes\\_previous\\ and put back if the new one does not run.")
    if dry_run:
        print("Dry run: nothing changed.")
        return 0
    if not _confirm(f"\nUpdate {names}?", assume_yes):
        return 5
    failed = 0
    for s in todo:
        print(f"\n{s.label}: {s.installed} -> {s.latest}")
        problem = apply_runtime_update(root, s)
        if problem:
            failed += 1
            print(f"  FAILED: {problem}")
        else:
            print(f"  Updated {s.label}.")
    print(f"\n{len(todo) - failed} updated, {failed} failed.")
    return 1 if failed else 0


def run_install(tool: str, root: Path = _SCRIPT_DIR, dry_run: bool = False, assume_yes: bool = False) -> int:
    """--install TOOL: add an optional tool (or a missing required one), then keep it updated."""
    if tool not in _INSTALLABLE:
        print(f"{tool!r} cannot be installed by this tool. It can install: {', '.join(_INSTALLABLE)}.")
        print("  FileBot is licensed and x265 is third-party (an ffmpeg build already carries libx265); "
              "Python is installed with winget or from python.org.")
        return 1
    cfg = _load_config_quietly(root)
    st = next(s for s in gather_runtime_status(root, cfg) if s.key == tool)
    if st.installed:
        print(f"{st.label} {st.installed} is already installed. Use --update-runtimes to keep it current.")
        return 0
    if tool in _PIP_PACKAGES:
        print(f"Would install the {_PIP_PACKAGES[tool]} Python package with pip.")
    else:
        latest = mkvtoolnix_latest() if tool == "mkvtoolnix" else ffmpeg_latest("release")
        if not latest:
            print(f"Could not find the latest {st.label} version (offline, or the site is unreachable).")
            return 1
        print(f"Would install {st.label} {latest} into runtimes\\{tool}\\ (checksum verified).")
    if dry_run:
        print("Dry run: nothing changed.")
        return 0
    if not _confirm(f"\nInstall {st.label}?", assume_yes):
        return 5
    if tool in _PIP_PACKAGES:
        problem = pip_install(tool, upgrade=False)
    elif tool == "mkvtoolnix":
        problem = install_mkvtoolnix(root, latest, st.extra["target"])
    else:
        problem = install_ffmpeg(root, "release", "full")
    if problem:
        print(f"FAILED: {problem}")
        return 1
    print(f"Installed {st.label}.")
    return 0


# --- repair -------------------------------------------------------------------------

def run_repair(root: Path = _SCRIPT_DIR, dry_run: bool = False, assume_yes: bool = False,
               files_only: bool = False) -> int:
    """
    --repair: bring an install back to a working state without touching the user's
    choices: restore missing or modified project files, recreate folders, report
    config problems, and re-install a missing MKVToolNix. Exit 0 when everything is
    fine or was fixed, 1 when something could not be fixed, 5 when declined.

    files_only checks and restores just the project files — what the installer uses to
    verify a fresh download without also creating a config or fetching tools.
    """
    print(f"Checking this MediaCleanup {__version__} install...\n")
    fixes: List[Tuple[str, Any]] = []          # (description, callable returning a problem or "")
    unfixable = 0

    def ok(msg: str) -> None:
        print(f"  [ok]   {msg}")

    def todo(msg: str, action) -> None:
        print(f"  [fix]  {msg}")
        fixes.append((msg, action))

    def bad(msg: str) -> None:
        nonlocal unfixable
        unfixable += 1
        print(f"  [FAIL] {msg}")

    def note(msg: str) -> None:
        print(f"  [--]   {msg}")

    # folders
    missing_dirs = [d for d in ("logs", "runtimes") if not (root / d).is_dir()] if not files_only else []

    def make_dirs() -> str:
        for d in missing_dirs:
            (root / d).mkdir(parents=True, exist_ok=True)
        return ""

    if missing_dirs:
        todo(f"create the missing folder(s): {', '.join(missing_dirs)}", make_dirs)
    elif not files_only:
        ok("folders")

    # project files
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    if _is_git_clone(root):
        note("this is a git clone - project files are managed by git (git status / git restore)")
    elif parse_version(__version__) is None:
        note("the version is unknown, so the project files cannot be checked")
    else:
        tag = "v" + __version__
        tree, why = fetch_release_tree(tag)
        if tree is None:
            note(f"project files not checked: {why}")
        else:
            plan = build_update_plan(root, tree, tree)
            broken = plan.add + plan.replace
            if not broken:
                ok(f"project files match release {tag} ({len(plan.unchanged)} checked)")
            else:
                shown = ", ".join(broken[:4]) + (f" and {len(broken) - 4} more" if len(broken) > 4 else "")
                todo(f"restore {len(broken)} project file(s) from {tag}: {shown}",
                     lambda: install_release_files(root, tag, tree, plan, _unique_path(
                         root / "backup" / f"repair-{__version__}-{stamp}")))

    def check_environment() -> None:
        # configuration
        cfg_path = root / "MediaCleanup.toml"
        example = root / "MediaCleanup.example.toml"
        cfg: Optional[Config] = None

        def copy_example() -> str:
            shutil.copyfile(example, cfg_path)
            return ""

        if not cfg_path.exists():
            if example.exists():
                todo("create MediaCleanup.toml from the example (you still need to set your paths)", copy_example)
            else:
                bad("MediaCleanup.toml is missing and so is MediaCleanup.example.toml")
        else:
            try:
                cfg = load_config(cfg_path)
                ok("MediaCleanup.toml reads correctly")
            except Exception as e:
                bad(f"MediaCleanup.toml has a problem you need to fix yourself: {e}")
            for line in new_config_settings(root):
                note(f"setting not in your MediaCleanup.toml (the default applies): {line}")

        # MKVToolNix
        exe = cfg.MKVMERGE_EXE if cfg else root / "runtimes" / "mkvtoolnix" / "mkvmerge.exe"
        runs = exe.exists() and run_cmd([str(exe), "--version"], 30).ok
        if runs:
            ok(f"MKVToolNix runs ({_first_line(run_cmd([str(exe), '--version'], 30).out)})")
        elif _inside(exe, root / "runtimes"):
            latest = mkvtoolnix_latest()
            if latest:
                todo(f"install MKVToolNix {latest} into {exe.parent}",
                     lambda: install_mkvtoolnix(root, latest, exe.parent))
            else:
                bad("MKVToolNix is missing and its latest version could not be looked up (offline?)")
        else:
            bad(f"MKVToolNix is missing or does not run ({exe}); it is outside runtimes\\, so fix that install yourself")

        # optional tools are reported, never repaired
        fb = cfg.FILEBOT_EXE if cfg else root / "runtimes" / "FileBot" / "filebot.exe"
        note("FileBot " + ("found" if fb.exists() else "not installed (optional)"))
        note("ffmpeg " + ("found" if _find_optional_tool("ffmpeg", root) else "not installed (optional, add with --install ffmpeg)"))

    if not files_only:
        check_environment()

    if not fixes:
        print("\n" + ("Nothing to repair." if not unfixable else f"\n{unfixable} problem(s) need your attention."))
        return 1 if unfixable else 0
    if dry_run:
        print(f"\nDry run: would make {len(fixes)} fix(es); nothing changed.")
        return 1 if unfixable else 0
    if not _confirm(f"\nMake {len(fixes)} fix(es)?", assume_yes):
        return 5
    failed = 0
    for desc, action in fixes:
        print(f"\n{desc}")
        problem = action()
        if problem:
            failed += 1
            print(f"  FAILED: {problem}")
        else:
            print("  Done.")
    print(f"\n{len(fixes) - failed} fixed, {failed + unfixable} still need attention. "
          "Run: python MediaCleanup.py --self-check")
    return 1 if (failed or unfixable) else 0


# =========================
# Main
# =========================

def report_pending_identity() -> int:
    """
    Save the numbered list of titles that could not be identified, so the choice
    can be made by number, and show the command that applies it.

    Every mode that can print numbered candidates must call this: the numbers
    are only meaningful because they are written down and read back by --pick,
    and a mode that prints them without saving them offers a choice that cannot
    be acted on.
    """
    need = write_pending_identity()
    if need:
        # One suggested number per title — the first candidate that has an id.
        first: Dict[str, int] = {}
        for r in _PENDING_IDENTITY:
            if r["id"] and r["key"] not in first:
                first[r["key"]] = r["n"]
        nums = " ".join(str(n) for n in sorted(first.values()))
        logging.warning("%d title(s) need identifying — pick from the numbered list above, "
                        "then rerun with the same scope plus --pick:", need)
        logging.warning("    python MediaCleanup.py --pick %s", nums or "N")
    return need


def main() -> int:
    rc = _main()
    if _UPDATE_NOTICES:
        try:
            finish_update_check()
        except Exception as e:        # a notice must never change how a run ends
            logging.debug("Update notice failed: %s", e)
    return rc


def _main() -> int:
    ap = argparse.ArgumentParser(description="MediaCleanup.py (Enhanced) - MKV cleanup/merge tool (Movies + TV) using MKVToolNix")
    ap.add_argument("--dry-run", action="store_true", help="Log actions without copying/remuxing.")
    ap.add_argument("--verbose", action="store_true", help="Enable verbose debug logging.")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1), help="Parallel workers.")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite existing outputs.")
    ap.add_argument("--inplace", action="store_true",
                    help="Remuxed output replaces the source file(s) in their own folder instead of "
                         "going to output_root. The output is VERIFIED (track counts + duration) "
                         "before any source is touched. Multi-file merges consume ALL variants.")
    ap.add_argument("--backup", action="store_true",
                    help="With --inplace: keep each consumed source as '<name>.original.mkv' next to "
                         "the new file instead of deleting it. Backups are excluded from all scans.")
    ap.add_argument("--log-file", type=str, default="", help="Optional log file path.")
    
    # Selection flags:
    # - If neither --movies nor --tv is provided, default is BOTH (Movies + TV).
    # - If one (or both) is provided, run exactly what is selected.
    ap.add_argument("--movies", action="store_true", help="Process Movies pipeline.")
    ap.add_argument("--tv", action="store_true", help="Process TV pipeline.")
    # Backward-compatibility (deprecated):
    ap.add_argument("--only-movies", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--only-tv", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--input", type=str, default="", metavar="PATH",
                    help="Override the scan root folder. With --movies, scans this path instead of "
                         "MOVIES_ROOT. With --tv, scans instead of TV_ROOT. With both (or neither), "
                         "applies to both pipelines. Also applies to --cleantags.")
    ap.add_argument("--self-check", action="store_true", help="Run unit-test-like self checks and exit.")
    ap.add_argument("--cleantags", action="store_true",
                    help="Standalone mode: clean promotional/advertising tags in-place on every MKV in the "
                         "scan root using mkvpropedit. Uses --movies/--tv/--input scope flags.")
    ap.add_argument("--coverart", action="store_true",
                    help="Standalone mode: fetch and embed cover art (cover.jpg attachment) into every "
                         "MKV in the scan root that doesn't already have one. Source chain: local "
                         "poster.jpg/cover.jpg/folder.jpg, then TMDB, fanart.tv, OMDb (API keys in the "
                         "[coverart] section of MediaCleanup.toml). Uses --movies/--tv/--input scope flags.")
    ap.add_argument("--coverart-overwrite", action="store_true",
                    help="With --coverart: replace existing embedded cover art instead of skipping the file.")
    ap.add_argument("--clear", action="store_true",
                    help="Removal modifier for the standalone modes. With --cleantags: wipe ALL tags, "
                         "the segment title and every track name, writing nothing back (offline, no "
                         "database lookups). With --coverart: delete embedded cover art and forget the "
                         "file in the ledger so a later run re-fetches it.")
    ap.add_argument("--cleanmetadata", action="store_true",
                    help="Standalone mode: --cleantags and --coverart in one command. Cleans tags, embeds "
                         "metadata and renames in place, then embeds cover art on the final filenames. "
                         "With --clear it instead wipes all tags AND removes cover art, and never renames.")
    ap.add_argument("--rename", action="store_true",
                    help="Standalone mode: rename MKVs into the canonical naming format via FileBot "
                         "(no remux, no tag changes unless --force-*-lang is given). Requires exactly "
                         "one of --movies or --tv, plus --input for the folder to scan. In-place by "
                         "default; see --rename-into. Every rename is logged for --rename-undo.")
    ap.add_argument("--rename-into", action="store_true",
                    help="With --rename: move files into the library structure under MOVIES_ROOT/TV_ROOT "
                         "(Movies: 'Title (Year)/...'; TV: 'Show (Year)/Season XX/...').")
    ap.add_argument("--rename-undo", action="store_true",
                    help="Revert the most recent --rename batch recorded in logs/rename_history.csv, then exit.")
    ap.add_argument("--subtitles", action="store_true",
                    help="Standalone mode: download missing subtitles from OpenSubtitles.com as sidecar "
                         ".srt files (no remux). Languages come from [subtitles] in MediaCleanup.toml "
                         "(default: English). Skips files that already have the language embedded or as "
                         "a sidecar. Uses --movies/--tv/--input scope flags.")
    ap.add_argument("--validate-keys", action="store_true",
                    help="Test the API keys in MediaCleanup.toml with one cheap call each "
                         "(TMDB, fanart.tv, OMDb, OpenSubtitles), print a verdict per key, and exit. "
                         "Exit code 1 if any configured key is invalid.")
    ap.add_argument("--preview-exact", action="store_true",
                    help="With --dry-run: ask FileBot itself for each predicted filename instead of "
                         "predicting it from the database. Authoritative but much slower (one FileBot "
                         "launch per item). Default: fast database prediction.")
    ap.add_argument("--no-fetch-tags", action="store_true",
                    help="Disable rich metadata tagging (genre/director/actors/synopsis from TMDB+OMDb) "
                         "during tag cleaning. Default: enabled whenever API keys are configured.")
    ap.add_argument("--filter", action="append", metavar="PATTERN", default=None,
                    help="Only process items matching this case-insensitive glob pattern "
                         "(matched against the movie/show folder name AND the MKV filename). "
                         "Repeatable. Works in every mode. Example: --filter \"A*\"")
    ap.add_argument("--no-color", action="store_true",
                    help="Disable colored output and summary tables (also honored via the "
                         "NO_COLOR environment variable). Automatic when 'rich' is not installed.")
    ap.add_argument("--skip-cleantags", action="store_true",
                    help="Disable the automatic tag-clean step that normally runs after each remux.")
    ap.add_argument("--skip-coverart", action="store_true",
                    help="Disable the automatic cover art embed that runs as the final pipeline step. "
                         "(The standalone --coverart mode is unaffected.)")
    ap.add_argument("--pick", metavar="N", type=int, nargs="+", default=None,
                    help="Choose films by the numbers shown in the previous run's list of "
                         "candidates, e.g. --pick 1 4. Several may be given, one per film.")
    ap.add_argument("--imdb", metavar="ttNNNNNNN", default=None,
                    help="Identify the film in scope as this IMDB id, for a title the tool refuses "
                         "to guess between. Scope the run to one film with --filter/--input; the id "
                         "is written into the file's tags, so later runs need it only once.")
    ap.add_argument("--mp4tomkv", action="store_true",
                    help="Standalone: remux MP4/M4V files (plus any sidecar .srt) into MKV beside the "
                         "source, then finish them completely — tag clean, metadata, languages, cover "
                         "art and rename. Sources are never modified or deleted.")
    ap.add_argument("--no-lang-detect", action="store_true",
                    help="Do not try to identify tracks tagged 'und'. By default a lone unlabelled "
                         "audio track takes the title's original language and unlabelled text "
                         "subtitles are identified from their own text.")
    ap.add_argument("--version", action="store_true",
                    help="Standalone: print this tool's version and the versions of the tools it "
                         "runs on (Python, MKVToolNix, FileBot, ffmpeg, x265, rich, Pillow), then exit.")
    ap.add_argument("--check-update", action="store_true",
                    help="Standalone: compare this version with the latest published GitHub release "
                         "and show what changed. Exit code 0 = up to date, 10 = a newer release is "
                         "available, 1 = could not check. Downloads and installs nothing.")
    ap.add_argument("--update", action="store_true",
                    help="Standalone: install the latest published release. Every file is verified "
                         "against GitHub's published hashes, only files the release contains are "
                         "written (never MediaCleanup.toml, logs\\ or runtimes\\), whatever is "
                         "replaced is backed up first, and a failure restores it. A git clone is "
                         "updated with git. Shows a plan and asks first; --dry-run only shows the plan.")
    ap.add_argument("--update-to", metavar="TAG", default=None,
                    help="Like --update, but to a specific release, e.g. --update-to v1.11.0. The "
                         "only way to move to an OLDER release.")
    ap.add_argument("--update-runtimes", action="store_true",
                    help="Standalone: update the tools MediaCleanup runs on. MKVToolNix, ffmpeg (once "
                         "installed) and the pip packages (rich, Pillow) are updated automatically — "
                         "downloads are checksum-verified and a replaced tool is kept in "
                         "runtimes\\_previous\\. FileBot, x265 and Python are only reported. Shows a "
                         "plan and asks first; --dry-run only shows the plan.")
    ap.add_argument("--install", metavar="TOOL", default=None,
                    help="Standalone: install an optional tool (ffmpeg, rich, pillow) or a missing "
                         "required one (mkvtoolnix), then keep it updated with --update-runtimes. "
                         "FileBot, x265 and Python are explained rather than installed.")
    ap.add_argument("--repair", action="store_true",
                    help="Standalone: bring an install back to a working state — restore missing or "
                         "modified project files (checked against the release), recreate folders, "
                         "report config problems and re-install a missing MKVToolNix. MediaCleanup.toml, "
                         "logs\\ and your ledgers are never touched.")
    ap.add_argument("--files-only", action="store_true",
                    help="With --repair: check and restore only the project files, not the folders, "
                         "config or tools. The installer uses it to verify a fresh download.")
    ap.add_argument("--yes", action="store_true",
                    help="Answer yes to the confirmation that --update and the other install/repair "
                         "modes ask — needed when there is no terminal.")
    ap.add_argument("--no-update-check", action="store_true",
                    help="Skip the once-a-day look for a newer release for this run. Config "
                         "equivalent: [updates] check = false.")
    ap.add_argument("--no-local-name", action="store_true",
                    help="Leave a title that no database knows exactly as it is. By default such a "
                         "file is named and its tags cleaned from facts in the file itself (title "
                         "and year from its filename, resolution, codec and audio languages from the "
                         "video) and reported as LOCAL; nothing is ever invented, and a title with "
                         "several possible matches is never named this way.")
    ap.add_argument("--force-video-lang", metavar="LANG", default=None,
                    help="Set the VIDEO track language to this value during tag cleaning instead of "
                         "the title's TMDB original language. Accepts any supported language "
                         "(ISO code or name), e.g. --force-video-lang Hindi")
    ap.add_argument("--include-forced-subs", action="store_true", help="Allow forced English subtitle selection.")
    ap.add_argument(
        "--audio-langs", nargs="+", metavar="LANG", default=None,
        help=(
            "Restrict audio tracks to these languages only. "
            "Accepts full names or codes: Telugu/tel, Hindi/hin, English/eng. "
            "Example: --audio-langs Telugu Hindi"
        ),
    )
    ap.add_argument("--similarity-threshold", type=float, default=Config.SIMILARITY_THRESHOLD_DEFAULT,
                    help=f"Movies grouping similarity threshold (default {Config.SIMILARITY_THRESHOLD_DEFAULT}).")
    ap.add_argument(
        "--force-audio-lang", nargs=2, action="append", metavar=("TRACK_ID", "LANG"), default=None,
        help="Force a specific audio track ID to be treated as a given language. "
             "Can be repeated. Example: --force-audio-lang 1 Hindi --force-audio-lang 2 Telugu"
    )
    ap.add_argument(
        "--force-sub-lang", nargs=2, action="append", metavar=("TRACK_ID", "LANG"), default=None,
        help="Force a specific subtitle track ID to be treated as a given language. "
             "Can be repeated. Example: --force-sub-lang 3 English"
    )
    args = ap.parse_args()

    # These two need no configuration, so a fresh install can run them before one exists.
    maintenance = [
        (args.version, lambda: print_version()),
        (args.check_update, lambda: run_check_update()),
        (args.repair, lambda: run_repair(dry_run=args.dry_run, assume_yes=args.yes, files_only=args.files_only)),
        (args.update or args.update_to,
         lambda: run_update(dry_run=args.dry_run, assume_yes=args.yes, to_tag=args.update_to)),
        (args.update_runtimes, lambda: run_update_runtimes(dry_run=args.dry_run, assume_yes=args.yes)),
        (args.install, lambda: run_install(args.install, dry_run=args.dry_run, assume_yes=args.yes)),
    ]
    if any(flag for flag, _ in maintenance):
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(errors="replace")
            except (AttributeError, ValueError, OSError):
                pass
        rc, first = 0, True
        for flag, run_it in maintenance:
            if flag:
                if not first:
                    print()
                first = False
                rc = run_it()
        return rc

    log_file = Path(args.log_file) if args.log_file else None

    # Colored output + summary tables when 'rich' is installed and color isn't
    # disabled via --no-color or the NO_COLOR convention.
    global _RICH_ENABLED, _CONSOLE
    if _RICH_AVAILABLE and not args.no_color and not os.environ.get("NO_COLOR"):
        _CONSOLE = _RichConsole()
        _RICH_ENABLED = True

    setup_logging(args.verbose, log_file)

    # Load paths from MediaCleanup.toml (same folder as this script).
    global CFG
    try:
        CFG = load_config()
    except ConfigError as e:
        logging.error("%s", e)
        return 2
    logging.debug("Config loaded from %s", CONFIG_FILE)

    # Once a day, in the background, look for a newer release; a one-line notice is
    # printed at the end of the run. A dry run stays offline, so it only shows what an
    # earlier check already found.
    global _UPDATE_NOTICES
    if CFG.UPDATE_CHECK and not args.no_update_check and not (args.validate_keys or args.self_check):
        _UPDATE_NOTICES = True
        if not args.dry_run:
            start_background_update_check()

    # --pick turns numbers from the last run's list into identified films.
    if args.pick:
        if args.imdb:
            logging.error("--pick and --imdb both choose a film; use one or the other.")
            return 2
        global _PICK_SELECTION
        _PICK_SELECTION, problems = load_pick_selection(args.pick)
        for p in problems:
            logging.error("--pick %s", p)
        if problems:
            return 2
        logging.info("Identifying %d title(s) from your picks.", len(_PICK_SELECTION))

    # --imdb identifies ONE film, so the run must be narrowed to one. Applying it
    # to a whole library would stamp the same id onto every file in it.
    if args.imdb:
        if not re.fullmatch(r"tt\d{7,10}", args.imdb.strip()):
            logging.error("--imdb must be an IMDB id like tt1234567, got %r", args.imdb)
            return 2
        if not (args.filter or args.input):
            logging.error("--imdb identifies a single film — scope the run with --filter or --input "
                          "so it cannot be applied to your whole library.")
            return 2
        if args.tv:
            logging.error("--imdb applies to films, not TV episodes.")
            return 2
        global _IMDB_OVERRIDE
        _IMDB_OVERRIDE = args.imdb.strip()
        logging.info("Films in scope will be identified as %s.", _IMDB_OVERRIDE)

    if args.no_lang_detect and CFG.DETECT_UNDETERMINED_LANGS:
        CFG = dataclasses.replace(CFG, DETECT_UNDETERMINED_LANGS=False)
        logging.info("Undetermined-language detection disabled (--no-lang-detect).")

    if args.no_local_name and CFG.LOCAL_NAME_FALLBACK:
        CFG = dataclasses.replace(CFG, LOCAL_NAME_FALLBACK=False)
        logging.info("Naming from the file alone disabled (--no-local-name).")

    global _FETCH_TAGS_ENABLED, _PREVIEW_EXACT
    if args.no_fetch_tags:
        _FETCH_TAGS_ENABLED = False
        logging.info("Rich metadata tagging disabled (--no-fetch-tags).")
    if args.preview_exact:
        if not args.dry_run:
            logging.error("--preview-exact only applies to --dry-run.")
            return 2
        _PREVIEW_EXACT = True
        logging.info("Exact preview enabled: FileBot will be asked for each name (slower).")

    # --validate-keys standalone: test each configured API key and exit.
    if args.validate_keys:
        status = validate_api_keys()
        for source, st in status.items():
            logging.info("%-10s: %s", source, st.upper() if st == "invalid" else st)
        invalid = [s for s, st in status.items() if st == "invalid"]
        if invalid:
            logging.error("Invalid key(s): %s — fix them in [coverart] of %s",
                          ", ".join(invalid), CONFIG_FILE)
            return 1
        return 0

    # Parse --audio-langs into canonical keys early so errors surface before any work starts.
    audio_lang_filter: Optional[List[str]] = None
    if args.audio_langs:
        try:
            audio_lang_filter = parse_audio_lang_filter(args.audio_langs)
        except ValueError as e:
            logging.error("--audio-langs error: %s", e)
            return 2
        logging.info("Audio language filter: %s", [CFG.LANG_DISPLAY_MAP.get(c, c) for c in audio_lang_filter])

    # Parse --force-audio-lang / --force-sub-lang overrides
    force_audio_langs: Dict[int, str] = {}
    force_sub_langs: Dict[int, str] = {}
    try:
        force_audio_langs = parse_force_lang_overrides(args.force_audio_lang)
        force_sub_langs = parse_force_lang_overrides(args.force_sub_lang)
    except ValueError as e:
        logging.error("--force-audio-lang / --force-sub-lang error: %s", e)
        return 2
    if force_audio_langs:
        logging.info("Force audio lang overrides: %s", {k: CFG.LANG_DISPLAY_MAP.get(v, v) for k, v in force_audio_langs.items()})
    if force_sub_langs:
        logging.info("Force subtitle lang overrides: %s", {k: CFG.LANG_DISPLAY_MAP.get(v, v) for k, v in force_sub_langs.items()})

    # --force-video-lang accepts ANY language in the built-in table (not just targets).
    global _FORCE_VIDEO_LANG
    if args.force_video_lang:
        iso2 = resolve_language(args.force_video_lang)
        if iso2 is None:
            logging.error("--force-video-lang: unknown language %r. Use an ISO code or English name.",
                          args.force_video_lang)
            return 2
        _FORCE_VIDEO_LANG = iso2
        logging.info("Force video lang: %s (%s)", _LANGUAGE_TABLE[iso2][1], iso2)

    if args.self_check:
        return self_check()

    if (args.only_movies or args.only_tv) and (args.movies or args.tv):
        logging.error("Invalid arguments: do not mix deprecated --only-* flags with --movies/--tv.")
        return 2
    if args.only_movies and args.only_tv:
        logging.error("Invalid arguments: cannot set both Movies-only and TV-only at the same time.")
        return 2

    # Resolve --input into per-pipeline roots
    input_override = Path(args.input) if args.input else None
    if input_override and not input_override.exists():
        logging.error("--input path does not exist: %s", input_override)
        return 2

    # Standalone modes are mutually exclusive.
    modes = [m for m, on in (("--cleantags", args.cleantags), ("--coverart", args.coverart),
                             ("--cleanmetadata", args.cleanmetadata),
                             ("--rename", args.rename), ("--subtitles", args.subtitles),
                             ("--mp4tomkv", args.mp4tomkv),
                             ("--rename-undo", args.rename_undo)) if on]
    if len(modes) > 1:
        logging.error("Invalid arguments: %s are separate modes; run them one at a time.", " and ".join(modes))
        return 2

    if args.clear and not (args.cleantags or args.coverart or args.cleanmetadata):
        logging.error("--clear applies to --cleantags, --coverart or --cleanmetadata.")
        return 2

    if args.backup and not args.inplace:
        logging.error("--backup only makes sense together with --inplace.")
        return 2
    if (args.inplace or args.backup) and modes:
        logging.error("--inplace/--backup apply to the main pipeline only, not to %s.", modes[0])
        return 2

    # --rename-undo needs nothing else — do it and exit.
    if args.rename_undo:
        return run_rename_undo()

    # mkvpropedit is needed for cleantags (standalone or auto after remux) and for --coverart.
    # Skip validation failure if mkvpropedit is absent and --skip-cleantags was set.
    need_propedit = (not args.skip_cleantags) or args.coverart or args.cleanmetadata
    try:
        validate_tools(need_propedit=need_propedit)
    except Exception as e:
        logging.error("Tool validation failed: %s", e)
        return 2

    # Soft key check at run start: a definitively invalid key (HTTP 401) would
    # otherwise fail once per file — disable that source up front instead.
    # Dry runs stay offline, so skip it there.
    if not args.dry_run and (CFG.TMDB_API_KEY or CFG.FANARTTV_API_KEY or CFG.OMDB_API_KEY):
        disable_invalid_api_keys()

    # Determine which pipelines to run
    if args.movies or args.tv:
        do_movies = args.movies
        do_tv = args.tv
    else:
        if args.only_movies:
            do_movies, do_tv = True, False
        elif args.only_tv:
            do_movies, do_tv = False, True
        else:
            do_movies, do_tv = True, True

    # SAFETY: --input with both pipelines active would point Movies AND TV at the
    # same folder — every file would be processed twice, concurrently. Require an
    # explicit choice instead.
    if input_override and do_movies and do_tv:
        logging.error("--input requires exactly one of --movies or --tv "
                      "(otherwise every file in %s would be processed twice, once per pipeline).",
                      input_override)
        return 2

    # Resolve effective roots (--input overrides per pipeline)
    if input_override:
        movies_root = input_override if do_movies else CFG.MOVIES_ROOT
        tv_root     = input_override if do_tv     else CFG.TV_ROOT
    else:
        movies_root = CFG.MOVIES_ROOT
        tv_root     = CFG.TV_ROOT

    # --mp4tomkv standalone: convert MP4/M4V to MKV, finish each file, then exit.
    if args.mp4tomkv:
        # The finishing chain embeds cover art as its last step, so the shared
        # cover art context has to be live here too — it is set up further down
        # for the main pipeline, which this mode returns before reaching.
        if not args.skip_coverart and not args.dry_run:
            _PIPELINE_COVERART.update(
                enabled=True, fetcher=CoverArtFetcher(), ledger=CoverartLedger(),
                review_dir=(_SCRIPT_DIR / "logs" / "coverart_review" /
                            _dt.datetime.now().strftime("%Y%m%d_%H%M%S")))
        mp4_results = run_mp4tomkv_pipeline(
            do_movies=do_movies,
            do_tv=do_tv,
            movies_root=movies_root,
            tv_root=tv_root,
            dry_run=args.dry_run,
            overwrite=args.overwrite,
            filters=args.filter,
            include_forced_subs=args.include_forced_subs,
            audio_lang_filter=audio_lang_filter,
            skip_cleantags=args.skip_cleantags,
            force_audio_langs=force_audio_langs,
            force_sub_langs=force_sub_langs,
        )
        ok_mp4 = sum(1 for r in mp4_results if r.ok)
        bad_mp4 = sum(1 for r in mp4_results if not r.ok)
        logging.info("mp4tomkv summary: total=%d OK=%d failed=%d", len(mp4_results), ok_mp4, bad_mp4)
        for r in mp4_results:
            if not r.ok:
                logging.warning("- %s | %s", r.source_items[0].name if r.source_items else "?", r.reason)
        if _PIPELINE_COVERART["enabled"] and not args.dry_run:
            _PIPELINE_COVERART["ledger"].save()
            ca = _PIPELINE_COVERART["results"]
            embedded = sum(1 for r in ca if r.ok and r.details.get("review_image"))
            if ca:
                logging.info("Cover art: %d file(s) processed, %d new cover(s) embedded.",
                             len(ca), embedded)
            if _PIPELINE_COVERART["review_dir"] and embedded:
                report = _write_coverart_report(_PIPELINE_COVERART["review_dir"], ca)
                if report:
                    logging.info("Cover art review: %s", report)
        print_results_table("MP4 to MKV", mp4_results)
        report_pending_identity()
        return 0 if bad_mp4 == 0 else 1

    # --cleanmetadata standalone: --cleantags then --coverart in one command.
    if args.cleanmetadata:
        # Step 1: tags + metadata (+ rename in place). With --clear this wipes the
        # tags instead, offline and without renaming.
        ct_results = run_cleantags_pipeline(
            do_movies=do_movies, do_tv=do_tv, dry_run=args.dry_run, workers=args.workers,
            movies_root=movies_root, tv_root=tv_root, skip_filebot=False,
            filters=args.filter, clear_all=args.clear,
        )
        ok_ct = sum(1 for r in ct_results if r.ok)
        bad_ct = len(ct_results) - ok_ct
        logging.info("%s summary: total=%d OK=%d failed=%d",
                     "cleartags" if args.clear else "cleantags", len(ct_results), ok_ct, bad_ct)
        for r in ct_results:
            if not r.ok:
                logging.error("  FAILED: %s | %s",
                              r.source_items[0].name if r.source_items else "?", r.reason)

        # Step 2: cover art. Hand over exactly the files step 1 produced — rescanning
        # with --filter would test their NEW names against a pattern meant for the
        # old ones, and silently skip anything the rename had changed.
        if args.clear:
            handed = None   # clearing never renames, so the ordinary scan is correct
        else:
            handed = [(r.output_path, bool(r.details.get("is_tv")))
                      for r in ct_results
                      if r.ok and r.output_path is not None and r.details.get("identified", True)]
            held_back = [r for r in ct_results if r.ok and not r.details.get("identified", True)]
            if held_back:
                logging.warning("Skipping cover art for %d film(s) that could not be identified — "
                                "a poster chosen by title alone could belong to a different film. "
                                "Use --pick, then run again.", len(held_back))
        ca_results = run_coverart_pipeline(
            do_movies=do_movies, do_tv=do_tv, dry_run=args.dry_run, workers=args.workers,
            movies_root=movies_root, tv_root=tv_root,
            overwrite_cover=args.coverart_overwrite, filters=args.filter,
            clear_only=args.clear, only_files=handed,
        )
        ok_ca = sum(1 for r in ca_results if r.ok)
        bad_ca = len(ca_results) - ok_ca
        if args.clear:
            cleared = sum(1 for r in ca_results if r.ok and r.details.get("source") == "cleared")
            logging.info("coverart clear summary: total=%d cleared=%d (had none: %d) failed=%d",
                         len(ca_results), cleared, ok_ca - cleared, bad_ca)
        else:
            skipped_ca = sum(1 for r in ca_results
                             if r.ok and r.reason in ("already_has_cover", "ledger_skip"))
            logging.info("coverart summary: total=%d OK=%d (already done: %d) failed=%d",
                         len(ca_results), ok_ca, skipped_ca, bad_ca)
        for r in ca_results:
            if not r.ok:
                logging.error("  FAILED: %s | %s",
                              r.source_items[0].name if r.source_items else "?", r.reason)

        print_results_table("Cleantags results", ct_results)
        print_results_table("Cover art results", ca_results)
        report_pending_identity()
        return 0 if (bad_ct == 0 and bad_ca == 0) else 1

    # --cleantags standalone: scan roots, clean tags in-place, then exit.
    if args.cleantags:
        ct_results = run_cleantags_pipeline(
            do_movies=do_movies,
            do_tv=do_tv,
            dry_run=args.dry_run,
            workers=args.workers,
            movies_root=movies_root,
            tv_root=tv_root,
            skip_filebot=False,  # always attempt FileBot rename in --cleantags mode
            filters=args.filter,
            clear_all=args.clear,
        )
        ok_ct  = sum(1 for r in ct_results if r.ok)
        bad_ct = sum(1 for r in ct_results if not r.ok)
        logging.info("%s summary: total=%d OK=%d failed=%d",
                     "cleartags" if args.clear else "cleantags", len(ct_results), ok_ct, bad_ct)
        if bad_ct:
            for r in ct_results:
                if not r.ok:
                    logging.error("  FAILED: %s | %s", r.source_items[0].name if r.source_items else "?", r.reason)
        print_results_table("Cleantags results", ct_results)
        report_pending_identity()
        return 0 if bad_ct == 0 else 1

    # --rename standalone: FileBot-rename every MKV in scope, then exit.
    if args.rename:
        if do_movies == do_tv:
            logging.error("--rename requires exactly one of --movies or --tv "
                          "(the two use different databases and naming formats).")
            return 2
        is_tv_mode = do_tv
        scan_root = tv_root if is_tv_mode else movies_root
        rn_results = run_rename_pipeline(
            is_tv=is_tv_mode,
            scan_root=scan_root,
            rename_into=args.rename_into,
            dry_run=args.dry_run,
            workers=args.workers,
            force_audio_langs=force_audio_langs,
            force_sub_langs=force_sub_langs,
            filters=args.filter,
        )
        ok_rn = sum(1 for r in rn_results if r.ok)
        bad_rn = sum(1 for r in rn_results if not r.ok)
        renamed = sum(1 for r in rn_results if r.ok and r.details.get("new"))
        logging.info("rename summary: total=%d renamed=%d OK=%d failed=%d",
                     len(rn_results), renamed, ok_rn, bad_rn)
        if bad_rn:
            for r in rn_results:
                if not r.ok:
                    logging.error("  FAILED: %s | %s",
                                  r.source_items[0].name if r.source_items else "?", r.reason)
        print_results_table("Rename results", rn_results)
        report_pending_identity()
        return 0 if bad_rn == 0 else 1

    # --subtitles standalone: download missing sidecar subs, then exit.
    if args.subtitles:
        st_results = run_subtitles_pipeline(
            do_movies=do_movies,
            do_tv=do_tv,
            dry_run=args.dry_run,
            workers=args.workers,
            movies_root=movies_root,
            tv_root=tv_root,
            filters=args.filter,
        )
        ok_st = sum(1 for r in st_results if r.ok)
        bad_st = sum(1 for r in st_results if not r.ok)
        covered = sum(1 for r in st_results if r.ok and r.reason == "already_covered")
        quota = sum(1 for r in st_results if not r.ok and r.details.get("blocked"))
        logging.info("subtitles summary: total=%d OK=%d (already covered: %d) failed=%d (quota-blocked: %d)",
                     len(st_results), ok_st, covered, bad_st, quota)
        if bad_st:
            for r in st_results:
                if not r.ok and not r.details.get("blocked"):
                    logging.error("  FAILED: %s | %s",
                                  r.source_items[0].name if r.source_items else "?", r.reason)
        blocked_why = next((r.reason for r in st_results if r.details.get("blocked")), "")
        if blocked_why:
            logging.warning("Downloads stopped: %s", blocked_why)
        print_results_table("Subtitle results", st_results)
        report_pending_identity()       # a title that could not be identified lists numbered candidates
        return 0 if bad_st == 0 else 1

    # --coverart standalone: scan roots, embed cover art in-place, then exit.
    if args.coverart:
        ca_results = run_coverart_pipeline(
            do_movies=do_movies,
            do_tv=do_tv,
            dry_run=args.dry_run,
            workers=args.workers,
            movies_root=movies_root,
            tv_root=tv_root,
            overwrite_cover=args.coverart_overwrite,
            filters=args.filter,
            clear_only=args.clear,
        )
        ok_ca = sum(1 for r in ca_results if r.ok)
        bad_ca = sum(1 for r in ca_results if not r.ok)
        if args.clear:
            cleared = sum(1 for r in ca_results if r.ok and r.details.get("source") == "cleared")
            logging.info("coverart clear summary: total=%d cleared=%d (had none: %d) failed=%d",
                         len(ca_results), cleared, ok_ca - cleared, bad_ca)
        else:
            skipped_ca = sum(1 for r in ca_results
                             if r.ok and r.reason in ("already_has_cover", "ledger_skip"))
            logging.info("coverart summary: total=%d OK=%d (already done: %d) failed=%d",
                         len(ca_results), ok_ca, skipped_ca, bad_ca)
        if bad_ca:
            for r in ca_results:
                if not r.ok:
                    logging.error("  FAILED: %s | %s",
                                  r.source_items[0].name if r.source_items else "?", r.reason)
        print_results_table("Cover art results", ca_results)
        report_pending_identity()
        return 0 if bad_ca == 0 else 1

    # Ensure the output root exists (not needed for --inplace runs)
    if not args.inplace:
        try:
            CFG.OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logging.error("Cannot access/create folder: %s | %s", CFG.OUTPUT_ROOT, e)
            return 3

    results: List[Result] = []
    started = time.time()

    # Cover art rides along as the final finishing step of the pipeline
    # (after FileBot rename) unless --skip-coverart. The ledger keeps
    # re-runs cheap; failures never fail a file.
    if not args.skip_coverart:
        review_dir = (_SCRIPT_DIR / "logs" / "coverart_review" /
                      _dt.datetime.now().strftime("%Y%m%d_%H%M%S")) if not args.dry_run else None
        _PIPELINE_COVERART.update(enabled=True, fetcher=CoverArtFetcher(),
                                  ledger=CoverartLedger(), review_dir=review_dir)

    # Movies: group per-folder then per similarity group
    movie_tasks: List[Tuple[List[Path], Path]] = []
    if do_movies:
        movies = apply_scan_filters(scan_mkvs(movies_root), movies_root, args.filter, "movies")
        logging.info("Movies scan: %d MKV(s) found in %s.", len(movies), movies_root)
        by_folder = group_movies_by_folder(movies)
        # Identity resolution rescues variants whose filenames differ too much
        # to match on title alone. Lookups are allowed in dry-run (read-only)
        # so the preview matches what a real run would do; the cache is only
        # written on real runs.
        identity_cache = IdentityCache()
        for folder, mkvs in by_folder.items():
            groups = group_movies_in_folder(
                mkvs, threshold=args.similarity_threshold,
                identity_cache=identity_cache,
                allow_lookup=len(mkvs) > 1,
            )
            for g in groups:
                movie_tasks.append((g, movies_root))
        if not args.dry_run:
            identity_cache.save()

    # TV: per-file
    tv_files: List[Path] = []
    if do_tv:
        tv_files = apply_scan_filters(scan_mkvs(tv_root), tv_root, args.filter, "tv")
        logging.info("TV scan: %d MKV(s) found in %s.", len(tv_files), tv_root)

    # Parallel execution
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs: List[concurrent.futures.Future] = []

        for g, root in movie_tasks:
            futs.append(ex.submit(
                process_movie_group, g, root, args.dry_run, args.overwrite,
                args.include_forced_subs, audio_lang_filter, args.skip_cleantags,
                force_audio_langs, force_sub_langs, args.inplace, args.backup
            ))

        for f in tv_files:
            futs.append(ex.submit(
                process_tv_file, f, tv_root, args.dry_run, args.overwrite,
                args.include_forced_subs, audio_lang_filter, args.skip_cleantags,
                force_audio_langs, force_sub_langs, args.inplace, args.backup
            ))

        for fut in concurrent.futures.as_completed(futs):
            try:
                res = fut.result()
            except Exception as e:
                logging.exception("Worker crashed: %s", e)
                res = Result(kind="unknown", source_items=[], output_path=None, ok=False, reason=f"Worker exception: {e}")
            results.append(res)

    # Finalize pipeline cover art: persist the ledger and write the review gallery.
    if _PIPELINE_COVERART["enabled"] and not args.dry_run:
        _PIPELINE_COVERART["ledger"].save()
        ca_results = _PIPELINE_COVERART["results"]
        embedded = sum(1 for r in ca_results if r.ok and r.details.get("review_image"))
        if ca_results:
            logging.info("Pipeline cover art: %d file(s) processed, %d new cover(s) embedded.",
                         len(ca_results), embedded)
        if _PIPELINE_COVERART["review_dir"] and embedded:
            report = _write_coverart_report(_PIPELINE_COVERART["review_dir"], ca_results)
            if report:
                logging.info("Cover art review: %s", report)

    # Summary report
    elapsed = time.time() - started
    ok = sum(1 for r in results if r.ok)
    bad = sum(1 for r in results if not r.ok)

    logging.info("========== SUMMARY ==========")
    logging.info("Elapsed: %s", str(_dt.timedelta(seconds=int(elapsed))))
    logging.info("Total tasks: %d | OK: %d | Failed: %d", len(results), ok, bad)

    if bad:
        logging.info("Failures:")
        for r in results:
            if not r.ok:
                srcs = ", ".join(p.name for p in r.source_items) if r.source_items else "(none)"
                logging.info("- %s | %s | %s", r.kind, srcs, r.reason)

    not_renamed = [r for r in results if r.ok and r.details.get("rename_failed")]
    if not_renamed:
        logging.warning("Processed but NOT renamed: %d file(s) — they keep their release names.",
                        len(not_renamed))
        for r in not_renamed:
            srcs = ", ".join(p.name for p in r.source_items) if r.source_items else "(none)"
            logging.warning("- %s | %s", srcs, r.details["rename_failed"])

    named_locally = [r for r in results if r.ok and r.details.get("local_named")]
    if named_locally:
        logging.info("%s from the file alone (LOCAL): %d file(s) — no database knew them, so "
                     "no id, poster or description is added.%s",
                     "Would be named" if args.dry_run else "Named", len(named_locally),
                     "" if args.dry_run else f" Listed in {LOCAL_NAMED_CSV.name}.")

    print_results_table("Run results", results)

    # Printed after the table, because the table is the last thing most people look at.
    report_pending_identity()
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
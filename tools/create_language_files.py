#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# create_language_files.py

"""
create_language_files.py

Incremental translation script for PFEMAME.

Uses Python's built-in ast module to extract translatable strings from source,
polib for all .po/.pot/.mo handling, and Google Translate for translation.

Only translates NEW or CHANGED strings — existing translations are cached
from the previous .po file, so typical runs complete in seconds rather than hours.

Strings are sent to Google in batches - one string per line, up to MAX_BATCH_CHARS per request - so a few
hundred new strings need only a handful of requests per language.  (deep-translator's one-request-per-string
approach used Google's translate.google.com/m page, which now answers with a CAPTCHA / HTTP 429.)

Format strings ({}, %s, etc.) are protected with safe placeholder tokens before
being sent to Google Translate, then restored afterward.  Each line of a multi-line string is translated
separately (Google drops or merges parts of long multi-line texts), keeping its indentation.

No external tools required (no pygettext.py, no msgfmt.py, no Tools/i18n).

Requirements:
    pip install polib requests

Compatibility: Python 3.10+
"""

import ast
import os
import sys
import time
import re
from pathlib import Path
from datetime import datetime

try:
    import polib
except ImportError:
    print('ERROR: polib is not installed. Please run: pip install polib')
    sys.exit(1)

try:
    import requests
except ImportError:
    print('ERROR: requests is not installed. Please run: pip install requests')
    sys.exit(1)


# === Configuration ===
LANGUAGES = ['fr', 'es', 'de', 'ja', 'zh-CN', 'ru']
FORCE_RETRANSLATE = False       # Set True to ignore cache and retranslate everything
LIMIT_TRANSLATION_SIZE = False  # Limits translation to TRANSLATION_SIZE entries for testing
TRANSLATION_SIZE = 300
SOURCE_LANGUAGE = 'en'          # Fixed rather than 'auto' - short strings like 'OK' or ROM names get misdetected
MAX_BATCH_CHARS = 4500          # Characters per request (Google rejects a single text much over 5000)
REQUEST_INTERVAL = 1.0          # Seconds between Google Translate requests
MAX_RETRIES = 4                 # Attempts per batch before giving up on the language
RETRY_DELAY = 30                # Seconds; doubled on each retry (Google's throttling lasts minutes, not seconds)
REQUEST_TIMEOUT = 30            # Seconds to wait for a response
DELIMITER = '-' * 110

GOOGLE_URL = 'https://translate.googleapis.com/translate_a/single'

# Placeholder tokens used to protect format strings during translation.
# Chosen to be unlikely to appear in real text and unlikely to be mangled by Google.
PH_PREFIX = 'XFMT'
PH_SUFFIX = 'X'


# ==============================================================================
# Path helpers
# ==============================================================================


def get_python_files(source_dir: Path) -> list:
    """Return a list of .py files in the source directory."""
    return [f for f in os.listdir(source_dir) if f.endswith('.py')]


# ==============================================================================
# AST-based string extraction (replaces pygettext.py + merge)
# ==============================================================================

def _extract_strings_from_file(filepath: Path) -> list[tuple[str, int]]:
    """Parse a single .py file and return all _("...") strings with line numbers.

    Walks the AST looking for Call nodes where the function is named '_'.
    Only extracts calls with a single string-literal argument.
    """
    try:
        source = filepath.read_text(encoding='utf-8')
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError) as e:
        print(f'  WARNING: Could not parse {filepath.name}: {e}')
        return []

    results = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        # Match calls to _() - and N_(), which marks a string for translation where it is defined but is translated
        # later where it is displayed (gettext's 'noop' convention).  Attribute calls (x._()) won't match.
        func = node.func
        if isinstance(func, ast.Name) and func.id in ('_', 'N_'):
            if len(node.args) == 1 and isinstance(node.args[0], ast.Constant):
                value = node.args[0].value
                if isinstance(value, str) and value:
                    results.append((value, node.lineno))

    return results


def extract_catalog(python_files: list, source_dir: Path) -> polib.POFile:
    """Extract translatable strings from all .py files into a deduplicated catalog.

    Uses Python's ast module — no external tools required.
    Saves a base.pot reference file to disk.
    """
    print(DELIMITER)
    print('Extracting translatable strings from Python source')
    print(DELIMITER)

    locales_dir = source_dir / 'locales'
    locales_dir.mkdir(exist_ok=True)

    catalog = polib.POFile()
    catalog.metadata = {
        'Project-Id-Version': 'PFEMAME',
        'MIME-Version': '1.0',
        'Content-Type': 'text/plain; charset=utf-8',
        'Content-Transfer-Encoding': '8bit',
        'Generated-By': 'create_language_files.py (ast)',
    }

    seen = set()  # for deduplication across files

    for py_file in python_files:
        filepath = source_dir / py_file
        strings = _extract_strings_from_file(filepath)

        if strings:
            print(f'  {py_file}: {len(strings)} strings found')

        for msgid, lineno in strings:
            if msgid in seen:
                # Add occurrence to existing entry instead of duplicating
                existing = catalog.find(msgid)
                if existing:
                    existing.occurrences.append((py_file, str(lineno)))
                continue
            seen.add(msgid)
            catalog.append(polib.POEntry(
                msgid=msgid,
                msgstr='',
                occurrences=[(py_file, str(lineno))],
            ))

    if not seen:
        print('ERROR: No translatable strings found in any source file')
        sys.exit(1)

    # Apply test size limit if configured
    if LIMIT_TRANSLATION_SIZE:
        entries = [e for e in catalog if e.msgid]
        if len(entries) > TRANSLATION_SIZE:
            for entry in entries[TRANSLATION_SIZE:]:
                catalog.remove(entry)

    # Save base.pot for reference/debugging
    pot_path = locales_dir / 'base.pot'
    catalog.save(str(pot_path))

    print(f'  Catalog: {len(seen)} unique translatable strings')

    return catalog


# ==============================================================================
# Format-string protection
# ==============================================================================

# Regex matching Python format placeholders and escape sequences that must
# survive translation unchanged.
_FORMAT_PATTERN = re.compile(
    r'(?:'
    r'\{[^{}]*\}'                                                       # {}, {0}, {name}, {n:<10}
    r'|%\([^)]+\)[#0\- +]?[0-9*]*\.?[0-9*]*[hlL]?[diouxXeEfFgGcrsab]' # %(name)s
    r'|%[#0\- +]?[0-9*]*\.?[0-9*]*[hlL]?[diouxXeEfFgGcrsab%]'         # %s, %d, %%
    r'|\\[ntr\\]'                                                       # \n, \t, \r, \\
    r')'
)


def protect_format_strings(text: str) -> tuple[str, list[str]]:
    """Replace format placeholders with safe tokens before translation.

    Returns:
        (protected_text, list_of_originals) — originals are in insertion order
        so they can be restored by index.
    """
    originals = []
    counter = [0]

    def _replace(match):
        original = match.group(0)
        token = f'{PH_PREFIX}{counter[0]}{PH_SUFFIX}'
        originals.append(original)
        counter[0] += 1
        return token

    protected = _FORMAT_PATTERN.sub(_replace, text)
    return protected, originals


def restore_format_strings(text: str, originals: list[str]) -> str:
    """Restore original format placeholders after translation.

    Handles cases where Google Translate may have added spaces around the
    token or changed its case.
    """
    for i, original in enumerate(originals):
        token = f'{PH_PREFIX}{i}{PH_SUFFIX}'

        # Try exact replacement first (fast path)
        if token in text:
            text = text.replace(token, original, 1)
        else:
            # Flexible match: optional surrounding spaces, case-insensitive
            pattern = re.compile(
                r'\s*' + re.escape(PH_PREFIX) + str(i) + re.escape(PH_SUFFIX) + r'\s*',
                re.IGNORECASE,
            )
            # A function, so a backslash in the original (e.g. a literal \n) isn't read as a regex escape
            text = pattern.sub(lambda _match: original, text, count=1)

    return text


# ==============================================================================
# Translation checks
# ==============================================================================

def _placeholder_fields(text: str) -> list[str]:
    """Return the format placeholders in text, sorted, with {} fields numbered as Python numbers them.

    So 'Downloading {} from {}' and a translation that swaps them round, '{1} ... {0}', give the same result.
    """
    fields = []
    auto_number = 0
    for match in _FORMAT_PATTERN.finditer(text):
        field = match.group(0)
        if field.startswith('{'):
            inner = field[1:-1]
            name = re.split(r'[:!]', inner, maxsplit=1)[0]
            if name == '':
                field = '{' + str(auto_number) + inner + '}'
                auto_number += 1
        fields.append(field)
    return sorted(fields)


def translation_problem(msgid: str, msgstr: str) -> str | None:
    """Return why msgstr can't be used as the translation of msgid, or None if it's fine.

    Checks that every placeholder survived (a missing or mangled one loses information or crashes .format()),
    that the line breaks match, and that no protection token was left behind.
    """
    if _placeholder_fields(msgid) != _placeholder_fields(msgstr):
        return 'placeholders differ'
    if msgid.count('\n') != msgstr.count('\n'):
        return 'line breaks differ'
    if PH_PREFIX.lower() in msgstr.lower() and PH_PREFIX.lower() not in msgid.lower():
        return 'placeholder token left in'
    return None


def _report_problems(heading: str, problems: list[tuple[str, str]]):
    """Print a heading and one line per (msgid, problem)."""
    print(f'  {heading}: {len(problems)}')
    for msgid, problem in problems:
        print(f'    {problem}: {msgid[:70]!r}')


# ==============================================================================
# Google Translate interface
# ==============================================================================

class GoogleUnavailableError(Exception):
    """Google kept refusing or failing requests after every retry (throttled, blocked or offline)."""


def _describe_error(error: Exception) -> str:
    """Return a short, readable description of a failed request."""
    response = getattr(error, 'response', None)
    if response is not None and response.status_code == 429:
        return 'Google is throttling requests (HTTP 429)'
    return f'{type(error).__name__}: {error}'


def _request_lines(lines: list[str], dest: str) -> list[str]:
    """Translate lines of text in one request and return the translated lines.

    The result can have a different number of lines than the input if Google merges or splits lines.
    """
    response = requests.post(
        GOOGLE_URL,
        params={'client': 'gtx', 'sl': SOURCE_LANGUAGE, 'tl': dest, 'dt': 't'},
        data={'q': '\n'.join(lines)},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    # The first element is a list of [translation, original, ...] segments - one per sentence, with the line
    # breaks kept inside them - so joining the translations and splitting on line breaks gives the lines back.
    segments = response.json()[0] or []
    text = ''.join(segment[0] for segment in segments if segment and segment[0])
    return [line.strip() for line in text.split('\n')]


def _request_with_retries(lines: list[str], dest: str) -> list[str]:
    """Run _request_lines(), retrying with a doubling delay.  Raises GoogleUnavailableError if every attempt fails."""
    for attempt in range(MAX_RETRIES):
        try:
            translated = _request_lines(lines, dest)
            time.sleep(REQUEST_INTERVAL)
            return translated
        except (requests.RequestException, ValueError, IndexError, TypeError) as e:
            if attempt == MAX_RETRIES - 1:
                raise GoogleUnavailableError(f'{_describe_error(e)} - gave up after {MAX_RETRIES} attempts') from e
            wait = RETRY_DELAY * 2 ** attempt
            print(f'    Retry {attempt + 1}/{MAX_RETRIES - 1}: {_describe_error(e)}  (waiting {wait}s)')
            time.sleep(wait)


def _translate_batch(lines: list[str], dest: str) -> list[str]:
    """Translate a batch of single-line strings, one result per string.

    If Google returns a different number of lines (so they can't be matched up), the batch is halved and each
    half translated separately, down to single strings if necessary.
    """
    translated = _request_with_retries(lines, dest)
    if len(translated) == len(lines):
        return translated
    if len(lines) == 1:
        return [' '.join(translated)]
    print(f'    Got {len(translated)} lines back for {len(lines)} strings - splitting the batch')
    middle = len(lines) // 2
    return _translate_batch(lines[:middle], dest) + _translate_batch(lines[middle:], dest)


def batch_translate(strings: list[str], dest: str) -> tuple[list[str], bool]:
    """Translate a list of single-line strings via Google Translate, several strings per request.

    Returns (translations, completed).  translations is the same length as strings; if Google stops responding,
    completed is False and the strings not yet translated are left empty (so the next run picks them up again).
    """
    results = list(strings)  # blank strings stay as they are - a blank line would be lost from a batch

    # Group the non-blank strings into batches of up to MAX_BATCH_CHARS characters (+1 for each line break)
    batches = []
    current, size = [], 0
    for index, text in enumerate(strings):
        if not text.strip():
            continue
        if current and size + len(text) + 1 > MAX_BATCH_CHARS:
            batches.append(current)
            current, size = [], 0
        current.append(index)
        size += len(text) + 1
    if current:
        batches.append(current)

    for number, batch in enumerate(batches, 1):
        print(f'    Batch {number}/{len(batches)}  ({len(batch)} strings)')
        try:
            translated = _translate_batch([strings[index] for index in batch], dest)
        except GoogleUnavailableError as e:
            print(f'    FAILED: {e}')
            for remaining in batches[number - 1:]:
                for index in remaining:
                    results[index] = ''
            return results, False
        for index, text in zip(batch, translated):
            results[index] = text

    return results, True


def translate_strings(msgids: list[str], dest: str) -> tuple[list[str], bool]:
    """Translate msgids, keeping their format placeholders, line breaks and indentation.

    Each line of a multi-line string is sent as a separate string - Google drops or merges parts of long
    multi-line texts.  Lines with nothing to translate (blank, or only placeholders and symbols) are kept as they
    are.  Returns (translations, completed) like batch_translate(); a string that couldn't be fully translated
    is returned empty, so the next run picks it up again.
    """
    to_send = []       # protected lines to send to Google
    layouts = []       # per msgid: a list of lines, each either a kept string or (to_send index, indent, originals)
    for msgid in msgids:
        layout = []
        for line in msgid.split('\n'):
            text = line.strip()
            if not re.search(r'[^\W\d_]', _FORMAT_PATTERN.sub('', text)):  # no letters to translate
                layout.append(line)
                continue
            protected, originals = protect_format_strings(text)
            layout.append((len(to_send), line[:len(line) - len(line.lstrip())], originals))
            to_send.append(protected)
        layouts.append(layout)

    translated, completed = batch_translate(to_send, dest)

    results = []
    for layout in layouts:
        lines = []
        for item in layout:
            if isinstance(item, str):
                lines.append(item)
                continue
            index, indent, originals = item
            if not translated[index]:
                lines = None
                break
            lines.append(indent + restore_format_strings(translated[index], originals))
        results.append('\n'.join(lines) if lines is not None else '')

    return results, completed


# ==============================================================================
# Per-language translation with caching
# ==============================================================================

def translate_language(language: str, source_dir: Path, pot_catalog: polib.POFile, use_google: bool = True) -> bool:
    """Translate one language incrementally and compile to .mo.

    1. Loads the existing .po file (if any) to build a {msgid: msgstr} cache.
    2. Compares against the current .pot catalog to find new/changed msgids.
    3. Only sends new strings to Google Translate (skipped if use_google is False).
    4. Writes the complete .po file and compiles to .mo via polib.

    Returns False if Google stopped responding, so the remaining languages don't wait through the same retries.
    """
    print(DELIMITER)
    print(f'Language: {language}')
    print(DELIMITER)

    lc_dir = source_dir / 'locales' / language / 'LC_MESSAGES'
    lc_dir.mkdir(parents=True, exist_ok=True)

    po_path = lc_dir / 'base.po'
    mo_path = lc_dir / 'base.mo'

    # --- Load existing translations as cache ---
    cache = {}
    rejected = []  # (msgid, problem) for cached translations that fail the checks - they are translated again
    if po_path.exists() and not FORCE_RETRANSLATE:
        try:
            old_po = polib.pofile(str(po_path))
            for entry in old_po:
                if entry.msgid and entry.msgstr:
                    problem = translation_problem(entry.msgid, entry.msgstr)
                    if problem:
                        rejected.append((entry.msgid, problem))
                    else:
                        cache[entry.msgid] = entry.msgstr
            print(f'  Loaded {len(cache)} cached translations from previous .po')
        except Exception as e:
            print(f'  WARNING: Could not read existing .po file: {e}')
    if rejected:
        _report_problems('Cached translations that failed the checks (translating again)', rejected)

    # --- Determine what needs translating ---
    pot_entries = [e for e in pot_catalog if e.msgid]  # skip empty-msgid header entry
    to_translate = []  # list of msgid strings needing translation

    for entry in pot_entries:
        if entry.msgid not in cache:
            to_translate.append(entry.msgid)

    cached_count = len(pot_entries) - len(to_translate)
    # Count strings that existed in cache but are no longer in the .pot (i.e. removed from source)
    removed_count = len(cache) - cached_count

    print(f'  Total strings in catalog: {len(pot_entries)}')
    print(f'  Cached (reused):          {cached_count}')
    print(f'  New (to translate):       {len(to_translate)}')
    if removed_count > 0:
        print(f'  Removed (no longer used): {removed_count}')

    # --- Translate new strings ---
    new_translations = {}
    google_ok = use_google

    if to_translate and not use_google:
        print('  Skipped - Google is unavailable; new strings are left untranslated until the next run')
    elif to_translate:
        start_time = time.time()
        translated, google_ok = translate_strings(to_translate, dest=language)
        elapsed = time.time() - start_time
        if google_ok:
            print(f'  Translation completed in {elapsed:.1f}s')
        else:
            done = sum(1 for text in translated if text)
            print(f'  Translation stopped after {elapsed:.1f}s - {done} of {len(translated)} strings translated, '
                  f'the rest are left untranslated until the next run')

        # A translation that fails the checks is never saved - the string stays untranslated (the English is shown)
        # and is tried again on the next run
        failed = []
        for msgid, msgstr in zip(to_translate, translated):
            problem = translation_problem(msgid, msgstr) if msgstr else None
            if problem:
                failed.append((msgid, problem))
            else:
                new_translations[msgid] = msgstr
        if failed:
            _report_problems('New translations that failed the checks (left in English)', failed)
    else:
        print('  Nothing new to translate — all strings already cached')

    # --- Build output .po file ---
    now = datetime.now()
    formatted_dt = now.strftime('%Y-%m-%d %H:%M%z')

    output_po = polib.POFile()
    output_po.metadata = {
        'Project-Id-Version': 'PFEMAME',
        'POT-Creation-Date': formatted_dt,
        'PO-Revision-Date': formatted_dt,
        'Last-Translator': 'GFINCH <pfemame@gmail.com>',
        'Language-Team': 'N/A',
        'Language': language,
        'MIME-Version': '1.0',
        'Content-Type': 'text/plain; charset=utf-8',
        'Content-Transfer-Encoding': '8bit',
        'Generated-By': 'create_language_files.py',
    }

    for entry in pot_entries:
        msgstr = cache.get(entry.msgid) or new_translations.get(entry.msgid, '')
        output_po.append(polib.POEntry(
            msgid=entry.msgid,
            msgstr=msgstr,
            occurrences=entry.occurrences,
            comment=entry.comment,
        ))

    # Save .po file
    output_po.save(str(po_path))
    print(f'  Saved: {po_path}')

    # Compile .mo file directly via polib (no msgfmt.py / .bat needed)
    output_po.save_as_mofile(str(mo_path))
    print(f'  Compiled: {mo_path}')

    return google_ok


# ==============================================================================
# Main
# ==============================================================================

def main():
    source_dir = Path.cwd().parent
    python_files = get_python_files(source_dir)

    print(f'Source directory: {source_dir}')
    print(f'Python files found: {len(python_files)}')
    print(f'Languages: {", ".join(LANGUAGES)}')
    print()

    # Step 1: Extract translatable strings from source via AST
    pot_catalog = extract_catalog(python_files, source_dir)

    # Step 2: Translate each language incrementally
    total_start = time.time()
    google_ok = True
    for language in LANGUAGES:
        # Once Google stops responding, the rest of the languages are still written (so they match the
        # catalog) but nothing more is sent to Google
        google_ok = translate_language(language, source_dir, pot_catalog, use_google=google_ok)

    total_elapsed = time.time() - total_start

    print()
    print(DELIMITER)
    print(f'All {len(LANGUAGES)} languages processed in {total_elapsed:.1f}s')
    if not google_ok:
        print('WARNING: Google Translate stopped responding - run again later to translate the missing strings')
    print(DELIMITER)


if __name__ == '__main__':
    main()

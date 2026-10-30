# pfeMAME

pfeMAME is a front end for MAME (and other emulators), written in Python with wxPython. It runs on Windows and Linux.

* Browse and launch your ROMs in a list or tile view, with artwork, videos, ratings, favourites and software lists.
* Configure MAME's slots, video, sound, input and performance options from one place.
* Available in English, German, Spanish, French, Japanese, Russian and Simplified Chinese.

The full user guide is `pfeMAME_Manual.pdf`, and the change history is in `changelog.docx`.

## Downloads

Ready-to-run Windows and Linux builds are on the [Releases](../../releases) page.

## Running from source

```
pip install -r requirements.txt
python pfemame.py
```

On Linux, install the wxPython wheel for your distribution (see the note in `requirements.txt`). You also need MAME itself, which is not included.

Run the tests (no MAME or network needed) with `python -m pytest tests`. Build notes are in `tools/` (see `tools/LINUX_BUILD.md` for Linux).

## Licence

pfeMAME is free for non-commercial use; changed versions must also share their source under the same licence. See [`license/license_en.txt`](license/license_en.txt) (translations are alongside it). The ready-to-run builds bundle other open-source software under its own licences.

MAME is a registered trademark of Gregory Ember. pfeMAME is not made, supported or endorsed by the MAME team.

# Test fonts

Fonts used to render synthetic ground-truth documents for the OCR quality gate
(`tests/quality.py`). Pillow's built-in font has no glyphs for ä, ö, ü, ß, so German
text would otherwise be rendered as boxes.

| File | Source | License |
| --- | --- | --- |
| `DejaVuSans.ttf`, `DejaVuSerif.ttf` | DejaVu Fonts 2.37, `dejavu-fonts-ttf-2.37.tar.bz2` from https://github.com/dejavu-fonts/dejavu-fonts/releases/tag/version_2_37 (archive sha256 `fa9ca4d13871dd122f61258a80d01751d603b4d3ee14095d65453b4e846e17d7`) | Bitstream Vera license + public domain DejaVu changes, see `LICENSE-DejaVu.txt` |

Retrieved 2026-11-10. Test-only; not shipped with the application.

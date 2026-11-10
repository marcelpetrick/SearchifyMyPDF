# Real-life scanned PDF fixtures

## ndl583_typewritten_scan.pdf

- Source URL: https://commons.wikimedia.org/wiki/File:NDL12920362_Pros._Doc._No._583-_Typewritten_letter_from_TOJO,_Hideki_to_GODO,_Takuo.pdf
- Original file: https://upload.wikimedia.org/wikipedia/commons/f/fb/NDL12920362_Pros._Doc._No._583-_Typewritten_letter_from_TOJO%2C_Hideki_to_GODO%2C_Takuo.pdf
- Original filename on Commons: NDL12920362 Pros. Doc. No. 583- Typewritten letter from TOJO, Hideki to GODO, Takuo.pdf
- Author / provenance: International Prosecution Section (IPS), 1946 (US National Archives RG 331, SCAP records), digitised by the National Diet Library, Japan
- License: Public domain (as marked on the Wikimedia Commons file page, Copyrighted = False). https://commons.wikimedia.org/wiki/Commons:Licensing
- Date retrieved: 2026-11-09
- sha256: 1d80481d39b13147caf7da0fa05d93738b0409aabb399e25edc659167b2c8264
- Pages: 2 (image-only, no text layer; pypdfium2 text length 0 on both pages)
- Language: English, typewritten, photographic microfilm-style scan with noise and artefacts
- Words OCR should find on page 1: INTERNATIONAL, PROSECUTION, DOCUMENTARY, Typewritten, Mobilization, Aggressive
- Note: the file carries an **owner password** (AES-256, empty user password, text
  extraction and modification forbidden). The application therefore rejects it as
  protected (VISION §5: never bypass protection); `tests/integration/test_real_corpus.py`
  checks that. Engine-level tests may still OCR it directly.

## lbj1964_maddox_memo_typewritten.pdf

- Source URL: https://commons.wikimedia.org/wiki/File:Memorandum_Notifying_President_Johnson_of_Attack_on_the_U.S.S._Maddox_-_DPLA_-_fd57bf521aad09e3a45e5ee9468134e4.pdf
- Author / provenance: Office of the Special Assistant to the President for National Security Affairs, 2 August 1964 (LBJ Presidential Library via DPLA)
- License: Public domain (work of the US federal government)
- Date retrieved: 2026-11-10 · unchanged original
- sha256: eb8a0a3a31c3da534025c0dea347cdb00354d715d1f77565f01b2715c2a9f041
- Pages: 1, image-only. Typewriter on aged paper, punch holes, handwritten mark.

## lbj1967_apollo1_memo_typed_and_handwritten.pdf

- Source URL: https://commons.wikimedia.org/wiki/File:Memorandum_from_Jim_Jones_to_President_Johnson_about_the_Fire_on_Apollo_1_-_DPLA_-_66e171fa968a328938ba41954cc63f33.pdf
- Author / provenance: Office of the President (Jim Jones), 27 January 1967 (LBJ Presidential Library via DPLA)
- License: Public domain (work of the US federal government)
- Date retrieved: 2026-11-10 · unchanged original
- sha256: 077774ef116d1a4dec6cc890ffe06ce9e1e1ace10ffc0b0856184948894db6db
- Pages: 1, image-only. Typewritten text plus a handwritten note (handwriting is not expected to be recognised).

## lloyds1929_survey_certificate_form.pdf

- Source URL: https://commons.wikimedia.org/wiki/File:Certificate_of_Survey_for_Jumna,_9th_April_1929.pdf
- Author: A W Paterson; Lloyd's Register Foundation, Heritage & Education Centre
  (https://hec.lrfoundation.org.uk/archive-library/ships/jumna-1929/search/everywhere:jumna/page/10)
- License: **CC BY-SA 4.0** — https://creativecommons.org/licenses/by-sa/4.0/ (attribution above; unchanged original)
- Date retrieved: 2026-11-10
- sha256: a2436bd7523e5a79871ff75e9f326ac2c9ebdd5599e585508358149b7c466700
- Pages: 1, image-only. Printed form with blackletter heading, typewriter fill-ins, strike-throughs, signature, watermark logo.

## bgbl1950_nr5_with_text_layer_de.pdf

- Source URL: https://commons.wikimedia.org/wiki/File:Bundesgesetzblatt_Nr._5,_1950.pdf (via https://offenegesetze.de/daten)
- Author: Deutscher Bundestag / Bundesgesetzblatt, 31 January 1950
- License: Public domain (official work, § 5 UrhG)
- Date retrieved: 2026-11-10
- Derivation: first 2 of 14 pages kept (pikepdf); the scan already carries an OCR text layer.
- sha256: 971a8b01698ae816acf86a06b141c033f0b5c41a1a3c01c7d692a68af3225efc
- Language: German, two-column print. Used for "existing text" policies (keep / replace).

## bgbl1950_nr5_page1_image_only_de.pdf

- Derived from the file above: page 1 rendered at 200 dpi greyscale (pypdfium2) and saved
  as an image-only PDF (Pillow), i.e. a real German scan without any text layer.
- License: Public domain (as above)
- sha256: fe57f8f0f51b0cad3962c4e80d1821a9235f771b27706a36978b0674dfc35d36

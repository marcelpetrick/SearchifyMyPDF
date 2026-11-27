# Finding text in searchable PDFs with Windows Search (A19)

Searchify PDF embeds text in the copy. Whether Windows *finds* a body-only word also
depends on Windows indexing, which the app never changes automatically.

1. Settings → Privacy & security → Searching Windows → **Enhanced** or add the folder
   with your documents under *Customize search locations*.
2. Indexing Options → Advanced → **File Types** → select `pdf` and choose
   **Index Properties and File Contents**. If `pdf` shows no filter, install a PDF IFilter
   (e.g. from Adobe Acrobat Reader or another PDF filter provider).
3. Wait for indexing to finish (Indexing Options shows "Indexing complete").
4. Convert a PDF from the [test corpus](../tests/fixtures/real/SOURCES.md) or one of
   your own scans. Search for a word that appears only in the copy's body text.

Network/cloud-only files (OneDrive "online-only") are not indexed until downloaded.
**Status:** Windows preview builds are available. Manual Windows Search verification
is pending under M3.

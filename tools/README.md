# Greyhound terrain capture helpers

These are the only Python helpers shipped with the Greyhound fork:

- `capture/organize_export.py` files native source artifacts under `capture/`.
- `capture/finalize_research_capture.py` validates and hashes the capture.
- `core/layout.py` defines the on-disk source boundary.

No reconstruction, compositing, BO3 generation, or reconstruction preset is
included. Those stages live in the separate terrain reconstruction repository.

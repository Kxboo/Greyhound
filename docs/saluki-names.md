# Saluki name databases

Open **Settings → In-game asset settings → Saluki names**.

- **Download / update** fetches the current `hash_pkg.zip` release directly from
  [echo000/cod-name-db](https://github.com/echo000/cod-name-db), validates it, and
  enables daily update checks when loading assets. No manual download is needed.
- **Choose folder...** accepts an extracted cod-name-db repository, its `csv`
  directory, or a directory containing Saluki `.cdb` databases. This selects a
  local database and turns off automatic downloads.
- **GitHub** opens the source/download page.
- **Disable** returns to the existing Greyhound name databases.

The asset list reloads when Settings closes, preserving and rerunning the current
search. Resolved names are used by the normal export and placement pipelines,
including model, material, image and animation names. Existing decoded entries
always take priority. Database entries fill missing names and hash placeholders;
empty names are ignored. An absent hash still uses Greyhound's original fallback.
Older placement and spline JSONs containing `xmodel_<hash>` references still map
to the same runtime model after its name is resolved.

The integration covers BO4/CW asset names, CW strings, MWII/MWIII hashed asset and
bone names, Vanguard hashed sounds/strings, BO2 IPAK names, and BO2/BO3/BO4 SAB names.
Unresolved material semantics and CW techset names also consult the database.
Files with the same stem prefer CDB over CSV. CSVs follow the upstream converter's
policy of ignoring invalid hash records (including merge-marker lines found in
some source snapshots). Hashes retain the mask used by their game/lookup.

Downloads are stored under `%LOCALAPPDATA%\Greyhound\name-db`, shared by Greyhound
builds. Only a completely extracted and validated version becomes active. Failed
downloads retain the previous selection. Turning off automatic updates retains
the current database for offline use. A manual update checks GitHub immediately;
automatic checks are limited to once per day after a successful check. No local
CSV folder or bundled WNI is rewritten.

CLI equivalents (transient settings):

```powershell
Greyhound-cli.exe assets list --type model --name-db-folder "C:\path\cod-name-db-main" --json
Greyhound-cli.exe assets list --type model --update-names --json
```

`--name-db-folder` and `--update-names` apply to normal `assets list` and `assets
export` selectors, and spline exports. They are mutually exclusive. Legacy
`--bo4-name-database` continues to select the base WNI provider; Saluki names
supplement that provider.

The CDB reader follows the upstream
[porter-utils PNDB layout](https://github.com/echo000/porter-lib/blob/master/crates/porter-utils/src/name_database.rs):
a 16-byte header, LZ4 block, null-terminated names, and little-endian 64-bit keys.
It validates lengths, decompression results, and the complete key/name table before
merging. Archive extraction permits recognized flat CDB filenames only and checks
ZIP integrity. The native parser tests include quoted CSV, full-width hashes,
preservation of known names, placeholders, empty names, and malformed CDB input.

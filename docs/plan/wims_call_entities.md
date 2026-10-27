# Call to entity

The checklist and the Country column ask one resolver which DXCC entity a
call is. When `cty.dat` is on this PC, that file is the list. The Country
column uses the builtin prefix list only when the file is missing, and the
DXCC checklist line stays off in that case. `log/pfx.py` is not this list.

## What the country file can say

The file is the AD1C layout (https://www.country-files.com/cty-dat-format/).
WIMS reads it and does not write it.

| Form | Meaning | WIMS |
| --- | --- | --- |
| Primary prefix and aliases | Longest prefix wins (`KH6` before `K`) | Used |
| `=CALL` | This exact call, not a prefix | Used. Wins over every rule below |
| `prefix(cq)` | CQ zone for that prefix | Used |
| `prefix[itu]` | ITU zone for that prefix | Used |
| `prefix{AF}` | Continent for that prefix | Used |
| `<lat/lon>` and `~offset~` | Beam and clock. Not the entity | Ignored |
| `*` on the primary (`*IT9`, `*4U1V`) | CQ / WAE only. Not a DXCC entity | Zone only. DXCC uses the parent (`IT9` is Italy, `4U1VIC` is Austria) |
| The same call twice | First one in the file wins | Used |
| A slash in a prefix (`3D2/c`, `VP8/g`, `3Y/b`) | That operating form | Used |
| A slash in an exact call (`=K9CS/KH8S`, `=KH6EE/7`, `=JG8NQJ/JD1`) | That station, including a portable zone | Used |

A prefix the file lists is not re-decided in code. `CE0X` is San Felix,
`CE0Y` is Easter Island, `CE0Z` and `CE0I` are Juan Fernandez, `VP2E` /
`VP2M` / `VP2V` are Anguilla, Montserrat, and the British Virgin Islands,
`KH6` is Hawaii, `KL` is Alaska, `KP4` is Puerto Rico, `KP2` is the US
Virgin Islands. An exact call can move one station (`=KL7NW` is filed as
the United States).

## Rules a prefix cannot say

Applied only when no exact call matched. If the file has no entry for that
shape, the rule does not invent one.

| Rule | Example | Entity |
| --- | --- | --- |
| KG4 and three letters | `KG4LDK` | United States, including US zone rules |
| KG4 and one or two letters | `KG4AA`, `W1AW/KG4` | Guantanamo Bay |
| KC4AAA–KC4AAF, KC4US… | `KC4AAB`, `KC4USV` | Antarctica. Any other KC4 call is the United States. An exact call still wins (`=KC4BB` is the United States) |
| `3Y0` | `3Y0J` | Peter I (`3Y/P` in the file). `=3Y0X` is the same entity |
| `3Y/B` | `3Y/B` | Bouvet. A lone `/B` on any other call is a beacon and does not move the entity |
| `3Y/P` | `3Y/P` | Peter I |
| VP8 plus `/G` `/H` `/O` `/S` | `VP8LP/G` | South Georgia, South Shetland, South Orkney, South Sandwich. Other VP8 calls are the Falklands |
| An SV call plus `/A`, except SV5 and SV9 | `SV2ASP/A`, `SV2RSG/A` | Mount Athos |
| `CE0/` plus X, Y, Z, or I | `CE0/X` | Same entity as `CE0X`, `CE0Y`, `CE0Z`, `CE0I` |
| Trailing `/P` `/M` `/MM` `/AM` `/QRP` `/R` `/A` `/B` `/LH`, or a single digit | `WD9EXD/R`, `W1AW/7`, `W1AW/MM` | The home entity. `/R` is a rover. A leading `R/` is Russia |
| Location prefix before or after the slash | `W1/VE3XX`, `VE3XX/W1`, `W1AW/KH6`, `KH6/W1AW` | The place of operation. A KH, KL, or KP call is that entity. The same letters after a slash are the place, not a portable tag |

`FT/W`, `FK/C`, `JD/M`, `HK0/M`, `KH8/S`, and the other slash prefixes are
handled because they are written in the file, not by an extra rule. A call
that only puts the island letter in a different place than the file shows
(`FR5ZQ/J` when the file says `FT/J`) is the limitation the file itself
documents. WIMS does not guess.

Russia outside those exact prefixes still follows the file. Call areas 0, 8,
and 9 are not all Asiatic: the file lists the exceptions (`R9X` is European
Russia). The builtin fallback still uses the coarse digit rule, and only
when `cty.dat` is missing.

## Zones

`(cq)` and `[itu]` on a prefix are that zone. United States, Canada,
Russia, Australia, and China, and Brazil for ITU, still take the zone from
the grid when the file does not give one number. The Country column shows
the DXCC name. Continent and CQ zone come from the same lookup, so a WAE
record can show Italy with the African Italy zone. The continent code is
the file's code. The current file tags Antarctica as SA.

## Audit

`tools/dev/audit_entities.py` runs every call in an ADIF log through this
resolver. It compares the result with `DXCC` and `COUNTRY` when the log has
them, and with N1MM's country column when an `.s3db` is passed. It does not
write the log.

# PiFinder rev4 Parts List

Working parts list for the rev4 (Landscape) PiFinder. This version of the PiFinder
is NOT intended as a DIY project and requires significant skill and experience to 
produce.  This list is provided as-is and no guarantee is provided. 

If you have questions, please reach out via the normal email or discord channels.


## Board files in this directory

Two of the line items below are boards produced from the gerbers here rather
than parts you order from a catalogue:

| File | Produces |
|---|---|
| `PiFinder4.zip` | The rev4 main board, ordered from JLCPCB as an assembled PCBA |
| `PiFinder4-top-plate.zip` | The rev4 keypad cover, ordered from JLCPCB as a bare PCB |
| `PiFinder4_jlc_bom.csv` | Component BOM for the PCBA assembly service |
| `PiFinder4-all_jlcpos.csv` | Pick-and-place positions for the PCBA assembly service |

The two CSVs describe the surface-mount parts that go onto the main board, so
they are not repeated in the tables below. The PCBA is a single line item here.
As with the v3 boards, the JLCPCB part numbers in the BOM can be cross-checked
or substituted using <https://jlcpcb.com/parts>.

## Electronics

| Qty | Item | Source | Notes |
|---|---|---|---|
| 1 | Raspberry Pi Compute Module 4 | TBD | CM4102000 — 2GB RAM, Lite, wireless. Lite because the board boots from its own microSD socket (J1). More RAM works if the SKU is easier to get |
| 1 | Camera module | TBD | imx296 or imx462 |
| 1 | M12 Lens (12mm or 16mm) | TBD | Set the Lens setting to match the focal length fitted, or the PiFinder will not solve |
| 1 | MicroSD card | TBD | Quality matters more than size — the software needs only a few GB |
| 1 | NHD-1.91-176176B | TBD | Newhaven Display 1.91" 176×176 display |
| 1 | Raspberry Pi heatsink kit | TBD | |
| 1 | Beitian BE-182 | TBD | GPS receiver |
| 1 | GPS cable (BE-182) | Shop-made | Current PCBA have 6 pin connector, BE-182 has 4 and currently requires a custom cable.  Future PCBA revisions will have the same 4 pin connector|
| 1 | 8000 mAh battery w JST 2.0 connector | TBD | |
| 1 | rev4 PCBA | JLCPCB, from `PiFinder4.zip` | Assembled board. See the BOM and pick-and-place CSVs in this directory |

## Other components

| Qty | Item | Source | Notes |
|---|---|---|---|
| 1 | Keypad cover (Landscape) | JLCPCB, from `PiFinder4-top-plate.zip` | A bare PCB, not a printed part |
| 1 | Rubber joystick cap | Adafruit | |

## Hardware

| Qty | Item | Source | Notes |
|---|---|---|---|
| 1 | M12 lock nut | TBD | Lens lock ring |
| 2 | M5 25 mm bolt | TBD | |
| 1 | M5 nut | TBD | |
| 2 | M5 nyloc nut | TBD | |
| 4 | M2.5 heat-set insert | TBD | |
| 7 | M2.5 8 mm screw | TBD | |
| 6 | M2.5 12 mm screw | TBD | |
| 4 | M2 10 mm self-tapping screw | TBD | |
| 1 | Spring | https://www.leespring.com/product/compression-spring-lc042d02m-music-wire | |

# L-probe Barcode Tools user guide

This Gradio app turns a gene/LbarID table into barcode assignments, robot input matrices, barcode-level pipetting explanations, verification reports, and Opentrons protocol files.

The app is organized as six workflows:

1. Assign codebook
2. Generate robot input
3. Explain barcode pipetting
4. Verify robot input
5. Generate Opentrons protocol
6. Run full workflow

Use **Run full workflow** when starting from a gene/LbarID list and you want all files at once. Use the individual workflows when you want to inspect or regenerate only one step.

## Hardware model used by the app

The app assumes this Opentrons OT-2 deck layout:

| Item | OT-2 deck slot |
| --- | --- |
| Destination tube rack | 1 |
| Detection oligo 1 source plate | 2 |
| Detection oligo 2 source plate | 3 |
| Detection oligo 3 source plate | 4 |
| Detection oligo 4 source plate | 5 |
| Detection oligo 5 source plate | 6 |
| Tip racks | 7 to 11 |

The source plates are 96-well plates. Each source plate contains one detection oligo channel. The app maps channels to source deck slots as:

| Channel | Source slot | App label |
| --- | --- | --- |
| 1 | 2 | Detection oligo 1 |
| 2 | 3 | Detection oligo 2 |
| 3 | 4 | Detection oligo 3 |
| 4 | 5 | Detection oligo 4 |
| 5 | 6 | Detection oligo 5 |

Cycles are deposited into a 24-position destination tube rack in row-major order:

| Cycle | Destination well |
| --- | --- |
| 1 | A1 |
| 2 | A2 |
| 3 | A3 |
| 4 | A4 |
| 5 | A5 |
| 6 | A6 |
| 7 | B1 |
| ... | ... |
| 24 | D6 |

The app supports up to 24 cycles because of the 24-position destination rack.

## Input file conventions

### Gene/LbarID CSV

Used by **Assign codebook** and **Run full workflow**.

Required columns:

| Column | Meaning |
| --- | --- |
| `Gene` | Gene or target name |
| `LbarID` | Integer barcode ID |

Example:

```csv
Gene;LbarID
GeneA;201
GeneB;202
GeneC;203
```

The app lets you choose the CSV separator: comma, semicolon, or tab. The default for gene/LbarID input is semicolon.

### Assigned-codes CSV

Used by **Generate robot input**, **Explain barcode pipetting**, and **Verify robot input**.

Required columns:

| Column | Meaning |
| --- | --- |
| `Gene` | Gene or target name |
| `LbarID` | Integer barcode ID |
| Cycle columns after `LbarID` | Detection oligo channel for each cycle |

The cycle columns are all columns after `LbarID`. Their names can be numbers or text, but their values must be channel numbers, typically 1 to 5.

Example:

```csv
Gene,LbarID,1,2,3,4,5
GeneA,201,1,3,5,2,4
GeneB,202,2,1,4,5,3
```

### Robot input CSV

Used by **Verify robot input** and optionally by **Generate Opentrons protocol**.

This is a numeric 0/1 matrix with no header row and no index column. Rows represent source wells across source plates; columns represent cycles.

For a 5-source-plate setup, the robot input usually has 480 rows:

```text
5 source plates x 96 wells = 480 rows
```

Each column is one cycle. A value of `1` means the robot should pipette from that source-row/well for that cycle. A value of `0` means no pipetting action.

## Workflow 1: Assign codebook

Use this workflow to create barcode assignments from a gene/LbarID table.

### Inputs

| Field | Description |
| --- | --- |
| Gene/LbarID CSV | Input table with `Gene` and `LbarID` columns |
| CSV separator | Separator used in the input file |
| Channels | Number of detection oligo channels, usually 5 |
| Add one extra cycle for Hamming-distance error correction | Adds an extra cycle to increase barcode separation |
| Output tag | Text inserted into output filenames |
| Random seed | Controls reproducible assignment |
| Subset input to an LbarID range before assigning codebook | Optional filter |
| Subset start LbarID | First LbarID to include, inclusive |
| Subset end LbarID | Last LbarID to include, inclusive |

### Outputs

| Output | File pattern | Use |
| --- | --- | --- |
| Assigned codes | `assigned_codes_<tag>.csv` | Main file for downstream workflows |
| Codebook | `codebook_<tag>.csv` | Barcode codebook used for assignment |
| Hamming-distance matrix | `hamming_distances_<tag>.csv` | Diagnostic matrix showing barcode distances |

### What to do next

Use the assigned-codes CSV as input for:

- **Generate robot input**
- **Explain barcode pipetting**
- **Verify robot input**

## Workflow 2: Generate robot input

Use this workflow to convert assigned codes into a robot input matrix.

### Inputs

| Field | Description |
| --- | --- |
| Assigned-codes CSV | Output from Assign codebook |
| CSV separator | Separator used in the assigned-codes file |
| Plate starting ID | First LbarID on the physical source plate block |
| Output tag | Text inserted into the robot input filename |

### Plate starting ID

The plate starting ID tells the app which physical block of source wells is being generated.

For example, if a source plate block starts at LbarID 201:

| LbarID | Source well |
| --- | --- |
| 201 | A1 |
| 202 | A2 |
| 203 | A3 |
| ... | ... |
| 296 | H12 |

If your assigned codes span more than one 96-ID block, generate one robot input per plate starting ID.

### Output

| Output | File pattern | Use |
| --- | --- | --- |
| Robot input CSV | `robot_input_plate_<starting_id>_<tag>.csv` | Input matrix for Opentrons protocol generation or verification |

The robot input CSV is written without headers and without an index, so it can be consumed by the protocol code.

## Workflow 3: Explain barcode pipetting

Use this workflow to inspect one barcode/LbarID and understand exactly what the robot should do.

### Inputs

| Field | Description |
| --- | --- |
| Assigned-codes CSV | Assigned codebook file |
| CSV separator | Separator used in the assigned-codes file |
| LbarID | Barcode ID to inspect |

### Outputs

| Output | File pattern | Use |
| --- | --- | --- |
| Interactive viewer | Shown in the app | Visual inspection of source and destination wells |
| Pipetting explanation CSV | `barcode_<LbarID>_pipetting_explanation.csv` | Downloadable table of the pipetting plan |

### How to read the viewer

The viewer shows:

- Source plates in deck slots 2 to 6.
- Destination tube rack in deck slot 1.
- The pipetting order for the selected barcode.

Hover over a cycle in the pipetting order panel to highlight:

- The source well used for that cycle.
- The destination well where that cycle is deposited.

When nothing is hovered, wells are shown as off.

## Workflow 4: Verify robot input

Use this workflow to check whether a robot input CSV matches an assigned-codes CSV.

### Inputs

| Field | Description |
| --- | --- |
| Assigned-codes CSV | Expected barcode assignment |
| Assigned-codes CSV separator | Separator used in the assigned-codes file |
| Robot input CSV | Robot matrix to verify |
| Robot input CSV separator | Separator used in the robot input file |
| Plate starting ID | First LbarID represented by this robot input |
| LbarID | Barcode to inspect in detail |

### Outputs

| Output | File pattern | Use |
| --- | --- | --- |
| Verification summary | Shown in the app | Overall pass/fail style summary |
| Selected barcode verification | `barcode_<LbarID>_robot_input_verification.csv` | Shows whether each expected pipetting step is present |
| Missing/extra instruction report | `robot_input_plate_<starting_id>_verification_issues.csv` | Lists missing and extra robot input instructions |

### What problems this catches

The verification workflow can detect:

- Expected pipetting instructions missing from the robot input.
- Extra pipetting instructions in the robot input.
- Header/index rows accidentally included in a robot input file.
- Robot input values other than 0 or 1.

## Workflow 5: Generate Opentrons protocol

Use this workflow to create a Python protocol file for the Opentrons App.

### Inputs

| Field | Description |
| --- | --- |
| Embed robot input in protocol file | If checked, the output `.py` contains the robot input data directly |
| Robot input CSV to embed | Required when embedding robot input |
| Robot input CSV separator | Separator used in the robot input file |
| Robot input filename in Opentrons user storage | Only needed when not embedding |
| Protocol name | Name shown in the Opentrons App |
| Output tag | Text inserted into the protocol filename |
| Transfer volume | Volume transferred per pipetting action, in microliters |
| Source plate labware | Opentrons labware API name for the source plates |
| Destination labware | Opentrons labware API name for the destination rack |
| Pipette | Opentrons pipette API name |
| Pipette mount | `left` or `right` |

### Outputs

| Output | File pattern | Use |
| --- | --- | --- |
| Opentrons protocol | `opentrons_cherry_picking_<tag>.py` | Import into the Opentrons App |

### Embedded vs non-embedded protocol

#### Embedded protocol

This is the recommended mode.

When **Embed robot input in protocol file** is checked, the generated `.py` contains the robot input matrix internally. You only need to import one file into the Opentrons App.

Use this when you want to avoid transferring a separate robot input CSV to the OT-2.

#### Non-embedded protocol

When embedding is unchecked, the generated `.py` expects to read a CSV from:

```text
/data/user_storage/<robot_input_filename>
```

In that mode, you must transfer both files to the robot environment:

- The protocol `.py`
- The robot input `.csv`

This is closer to the older workflow and is mainly useful for debugging or compatibility.

### Labware note

The generated protocol uses the source and destination labware names entered in the app. The Opentrons App must know those labware definitions.

If the Opentrons App reports an error like:

```text
Labware "idtedeep_96_wellplate_1000ul" not found
```

then the protocol file is syntactically fine, but the labware definition is missing from the Opentrons App. Import the custom labware JSON into the Opentrons App, or change the labware field to a built-in labware definition that matches your hardware.

## Workflow 6: Run full workflow

Use this workflow to run the complete pipeline from a gene/LbarID CSV.

### Inputs

| Field | Description |
| --- | --- |
| Gene/LbarID CSV | Input table with `Gene` and `LbarID` columns |
| CSV separator | Separator used in the input file |
| Channels / detection oligos | Number of detection oligo channels |
| Add one extra cycle for Hamming-distance error correction | Adds one extra barcode cycle |
| Output tag | Text inserted into output filenames |
| Random seed | Controls reproducible assignment |
| Plate starting ID | First LbarID on the source plate block |
| Subset input to an LbarID range before assigning codebook | Optional LbarID range filter |
| Subset start LbarID | First LbarID to include, inclusive |
| Subset end LbarID | Last LbarID to include, inclusive |
| Embed robot input in Opentrons protocol file | If checked, the protocol `.py` is self-contained |

### Outputs

The full workflow shows previews in the app and creates a ZIP file containing:

| File pattern | Description |
| --- | --- |
| `assigned_codes_<tag>.csv` | Assigned codes |
| `codebook_<tag>.csv` | Barcode codebook |
| `hamming_distances_<tag>.csv` | Hamming-distance matrix |
| `robot_input_plate_<starting_id>_<tag>.csv` | Robot input matrix |
| `opentrons_cherry_picking_plate_<starting_id>_<tag>.py` | Opentrons protocol |
| `robot_input_plate_<starting_id>_<tag>_verification_issues.csv` | Missing/extra robot input report |
| `workflow_report_<tag>.txt` | Text summary of the full run |

### Recommended use

1. Upload the gene/LbarID CSV.
2. Confirm the number of channels and whether Hamming-distance correction should be used.
3. Enter the plate starting ID.
4. Optionally enable LbarID subsetting.
5. Keep **Embed robot input in Opentrons protocol file** checked unless you specifically need the older two-file protocol behavior.
6. Run the workflow.
7. Download the ZIP.
8. Inspect the workflow report and verification issues.
9. Import the generated `.py` protocol into the Opentrons App.

## What to do with the output files

### Files for record keeping and checking

Keep these files with the experiment record:

- `assigned_codes_<tag>.csv`
- `codebook_<tag>.csv`
- `hamming_distances_<tag>.csv`
- `robot_input_plate_<starting_id>_<tag>.csv`
- `workflow_report_<tag>.txt`
- Any verification CSVs

These files make it possible to reconstruct what was assigned, what was expected, and what the robot was instructed to do.

### File to run on the Opentrons

Use the generated `.py` protocol file:

```text
opentrons_cherry_picking_plate_<starting_id>_<tag>.py
```

If the protocol is self-contained, import only this `.py` into the Opentrons App.

If the protocol is not self-contained, also place the robot input CSV at:

```text
/data/user_storage/<robot_input_filename>
```

### Before running on the robot

Before an actual run:

1. Confirm the physical deck layout matches the app assumptions.
2. Confirm the source plates are in slots 2 to 6.
3. Confirm the destination rack is in slot 1.
4. Confirm the tip racks are in slots 7 to 11.
5. Confirm the labware definitions are available in the Opentrons App.
6. Confirm the pipette name and mount match the installed pipette.
7. Check the verification report for missing or extra instructions.
8. Optionally use **Explain barcode pipetting** to inspect selected barcodes by eye.

## Common issues

### `Assigned-codes CSV is missing required column(s): LbarID`

The uploaded file is probably not an assigned-codes CSV, or the wrong separator was selected. Check that the file has `Gene` and `LbarID` columns and that the separator matches the file.

### `Input CSV is missing required column(s): Gene, LbarID`

The uploaded file for Assign or Full workflow does not have the required gene/LbarID columns, or the wrong separator was selected.

### Robot input has unexpected extra rows or columns

The robot input may have been saved with an index or header. The app tries to handle a simple accidental header row, but robot input files should be saved without headers and without an index.

### `Labware ... not found`

The Opentrons App does not know the labware definition named in the protocol. Import the custom labware JSON or use a built-in labware name.

### More than 24 cycles

The default destination rack has 24 positions. The app will reject protocols requiring more than 24 cycles.

## Data flow summary

```text
Gene/LbarID CSV
    -> Assign codebook
    -> assigned_codes CSV
    -> Generate robot input
    -> robot_input CSV
    -> Generate Opentrons protocol
    -> Opentrons .py protocol
```

The full workflow performs all of these steps in one run and packages the outputs into one ZIP file.

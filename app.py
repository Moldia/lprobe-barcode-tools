from __future__ import annotations

import math
import re
import tempfile
import zipfile
from html import escape
from itertools import product
from pathlib import Path

import gradio as gr
import numpy as np
import pandas as pd


def _read_csv(uploaded_file, separator: str) -> pd.DataFrame:
    if uploaded_file is None:
        raise gr.Error("Upload a CSV file first.")

    sep = "\t" if separator == "\\t" else separator
    file_path = uploaded_file if isinstance(uploaded_file, str) else uploaded_file.name
    return pd.read_csv(file_path, sep=sep)


def _read_robot_input_csv(uploaded_file, separator: str) -> pd.DataFrame:
    if uploaded_file is None:
        raise gr.Error("Upload a robot input CSV file first.")

    sep = "\t" if separator == "\\t" else separator
    file_path = uploaded_file if isinstance(uploaded_file, str) else uploaded_file.name
    robot_input = pd.read_csv(file_path, sep=sep, header=None)
    robot_input = robot_input.dropna(axis=0, how="all").dropna(axis=1, how="all")
    if robot_input.empty:
        raise gr.Error("Robot input CSV is empty.")
    robot_input = robot_input.apply(pd.to_numeric, errors="raise").fillna(0).astype(int)
    header_like = list(range(robot_input.shape[1]))
    if robot_input.shape[0] % 96 == 1 and robot_input.iloc[0].tolist() == header_like:
        robot_input = robot_input.iloc[1:].reset_index(drop=True)
    robot_input.columns = range(robot_input.shape[1])
    values = set(pd.unique(robot_input.to_numpy().ravel()))
    if not values.issubset({0, 1}):
        invalid_values = ", ".join(str(value) for value in sorted(values - {0, 1}))
        raise gr.Error(f"Robot input CSV must contain only 0/1 values. Found: {invalid_values}")
    return robot_input


def _clean_tag(tag: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", tag.strip())
    return cleaned.strip("._-") or fallback


def _write_csv(df: pd.DataFrame, filename: str, index: bool = False, header: bool = True) -> str:
    out_dir = Path(tempfile.mkdtemp(prefix="lprobe_app_"))
    out_path = out_dir / filename
    df.to_csv(out_path, index=index, header=header)
    return str(out_path)


def _empty_issues_df() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "Issue",
        "Cycle",
        "Channel",
        "Source deck slot",
        "Source well",
        "Destination deck slot",
        "Destination well",
        "LbarID",
        "Gene",
        "Robot CSV row",
        "Robot CSV column",
    ])


def _drop_exported_index_columns(df: pd.DataFrame) -> pd.DataFrame:
    index_like_columns = [
        column for column in df.columns
        if str(column).startswith("Unnamed:") or str(column).lower() == "index"
    ]
    return df.drop(columns=index_like_columns)


def _normalize_assigned_codes(df: pd.DataFrame) -> pd.DataFrame:
    df = _drop_exported_index_columns(df).copy()
    required_columns = {"Gene", "LbarID"}
    missing = required_columns - set(df.columns)
    if missing:
        raise gr.Error(f"Assigned-codes CSV is missing required column(s): {', '.join(sorted(missing))}")

    lbarid_position = df.columns.get_loc("LbarID")
    cycle_columns = list(df.columns[lbarid_position + 1:])
    if not cycle_columns:
        raise gr.Error("Assigned-codes CSV must include at least one cycle column after LbarID.")

    normalized = df.loc[:, ["Gene", "LbarID", *cycle_columns]].copy()
    normalized = normalized.dropna(subset=["Gene", "LbarID", *cycle_columns])
    if normalized.empty:
        raise gr.Error("Assigned-codes CSV does not contain any complete Gene/LbarID/cycle rows.")

    normalized["LbarID"] = pd.to_numeric(normalized["LbarID"], errors="raise").astype(int)
    for cycle in cycle_columns:
        normalized[cycle] = pd.to_numeric(normalized[cycle], errors="raise").astype(int)
    return normalized


def _duplicate_lbarid_warning(assigned_codes: pd.DataFrame) -> str:
    duplicated = assigned_codes.loc[assigned_codes["LbarID"].duplicated(keep=False), "LbarID"]
    if duplicated.empty:
        return ""

    duplicate_values = ", ".join(str(value) for value in sorted(duplicated.unique()))
    return f" WARNING: duplicate LbarID value(s) detected: {duplicate_values}."


def _barcode_plate_info(lbar_id: int, first_lbar_id: int = 201, plate_size: int = 96) -> tuple[int, int, int, str]:
    rows = "ABCDEFGH"
    plate_number = ((lbar_id - first_lbar_id) // plate_size) + 1
    starting_id = first_lbar_id + ((plate_number - 1) * plate_size)
    well_index = lbar_id - starting_id
    row_index, column_index = divmod(well_index, 12)
    source_well = f"{rows[row_index]}{column_index + 1}"
    return plate_number, starting_id, well_index, source_well


def _well_from_index(well_index: int) -> str:
    rows = "ABCDEFGH"
    row_index, column_index = divmod(well_index, 12)
    return f"{rows[row_index]}{column_index + 1}"


def _render_plate(active_well_index: int | None = None, active_steps: list[int] | None = None) -> str:
    active_steps = active_steps or []
    wells = []
    for row_index, row_name in enumerate("ABCDEFGH"):
        for column_index in range(12):
            well_index = row_index * 12 + column_index
            well_name = f"{row_name}{column_index + 1}"
            active = well_index == active_well_index
            step_classes = " ".join(f"path-step-{step}" for step in active_steps) if active else ""
            wells.append(
                "<div "
                f"class=\"viewer-well {'active-source path-marker ' + step_classes if active else ''}\" "
                f"title=\"{escape(well_name)}\"></div>"
            )
    return f"<div class=\"viewer-plate\">{''.join(wells)}</div>"


def _render_tube_rack(explanation: pd.DataFrame) -> str:
    destination_by_well = {
        row["Destination well"]: int(position) + 1 for position, (_, row) in enumerate(explanation.iterrows())
    }
    tubes = []
    for i in range(1, 7):
        well = f"A{i}"
        order = destination_by_well.get(well)
        step_class = f"path-marker path-step-{order}" if order else ""
        tubes.append(
            "<div "
            f"class=\"viewer-tube {'active-destination ' + step_class if order else ''}\" "
            f"title=\"{well}\">"
            f"<span>{well}</span>"
            f"{f'<strong>{order}</strong>' if order else ''}"
            "</div>"
        )
    return f"<div class=\"viewer-tube-rack\">{''.join(tubes)}</div>"


def render_pipetting_viewer(explanation: pd.DataFrame) -> str:
    if explanation.empty:
        return ""

    oligo_colors = {
        1: "#00bcd4",
        2: "#2e7d32",
        3: "#f5c400",
        4: "#d32f2f",
        5: "#6b7280",
    }
    first = explanation.iloc[0]
    source_well = str(first["Source well"])
    source_well_index = int(str(first["Robot CSV row"])) % 96
    active_slots: dict[int, list[int]] = {}
    for position, (_, row) in enumerate(explanation.iterrows(), start=1):
        active_slots.setdefault(int(row["Source deck slot"]), []).append(position)
    deck_slots = [
        [4, 5, 6],
        [1, 2, 3],
    ]

    def slot_card(slot: int | None) -> str:
        if slot is None:
            return "<div class=\"viewer-slot empty\"></div>"
        if slot == 1:
            body = _render_tube_rack(explanation)
            label = "Destination tube rack"
            detail = "Cycles land in A1-A5"
            kind = "destination"
        elif 2 <= slot <= 6:
            channel = slot - 1
            orders = active_slots.get(slot, [])
            body = _render_plate(source_well_index if orders else None, orders)
            label = f"Detection oligo {channel}"
            detail = f"Deck slot {slot}" + (f" · source well {source_well}" if orders else "")
            kind = f"source detection-oligo detection-oligo-{channel}" + (" active" if orders else "")
        elif 7 <= slot <= 11:
            body = "<div class=\"viewer-tiprack\">tips</div>"
            label = "Tip rack"
            detail = f"Deck slot {slot}"
            kind = "tiprack"
        else:
            body = ""
            label = "Deck slot"
            detail = str(slot)
            kind = ""
        return (
            f"<section class=\"viewer-slot {kind} {' '.join(f'slot-step-{step}' for step in active_slots.get(slot, [])) if slot else ''} {' '.join(f'slot-step-{step}' for step in range(1, len(explanation) + 1)) if slot == 1 else ''}\">"
            f"<div class=\"viewer-slot-head\"><strong>Slot {slot}</strong><span>{escape(label)}</span></div>"
            f"<div class=\"viewer-slot-detail\">{escape(detail)}</div>"
            f"{body}"
            "</section>"
        )

    deck_html = "".join(slot_card(slot) for row in deck_slots for slot in row)
    steps = []
    for position, (_, row) in enumerate(explanation.iterrows(), start=1):
        status = str(row.get("Instruction status", ""))
        status_class = " viewer-step-ok" if status == "OK" else (" viewer-step-missing" if status else "")
        status_html = f"<em>{escape(status)}</em>" if status else ""
        steps.append(
            f"<li class=\"viewer-step viewer-step-{position}{status_class}\">"
            f"<strong>{position}</strong>"
            f"<span>Cycle {escape(str(row['Cycle']))}</span>"
            f"<span>from slot {int(row['Source deck slot'])}, {escape(str(row['Source well']))}</span>"
            f"<span>to slot {int(row['Destination deck slot'])}, {escape(str(row['Destination well']))}</span>"
            f"{status_html}"
            "</li>"
        )

    title = f"{escape(str(first['Gene']))} · LbarID {int(first['LbarID'])}"
    subtitle = (
        f"Barcode ID plate {int(first['Barcode ID plate'])}, "
        f"starting ID {int(first['Barcode plate starting ID'])}, source well {escape(source_well)}"
    )
    hover_blocks = []
    for step, (_, row) in enumerate(explanation.iterrows(), start=1):
        channel = int(row["Channel"])
        color = oligo_colors.get(channel, "#2563eb")
        text_color = "#172033" if channel == 3 else "#ffffff"
        hover_blocks.append(
        f"""
.viewer-wrap:has(.viewer-step-{step}:hover) .viewer-slot {{
  opacity: 0.42;
}}
.viewer-wrap:has(.viewer-step-{step}:hover) .viewer-slot.slot-step-{step} {{
  opacity: 1;
  border-color: {color};
  box-shadow: inset 0 0 0 2px color-mix(in srgb, {color} 24%, transparent);
}}
.viewer-wrap:has(.viewer-step-{step}:hover) .path-marker {{
  opacity: 0.18;
  transform: none;
}}
.viewer-wrap:has(.viewer-step-{step}:hover) .path-step-{step} {{
  opacity: 1;
  transform: scale(1.08);
  z-index: 2;
}}
.viewer-wrap:has(.viewer-step-{step}:hover) .viewer-well.path-step-{step} {{
  background: {color};
  border-color: {color};
}}
.viewer-wrap:has(.viewer-step-{step}:hover) .viewer-tube.path-step-{step} {{
  background: {color};
  border-color: {color};
  color: {text_color};
}}
.viewer-wrap:has(.viewer-step-{step}:hover) .viewer-step-{step} {{
  background: color-mix(in srgb, {color} 14%, white);
  border-color: color-mix(in srgb, {color} 38%, white);
}}
"""
        )
    hover_css = "\n".join(hover_blocks)
    return f"""
<style>
.viewer-wrap {{
  color: #172033;
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}}
.viewer-title {{
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: end;
  margin: 6px 0 14px;
}}
.viewer-title h3 {{
  margin: 0;
  font-size: 20px;
  line-height: 1.2;
}}
.viewer-title p {{
  margin: 4px 0 0;
  color: #526071;
  font-size: 13px;
}}
.viewer-layout {{
  display: grid;
  grid-template-columns: minmax(520px, 1fr) 340px;
  gap: 18px;
  align-items: start;
}}
.viewer-deck {{
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  padding: 12px;
  background: #eef2f5;
  border: 1px solid #cfd8e3;
  border-radius: 8px;
}}
.viewer-slot {{
  min-height: 154px;
  background: #ffffff;
  border: 1px solid #d7dde6;
  border-radius: 8px;
  padding: 9px;
  transition: opacity 120ms ease, border-color 120ms ease, box-shadow 120ms ease;
}}
.viewer-slot.empty {{
  background: transparent;
  border: 1px dashed #c6ced8;
}}
.viewer-slot.active {{
  border-color: #2563eb;
  box-shadow: inset 0 0 0 2px rgba(37, 99, 235, 0.18);
}}
.viewer-slot.destination {{
  border-color: #0f766e;
}}
.viewer-slot.detection-oligo {{
  border-color: color-mix(in srgb, var(--oligo-color) 46%, #d7dde6);
  background: linear-gradient(
    180deg,
    color-mix(in srgb, var(--oligo-color) 10%, white) 0%,
    #ffffff 36%
  );
}}
.viewer-slot.detection-oligo .viewer-slot-head span {{
  color: var(--oligo-text);
  background: color-mix(in srgb, var(--oligo-color) 18%, white);
  border: 1px solid color-mix(in srgb, var(--oligo-color) 34%, white);
  border-radius: 999px;
  padding: 2px 7px;
}}
.viewer-slot.detection-oligo-1 {{
  --oligo-color: #00bcd4;
  --oligo-text: #075985;
}}
.viewer-slot.detection-oligo-2 {{
  --oligo-color: #2e7d32;
  --oligo-text: #14532d;
}}
.viewer-slot.detection-oligo-3 {{
  --oligo-color: #f5c400;
  --oligo-text: #713f12;
}}
.viewer-slot.detection-oligo-4 {{
  --oligo-color: #d32f2f;
  --oligo-text: #7f1d1d;
}}
.viewer-slot.detection-oligo-5 {{
  --oligo-color: #6b7280;
  --oligo-text: #374151;
}}
.viewer-slot.tiprack {{
  background: #f8fafc;
  color: #64748b;
}}
.viewer-slot-head {{
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: baseline;
  font-size: 12px;
}}
.viewer-slot-head span {{
  color: #526071;
  text-align: right;
}}
.viewer-slot-detail {{
  min-height: 18px;
  margin: 4px 0 8px;
  color: #64748b;
  font-size: 11px;
}}
.viewer-plate {{
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 3px;
}}
.viewer-well {{
  aspect-ratio: 1;
  border-radius: 999px;
  border: 1px solid #cbd5e1;
  background: #f8fafc;
  color: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 700;
  position: relative;
  transition: opacity 120ms ease, transform 120ms ease, background 120ms ease;
}}
.viewer-well.active-source {{
  background: #f8fafc;
  border-color: #cbd5e1;
  color: transparent;
}}
.viewer-tube-rack {{
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 8px;
  padding-top: 8px;
}}
.viewer-tube {{
  min-height: 62px;
  border-radius: 999px;
  border: 1px solid #99b6b0;
  background: #ecfdf5;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  color: #0f766e;
  transition: opacity 120ms ease, transform 120ms ease, background 120ms ease;
}}
.viewer-tube.active-destination {{
  background: #0f766e;
  color: #ffffff;
}}
.viewer-tube strong {{
  font-size: 18px;
  line-height: 1;
}}
.viewer-tiprack {{
  height: 100px;
  border-radius: 6px;
  border: 1px dashed #cbd5e1;
  display: flex;
  align-items: center;
  justify-content: center;
  text-transform: uppercase;
  letter-spacing: 0;
  font-size: 11px;
}}
.viewer-steps {{
  margin: 0;
  padding: 12px;
  list-style: none;
  border: 1px solid #d7dde6;
  border-radius: 8px;
  background: #ffffff;
}}
.viewer-steps h4 {{
  margin: 0 0 10px;
  font-size: 15px;
}}
.viewer-steps li {{
  display: grid;
  grid-template-columns: 30px 72px 1fr;
  gap: 8px;
  align-items: center;
  padding: 8px 0;
  border-top: 1px solid #edf1f5;
  border-radius: 6px;
  font-size: 13px;
  cursor: default;
  transition: background 120ms ease, border-color 120ms ease;
}}
.viewer-steps li:first-of-type {{
  border-top: 0;
}}
.viewer-steps li strong {{
  width: 24px;
  height: 24px;
  border-radius: 999px;
  background: #172033;
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
}}
.viewer-steps li span:last-child {{
  grid-column: 3;
  color: #0f766e;
}}
.viewer-steps li em {{
  grid-column: 1 / 4;
  justify-self: start;
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 11px;
  font-style: normal;
  font-weight: 700;
}}
.viewer-step-ok em {{
  background: #dcfce7;
  color: #166534;
}}
.viewer-step-missing em {{
  background: #fee2e2;
  color: #991b1b;
}}
.viewer-step-missing strong {{
  background: #991b1b;
}}
{hover_css}
@media (max-width: 900px) {{
  .viewer-layout {{
    grid-template-columns: 1fr;
  }}
  .viewer-deck {{
    grid-template-columns: 1fr;
  }}
}}
</style>
<div class="viewer-wrap">
  <div class="viewer-title">
    <div>
      <h3>{title}</h3>
      <p>{subtitle}</p>
    </div>
  </div>
  <div class="viewer-layout">
    <div class="viewer-deck">{deck_html}</div>
    <ol class="viewer-steps"><h4>Selected-barcode pipetting order</h4>{''.join(steps)}</ol>
  </div>
</div>
"""


def assign_geneslist_to_codebook(
    genesdf: pd.DataFrame,
    channels: int,
    hamming_distance: bool = True,
    random_state: int = 0,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, int]:
    genesdf = _drop_exported_index_columns(genesdf)
    required_columns = {"Gene", "LbarID"}
    missing = required_columns - set(genesdf.columns)
    if missing:
        raise gr.Error(f"Input CSV is missing required column(s): {', '.join(sorted(missing))}")

    genesdf = genesdf.reset_index(drop=True).copy()
    ngenes = len(genesdf)
    if ngenes <= channels:
        raise gr.Error("The number of genes must be greater than the number of channels.")

    required_cycles = math.ceil(math.log((ngenes - channels), channels)) + int(hamming_distance)
    combinations = np.array(list(product(range(1, channels + 1), repeat=required_cycles)), dtype=np.int16)

    homogeneous = np.all(combinations == combinations[:, [0]], axis=1)
    combinations = combinations[~homogeneous]

    rng = np.random.default_rng(random_state)
    combinations = combinations[rng.permutation(len(combinations))]

    # Full Hamming distance in cycle counts, not proportions.
    distances = np.count_nonzero(combinations[:, None, :] != combinations[None, :, :], axis=2).astype(np.int16)

    balanced_mask = np.ones(len(combinations), dtype=bool)
    for channel in range(1, channels + 1):
        balanced_mask &= np.count_nonzero(combinations == channel, axis=1) < 2

    balanced_indices = np.flatnonzero(balanced_mask)
    first_index = int(balanced_indices[0] if len(balanced_indices) else 0)
    selected = [first_index]
    remaining = np.ones(len(combinations), dtype=bool)
    remaining[first_index] = False

    min_distance_to_selected = distances[first_index].copy()
    while len(selected) < ngenes:
        candidate_indices = np.flatnonzero(remaining)
        if not len(candidate_indices):
            raise gr.Error("Not enough barcode combinations are available for the requested gene count.")

        best_candidate = candidate_indices[np.argmax(min_distance_to_selected[candidate_indices])]
        selected.append(int(best_candidate))
        remaining[best_candidate] = False
        min_distance_to_selected = np.minimum(min_distance_to_selected, distances[best_candidate])

    cycle_columns = list(range(1, required_cycles + 1))
    selected_codebook = pd.DataFrame(combinations[selected], columns=cycle_columns)
    assigned_codes = pd.concat([genesdf.loc[:, ["Gene", "LbarID"]], selected_codebook], axis=1)
    codebook = pd.concat([genesdf.loc[:, ["Gene"]], selected_codebook], axis=1)
    hamming_matrix = pd.DataFrame(distances[np.ix_(selected, selected)])

    return assigned_codes, codebook, hamming_matrix, required_cycles


def translate_to_robot(assigned_codes: pd.DataFrame, starting_id: int) -> pd.DataFrame:
    assigned_codes = _normalize_assigned_codes(assigned_codes)

    possible_starting_ids = [201 + 96 * plate for plate in range(20)]
    if starting_id not in possible_starting_ids:
        raise gr.Error(f"Not a valid starting ID. Options: {possible_starting_ids}")

    cycle_columns = list(assigned_codes.columns[2:])
    channel_values = assigned_codes.loc[:, cycle_columns].to_numpy().ravel()
    channels = sorted(int(channel) for channel in pd.unique(channel_values) if not pd.isna(channel))
    machine_input = np.zeros((96 * len(channels), len(cycle_columns)), dtype=int)

    mod_codes = assigned_codes.loc[
        assigned_codes["LbarID"].isin(range(starting_id, starting_id + 96)), :
    ].copy()
    if mod_codes.empty:
        raise gr.Error(f"No LbarID values found between {starting_id} and {starting_id + 95}.")

    mod_codes["well_index"] = mod_codes["LbarID"].astype(int) - starting_id
    for cycle_index, cycle in enumerate(cycle_columns):
        for _, row in mod_codes.iterrows():
            channel = int(row[cycle])
            robot_row = int(row["well_index"]) + 96 * (channel - 1)
            machine_input[robot_row, cycle_index] = 1

    return pd.DataFrame(machine_input)


def explain_barcode_pipetting(assigned_codes: pd.DataFrame, lbar_id: int) -> pd.DataFrame:
    assigned_codes = _normalize_assigned_codes(assigned_codes)
    match = assigned_codes.loc[assigned_codes["LbarID"] == lbar_id]
    if match.empty:
        raise gr.Error(f"LbarID {lbar_id} not found in assigned-codes CSV.")
    if len(match) > 1:
        genes = ", ".join(str(gene) for gene in match["Gene"].tolist())
        raise gr.Error(f"LbarID {lbar_id} appears in multiple rows ({genes}). It must be unique to explain one barcode.")

    record = match.iloc[0]
    plate_number, starting_id, well_index, source_well = _barcode_plate_info(lbar_id)
    explained = []
    for cycle_index, cycle in enumerate(assigned_codes.columns[2:]):
        channel = int(record[cycle])
        source_deck_slot = channel + 1
        destination_well = f"A{cycle_index + 1}"
        explained.append(
            {
                "Gene": record["Gene"],
                "LbarID": lbar_id,
                "Barcode ID plate": plate_number,
                "Barcode plate starting ID": starting_id,
                "Source deck slot": source_deck_slot,
                "Source well": source_well,
                "Cycle": cycle,
                "Channel": channel,
                "Destination deck slot": 1,
                "Destination well": destination_well,
                "Robot CSV row": well_index + 96 * (channel - 1),
                "Robot CSV column": cycle_index,
            }
        )
    return pd.DataFrame(explained)


def _instruction_rows_from_mask(mask: pd.DataFrame, assigned_codes: pd.DataFrame, starting_id: int, issue_type: str) -> list[dict]:
    assigned_lookup = assigned_codes.set_index("LbarID")["Gene"].to_dict()
    rows = []
    for robot_row, robot_col in zip(*np.where(mask.to_numpy())):
        channel = (int(robot_row) // 96) + 1
        well_index = int(robot_row) % 96
        lbar_id = int(starting_id) + well_index
        rows.append(
            {
                "Issue": issue_type,
                "Cycle": int(robot_col) + 1,
                "Channel": channel,
                "Source deck slot": channel + 1,
                "Source well": _well_from_index(well_index),
                "Destination deck slot": 1,
                "Destination well": f"A{int(robot_col) + 1}",
                "LbarID": lbar_id,
                "Gene": assigned_lookup.get(lbar_id, ""),
                "Robot CSV row": int(robot_row),
                "Robot CSV column": int(robot_col),
            }
        )
    return rows


def verify_robot_input_matrix(
    assigned_codes: pd.DataFrame,
    robot_input: pd.DataFrame,
    starting_id: int,
) -> tuple[str, pd.DataFrame]:
    assigned_codes = _normalize_assigned_codes(assigned_codes)
    duplicate_warning = _duplicate_lbarid_warning(assigned_codes)
    expected = translate_to_robot(assigned_codes, int(starting_id))
    actual = robot_input.fillna(0).astype(int)

    max_rows = max(expected.shape[0], actual.shape[0])
    max_cols = max(expected.shape[1], actual.shape[1])
    expected_full = expected.reindex(index=range(max_rows), columns=range(max_cols), fill_value=0).astype(int)
    actual_full = actual.reindex(index=range(max_rows), columns=range(max_cols), fill_value=0).astype(int)

    missing_mask = (expected_full != 0) & (actual_full == 0)
    extra_mask = (expected_full == 0) & (actual_full != 0)
    missing_count = int(missing_mask.to_numpy().sum())
    extra_count = int(extra_mask.to_numpy().sum())
    expected_count = int((expected_full != 0).to_numpy().sum())
    actual_count = int((actual_full != 0).to_numpy().sum())

    issues = _instruction_rows_from_mask(missing_mask, assigned_codes, starting_id, "Missing")
    issues.extend(_instruction_rows_from_mask(extra_mask, assigned_codes, starting_id, "Extra"))
    issues_df = pd.DataFrame(issues)

    shape_note = ""
    if expected.shape != actual.shape:
        shape_note = f" Shape differs: expected {expected.shape[0]}x{expected.shape[1]}, got {actual.shape[0]}x{actual.shape[1]}."
    if missing_count == 0 and extra_count == 0 and not shape_note:
        summary = f"PASS: robot input matches assigned codes exactly ({expected_count} transfers).{duplicate_warning}"
    else:
        summary = (
            f"CHECK FAILED: {missing_count} missing transfer(s), {extra_count} extra transfer(s). "
            f"Expected {expected_count} transfer(s), robot input contains {actual_count}."
            f"{shape_note}{duplicate_warning}"
        )

    return summary, issues_df


def verify_barcode_robot_input(
    assigned_codes: pd.DataFrame,
    robot_input: pd.DataFrame,
    starting_id: int,
    lbar_id: int,
) -> pd.DataFrame:
    if not int(starting_id) <= int(lbar_id) < int(starting_id) + 96:
        raise gr.Error(f"LbarID {int(lbar_id)} is not on the plate starting at {int(starting_id)}.")

    explanation = explain_barcode_pipetting(assigned_codes, int(lbar_id))
    actual = robot_input.fillna(0).astype(int)
    statuses = []
    for _, row in explanation.iterrows():
        robot_row = int(row["Robot CSV row"])
        robot_col = int(row["Robot CSV column"])
        present = (
            robot_row < actual.shape[0]
            and robot_col < actual.shape[1]
            and int(actual.iat[robot_row, robot_col]) != 0
        )
        statuses.append("OK" if present else "Missing")

    explanation = explanation.copy()
    explanation["Instruction status"] = statuses
    explanation["Verification"] = statuses
    return explanation


def run_assign_workflow(uploaded_file, separator, channels, use_hamming, tag, random_state):
    genesdf = _read_csv(uploaded_file, separator)
    assigned_codes, codebook, hamming_matrix, required_cycles = assign_geneslist_to_codebook(
        genesdf,
        channels=int(channels),
        hamming_distance=bool(use_hamming),
        random_state=int(random_state),
    )

    clean_tag = _clean_tag(tag, "codebook")
    assigned_path = _write_csv(assigned_codes, f"assigned_codes_{clean_tag}.csv")
    codebook_path = _write_csv(codebook, f"codebook_{clean_tag}.csv")
    hamming_path = _write_csv(hamming_matrix, f"hamming_distances_{clean_tag}.csv", index=True)
    summary = (
        f"Created {len(assigned_codes)} assigned codes with {required_cycles} cycles "
        f"and {int(channels)} channels."
    )
    return summary, assigned_codes, assigned_path, codebook_path, hamming_path


def run_robot_workflow(uploaded_file, separator, starting_id, tag):
    assigned_codes = _read_csv(uploaded_file, separator)
    robot_input = translate_to_robot(assigned_codes, int(starting_id))
    clean_tag = _clean_tag(tag, "robot_input")
    robot_path = _write_csv(robot_input, f"robot_input_plate_{int(starting_id)}_{clean_tag}.csv", header=False)
    summary = f"Created robot input with {robot_input.shape[0]} rows and {robot_input.shape[1]} cycles."
    return summary, robot_input, robot_path


def run_explain_workflow(uploaded_file, separator, lbar_id):
    assigned_codes = _read_csv(uploaded_file, separator)
    explanation = explain_barcode_pipetting(assigned_codes, int(lbar_id))
    viewer = render_pipetting_viewer(explanation)
    explanation_path = _write_csv(explanation, f"barcode_{int(lbar_id)}_pipetting_explanation.csv")
    return viewer, explanation, explanation_path


def run_verify_workflow(
    assigned_file,
    assigned_separator,
    robot_file,
    robot_separator,
    starting_id,
    lbar_id,
):
    assigned_codes = _read_csv(assigned_file, assigned_separator)
    robot_input = _read_robot_input_csv(robot_file, robot_separator)
    summary, issues = verify_robot_input_matrix(assigned_codes, robot_input, int(starting_id))
    selected = verify_barcode_robot_input(assigned_codes, robot_input, int(starting_id), int(lbar_id))

    selected_path = _write_csv(selected, f"barcode_{int(lbar_id)}_robot_input_verification.csv")
    if issues.empty:
        issues = _empty_issues_df()
    issues_path = _write_csv(issues, f"robot_input_plate_{int(starting_id)}_verification_issues.csv")
    return summary, selected, issues, selected_path, issues_path


def run_full_workflow(uploaded_file, separator, channels, use_hamming, tag, random_state, starting_id):
    genesdf = _read_csv(uploaded_file, separator)
    clean_tag = _clean_tag(tag, "standard_barcoding_scheme")
    channels = int(channels)
    random_state = int(random_state)
    starting_id = int(starting_id)

    assigned_codes, codebook, hamming_matrix, required_cycles = assign_geneslist_to_codebook(
        genesdf,
        channels=channels,
        hamming_distance=bool(use_hamming),
        random_state=random_state,
    )
    robot_input = translate_to_robot(assigned_codes, starting_id)
    verification_summary, issues = verify_robot_input_matrix(assigned_codes, robot_input, starting_id)
    normalized_assigned = _normalize_assigned_codes(assigned_codes)
    duplicate_warning = _duplicate_lbarid_warning(normalized_assigned)
    if issues.empty:
        issues = _empty_issues_df()

    transfer_count = int((robot_input != 0).to_numpy().sum())
    input_name = Path(uploaded_file if isinstance(uploaded_file, str) else uploaded_file.name).name
    report_lines = [
        "L-probe barcode workflow report",
        "",
        "Inputs",
        f"- Input file: {input_name}",
        f"- CSV separator: {separator}",
        f"- Channels / detection oligos: {channels}",
        f"- Hamming-distance extra cycle: {bool(use_hamming)}",
        f"- Random seed: {random_state}",
        f"- Plate starting ID: {starting_id}",
        f"- Output tag: {clean_tag}",
        "",
        "Assignment",
        f"- Input rows: {len(genesdf)}",
        f"- Assigned rows: {len(assigned_codes)}",
        f"- Required cycles: {required_cycles}",
        f"- Codebook shape: {codebook.shape[0]} rows x {codebook.shape[1]} columns",
        f"- Hamming matrix shape: {hamming_matrix.shape[0]} x {hamming_matrix.shape[1]}",
        duplicate_warning.strip() or "- Duplicate LbarID check: none detected",
        "",
        "Robot input",
        f"- Robot input shape: {robot_input.shape[0]} rows x {robot_input.shape[1]} columns",
        f"- Active transfer instructions: {transfer_count}",
        "- Robot input CSV is written without headers or index for Opentrons compatibility",
        "",
        "Verification",
        f"- {verification_summary}",
        f"- Missing/extra issue rows: {len(issues)}",
        "",
        "Generated files",
        f"- assigned_codes_{clean_tag}.csv",
        f"- codebook_{clean_tag}.csv",
        f"- hamming_distances_{clean_tag}.csv",
        f"- robot_input_plate_{starting_id}_{clean_tag}.csv",
        f"- robot_input_plate_{starting_id}_{clean_tag}_verification_issues.csv",
        f"- workflow_report_{clean_tag}.txt",
    ]
    report = "\n".join(report_lines)

    out_dir = Path(tempfile.mkdtemp(prefix="lprobe_full_workflow_"))
    files = [
        (out_dir / f"assigned_codes_{clean_tag}.csv", assigned_codes, False, True),
        (out_dir / f"codebook_{clean_tag}.csv", codebook, False, True),
        (out_dir / f"hamming_distances_{clean_tag}.csv", hamming_matrix, True, True),
        (out_dir / f"robot_input_plate_{starting_id}_{clean_tag}.csv", robot_input, False, False),
        (out_dir / f"robot_input_plate_{starting_id}_{clean_tag}_verification_issues.csv", issues, False, True),
    ]
    for path, df, index, header in files:
        df.to_csv(path, index=index, header=header)

    report_path = out_dir / f"workflow_report_{clean_tag}.txt"
    report_path.write_text(report)

    zip_path = out_dir / f"lprobe_workflow_{clean_tag}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for path, _, _, _ in files:
            zip_file.write(path, arcname=path.name)
        zip_file.write(report_path, arcname=report_path.name)

    return report, assigned_codes, robot_input, issues, str(zip_path)


def get_first_lbar_id(uploaded_file, separator):
    if uploaded_file is None:
        return gr.update()

    assigned_codes = _normalize_assigned_codes(_read_csv(uploaded_file, separator))
    return gr.update(value=int(assigned_codes["LbarID"].iloc[0]))


with gr.Blocks(title="L-probe Barcode Tools") as demo:
    gr.Markdown("# L-probe Barcode Tools")
    workflow = gr.Radio(
        ["Run full workflow", "Assign codebook", "Generate robot input", "Explain barcode pipetting", "Verify robot input"],
        label="Workflow",
        value="Run full workflow",
    )

    with gr.Group(visible=True) as full_panel:
        gr.Markdown("## Run full workflow")
        full_genes_file = gr.File(label="Gene/LbarID CSV")
        full_separator = gr.Radio([",", ";", "\\t"], label="CSV separator", value=";")
        full_channels = gr.Number(label="Channels / detection oligos", value=5, precision=0)
        full_hamming = gr.Checkbox(label="Add one extra cycle for Hamming-distance error correction", value=True)
        full_tag = gr.Textbox(label="Output tag", value="standard_barcoding_scheme")
        full_random_state = gr.Number(label="Random seed", value=0, precision=0)
        full_starting_id = gr.Number(label="Plate starting ID", value=201, precision=0)
        full_button = gr.Button("Run full workflow", variant="primary")
        full_report = gr.Textbox(label="Workflow report", lines=18, interactive=False)
        full_assigned_preview = gr.Dataframe(label="Assigned codes preview", interactive=False)
        full_robot_preview = gr.Dataframe(label="Robot input preview", interactive=False)
        full_issues_preview = gr.Dataframe(label="Verification issues", interactive=False)
        full_zip_download = gr.File(label="Download all outputs as ZIP")

    with gr.Group(visible=False) as assign_panel:
        gr.Markdown("## Assign codebook")
        genes_file = gr.File(label="Gene/LbarID CSV")
        genes_separator = gr.Radio([",", ";", "\\t"], label="CSV separator", value=";")
        assign_channels = gr.Number(label="Channels", value=5, precision=0)
        assign_hamming = gr.Checkbox(label="Add one extra cycle for Hamming-distance error correction", value=True)
        assign_tag = gr.Textbox(label="Output tag", value="standard_barcoding_scheme")
        assign_random_state = gr.Number(label="Random seed", value=0, precision=0)
        assign_button = gr.Button("Run assignment", variant="primary")
        assign_summary = gr.Textbox(label="Summary", interactive=False)
        assigned_preview = gr.Dataframe(label="Assigned codes preview", interactive=False)
        assigned_download = gr.File(label="Download assigned codes")
        codebook_download = gr.File(label="Download codebook")
        hamming_download = gr.File(label="Download Hamming-distance matrix")

    with gr.Group(visible=False) as robot_panel:
        gr.Markdown("## Generate robot input")
        assigned_file = gr.File(label="Assigned-codes CSV")
        assigned_separator = gr.Radio([",", ";", "\\t"], label="CSV separator", value=",")
        robot_starting_id = gr.Number(label="Plate starting ID", value=393, precision=0)
        robot_tag = gr.Textbox(label="Output tag", value="robot_input")
        robot_button = gr.Button("Generate robot input", variant="primary")
        robot_summary = gr.Textbox(label="Summary", interactive=False)
        robot_preview = gr.Dataframe(label="Robot input preview", interactive=False)
        robot_download = gr.File(label="Download robot input")

    with gr.Group(visible=False) as explain_panel:
        gr.Markdown("## Explain barcode pipetting")
        explain_file = gr.File(label="Assigned-codes CSV")
        explain_separator = gr.Radio([",", ";", "\\t"], label="CSV separator", value=",")
        explain_lbar_id = gr.Number(label="LbarID", value=393, precision=0)
        explain_button = gr.Button("Explain barcode", variant="primary")
        explain_viewer = gr.HTML(label="Pipetting viewer")
        explain_preview = gr.Dataframe(label="Pipetting explanation", interactive=False)
        explain_download = gr.File(label="Download explanation")

    with gr.Group(visible=False) as verify_panel:
        gr.Markdown("## Verify robot input")
        verify_assigned_file = gr.File(label="Assigned-codes CSV")
        verify_assigned_separator = gr.Radio([",", ";", "\\t"], label="Assigned-codes CSV separator", value=",")
        verify_robot_file = gr.File(label="Robot input CSV")
        verify_robot_separator = gr.Radio([",", ";", "\\t"], label="Robot input CSV separator", value=",")
        verify_starting_id = gr.Number(label="Plate starting ID", value=201, precision=0)
        verify_lbar_id = gr.Number(label="LbarID", value=201, precision=0)
        verify_button = gr.Button("Verify robot input", variant="primary")
        verify_summary = gr.Textbox(label="Verification summary", interactive=False)
        verify_selected_preview = gr.Dataframe(label="Selected barcode verification", interactive=False)
        verify_issues_preview = gr.Dataframe(label="Missing/extra robot input instructions", interactive=False)
        verify_selected_download = gr.File(label="Download selected barcode verification")
        verify_issues_download = gr.File(label="Download missing/extra instruction report")

    def _show_workflow(selected):
        return (
            gr.update(visible=selected == "Run full workflow"),
            gr.update(visible=selected == "Assign codebook"),
            gr.update(visible=selected == "Generate robot input"),
            gr.update(visible=selected == "Explain barcode pipetting"),
            gr.update(visible=selected == "Verify robot input"),
        )

    workflow.change(_show_workflow, inputs=workflow, outputs=[full_panel, assign_panel, robot_panel, explain_panel, verify_panel])

    full_button.click(
        run_full_workflow,
        inputs=[
            full_genes_file,
            full_separator,
            full_channels,
            full_hamming,
            full_tag,
            full_random_state,
            full_starting_id,
        ],
        outputs=[
            full_report,
            full_assigned_preview,
            full_robot_preview,
            full_issues_preview,
            full_zip_download,
        ],
    )
    assign_button.click(
        run_assign_workflow,
        inputs=[genes_file, genes_separator, assign_channels, assign_hamming, assign_tag, assign_random_state],
        outputs=[assign_summary, assigned_preview, assigned_download, codebook_download, hamming_download],
    )
    robot_button.click(
        run_robot_workflow,
        inputs=[assigned_file, assigned_separator, robot_starting_id, robot_tag],
        outputs=[robot_summary, robot_preview, robot_download],
    )
    explain_file.change(
        get_first_lbar_id,
        inputs=[explain_file, explain_separator],
        outputs=explain_lbar_id,
    )
    explain_separator.change(
        get_first_lbar_id,
        inputs=[explain_file, explain_separator],
        outputs=explain_lbar_id,
    )
    verify_assigned_file.change(
        get_first_lbar_id,
        inputs=[verify_assigned_file, verify_assigned_separator],
        outputs=verify_lbar_id,
    )
    verify_assigned_separator.change(
        get_first_lbar_id,
        inputs=[verify_assigned_file, verify_assigned_separator],
        outputs=verify_lbar_id,
    )
    explain_button.click(
        run_explain_workflow,
        inputs=[explain_file, explain_separator, explain_lbar_id],
        outputs=[explain_viewer, explain_preview, explain_download],
    )
    verify_button.click(
        run_verify_workflow,
        inputs=[
            verify_assigned_file,
            verify_assigned_separator,
            verify_robot_file,
            verify_robot_separator,
            verify_starting_id,
            verify_lbar_id,
        ],
        outputs=[
            verify_summary,
            verify_selected_preview,
            verify_issues_preview,
            verify_selected_download,
            verify_issues_download,
        ],
    )


if __name__ == "__main__":
    demo.launch()

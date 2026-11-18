#!/usr/bin/env python3
"""Mensural2MusicXML

Convert MEI 5.1 files containing mensural notation to MusicXML.

Supported features:
  * One MEI staff with one layer per input file.
  * Mensural durations: maxima, longa, brevis, semibrevis, minima,
    semiminima, fusa and semifusa.
  * Augmentation dots become genuine dotted MusicXML notes.
  * Division dots are retained as MusicXML textual annotations.
  * Notes, rests, pitches, octaves, accidentals and initial clef.
  * Mensuration and proportion signs are retained as explanatory text.
  * MEI barLine elements delimit MusicXML measures.

Known limitations:
  * Mensural perfection/imperfectio, coloration, ligatures and proportional
    arithmetic are not yet interpreted.
  * Division dots are annotations, not historical mensural glyphs.
  * Multiple simultaneous MEI layers/staves are not yet merged into a score.
  * Custodes and page/system breaks are skipped.
  * The converter preserves encoded values; it does not infer missing
    mensural rules from musical context.
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from fractions import Fraction
from pathlib import Path

DIVISIONS = 1024  # per quarter note; enough for dotted 256th notes

# ---------------------------------------------------------------------------
# MEI 5.1 -> MusicXML conversion
# ---------------------------------------------------------------------------

MEI_NS = "http://www.music-encoding.org/ns/mei"
XML_NS = "{http://www.w3.org/XML/1998/namespace}"

MEI_DURATIONS = {
    "maxima": ("maxima", Fraction(32, 1)),
    "longa": ("long", Fraction(16, 1)),
    "brevis": ("breve", Fraction(8, 1)),
    "semibrevis": ("whole", Fraction(4, 1)),
    "minima": ("half", Fraction(2, 1)),
    "semiminima": ("quarter", Fraction(1, 1)),
    "fusa": ("eighth", Fraction(1, 2)),
    "semifusa": ("16th", Fraction(1, 4)),
}

MEI_ACCIDENTALS = {
    "s": (1, "sharp"),
    "f": (-1, "flat"),
    "n": (0, "natural"),
    "ss": (2, "double-sharp"),
    "ff": (-2, "flat-flat"),
    "su": (Fraction(1, 2), "quarter-sharp"),
    "fu": (Fraction(-1, 2), "quarter-flat"),
}


def mei_tag(element):
    return element.tag.rsplit("}", 1)[-1]


def mei_children(element, tag=None):
    children = list(element)
    return [child for child in children if tag is None or mei_tag(child) == tag]


def mei_find(element, tag):
    for child in element.iter():
        if mei_tag(child) == tag:
            return child
    return None


def parse_mei_clef(clef):
    shape = (clef.get("shape") or "G").upper()
    line = int(clef.get("line") or 2)
    if shape not in {"G", "F", "C", "PERCUSSION", "PERC"}:
        raise ValueError(f"Unsupported MEI clef: shape={shape!r}")
    if shape in {"PERCUSSION", "PERC"}:
        shape = "percussion"
    return shape, line, clef.get("dis"), clef.get("dis.place")


def add_musicxml_clef(measure, clef_data):
    shape, line, dis, dis_place = clef_data
    attributes = ET.SubElement(measure, "attributes")
    clef = ET.SubElement(attributes, "clef")
    ET.SubElement(clef, "sign").text = shape
    if shape != "percussion":
        ET.SubElement(clef, "line").text = str(line)
    if dis:
        octave_change = {"8": 1, "15": 2}.get(dis)
        if octave_change is not None:
            if dis_place == "below":
                octave_change *= -1
            ET.SubElement(clef, "clef-octave-change").text = str(octave_change)


def parse_mei_accidental(note):
    accid_el = next((c for c in list(note) if mei_tag(c) == "accid"), None)
    code = accid_el.get("accid") if accid_el is not None else (
        note.get("accid") or note.get("accid.ges")
    )
    if not code:
        return None
    if code not in MEI_ACCIDENTALS:
        raise ValueError(f"Unsupported MEI accidental: {code!r}")
    alter, display = MEI_ACCIDENTALS[code]
    return alter, display, accid_el


def mei_note_event(element):
    dur = element.get("dur")
    if dur not in MEI_DURATIONS:
        raise ValueError(
            f"Unrecognized MEI duration {dur!r} in "
            f"{element.get(XML_NS + 'id', 'note without an ID')}"
        )
    note_type, base_duration = MEI_DURATIONS[dur]
    dots = 0
    if element.get("dur.quality"):
        print(
            f"Warning: dur.quality={element.get('dur.quality')!r} "
            "is not implemented; the base note value is preserved.",
            file=sys.stderr,
        )

    if mei_tag(element) == "rest":
        return {
            "kind": "rest", "type": note_type,
            "quarters": base_duration, "dots": dots,
        }

    pname = (element.get("pname") or "").upper()
    octave = element.get("oct")
    if pname not in {"A", "B", "C", "D", "E", "F", "G"} or octave is None:
        raise ValueError(
            f"Incomplete MEI pitch in {element.get(XML_NS + 'id', 'note without an ID')}"
        )
    accidental = parse_mei_accidental(element)
    alter, accidental_name = (accidental[0], accidental[1]) if accidental else (0, None)
    return {
        "kind": "note", "step": pname, "octave": int(octave),
        "alter": alter, "accidental": accidental_name,
        "type": note_type, "quarters": base_duration, "dots": dots,
        "id": element.get(XML_NS + "id"),
    }


def add_mei_note(measure, event, voice="1", staff="1"):
    note = ET.SubElement(measure, "note")
    if event["kind"] == "rest":
        ET.SubElement(note, "rest")
    else:
        pitch = ET.SubElement(note, "pitch")
        ET.SubElement(pitch, "step").text = event["step"]
        if event["alter"] != 0:
            ET.SubElement(pitch, "alter").text = str(event["alter"])
        ET.SubElement(pitch, "octave").text = str(event["octave"])

    quarters = event["quarters"] * (
        Fraction(2, 1) - Fraction(1, 2 ** event["dots"])
        if event["dots"] else Fraction(1, 1)
    )
    duration = quarters * DIVISIONS
    if duration.denominator != 1:
        raise ValueError(f"Unrepresentable duration: {duration}")
    ET.SubElement(note, "duration").text = str(duration.numerator)
    ET.SubElement(note, "voice").text = str(voice)
    ET.SubElement(note, "type").text = event["type"]

    for _ in range(event["dots"]):
        ET.SubElement(note, "dot")

    if event["kind"] == "note" and event.get("accidental"):
        ET.SubElement(note, "accidental").text = event["accidental"]

    ET.SubElement(note, "staff").text = str(staff)


def add_mei_direction(measure, words):
    direction = ET.SubElement(measure, "direction", placement="above")
    direction_type = ET.SubElement(direction, "direction-type")
    ET.SubElement(direction_type, "words").text = words
    ET.SubElement(direction, "staff").text = "1"


def add_mei_key_signature(measure, key_sig):
    sig = key_sig.get("sig", "0")
    match = re.fullmatch(r"(\d+)([sf])", sig)
    if sig in {"0", "0s", "0f"}:
        fifths = 0
    elif match:
        count, kind = int(match.group(1)), match.group(2)
        fifths = count if kind == "s" else -count
    else:
        print(f"Warning: unrecognized MEI key signature: {sig!r}", file=sys.stderr)
        return
    attributes = ET.SubElement(measure, "attributes")
    key = ET.SubElement(attributes, "key")
    ET.SubElement(key, "fifths").text = str(fifths)
    mode = key_sig.get("mode")
    if mode in {"major", "minor"}:
        ET.SubElement(key, "mode").text = mode


def mei_measure_groups(layer):
    groups = []
    current = []
    pending_barlines = 0

    for child in list(layer):
        tag = mei_tag(child)
        if tag == "barLine":
            pending_barlines += 1
            continue

        if pending_barlines:
            if current:
                groups.append((current, "light-light" if pending_barlines > 1 else "regular"))
                current = []
            elif groups and pending_barlines > 1:
                groups[-1] = (groups[-1][0], "light-light")
            pending_barlines = 0

        current.append(child)

    if current:
        groups.append((current, "light-heavy" if pending_barlines > 1 else "regular"))
    elif pending_barlines and groups and pending_barlines > 1:
        groups[-1] = (groups[-1][0], "light-heavy")

    return groups


def convert_mei(input_path: Path, output_path: Path):
    tree = ET.parse(input_path)
    root = tree.getroot()

    staff = mei_find(root, "staff")
    if staff is None:
        raise ValueError("The MEI file does not contain a <staff> element.")
    layers = mei_children(staff, "layer")
    if not layers:
        raise ValueError("Could not find a <layer> inside <staff>.")
    if len(layers) > 1:
        raise ValueError(
            f"This version found {len(layers)} layers in one staff. "
            "Conversion of multiple simultaneous layers will be added in a future version."
        )

    layer = layers[0]
    staff_def = mei_find(root, "staffDef")
    if staff_def is None:
        raise ValueError("Could not find <staffDef>; the initial clef cannot be determined.")

    clef_element = next((c for c in list(staff_def) if mei_tag(c) == "clef"), None)
    if clef_element is None:
        raise ValueError("Could not find the initial <clef> in <staffDef>.")
    initial_clef = parse_mei_clef(clef_element)

    key_sig = next((c for c in list(staff_def) if mei_tag(c) == "keySig"), None)
    notation_type = staff_def.get("notationtype")
    staff_number = staff.get("n", "1")

    groups = mei_measure_groups(layer)
    if not groups:
        raise ValueError("The MEI layer contains no musical events.")

    title_el = mei_find(root, "title")
    title = (title_el.text or "").strip() if title_el is not None else ""
    title = title or input_path.stem
    part_name = staff_def.get("label") or staff_def.get("label.abbr") or "Mensural part"

    score = ET.Element("score-partwise", version="4.0")
    work = ET.SubElement(score, "work")
    ET.SubElement(work, "work-title").text = title
    identification = ET.SubElement(score, "identification")
    encoding = ET.SubElement(identification, "encoding")
    ET.SubElement(encoding, "software").text = "Mensural2MusicXML"
    ET.SubElement(encoding, "encoding-description").text = (
        "Converted from MEI 5.1; mensural note values mapped to MusicXML note types."
    )

    part_list = ET.SubElement(score, "part-list")
    score_part = ET.SubElement(part_list, "score-part", id="P1")
    ET.SubElement(score_part, "part-name").text = part_name
    part = ET.SubElement(score, "part", id="P1")

    warnings = Counter()
    clef_state = initial_clef

    for measure_index, (children, bar_style) in enumerate(groups, start=1):
        measure = ET.SubElement(part, "measure", number=str(measure_index))
        if measure_index == 1:
            attributes = ET.SubElement(measure, "attributes")
            ET.SubElement(attributes, "divisions").text = str(DIVISIONS)
            clef = ET.SubElement(attributes, "clef")
            ET.SubElement(clef, "sign").text = initial_clef[0]
            if initial_clef[0] != "percussion":
                ET.SubElement(clef, "line").text = str(initial_clef[1])
            if initial_clef[2]:
                octave_change = {"8": 1, "15": 2}.get(initial_clef[2])
                if octave_change is not None:
                    if initial_clef[3] == "below":
                        octave_change *= -1
                    ET.SubElement(clef, "clef-octave-change").text = str(octave_change)
            if key_sig is not None:
                add_mei_key_signature(measure, key_sig)
            if notation_type:
                add_mei_direction(measure, f"MEI notation type: {notation_type}")

        last_note_event = None
        for child in children:
            tag = mei_tag(child)

            if tag in {"note", "rest"}:
                event = mei_note_event(child)
                add_mei_note(measure, event, voice="1", staff=staff_number)
                last_note_event = event
                if event["kind"] == "note":
                    warnings["notes"] += 1
                else:
                    warnings["rests"] += 1

            elif tag == "dot":
                form = child.get("form", "aug")
                if form == "aug":
                    if last_note_event is None:
                        raise ValueError("Found an augmentation dot without a preceding note.")
                    last_note_event["dots"] += 1
                    # The corresponding MusicXML note was already written.
                    # Update it in place: add <dot/> and increase <duration>.
                    xml_note = measure.findall("note")[-1]
                    duration_el = xml_note.find("duration")
                    base_quarters = last_note_event["quarters"]
                    dotted_quarters = base_quarters * (
                        Fraction(2, 1) - Fraction(1, 2 ** last_note_event["dots"])
                    )
                    duration_el.text = str(int(dotted_quarters * DIVISIONS))
                    dot_element = ET.Element("dot")
                    child_tags = [mei_tag(x) for x in list(xml_note)]
                    insert_at = child_tags.index("type") + 1
                    xml_note.insert(insert_at, dot_element)
                    warnings["augmentation dots"] += 1
                elif form == "div":
                    if last_note_event is None:
                        raise ValueError("Found a division dot without a preceding note.")
                    xml_note = measure.findall("note")[-1]
                    notations = xml_note.find("notations")
                    if notations is None:
                        notations = ET.SubElement(xml_note, "notations")
                    other = ET.SubElement(notations, "other-notation", type="single")
                    other.text = "division dot"
                    warnings["division dots"] += 1
                else:
                    warnings[f"unsupported dot form: {form}"] += 1
                # A dot is attached to the preceding note, not to the next event.

            elif tag == "clef":
                clef_state = parse_mei_clef(child)
                add_musicxml_clef(measure, clef_state)
                last_note_event = None

            elif tag == "mensur":
                sign = child.get("sign", "?")
                slash = child.get("slash")
                if slash in {"1", "true"}:
                    label = f"Mensuration: {sign} with slash"
                else:
                    label = f"Mensuration: {sign}"
                add_mei_direction(measure, label)
                warnings["mensuration signs"] += 1
                last_note_event = None

            elif tag == "proport":
                label = "Proportion: " + " ".join(
                    f"{k}={v}" for k, v in child.attrib.items()
                )
                add_mei_direction(measure, label)
                warnings["proportion signs"] += 1
                last_note_event = None

            elif tag in {"sb", "pb", "custos"}:
                warnings[tag] += 1
                last_note_event = None

            elif tag in {"accid", "keySig"}:
                # These may occur as independent MEI events in other exports.
                warnings[f"unattached {tag}"] += 1
                last_note_event = None

            else:
                warnings[f"unhandled MEI element: {tag}"] += 1
                last_note_event = None

        barline = ET.SubElement(measure, "barline", location="right")
        ET.SubElement(barline, "bar-style").text = bar_style

    ET.indent(score, space="  ")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(score).write(
        output_path, encoding="UTF-8", xml_declaration=True
    )

    print(f"MusicXML output: {output_path}")
    print(f"Input MEI: {input_path}")
    print(f"Delimited measures/sections: {len(groups)}")
    print("Summary:")
    for label, count in sorted(warnings.items()):
        print(f"  {label}: {count}")
    print(
        "Note: MEI form='aug' dots are converted to MusicXML augmentation dots; "
        "form='div' dots are preserved as textual annotations without "
        "changing the duration."
    )




def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert mensural MEI 5.1 files to MusicXML."
    )
    parser.add_argument("input_file", type=Path, help="Input .mei file")
    parser.add_argument("-o", "--output", type=Path, help="Output .musicxml file")
    args = parser.parse_args()

    if not args.input_file.exists():
        print(f"Error: input file does not exist: {args.input_file}", file=sys.stderr)
        return 1

    if args.input_file.suffix.lower() != ".mei":
        print("Error: unsupported input format. Please provide an .mei file.", file=sys.stderr)
        return 1

    output = args.output or args.input_file.with_suffix(".musicxml")
    try:
        convert_mei(args.input_file, output)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

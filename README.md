# Mensural2MusicXML

A lightweight Python converter for mensural notation encoded in MEI 5.1,
including MEI exports from OMR tools such as MuRET. It converts MEI files
to MusicXML, which can then be opened in MuseScore.

## Requirements

- Python 3.10 or newer
- No third-party Python packages required

## Convert an MEI file

```bash
python mensural2musicxml.py path/to/file.mei -o file.musicxml
```

Then open `file.musicxml` in MuseScore.

## MEI features supported

- One MEI staff and one layer per input file.
- Mensural note values: maxima, longa, brevis, semibrevis, minima,
  semiminima, fusa and semifusa.
- Notes, rests, pitches, octaves, note accidentals and the initial clef.
- MEI augmentation dots (`<dot form="aug"/>`) become dotted MusicXML notes
  and increase the note duration accordingly.
- Division dots (`<dot form="div"/>`) are preserved as MusicXML textual
  annotations without changing the duration.
- Mensuration and proportion signs are retained as explanatory text directions.
- MEI `barLine` elements are used to delimit MusicXML measures.

## Current limitations

This version does not yet interpret mensural perfection/imperfectio, coloration,
ligatures or proportional arithmetic. Division dots are preserved as annotations
rather than rendered as historical glyphs. Multiple simultaneous MEI layers or
staves are not yet combined. Custodes and page/system breaks are skipped.

The converter preserves the values encoded in the MEI file; it does not infer
missing mensural rules from musical context.

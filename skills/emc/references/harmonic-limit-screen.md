# Harmonic-Limit Screening

`analyze_harmonic_limits.py` compares already-calculated RMS dBµV spectral lines with a user-supplied band-limit profile. The result is an engineering screen, not a compliance determination. The tool does not process waveforms, emulate detector timing or receiver bandwidth, invoke a simulator, or provide regulatory limit tables.

## Command

```bash
python3 skills/emc/scripts/analyze_harmonic_limits.py \
  --spectrum harmonic-lines.json \
  --limits limit-profile.json \
  --detector peak \
  --design-margin-db 3 \
  --output harmonic-limit-screen.json
```

## Spectrum format

The input must use schema `harmonic-lines/1` and `level_unit: dbuv_rms`. Frequencies are positive finite hertz values, levels are finite RMS-referenced dBµV values, and duplicate frequencies are rejected. An optional `source` must be an object; it is echoed to the output as `spectrum_source` (`null` when absent). Input files must be UTF-8 (a leading byte-order mark is accepted), and JSON objects with duplicate keys are rejected rather than resolved last-wins.

```json
{
  "schema_version": "harmonic-lines/1",
  "level_unit": "dbuv_rms",
  "source": {
    "kind": "simulation",
    "description": "synthetic spectral lines"
  },
  "points": [
    {"frequency_hz": 1000000, "level_dbuv": 42.0},
    {"frequency_hz": 2000000, "level_dbuv": 31.5}
  ]
}
```

## Limit-profile format

Profiles use schema `emc-limit-profile/1`. `profile_id`, `source.kind`, and `source.citation` are required, and any additional `source` fields (for example a URL or edition) are copied to the output unchanged. A profile needs at least one band. Each uniquely named band has an inclusive positive frequency range and at least one finite dBµV limit named `peak`, `quasi_peak`, or `average`.

The repository does not provide regulatory tables. The following values are fictional and must not be used for a product decision:

```json
{
  "schema_version": "emc-limit-profile/1",
  "profile_id": "fictional-user-profile",
  "source": {
    "kind": "user_supplied",
    "citation": "Fictional example — not a regulatory source"
  },
  "bands": [
    {
      "name": "fictional-band",
      "start_hz": 500000,
      "stop_hz": 1800000,
      "limits_dbuv": {
        "peak": 54.0,
        "quasi_peak": 41.0,
        "average": 34.0
      }
    }
  ]
}
```

## Comparison and output

For each band, the tool selects the in-band point with the greatest `level_dbuv`; equal levels choose the lower frequency deterministically. Band endpoints are inclusive, and overlapping bands are evaluated independently. `margin_db` is `limit_dbuv - level_dbuv`, rounded to 1e-6 dB before it is classified or written, so decimal inputs such as a 3 dB design margin classify as written rather than by binary floating-point noise. A margin that is not finite (for example from extreme finite inputs) is rejected with an error naming the band.

| Status | Meaning |
|---|---|
| `below_limit_screen` | Margin is at least the requested design margin. |
| `near_limit` | Margin is nonnegative but smaller than the requested design margin. |
| `above_limit_screen` | Margin is negative. |
| `not_assessed` | The band has no points or no limit for the selected detector. |

`--detector` only selects which profile limit is compared. It does not emulate or validate the detector used for the measurement, so `margin_db` is not a detector-specific receiver margin.

An empty band has null worst-point fields. A missing detector limit has a null limit and margin but retains the worst point when one exists. Every result uses `result_class: screening_only` and includes `This comparison is not a compliance determination.` The result also carries `spectrum_source` (the spectrum's `source` object, or `null`) and `profile.source` (the profile's complete `source` object) for provenance.

```json
{
  "schema_version": "harmonic-limit-screen/1",
  "result_class": "screening_only",
  "detector": "peak",
  "design_margin_db": 3.0,
  "spectrum_source": {"kind": "simulation", "description": "synthetic spectral lines"},
  "profile": {
    "profile_id": "fictional-user-profile",
    "source": {"kind": "user_supplied", "citation": "Fictional example — not a regulatory source"}
  },
  "bands": [
    {
      "name": "fictional-band",
      "worst_frequency_hz": 1000000.0,
      "level_dbuv": 42.0,
      "limit_dbuv": 54.0,
      "margin_db": 12.0,
      "status": "below_limit_screen"
    }
  ],
  "claim_boundary": "This comparison is not a compliance determination."
}
```

## Limitations

- Input levels must already be RMS-referenced dBµV.
- No peak-to-RMS conversion is performed.
- No waveform import, FFT, Goertzel analysis, resampling, window correction, receiver-bandwidth integration, detector emulation, uncertainty budget, spread-spectrum estimate, or simulator invocation is included.
- The result does not alter EMC rules, findings, severities, risk scores, test plans, cache artifacts, or `emc.json`.
- A screen below a supplied profile is not evidence of regulatory compliance. Use calibrated equipment and the applicable test method for a compliance determination.

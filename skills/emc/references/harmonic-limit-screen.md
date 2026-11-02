# Harmonic-Limit Screening

`analyze_harmonic_limits.py` compares already-calculated RMS spectral levels (dBµV, dBµV/m, or dBµA) with a user-supplied band-limit profile. The result is an engineering screen, not a compliance determination. The tool does not process waveforms, emulate detector timing or receiver bandwidth, invoke a simulator, or provide regulatory limit tables.

## Command

```bash
python3 skills/emc/scripts/analyze_harmonic_limits.py \
  --spectrum harmonic-lines.json \
  --limits limit-profile.json \
  --limit-column peak \
  --design-margin-db 3 \
  --output harmonic-limit-screen.json
```

The command exits with status 0 when the result is written and 2 on any error (invalid arguments, a missing or unreadable input, invalid JSON, a schema violation, or a failure to write `--output`). Errors are reported on stderr and no result is emitted.

## Spectrum format

The result must be written separately from both inputs. An `--output` path that refers to either input file (including a link to it) is rejected before writing. The result is written to a temporary file in the output directory and then renamed over `--output`, so a failed write leaves any existing file at that path unchanged.

The input must use schema `harmonic-lines/1` and a `level_unit` of `dbuv` (dBµV), `dbuv_per_m` (dBµV/m), or `dbua` (dBµA). Frequencies are positive finite hertz values, each `level` is a finite RMS-referenced value in that unit, and duplicate frequencies are rejected.

Levels must be RMS. A spectrum expressed as sinusoid peak amplitudes must be converted before screening by subtracting 20·log10(√2) ≈ 3.01 dB from every level; the tool cannot detect or correct this. This applies to the EMC skill's own harmonic estimates: `trapezoidal_harmonic_amplitude()` and `harmonic_spectrum()` in `emc_formulas.py` return peak amplitudes (`amplitude_v`, `amplitude_dbuv`), so subtract 3.01 dB from `amplitude_dbuv` to obtain `level`.

An optional `source` must be an object; it is echoed to the output as `spectrum_source` (`null` when absent). Input files must be UTF-8 (a leading byte-order mark is accepted), JSON objects with duplicate keys are rejected rather than resolved last-wins, and non-finite numbers (`NaN`, `Infinity`, `-Infinity`, or a literal such as `1e400` that overflows) are rejected at load time with an error naming the file.

```json
{
  "schema_version": "harmonic-lines/1",
  "level_unit": "dbuv",
  "source": {
    "kind": "simulation",
    "description": "synthetic spectral lines"
  },
  "points": [
    {"frequency_hz": 1000000, "level": 42.0},
    {"frequency_hz": 2000000, "level": 31.5}
  ]
}
```

## Limit-profile format

Profiles use schema `emc-limit-profile/1`. `profile_id`, `limit_unit`, `source.kind`, and `source.citation` are required, and any additional `source` fields (for example a URL or edition) are copied to the output unchanged. A profile needs at least one band. Each uniquely named band has an inclusive positive frequency range and at least one finite limit named `peak`, `quasi_peak`, or `average`, expressed in the profile's `limit_unit` (`dbuv`, `dbuv_per_m`, or `dbua`). `limit_unit` must equal the spectrum's `level_unit`; a mismatch is rejected rather than converted, so for example a dBµV/m radiated limit cannot be compared with conducted dBµV levels.

A limit is either a number (flat across the band) or an object `{"start": <limit at start_hz>, "stop": <limit at stop_hz>}` for a limit that varies linearly with log-frequency across the band, as many conducted-emission limits do between 150 kHz and 500 kHz. The limit at frequency `f` is `start + (stop - start) * log10(f / start_hz) / log10(stop_hz / start_hz)`, rounded to 1e-6 dB; at `start_hz` and `stop_hz` the `start` and `stop` values are used exactly. A band whose `start_hz` equals `stop_hz` must use equal `start` and `stop` values. For example, a fictional quasi-peak limit falling from 66 to 56:

```json
"limits": {"quasi_peak": {"start": 66.0, "stop": 56.0}}
```

The repository does not provide regulatory tables. The following values are fictional and must not be used for a product decision:

```json
{
  "schema_version": "emc-limit-profile/1",
  "profile_id": "fictional-user-profile",
  "limit_unit": "dbuv",
  "source": {
    "kind": "user_supplied",
    "citation": "Fictional example — not a regulatory source"
  },
  "bands": [
    {
      "name": "fictional-band",
      "start_hz": 500000,
      "stop_hz": 1800000,
      "limits": {
        "peak": 54.0,
        "quasi_peak": 41.0,
        "average": 34.0
      }
    }
  ]
}
```

## Comparison and output

For each band, the tool selects the in-band point with the smallest margin (`limit - level`, using the limit at that point's frequency); for a flat limit this is the point with the greatest `level`. Equal margins choose the lower frequency deterministically. Band endpoints are inclusive, and overlapping bands are evaluated independently. `limit` in the output is the limit at `worst_frequency_hz`. `margin_db` is `limit - level`, rounded to 1e-6 dB before it is classified or written, so decimal inputs such as a 3 dB design margin classify as written rather than by binary floating-point noise. A margin that is not finite (for example from extreme finite inputs) is rejected with an error naming the band.

| Status | Meaning |
|---|---|
| `below_limit_screen` | Margin is at least the requested design margin. |
| `near_limit` | Margin is nonnegative but smaller than the requested design margin. |
| `above_limit_screen` | Margin is negative. |
| `not_assessed` | The band has no points or no limit in the selected limit column. |

`--limit-column` only selects which profile limit (`peak`, `quasi_peak`, or `average`) is compared, and the result records it as `limit_column`. It does not emulate or validate the detector used for the measurement, so `margin_db` is not a detector-specific receiver margin.

An empty band has null worst-point fields; it reports a flat limit but a null `limit` for a sloped one. A missing limit for the selected column has a null limit and margin but retains the highest-level point when one exists. Every result uses `result_class: screening_only` and includes `This comparison is not a compliance determination.` The result also carries `spectrum_source` (the spectrum's `source` object, or `null`) and `profile.source` (the profile's complete `source` object) for provenance.

```json
{
  "schema_version": "harmonic-limit-screen/1",
  "result_class": "screening_only",
  "limit_column": "peak",
  "design_margin_db": 3.0,
  "level_unit": "dbuv",
  "spectrum_source": {"kind": "simulation", "description": "synthetic spectral lines"},
  "profile": {
    "profile_id": "fictional-user-profile",
    "source": {"kind": "user_supplied", "citation": "Fictional example — not a regulatory source"}
  },
  "bands": [
    {
      "name": "fictional-band",
      "worst_frequency_hz": 1000000.0,
      "level": 42.0,
      "limit": 54.0,
      "margin_db": 12.0,
      "status": "below_limit_screen"
    }
  ],
  "claim_boundary": "This comparison is not a compliance determination."
}
```

## Limitations

- Input levels must already be RMS-referenced and in the same unit as the profile limits.
- No peak-to-RMS conversion is performed; subtract 3.01 dB from peak-amplitude levels first.
- No waveform import, FFT, Goertzel analysis, resampling, window correction, receiver-bandwidth integration, detector emulation, uncertainty budget, spread-spectrum estimate, or simulator invocation is included.
- The result does not alter EMC rules, findings, severities, risk scores, test plans, cache artifacts, or `emc.json`.
- A screen below a supplied profile is not evidence of regulatory compliance. Use calibrated equipment and the applicable test method for a compliance determination.

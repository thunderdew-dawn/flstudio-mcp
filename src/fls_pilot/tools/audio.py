"""Audio analysis (Integration 2/3): tempo + key (Stage 1).

Pure server-side analysis -- does NOT touch FL. librosa/numpy are imported
LAZILY inside the functions so the MCP server starts fast and stays usable
even if the optional [audio] extra isn't installed.

Key detection (Krumhansl-Schmuckler chroma correlation) is ~60-80% accurate and
often confuses relative major/minor -- always labelled 'estimated'.
"""

from __future__ import annotations

import os
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

# Krumhansl-Schmuckler key profiles (C-rooted; rotated per candidate tonic).
_KS_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
_KS_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
_NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def estimate_key(chroma_mean):
    """12-bin mean chroma -> {key, tonic, mode, confidence, estimated}."""
    import numpy as np

    maj, minr = np.array(_KS_MAJOR), np.array(_KS_MINOR)
    best = None
    for i in range(12):
        for mode, prof in (("major", maj), ("minor", minr)):
            r = float(np.corrcoef(np.roll(prof, i), chroma_mean)[0, 1])
            if best is None or r > best["confidence"]:
                best = {"tonic": _NOTES[i], "mode": mode, "confidence": r}
    return {
        "key": "{} {}".format(best["tonic"], best["mode"]),
        "tonic": best["tonic"],
        "mode": best["mode"],
        "confidence": round(best["confidence"], 3),
        "estimated": True,
    }


def audio_analyze(path):
    """Tempo (beat_track), estimated key, duration, beat/onset counts."""
    import librosa
    import numpy as np

    y, sr = librosa.load(path, mono=True)  # WAV direct; MP3 via ffmpeg
    duration = float(librosa.get_duration(y=y, sr=sr))
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
    tempo = float(np.atleast_1d(tempo).ravel()[0])
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    key = estimate_key(chroma.mean(axis=1))
    onsets = librosa.onset.onset_detect(y=y, sr=sr)
    out = {
        "path": str(path),
        "duration_sec": round(duration, 2),
        "tempo_bpm": round(tempo, 1),
        "beats": int(len(beats)),
        "onsets": int(len(onsets)),
        "key": key,
        "note": "key is ESTIMATED (~60-80% accurate; may confuse relative major/minor)",
    }
    # beat_track often locks to 2x on busy material -> surface the halved value.
    if tempo > 180.0:
        out["tempo_bpm_likely"] = round(tempo / 2.0, 1)
        out["tempo_note"] = (
            "tempo > 180 BPM -- likely a 2x (octave) detection; "
            "tempo_bpm_likely is the halved, probably-real value"
        )
    return out


def analyze_bands(path):
    """Reference-track tonal profile: overall level (rms/peak dBFS) + low/mid/high
    spectral-band energy SHARES (%). Offline; reuses librosa (cheap STFT)."""
    import librosa
    import numpy as np

    y, sr = librosa.load(path, mono=True)
    if not y.size:
        return {"path": str(path), "error": "empty audio"}
    rms = float(np.sqrt(np.mean(y**2)))
    peak = float(np.max(np.abs(y)))
    n_fft = 2048
    S = np.abs(librosa.stft(y, n_fft=n_fft)) ** 2
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    low = float(S[freqs < 250].sum())
    mid = float(S[(freqs >= 250) & (freqs < 4000)].sum())
    high = float(S[freqs >= 4000].sum())
    total = (low + mid + high) or 1.0
    return {
        "path": str(path),
        "duration_sec": round(float(librosa.get_duration(y=y, sr=sr)), 2),
        "rms_db": round(20 * np.log10(rms), 1) if rms > 0 else None,
        "peak_db": round(20 * np.log10(peak), 1) if peak > 0 else None,
        "bands_pct": {
            "low": round(100 * low / total, 1),
            "mid": round(100 * mid / total, 1),
            "high": round(100 * high / total, 1),
        },
        "band_edges_hz": {"low": "<250", "mid": "250-4000", "high": ">4000"},
    }


# -- pitch engines ----------------------------------------------------------
# Two monophonic pitch trackers share one segmenter/quantizer:
#   pyin  -- librosa, light, instant, lower accuracy (ships in [audio]).
#   crepe -- torchcrepe deep model: ~500MB (torch), slower on CPU, but much
#            higher accuracy AND meaningful confidence (ships in
#            [audio-accurate]). Engine resolves: arg -> $FLS_PILOT_PITCH_ENGINE
#            -> "auto" (= crepe if torch+torchcrepe import, else pyin).


def _crepe_available() -> bool:
    try:
        import torch  # noqa: F401
        import torchcrepe  # noqa: F401

        return True
    except Exception:
        return False


def resolve_pitch_engine(engine=None) -> str:
    """Pick 'crepe' or 'pyin' from arg / env / availability."""
    if not engine:
        engine = os.environ.get("FLS_PILOT_PITCH_ENGINE", "auto")
    engine = str(engine).lower()
    if engine == "auto":
        return "crepe" if _crepe_available() else "pyin"
    if engine == "crepe" and not _crepe_available():
        return "pyin"  # asked for crepe but not installed
    return engine if engine in ("pyin", "crepe") else "pyin"


def _pitch_pyin(y, sr, fmin, fmax):
    """librosa pyin -> (f0 [NaN where unvoiced], conf, times); conf = voiced prob."""
    import librosa
    import numpy as np

    f0, _voiced, vprob = librosa.pyin(y, fmin=fmin, fmax=fmax, sr=sr)
    times = librosa.times_like(f0, sr=sr)
    return f0, np.nan_to_num(vprob, nan=0.0), times


def _pitch_crepe(y, sr, fmin, fmax, voiced_floor=0.3, hop_sec=0.01):
    """torchcrepe -> (f0 [NaN where conf<voiced_floor], periodicity, times).

    CREPE emits a pitch every frame; we NaN-out sub-floor frames so the shared
    segmenter treats them as silence -- same contract as pyin's f0."""
    import librosa
    import numpy as np
    import torch
    import torchcrepe

    target_sr = 16000  # CREPE is trained at 16 kHz
    if sr != target_sr:
        y = librosa.resample(y, orig_sr=sr, target_sr=target_sr)
    hop = int(target_sr * hop_sec)
    audio = torch.tensor(y, dtype=torch.float32).unsqueeze(0)
    pitch, period = torchcrepe.predict(
        audio,
        target_sr,
        hop_length=hop,
        fmin=float(fmin),
        fmax=float(fmax),
        model="full",
        return_periodicity=True,
        batch_size=512,
        device="cpu",
    )
    f0 = pitch.squeeze(0).cpu().numpy().astype(float).copy()
    conf = period.squeeze(0).cpu().numpy().astype(float)
    f0[conf < voiced_floor] = np.nan
    times = np.arange(len(f0)) * hop / float(target_sr)
    return f0, conf, times


def _segment_notes(f0, conf, times, min_note_sec):
    """Group consecutive same-rounded-pitch voiced (non-NaN) frames into
    (midi, start_sec, dur_sec, mean_conf) tuples. Engine-agnostic."""
    import librosa
    import numpy as np

    midi = librosa.hz_to_midi(f0)
    raw, cur, start, probs = [], None, None, []

    def flush(end_t):
        if cur is not None and start is not None and (end_t - start) >= min_note_sec:
            raw.append(
                (
                    int(round(cur)),
                    float(start),
                    float(end_t - start),
                    float(np.mean(probs)) if probs else 0.0,
                )
            )

    for i in range(len(f0)):
        if not np.isnan(midi[i]):
            if cur is None or int(round(midi[i])) != int(round(cur)):
                flush(times[i])
                cur, start, probs = midi[i], times[i], [conf[i]]
            else:
                probs.append(conf[i])
        else:
            flush(times[i])
            cur = start = None
            probs = []
    if len(times):
        flush(times[-1])
    return raw


_DEFAULT_MIN_CONF = {"crepe": 0.8, "pyin": 0.0}  # pyin conf doesn't discriminate -> keep all
_QUALITY = {
    "crepe": (
        "CREPE (torchcrepe deep pitch tracker): strong on solo/sung/lead; "
        "confidence is MEANINGFUL -- min_conf gate filters most errors. "
        "Monophonic; review before writing (in-key != correct note)."
    ),
    "pyin": (
        "pyin = MONOPHONIC only: clean on solo vocal/lead/isolated stem; "
        "ROUGH/unreliable on full polyphonic mixes -- review before writing"
    ),
}


def audio_extract_melody(
    path,
    bpm=None,
    quantize=1 / 16.0,
    min_note_sec=0.06,
    fmin_note="C2",
    fmax_note="C7",
    min_conf=None,
    engine=None,
    voiced_floor=0.3,
):
    """Transcribe a MONOPHONIC melody into quantized notes.

    engine: "crepe" (accurate, needs [audio-accurate]), "pyin" (light), or
    "auto"/None (crepe if installed, else pyin; also reads
    $FLS_PILOT_PITCH_ENGINE). min_conf defaults per engine (crepe 0.8,
    pyin 0.0).

    Returns ALL detected notes, each with voiced_prob + a `kept` flag
    (kept = voiced_prob >= min_conf). bridge_notes holds ONLY kept notes, so a
    caller can write the confident set while still seeing/keeping low-conf ones.
    """
    import librosa
    import numpy as np

    y, sr = librosa.load(path, mono=True)
    fmin = float(librosa.note_to_hz(fmin_note))
    fmax = float(librosa.note_to_hz(fmax_note))

    eng = resolve_pitch_engine(engine)
    if min_conf is None:
        min_conf = _DEFAULT_MIN_CONF.get(eng, 0.0)

    if eng == "crepe":
        f0, conf, times = _pitch_crepe(y, sr, fmin, fmax, voiced_floor=voiced_floor)
    else:
        f0, conf, times = _pitch_pyin(y, sr, fmin, fmax)

    if bpm is None:
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        bpm = float(np.atleast_1d(tempo).ravel()[0])
        if bpm > 180.0:
            bpm /= 2.0

    raw = _segment_notes(f0, conf, times, min_note_sec)
    barlen = 4.0 * 60.0 / bpm  # seconds per 4/4 bar

    def q(x):
        return round(round(x / quantize) * quantize, 4) if quantize else round(x, 4)

    notes, bridge, kept = [], [], 0
    for pitch, st, dur, pr in raw:
        is_kept = pr >= min_conf
        notes.append(
            {
                "midi": pitch,
                "name": str(librosa.midi_to_note(pitch, unicode=False)),
                "start_sec": round(st, 3),
                "dur_sec": round(dur, 3),
                "voiced_prob": round(pr, 3),
                "kept": bool(is_kept),
            }
        )
        if is_kept:
            kept += 1
            bridge.append(
                {
                    "pitch": pitch,
                    "time_bars": q(st / barlen),
                    "length_bars": max(q(dur / barlen), quantize),
                    "velocity": 0.787,
                }
            )
    kept_notes = [n for n in notes if n["kept"]]
    conf_mean = (
        round(float(np.mean([n["voiced_prob"] for n in kept_notes])), 3) if kept_notes else 0.0
    )
    return {
        "path": str(path),
        "engine": eng,
        "bpm_used": round(bpm, 1),
        "note_count": len(notes),
        "kept_count": kept,
        "confidence": conf_mean,
        "filters": {
            "fmin": fmin_note,
            "fmax": fmax_note,
            "min_conf": min_conf,
            "voiced_floor": voiced_floor if eng == "crepe" else None,
            "below_gate": len(notes) - kept,
        },
        "quality": _QUALITY.get(eng, _QUALITY["pyin"]),
        "notes": notes[:200],
        "bridge_notes": bridge[:200],
    }


def register(mcp: FastMCP) -> None:
    _RO = {
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
        "safetyClass": "read-only",
    }

    @mcp.tool(annotations={"title": "Analyze audio (tempo/key)", **_RO})
    def fl_analyze_audio(
        path: Annotated[
            str, Field(description="Path to a WAV/MP3 file (MP3 needs ffmpeg on PATH).")
        ],
    ) -> dict:
        """Estimate tempo + key (+ duration, beats, onsets) of an audio file.
        Pure offline analysis -- does NOT touch FL. Key is ESTIMATED.

        Safety: Read-Only.
        """
        import os

        if not os.path.isfile(path):
            return {"ok": False, "error": f"file not found: {path}"}
        try:
            return {"ok": True, **audio_analyze(path)}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    @mcp.tool(annotations={"title": "Extract melody from audio (pyin/CREPE)", **_RO})
    def fl_extract_melody(
        path: Annotated[
            str, Field(description="Path to a MONOPHONIC source (solo vocal/lead/stem).")
        ],
        bpm: Annotated[
            float | None,
            Field(description="Override BPM for bar quantization; auto-detected if omitted."),
        ] = None,
        engine: Annotated[
            str | None,
            Field(
                description=(
                    "Pitch engine: 'crepe' (needs [audio-accurate]), 'pyin' (light), "
                    "or 'auto' (crepe if installed). Overrides $FLS_PILOT_PITCH_ENGINE."
                )
            ),
        ] = None,
        min_conf: Annotated[
            float | None,
            Field(
                description=(
                    "Confidence gate 0..1 for bridge_notes (default 0.8 crepe / "
                    "0.0 pyin). All notes are returned with voiced_prob."
                )
            ),
        ] = None,
    ) -> dict:
        """Transcribe a monophonic melody to quantized notes; engine-selectable
        (CREPE = accurate/heavy, pyin = light). Returns ALL notes with confidence
        + a `kept` flag; bridge_notes holds only the confident notes, ready for
        fl_write_piano_roll_notes. Does NOT write to FL -- review first.

        Safety: Read-Only.
        """
        import os

        if not os.path.isfile(path):
            return {"ok": False, "error": f"file not found: {path}"}
        try:
            return {"ok": True, **audio_extract_melody(path, bpm, engine=engine, min_conf=min_conf)}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

"""The frame-exact work of a film made on its audio (film.py), run on real ffmpeg with small made-up clips and tones."""

import asyncio

import pytest

from scene import film, media


def run(coro):
    return asyncio.run(coro)


def clip(path, seconds, size="64x64", colour="blue", sound=False):
    source = ["-f", "lavfi", "-i", "color=c={}:s={}:r=24:d={}".format(colour, size, seconds)]
    if sound:
        source += ["-f", "lavfi", "-i", "sine=frequency=440:duration={}".format(seconds)]
    run(media._ffmpeg("-loglevel", "error", *source, "-pix_fmt", "yuv420p", "-c:v", "libx264", path))
    return path


def tones(path, parts):
    """A sound of tones and silences: parts is [(seconds, loud)], loud True for a tone."""
    graph, labels = [], ""
    for i, (seconds, loud) in enumerate(parts):
        graph.append("sine=frequency=300:duration={0},volume={1}[p{2}]".format(seconds, 0.5 if loud else 0, i))
        labels += "[p{}]".format(i)
    graph.append("{}concat=n={}:v=0:a=1[a]".format(labels, len(parts)))
    run(media._ffmpeg("-loglevel", "error", "-filter_complex", ";".join(graph), "-map", "[a]", "-ar", "16000", path))
    return path


def test_reference_is_1500_on_the_longer_side_and_never_larger(tmp_path):
    run(media._ffmpeg("-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=3000x1500", "-frames:v", "1", tmp_path / "big.png"))
    run(media._ffmpeg("-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=800x600", "-frames:v", "1", tmp_path / "small.png"))
    big = run(film.reference(tmp_path / "big.png", tmp_path / "big_1500.png"))
    small = run(film.reference(tmp_path / "small.png", tmp_path / "small_1500.png"))
    assert (big["width"], big["height"]) == (1500, 750)
    assert (small["width"], small["height"]) == (800, 600)


def test_audio_slice_is_the_exact_frames(tmp_path):
    tones(tmp_path / "master.wav", [(3, True)])
    made = run(film.audio_slice(tmp_path / "master.wav", 24, 60, tmp_path / "c1.wav"))
    assert made["seconds"] == 1.5
    assert abs(run(media.probe(tmp_path / "c1.wav"))["seconds"] - 1.5) < 0.01
    with pytest.raises(media.MediaError):
        run(film.audio_slice(tmp_path / "master.wav", 24, 240, tmp_path / "c2.wav"))   # past the end


def test_timing_track_has_one_block_per_shot_at_its_frames(tmp_path):
    made = run(film.timing_track([30, 45, 50], tmp_path / "t1.mp4"))
    assert made["frames"] == 125 and run(film.frames_of(tmp_path / "t1.mp4")) == 125
    short = run(film.timing_track([20, 30], tmp_path / "t2.mp4"))
    assert short["frames"] == film.MIN_FRAMES and short["blocks"] == [20, 76]


def test_trim_cuts_holds_a_few_frames_and_refuses_more(tmp_path):
    clip(tmp_path / "c.mp4", 3)                                        # 72 frames
    made = run(film.trim(tmp_path / "c.mp4", 50, tmp_path / "t.mp4", size=(96, 96)))
    assert made["frames"] == 50 and run(film.frames_of(tmp_path / "t.mp4")) == 50
    assert run(media.probe(tmp_path / "t.mp4"))["width"] == 96
    held = run(film.trim(tmp_path / "c.mp4", 80, tmp_path / "h.mp4", size=(96, 96)))
    assert held["held"] == 8 and run(film.frames_of(tmp_path / "h.mp4")) == 80
    with pytest.raises(media.MediaError):
        run(film.trim(tmp_path / "c.mp4", 100, tmp_path / "x.mp4", size=(96, 96)))
    stretched = run(film.trim(tmp_path / "c.mp4", 100, tmp_path / "s.mp4", stretch=1.4, size=(96, 96)))
    assert stretched["frames"] == 100


def test_segment_map_puts_the_speech_on_the_master_and_lasts_the_chunk():
    def length(segments):
        return sum((e - s) * f for s, e, f in segments)
    # the clip says the line early and fast: at 1.0-2.0, where the master has it at 3.0-4.5
    segments = film.segment_map([{"master": [3.0, 4.5], "clip": [1.0, 2.0]}], 8.0, 6.0)
    assert abs(length(segments) - 8.0) < 0.01
    assert segments[1] == [1.0, 2.0, 1.5]                        # the speech slowed onto its 1.5 s
    assert abs((segments[0][1] - segments[0][0]) * segments[0][2] - 3.0) < 0.01   # it starts at 3.0
    # far too fast: the factor stops at 2 and the rest of the time goes to the gap after it
    capped = film.segment_map([{"master": [1.0, 5.0], "clip": [1.0, 2.0]}], 8.0, 6.0)
    assert capped[1][2] == film.SPEECH_FACTOR[1] and abs(length(capped) - 8.0) < 0.01
    # a long opening gap that would need more than 1.4x is cut from its start, at normal speed
    cut = film.segment_map([{"master": [1.0, 2.0], "clip": [4.0, 5.0]}], 5.0, 6.0)
    assert cut[0] == [3.0, 4.0, 1.0] and abs(length(cut) - 5.0) < 0.01
    # speech at the clip's very start but late in the master: the first frame is held until then
    held = film.segment_map([{"master": [2.0, 3.0], "clip": [0.0, 1.0]}], 4.0, 4.0)
    assert held[0][1] - held[0][0] == pytest.approx(1 / 24, abs=1e-3) and abs(length(held) - 4.0) < 0.01


def test_retime_makes_exactly_the_chunks_frames(tmp_path):
    clip(tmp_path / "c.mp4", 4)
    segments = film.segment_map([{"master": [2.0, 3.0], "clip": [0.0, 1.0]}], 4.0, 4.0)
    made = run(film.retime(tmp_path / "c.mp4", segments, 96, tmp_path / "r.mp4", size=(64, 64)))
    assert made["frames"] == 96 and run(film.frames_of(tmp_path / "r.mp4")) == 96


def test_proof_sheets_sixty_frames_to_a_sheet(tmp_path):
    clip(tmp_path / "c.mp4", 3)
    marks = [{"at": i * 0.04, "label": "u{:03d} 00:{:04.1f}".format(i, i * 0.04)} for i in range(61)]
    sheets = run(film.proof_sheets(tmp_path / "c.mp4", marks, tmp_path / "proof.png"))
    assert [p.name for p in sheets] == ["proof.png", "proof_2.png"]
    first = run(media.probe(sheets[0]))
    assert first["width"] == 6 * film.SHEET_TILE + 5 * 4      # six tiles and the padding between them


def test_cues_keep_to_two_rows_of_28_and_to_the_speech():
    lines = [{"start": 0.0, "end": 9.0, "text": "The storm came over the hills before anyone in the village had woken up",
              "speaker": "narrator", "lead": True},
             {"start": 10.0, "end": 11.5, "text": "Run!", "speaker": "maya"}]
    cues = film.subtitle_cues(lines)
    for _, _, text in cues:
        rows = text.split(r"\N")
        assert len(rows) <= 2 and all(len(r) <= film.ROW_CHARS for r in rows)
    # 14 words of narration need 5.6 s; the line lasts 9, so the 3.4 s of music before it get no subtitle
    assert cues[0][0] == pytest.approx(3.4) and cues[-2][1] == pytest.approx(9.0)
    assert cues[-1] == (10.0, 11.5, "Run!")
    assert film._clock(3661.25) == "1:01:01.25"


def test_burned_subtitles_and_the_join_on_the_master(tmp_path):
    a = clip(tmp_path / "a.mp4", 1, size="160x160")
    b = clip(tmp_path / "b.mp4", 1, size="160x160", colour="green")
    trims = [run(film.trim(c, 24, tmp_path / ("t" + c.name), size=(160, 160))) and tmp_path / ("t" + c.name) for c in (a, b)]
    tones(tmp_path / "master.wav", [(1, True), (1, False)])
    made = run(film.join_on_master(trims, tmp_path / "master.wav", tmp_path / "film.mp4"))
    assert made["frames"] == 48
    found = run(media.probe(tmp_path / "film.mp4"))
    assert found["audio"] and abs(found["seconds"] - 2.0) < 0.06
    subbed = run(film.burn_subtitles(tmp_path / "film.mp4", [(0.0, 1.0, "Hello")], tmp_path / "subs.mp4"))
    assert subbed["cues"] == 1 and run(media.probe(tmp_path / "subs.mp4"))["audio"]
    tones(tmp_path / "long.wav", [(3, True)])
    with pytest.raises(media.MediaError):   # pictures and master that do not match are refused
        run(film.join_on_master(trims, tmp_path / "long.wav", tmp_path / "bad.mp4"))


def test_speech_spans_drop_the_narration_around_a_line(tmp_path):
    # narration 0-2 s, silence, the character 3-4.5 s, silence, narration 5.5-7 s
    tones(tmp_path / "voice.wav", [(2, True), (1, False), (1.5, True), (1, False), (1.5, True)])
    lines = [{"n": 1, "start": 0.0, "end": 2.2, "speaker": "narrator"},
             {"n": 2, "start": 2.0, "end": 5.0, "speaker": "maya"},     # the transcript puts it early and long
             {"n": 3, "start": 5.2, "end": 7.0, "speaker": "narrator"}]
    spans = run(film.speech_spans(tmp_path / "voice.wav", lines))
    assert list(spans) == [2]
    assert spans[2][0] == pytest.approx(3.0, abs=0.03) and spans[2][1] == pytest.approx(4.5, abs=0.03)
    runs = run(film.speech_runs(tmp_path / "voice.wav", [[2.5, 5.0]]))
    assert len(runs[0]) == 1 and runs[0][0][0] == pytest.approx(3.0, abs=0.03)

# Scene.ai workflows: report (2026-10-19)

All workflows were built and tested on the render PC (RTX 5090 32 GB, ComfyUI 0.38.0, torch 2.14.0+cu130).
No existing workflow was changed. Open models only, no API nodes.

Files: `scene_ai_workflows/<kind>/<name>.json` (UI format, also saved in ComfyUI's workflow list),
`<name>_api.json` (API export) and `<name>.studio.json` (sidecar). Node ids are the same in all three.

## Custom nodes

| Pack | Source | Notes |
|---|---|---|
| `comfyui_scene_ai_nodes` (new) | local folder `ComfyUI/custom_nodes/comfyui_scene_ai_nodes` (zip in the Library). **No git repo yet**: say if you want it pushed to one | 9 nodes: `SceneQwenEditRefs`, `SceneAspectSize`, `SceneH3Chunk`, `SceneH3ShotPins`, `SceneVoiceSeparate`, `SceneSaveAudioWav`, `SceneTranscribe`, `SceneLipSync` |
| bundled in it: LatentSync code | github.com/bytedance/LatentSync @ `a229c3948406bc2cf6eaf4873e662e70c6a04746` (Apache-2.0) | used by `SceneLipSync`; InsightFace detector replaced with MediaPipe |
| `h3_optional_refs.py` (existing) | local file | H3OptionalImage / Video / Audio, H3OptionalGuides |
| `seedvr2_videoupscaler` (existing) | local folder, not a git checkout | SeedVR2 image upscale in the image workflows |

pip packages added (torch, torchaudio, numpy unchanged; list before: `packages_before_scene_ai.txt`):
`pyannote.audio 4.0.7`, `demucs 4.1.0`, `mediapipe 1.1.1` (no-deps), `decord 0.6.0`, `DeepCache 0.1.1`, `ffmpeg-python`, `soundfile`, `scikit-image`, `numba`, `face-alignment` and their deps.

## Models

| File (folder under ComfyUI/models) | Source | Size | License | Commercial |
|---|---|---|---|---|
| qwen_image_edit_2511_fp8mixed.safetensors (diffusion_models) | Comfy-Org/Qwen-Image-Edit_ComfyUI (installed earlier) | 20.5 GB | Apache-2.0 | yes |
| qwen_2.5_vl_7b_fp8_scaled.safetensors (text_encoders) | Comfy-Org/Qwen-Image_ComfyUI | 9.4 GB | Apache-2.0 | yes |
| qwen_image_vae.safetensors (vae) | Comfy-Org/Qwen-Image_ComfyUI | 254 MB | Apache-2.0 | yes |
| Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors (loras) | lightx2v/Qwen-Image-Edit-2511-Lightning (installed earlier) | 850 MB | Apache-2.0 | yes |
| RealESRGAN_x2plus.pth (upscale_models) | xinntao/Real-ESRGAN | 67 MB | BSD-3 | yes |
| seedvr2_ema_7b_sharp_fp16 + ema_vae_fp16 (SEEDVR2) | SeedVR2 (installed earlier) | 16.5 GB + 0.5 GB | Apache-2.0 | yes |
| MiniMax H3 models (existing h3_director set) | Comfy-Org/MiniMax-H3 | as installed | as already in use | as already in use |
| htdemucs_ft_vocals_04573f0d-f3cf25b2.th (audio_separation) | dl.fbaipublicfiles.com/demucs/hybrid_transformer/04573f0d-f3cf25b2.th | 84 MB | MIT (Demucs) | yes* |
| hdemucs_high_trained.pt (audio_separation, fallback) | download.pytorch.org/torchaudio/models/hdemucs_high_trained.pt | 335 MB | torchaudio (BSD) | yes* |
| whisper/whisper-large-v3 (model.safetensors + configs) | openai/whisper-large-v3 | 3.1 GB | Apache-2.0 (card) / MIT (code) | yes |
| wav2vec2_align/en | jonatasgrosman/wav2vec2-large-xlsr-53-english | 1.3 GB | Apache-2.0 | yes |
| wav2vec2_align/hi (**not downloaded yet**, gated) | ai4bharat/indicwav2vec-hindi | ~1.3 GB | Apache-2.0 | yes |
| pyannote/speaker-diarization-community-1 (**not downloaded yet**, gated) | pyannote/speaker-diarization-community-1 | ~30 MB | CC-BY-4.0 | yes, with attribution |
| latentsync/latentsync_unet.pt + whisper/tiny.pt | ByteDance/LatentSync-1.6 | 5.1 GB + 76 MB | OpenRAIL++ | **yes, with use restrictions (flag)** |
| latentsync/sd-vae-ft-mse | stabilityai/sd-vae-ft-mse | 335 MB | MIT | yes |
| latentsync/face_landmarker.task | MediaPipe (storage.googleapis.com/mediapipe-models) | 3.7 MB | Apache-2.0 | yes |

\* Demucs weights are MIT-licensed; they were trained on MUSDB18-HQ, whose audio is licensed for research. Common practice treats the weights as usable; your legal call.

Rejected on license: Qwen Image 2.1 (Qwen Research License, non-commercial), FLUX.2 Klein 9B (FLUX non-commercial),
FLUX.1 Kontext [dev] (non-commercial), InsightFace buffalo models that upstream LatentSync uses (non-commercial).

## 1. image/image_ref_edit

- Engine: Qwen Image Edit 2511. Compared with Qwen Image Edit 2509 and JoyAI Image Edit Plus (Apache-2.0, int8, native 6 references), same tests:
  - 2509: similar sheets, but the man's face drifted in the anchor.
  - JoyAI (1344×768, 40 steps, cfg 4): (a) sheet added a coffee cup and a non-frontal close-up; (b) with 4 separate references
    the image broke into a mosaic with people missing; with the sheets stitched it placed all 3 people but moved the camera closer
    and both women's faces drifted from their sheets; (c) the edit moved the man but shifted the whole frame. Faster (45-90 s final).
  - Kept 2511: best face match and the only one that keeps the camera and pixel alignment.
- Reference 1 = Picture 1 (base / location). References 2-6 are put side by side on one grey canvas = Picture 2
  (`combine = native` gives each its own picture: tested, 75% slower and no better). Bypassed loaders drop out.
- When Reference 1 has the output's aspect ratio, it is encoded at exactly the render size, so edits stay pixel-aligned
  (without this the whole frame shifted/zoomed in test c).
- Aspect: 1:1 → 1536×1536, 16:9 → 2752×1536, 9:16 → 1536×2752, 4:3 → 2048×1536. Rendered at ~1.5 MP
  (1328², 1664×928, 928×1664, 1472×1104) and upscaled: draft = RealESRGAN x2, final = SeedVR2 7B, then exact resize.
- Quality: draft = Lightning LoRA 4 steps cfg 1; final = 40 steps cfg 4 (sidecar rules set `15.steps`, `15.cfg`, `6.strength_model`, `45.switch`).
- Time (warm): draft 16 s for a 4-reference anchor at 2752×1536; final 212 s (render ~180 s + SeedVR2). One-reference sheet: final render 108 s.
- VRAM: the card sits at 30-31 GB during runs (ComfyUI keeps models resident and offloads as needed); fits 32 GB.
- Tests: (a) sheets from one photo for 3 people: full body + head close-up, grey background, faces kept. PASS.
  (b) empty cafe plate + 3 sheets → right 3 people, right count, faces match. PASS.
  (c) "move the man to the counter": only the man moves; mean pixel change on the women's area 12 (vs 26 before the alignment fix). PASS.
- Limits: faces at the back of wide anchors are small, so check them at full size; describe each person by look in the prompt.

## 2. image/image_location_rebuild

- Same engine and sizes; the rebuild instruction (same layout/camera, real materials, no people, add nothing) is built in; PROMPT adds notes.
- Test: a posterised "drawn" cafe → real photo with the same tables, chairs, window, plant, lamp and camera. PASS.
  Draft turned a pink blob into a red chair; final kept colours closer. Time: draft ~9 s, final ~130 s + upscale.

## 3. audio/audio_separate_voice

- Demucs htdemucs_ft vocals model (fallback hdemucs_high), 30 s chunks with 2 s linear crossfade, resampled back to the input rate.
- Outputs (24-bit wav via `SceneSaveAudioWav`, listed in /history like Save Audio under `audio`): node 3 **VOICE STEM**, node 4 music+fx (= input − voice).
- Tests: 60 s synthetic mix → stem length 2,881,234 = input 2,881,234 samples, 0-sample lag, voice SNR 14.8 dB (hdemucs 13.2 dB).
  30-minute mix (86,412,345 samples, 48 kHz stereo) → both stems exactly 86,412,345 samples, 26 s, no OOM.
- Limit: tested on synthetic music + TTS speech, not a real episode.

## 4. audio/audio_transcribe (+ audio_transcribe_video)

- Whisper large-v3 (text, language detection; only the names and special spellings found in SCRIPT go in as Whisper's prompt, never the script text itself) →
  wav2vec2 CTC forced alignment per Whisper segment for every word (times come only from the alignment) →
  pyannote community-1 speakers per word by overlap → one segment per sentence (also split on speaker change).
- Output: `/history` → `outputs["12"]["transcripts"]` = 2 items `{filename, subfolder, type: "output"}`: `.json` and `.srt`
  in `output/scene_ai/`. JSON = `{"language", "segments": [{start, end, speaker, text}], "words": [{start, end, word, speaker}]}`,
  seconds with 3 decimals. Each word also has `aligned`: true = time from forced alignment; false = the segment's text could not belong to its audio
  (did not fit the CTC frames, or faster than 30 letters a second), so that segment keeps Whisper's own word times
  (cross-attention, less precise: mean error 0.12 s in test) instead of failing the job. Words the aligner cannot spell
  (digits, symbols) in an aligned segment get `start`/`end` = null.
- Video variant: `audio_transcribe_video` (Load Video → its sound).
- **HF token**: put a read token in `C:\ComfyUi\scene_ai_workflows\hf_token.txt` after accepting the terms of
  `pyannote/speaker-diarization-community-1` and `ai4bharat/indicwav2vec-hindi`. It is used once to download them into
  `models/pyannote/` and `models/wav2vec2_align/hi`; runs do not need it.
- Test: 27 s two-speaker English clip (49 words): 48/49 word starts within 0.1 s, mean +0.046 s, worst 0.115 s.
  Truth = Windows speech engine word markers (approximate themselves). Time 4.8 s. Speaker labels not yet tested (token).
- Fix 2026-10-20: a filled SCRIPT made the job fail ("targets length is too long for CTC") when Whisper repeated script text over a
  short segment. Now the script only supplies names/spellings, and such a segment falls back to Whisper's word times (aligned = false).
  Retested with a long script: same accuracy (48/49 within 0.1 s), no failure.
- Limits: Hindi and diarization wait on the token; a Hindi+English mix is transcribed in one detected language per file.

## 5. video/h3_chunk

- From h3_director with a new `SceneH3Chunk` node: BACKGROUND / LOCATION (required, Picture 1, gets the anchor),
  CHARACTER 1-5, PROP, PROP 2, EXTRA REFERENCE = **9 image slots, H3's maximum** (MiniMaxH3ReferenceToVideo takes up to 9 images,
  3 videos, 3 audios). A line saying what each <Picture N> is goes in front of the prompt.
- DURATION 4-15 s, decimals. **Frame rule: frames = round(24 × DURATION)** (6.3 s → 151). H3 renders the next 17k+5 count
  (6.3 s → 158) and the workflow trims; the sound is trimmed to frames/24 s.
- Sizes (sidecar option): 512², 768², 864×480, 1344×768, 480×864, 768×1344.
- VOICE TRACK + LIPS FOLLOW AUDIO switch; KEEP GENERATED SOUND off skips audio decoding (silent clip); FINAL QUALITY; SEED.
- Optional frame-exact multi-shot: SHOT CUT FRAMES + SHOT 1-6 KEYFRAME (see E1).
- Time: 6 s 768² draft 48 s, final 198 s; 6.3 s 864×480 draft 38 s; 12 s 864×480 draft with 5 keyframes 83 s. VRAM: uses the whole 32 GB (offloads).
- Tests: 6.3 s → 151 frames, 24 fps, sound 6.2917 s. PASS. Keyframe cuts at 48/84/156/216 → 0 frames off. PASS.

## 6. video/video_lipsync

- LatentSync 1.6 (512 px face model) driven by the voice track at the clip's own fps; MediaPipe picks the face:
  largest / left / right / index (0 = leftmost), tracked frame to frame. Only LatentSync's lower-face mask is re-rendered and
  pasted back with a soft edge. Output: same size, fps and frame count; sound = the voice track padded/cut to the clip.
- MuseTalk 1.5 was not compared: its face preprocessing needs mmcv/mmpose, which have no wheels for this Python 3.13 / torch 2.14 setup.
- Test on a 480×480, 144-frame close-up: 144 frames in, 144 out, 480×480, 24 fps. PASS.
  Changed area 1.4% of the frame (face only); outside it mean change 0.07/255.
  Edge flicker: frame-to-frame change on a ring around the pasted face 1.59 vs 1.32 in the source; no visible flicker. PASS.
  Mouth opening vs voice loudness correlation 0.05 (source) → 0.32 (synced), best at a 2-frame (83 ms) lag.
- Time 79 s for 6 s at 480²; VRAM ~26 GB.
- Limits: small faces (<100 px) sync weakly; mouth trails the voice by ~2 frames; OpenRAIL++ use restrictions on the weights.

## Experiments (h3_chunk / h3_director, 864×480, cafe anchor + 3 character sheets)

- **E1 multi-shot prompt:** H3 makes clean hard cuts with the right shot content and the same faces at draft and final.
  Timing is not reliable. 12 s, cuts asked at 48/84/156/216: draft got 49/126/191/246 (+1/+42/+35/+30 frames),
  final 49/126/197/239 (+1/+42/+41/+23). 13 s, asked 60/108/180/240: got 73/154/216/288 (+13/+46/+36/+48).
  Short shots are stretched; later cuts land late.
- **E2 timing video in MOTION / CAMERA REFERENCE:** cuts 49/122/190/228 vs 48/84/156/216 (+1/+38/+34/+12). Not reliable,
  roughly as bad as E1. The grey blocks did not leak into the picture.
- **What does work:** pinning a keyframe per shot at its first and last frame (MiniMaxH3AddGuide) → cuts at exactly
  48/84/156/216 (0 frames off) at draft and final. Built into h3_chunk as SHOT KEYFRAMES + SHOT CUT FRAMES; keyframes can come
  from image_ref_edit. Cost: a shot drifts back to its keyframe at its end, so a still wide shot stays almost frozen.
  **Plainly: E1 and E2 alone do not give reliable cuts. Either use the keyframe method or one clip per shot.**
- **E3 voice track (narrator + one line at 3.2-5.0 s), LIPS FOLLOW AUDIO on:** the clip's sound is the voice track exactly.
  With "<name> speaks '<line>' at 3.2-5.0 s; nobody else's lips move" only that character's lips move, from about frame 72
  (3.0 s) to frame 120 (5.0 s); others keep lips closed. Without that sentence she starts early (~3.0 s) and turns away; the hint helps.
- **E4 same, voice track off, line in the prompt:** H3 generates its own narrator and line in roughly the right order
  (narration 0-2.5 s, line ~3.0-4.75 s, narration ~6.0-7.5 s); timing and voice are not controllable.
- **E5 anchor fidelity:** in every wide shot the people sit/stand where the anchor puts them (blazer woman left, denim
  woman right, man behind) with faces matching their sheets; when the prompt moves someone, they move.

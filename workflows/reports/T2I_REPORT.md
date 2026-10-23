# Text-to-image workflows (2026-10-21)

19 workflows, all in ComfyUI's workflow list as `image_t2i_<model>` and in
`C:\ComfyUi\ComfyUI_windows_portable\scene_ai_workflows\image\` (UI `.json`, `_api.json`, `.studio.json` sidecar).
Same controls in every one: PROMPT, NEGATIVE PROMPT (where the model uses one), SEED, aspect ratio
(1:1 1536x1536, 16:9 2752x1536, 9:16 1536x2752, 4:3 2048x1536), Quality draft / final
(final = more steps + SeedVR2 upscale). Comparison sheet: `t2i_comparison_final.jpg` (same prompt, seed 42, 16:9, final).

Test prompt: a young Indian woman laughing at a Mumbai street-food stall at dusk, sign reading "MUMBAI CHAAT HOUSE".

| Workflow | Model | Final (s) | Sign text correct | License / monetized use |
|---|---|---|---|---|
| image_t2i_qwen_image_2512 | Qwen-Image 2512 | 96 | yes | Apache-2.0, yes |
| image_t2i_z_image | Z-Image (base) | 66 | yes | Apache-2.0, yes |
| image_t2i_z_image_turbo | Z-Image Turbo | 39 | yes | Apache-2.0, yes |
| image_t2i_hidream_o1 | HiDream-O1 | 46 | yes | MIT, yes |
| image_t2i_flux2_klein_4b | FLUX.2 Klein 4B base | 39 | yes | Apache-2.0, yes |
| image_t2i_flux2_dev | FLUX.2 dev | 79 | yes | FLUX non-commercial; outputs usable |
| image_t2i_sd35_large | SD 3.5 Large | 39 | yes | free under $1M revenue |
| image_t2i_moss_image | MOSS-Image | 67 | yes | Apache-2.0, yes |
| image_t2i_krea2_turbo | Krea 2 Turbo | 33 | yes | Krea 2 Community License (check terms) |
| image_t2i_qwen_image_21 | Qwen Image 2.1 | 52 | mostly (cropped) | research only: **not for monetized posts** |
| image_t2i_flux3_klein | FLUX 3 Image Klein | 39 | mostly (cropped) | Kommunity: outputs OK under $5M revenue |
| image_t2i_hunyuan_image_21 | HunyuanImage 2.1 | 60 | no ("HOUSE HOUSE") | Tencent community, OK in India |
| image_t2i_flux2_klein_9b | FLUX.2 Klein 9B (distilled) | 31 | no | FLUX non-commercial; outputs usable |
| image_t2i_flux1_krea_dev | FLUX.1 Krea dev | 48 | no ("MULIBAI") | FLUX.1 dev non-commercial; outputs usable |
| image_t2i_flux1_schnell | FLUX.1 schnell | 31 | no | Apache-2.0, yes |
| image_t2i_chroma | Chroma1-HD | 56 | no | Apache-2.0, yes |
| image_t2i_lumina2 | Lumina-Image 2.0 | 32 | no | Apache-2.0, yes |
| image_t2i_sdxl | SDXL base | 24 | no (no sign) | OpenRAIL++, yes |
| image_t2i_cogview4 | CogView4-6B | 122 | no | Apache-2.0, yes |

Times are one warm-ish run at final quality including the SeedVR2 upscale to 2752x1536 (draft runs: 7-60 s).
The 32 GB card stays nearly full during runs because ComfyUI keeps models loaded and offloads as needed; every model ran without errors.
CogView4 runs through diffusers (our node `SceneCogView4`) and reloads the model each run, so it is the slowest and its colours are the least natural.

Notes:
- Prompt helpers kept from ComfyUI's templates: FLUX 3 Klein uses BFL's prompt upsampler, MOSS-Image and Krea 2 Turbo their prompt enhancers (your prompt is expanded first).
- Lumina 2 adds a quality system prompt in front of your prompt.
- Distilled models (FLUX.1 schnell, FLUX.2 Klein 9B, FLUX 3 Klein, Z-Image Turbo, Krea 2 Turbo) ignore the negative prompt.
- FLUX.2 dev is larger than the card and runs with offloading.
- ComfyUI was updated to 0.42.3 for FLUX 3 Klein and MOSS-Image (backup + rollback note in `C:\ComfyUi\ComfyUI_windows_portable\backups\`).

## Optional reference images (added 2026-10-22)

Reference loaders are bypassed by default; with no reference the workflow runs exactly as before (tested for all 7, in API and in the ComfyUI UI).
Backups of the previous versions: `C:\ComfyUi\ComfyUI_windows_portable\backups\2026-10-22_t2i_workflows_before_refs\`.

| Workflow | References | What they can be | How to name them in the prompt | Tested with 2 character sheets |
|---|---|---|---|---|
| image_t2i_flux2_klein_4b | 4 | character, face, outfit, product, style, location | "image 1", "image 2" | faces + outfits kept |
| image_t2i_flux2_klein_9b | 4 | same | "image 1", "image 2" | faces + outfits kept |
| image_t2i_flux2_dev | 4 | same | "image 1", "image 2" | faces + outfits kept |
| image_t2i_flux3_klein | 4 | same | `<ref_image_0>`, `<ref_image_1>` | kept only with these tokens |
| image_t2i_hidream_o1 | 4 | character, product, style | "image 1", "image 2" | faces + outfits kept |
| image_t2i_qwen_image_21 | 4 | character, product, style | `<image1>`, `<image2>` | faces + outfits kept (research license) |
| image_t2i_krea2_turbo | 1 | style only (Krea 2 style-reference LoRA, on only when an image is given) | "in the style of the reference" | runs; style effect mild |

No reference support (text only): Qwen-Image 2512, Z-Image, Z-Image Turbo, FLUX.1 schnell, FLUX.1 Krea dev, Chroma, Lumina 2, SD 3.5 Large, SDXL, HunyuanImage 2.1, MOSS-Image, CogView4.
For references with those looks, use image_ref_edit (Qwen Image Edit 2511, up to 6 references).

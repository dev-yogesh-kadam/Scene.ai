# Image generation models: what to download (checked 2026-10-21)

Folders are under `C:\ComfyUi\ComfyUI_windows_portable\ComfyUI\models\`. Links are direct downloads.
"Have" = already on the PC. Output use = can you use the images in monetized Instagram/YouTube posts.

## A. Run on the current ComfyUI (0.38)

| # | Model (version I'll use) | File | Folder | Size | Notes |
|---|---|---|---|---|---|
| 1 | **Qwen-Image 2512** (newest Qwen-Image, Apache-2.0, output use: yes) | [qwen_image_2512_fp8_e4m3fn.safetensors](https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/diffusion_models/qwen_image_2512_fp8_e4m3fn.safetensors) | diffusion_models | 20.4 GB | text encoder + VAE: have |
| | | [Qwen-Image-2512-Lightning-4steps-V1.0-fp32.safetensors](https://huggingface.co/lightx2v/Qwen-Image-2512-Lightning/resolve/main/Qwen-Image-2512-Lightning-4steps-V1.0-fp32.safetensors) | loras | 1.7 GB | draft mode |
| 2 | **Z-Image** base (Apache-2.0, yes) | [z_image_bf16.safetensors](https://huggingface.co/Comfy-Org/z_image/resolve/main/split_files/diffusion_models/z_image_bf16.safetensors) | diffusion_models | 12.3 GB | Turbo: have. Base = full quality with negative prompt |
| 3 | **HiDream-O1** (newest HiDream, MIT, yes) | [hidream_o1_image_fp8_scaled.safetensors](https://huggingface.co/Comfy-Org/HiDream-O1-Image/resolve/main/checkpoints/hidream_o1_image_fp8_scaled.safetensors) | checkpoints | 8.1 GB | |
| | | [gemma4_e4b_it_fp8_scaled.safetensors](https://huggingface.co/Comfy-Org/gemma-4/resolve/main/text_encoders/gemma4_e4b_it_fp8_scaled.safetensors) | text_encoders | 9.1 GB | |
| 3b | HiDream-I1 Full (MIT, yes) | [hidream_i1_full_fp8.safetensors](https://huggingface.co/Comfy-Org/HiDream-I1_ComfyUI/resolve/main/split_files/diffusion_models/hidream_i1_full_fp8.safetensors) | diffusion_models | 17.1 GB | optional; O1 is newer |
| | | [llama_3.1_8b_instruct_fp8_scaled](https://huggingface.co/Comfy-Org/HiDream-I1_ComfyUI/resolve/main/split_files/text_encoders/llama_3.1_8b_instruct_fp8_scaled.safetensors), [clip_g_hidream](https://huggingface.co/Comfy-Org/HiDream-I1_ComfyUI/resolve/main/split_files/text_encoders/clip_g_hidream.safetensors), [clip_l_hidream](https://huggingface.co/Comfy-Org/HiDream-I1_ComfyUI/resolve/main/split_files/text_encoders/clip_l_hidream.safetensors), t5xxl_fp8 (see 6) | text_encoders | 10.7 GB | |
| 4 | **FLUX.2 Klein 4B** (Apache-2.0, yes) | [flux-2-klein-4b.safetensors](https://huggingface.co/Comfy-Org/flux2-klein/resolve/main/split_files/diffusion_models/flux-2-klein-4b.safetensors) | diffusion_models | 7.8 GB | text encoder + VAE: have |
| | | [flux-2-klein-base-4b.safetensors](https://huggingface.co/Comfy-Org/flux2-klein/resolve/main/split_files/diffusion_models/flux-2-klein-base-4b.safetensors) | diffusion_models | 7.8 GB | base = more steps, better quality |
| 5 | **FLUX.1 schnell** (Apache-2.0, yes) | [flux1-schnell.safetensors](https://huggingface.co/Comfy-Org/flux1-schnell/resolve/main/flux1-schnell.safetensors) | diffusion_models | 23.8 GB | VAE (ae): have |
| | FLUX.1 text encoders (shared by 5, 10) | [clip_l.safetensors](https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors), [t5xxl_fp16.safetensors](https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors) | text_encoders | 10.0 GB | |
| 6 | **Chroma1-HD** (Apache-2.0, yes) | [Chroma1-HD-fp8mixed.safetensors](https://huggingface.co/Comfy-Org/Chroma1-HD_repackaged/resolve/main/split_files/diffusion_models/Chroma1-HD-fp8mixed.safetensors) | diffusion_models | 9.2 GB | |
| | | [t5xxl_fp8_e4m3fn_scaled.safetensors](https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn_scaled.safetensors) | text_encoders | 5.2 GB | |
| 7 | **Lumina-Image 2.0** (Apache-2.0, yes) | [lumina_2.safetensors](https://huggingface.co/Comfy-Org/Lumina_Image_2.0_Repackaged/resolve/main/all_in_one/lumina_2.safetensors) | checkpoints | 10.6 GB | all-in-one |
| 8 | **CogView4-6B** (Apache-2.0, yes) | whole repo [zai-org/CogView4-6B](https://huggingface.co/zai-org/CogView4-6B) | `models/diffusers/CogView4-6B` | 31.1 GB | not in core ComfyUI: I'd add a small diffusers node to our pack |
| 9 | **SDXL** (OpenRAIL++, yes) | - | - | have | sd_xl_base_1.0 |
| 10 | **FLUX.1 Krea dev** (newest FLUX.1 dev; non-commercial model, output use: yes per license) | [flux1-krea-dev_fp8_scaled.safetensors](https://huggingface.co/Comfy-Org/FLUX.1-Krea-dev_ComfyUI/resolve/main/split_files/diffusion_models/flux1-krea-dev_fp8_scaled.safetensors) | diffusion_models | 11.9 GB | more photoreal than FLUX.1 dev |
| 10b | FLUX.1 dev (same license) | [flux1-dev.safetensors](https://huggingface.co/Comfy-Org/flux1-dev/resolve/main/flux1-dev.safetensors) | diffusion_models | 23.8 GB | optional |
| 11 | **FLUX.2 dev** (non-commercial model, output use: yes per license) | [flux2_dev_fp8mixed.safetensors](https://huggingface.co/Comfy-Org/flux2-dev/resolve/main/split_files/diffusion_models/flux2_dev_fp8mixed.safetensors) | diffusion_models | 35.5 GB | larger than VRAM, runs with offloading (slow) |
| | | [mistral_3_small_flux2_fp8.safetensors](https://huggingface.co/Comfy-Org/flux2-dev/resolve/main/split_files/text_encoders/mistral_3_small_flux2_fp8.safetensors) | text_encoders | 18.0 GB | VAE: have |
| 12 | **FLUX.2 Klein 9B** (non-commercial model, output use: yes per license) **gated: log in + accept on HF** | [flux-2-klein-9b-fp8.safetensors](https://huggingface.co/black-forest-labs/FLUX.2-klein-9b-fp8) | diffusion_models | ~9 GB | text encoder + VAE: have |
| | | [flux-2-klein-base-9b-fp8.safetensors](https://huggingface.co/black-forest-labs/FLUX.2-klein-base-9b-fp8) | diffusion_models | ~9 GB | |
| 13 | **Qwen Image 2.1** (Qwen Research License: research only, **monetized use not allowed**) | [qwen_image_2.1_int8_convrot](https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/diffusion_models/qwen_image_2.1_int8_convrot.safetensors) (7.3 GB), [qwen3vl_8b_int8_convrot](https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/text_encoders/qwen3vl_8b_int8_convrot.safetensors) (9.4 GB), [qwen_image_2.1_vae_bf16](https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/vae/qwen_image_2.1_vae_bf16.safetensors) (0.7 GB), [prompt enhancer pe_t2i](https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/text_encoders/qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors) (9.5 GB) | diffusion_models / text_encoders / vae | 26.9 GB | |
| 14 | **HunyuanImage 2.1** (Tencent Community License: not EU/UK/S.Korea, fine for India; output use: yes) | [hunyuanimage2.1_fp8_e4m3fn](https://huggingface.co/Comfy-Org/HunyuanImage_2.1_ComfyUI/resolve/main/split_files/diffusion_models/hunyuanimage2.1_fp8_e4m3fn.safetensors) (17.4 GB), [byt5_small_glyphxl_fp16](https://huggingface.co/Comfy-Org/HunyuanImage_2.1_ComfyUI/resolve/main/split_files/text_encoders/byt5_small_glyphxl_fp16.safetensors) (0.4 GB), [hunyuan_image_2.1_vae_fp16](https://huggingface.co/Comfy-Org/HunyuanImage_2.1_ComfyUI/resolve/main/split_files/vae/hunyuan_image_2.1_vae_fp16.safetensors) (0.8 GB) | diffusion_models / text_encoders / vae | 18.6 GB | native 2K; Qwen2.5-VL encoder: have |
| | (optional refiner) | [hunyuanimage2.1_refiner_fp8_e4m3fn](https://huggingface.co/Comfy-Org/HunyuanImage_2.1_ComfyUI/resolve/main/split_files/diffusion_models/hunyuanimage2.1_refiner_fp8_e4m3fn.safetensors) (15.0 GB), [hunyuan_image_refiner_vae_fp16](https://huggingface.co/Comfy-Org/HunyuanImage_2.1_ComfyUI/resolve/main/split_files/vae/hunyuan_image_refiner_vae_fp16.safetensors) (2.5 GB) | | 17.5 GB | |
| 15 | **SD 3.5 Large** (Stability Community License: free under $1M revenue, output use: yes) | [sd3.5_large_fp8_scaled.safetensors](https://huggingface.co/Comfy-Org/stable-diffusion-3.5-fp8/resolve/main/sd3.5_large_fp8_scaled.safetensors) | checkpoints | 14.9 GB | |

**HunyuanImage 3.0: I suggest skipping it.** It is an 80B model with only third-party nodes; on a 32 GB card it needs heavy quantisation or disk offload and runs very slowly. 2.1 is supported natively.

## B. Newer than your list, need a ComfyUI update to 0.41+ first

| Model | Files | Size | License / output use |
|---|---|---|---|
| **FLUX 3 Image Klein** (released 2026-10-15, 5.6B) **gated** | [black-forest-labs/flux-3-image-klein-comfy](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy): flux3-image-klein-bf16 (11.1 GB), qwen3vl_4b_bf16 (8.9 GB), qwen3.5_9b_flux3_prompt_upsampler_int8_convrot (9.7 GB, BFL says always use it), flux2-vae (have) | 29.7 GB | FLUX Kommunity License: output use yes if revenue < $5M |
| **MOSS-Image SFT** (2026-10-16, 5B, strong text and layout control) | [Comfy-Org/MOSS-Image](https://huggingface.co/Comfy-Org/MOSS-Image): moss_image_sft_bf16 (10.2 GB), qwen3.5_9b_int8_convrot (9.7 GB), flux2-vae (have) | 19.9 GB | Apache-2.0, yes |

Skipped: Fibo 2.0 (CC-BY-NC, no monetized use).

**Total for section A without the optional rows: about 300 GB.** Drive C has 693 GB free.

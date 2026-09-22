# Parakeet ASR Notes

The current Parakeet ASR module is intentionally flexible while the setup is still in flux.

## Current State

- Service module: `software/parakeet_asr.nix`
- Enable option: `parakeetAsr.enable = true;`
- Model: `nvidia/parakeet-tdt-0.6b-v3`
- Runtime: CUDA 12 PyTorch Docker image
- API: HTTP transcription service on port `8765`
- Cache/data directory: `/var/lib/parakeet-asr`

## Known Reproducibility Issues

- The service installs some dependencies at runtime with `apt-get` and `pip`.
- Transformers is installed from the live Hugging Face GitHub repository instead of a pinned commit.
- Python package versions are not fully pinned.
- The Docker image is referenced by tag instead of digest.
- First startup depends on network access to Docker Hub, Ubuntu package repos, PyPI, GitHub, and Hugging Face.

## Why This Is Acceptable For Now

Parakeet V3 and its Transformers support are still moving, so keeping the setup loose makes it easier to adapt quickly. Locking everything down too early could make iteration harder.

## Future Hardening Ideas

- Pin the PyTorch CUDA image by digest.
- Pin Transformers to a known working commit.
- Pin Python dependency versions.
- Build a custom image with dependencies preinstalled instead of installing them at service startup.
- Consider building the image declaratively with Nix or `dockerTools`.
- Add a small integration test that checks `/health` and performs a known transcription sample.

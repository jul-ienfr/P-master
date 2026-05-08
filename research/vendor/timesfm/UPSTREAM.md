# TimesFM Upstream Snapshot

Source repository: `https://github.com/google-research/timesfm`
Source branch: `master`
Frozen commit SHA: `d720daa6786539c2566a44464fbda1019c0a82c0`
Snapshot date: `2026-04-17`

Master resolution evidence:
- `git ls-remote https://github.com/google-research/timesfm.git refs/heads/master`
- Resolved on `2026-04-17` to `d720daa6786539c2566a44464fbda1019c0a82c0`

Imported paths:
- `LICENSE`
- `README.upstream.md` (copied from upstream `README.md`)
- `src/timesfm/__init__.py`
- `src/timesfm/configs.py`
- `src/timesfm/timesfm_2p5/timesfm_2p5_base.py`
- `src/timesfm/timesfm_2p5/timesfm_2p5_torch.py`
- `src/timesfm/torch/__init__.py`
- `src/timesfm/torch/dense.py`
- `src/timesfm/torch/normalization.py`
- `src/timesfm/torch/transformer.py`
- `src/timesfm/torch/util.py`

Local patches:
- none inside the vendored source tree

Notes:
- This is a minimal Torch-only snapshot for offline runtime-metric experiments.
- Flax and XReg support are intentionally excluded from this local snapshot.

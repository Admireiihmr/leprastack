"""
foot_pipeline.py
================
Complete foot measurement pipeline for leprosy patient footwear.
Optimised for RTX 4050 6GB VRAM + 16GB RAM.

Views (3 per foot, 6 images total per session):
  plantar — bottom of foot (plantar surface)
  dorsal  — top of foot (dorsal surface)
  medial  — inner side (inner side)

Models: 6 total
  left_sole, left_top, left_side
  right_sole, right_top, right_side

Landmark counts:
  sole : 4  (toe_tip, met1, met5, pternion)
  top  : 4  (toe_tip, met1, met5, pternion)
  side : 6  (toe_tip, met1, met1_apex, arch_low, pternion, foot_leg_jxn)

Hardware strategy:
  Models loaded and unloaded one at a time — never two large
  models in VRAM simultaneously. SAM (~2.5GB) runs and unloads
  before MMPose (~1.5GB) loads. Safe for 6GB VRAM.

Usage
-----
    from foot_pipeline import FootPipeline

    pipeline = FootPipeline(
        sam_path  = "checkpoints/sam_b.pt",
        card_model_path = "checkpoints/card_detector.pt",
        coin_model_path = "checkpoints/coin_detector.pt",
        landmark_configs = {
            ("left",  "plantar"): ("configs/left_sole_hrnet_w32.py",  "checkpoints/left_sole.pth"),
            ("left",  "dorsal"):  ("configs/left_top_hrnet_w32.py",   "checkpoints/left_top.pth"),
            ("left",  "medial"): ("configs/left_side_hrnet_w32.py",  "checkpoints/left_side.pth"),
            ("right", "plantar"): ("configs/right_sole_hrnet_w32.py", "checkpoints/right_sole.pth"),
            ("right", "dorsal"):  ("configs/right_top_hrnet_w32.py",  "checkpoints/right_top.pth"),
            ("right", "medial"): ("configs/right_side_hrnet_w32.py", "checkpoints/right_side.pth"),
        }
    )

    result = pipeline.run(
        patient_id = "PAT-001",
        images = {
            ("left",  "plantar"): "patients/PAT-001/left_plantar.jpg",
            ("left",  "dorsal"):  "patients/PAT-001/left_dorsal.jpg",
            ("left",  "medial"): "patients/PAT-001/left_medial.jpg",
            ("right", "plantar"): "patients/PAT-001/right_plantar.jpg",
            ("right", "dorsal"):  "patients/PAT-001/right_dorsal.jpg",
            ("right", "medial"): "patients/PAT-001/right_medial.jpg",
        }
    )
    print(result.summary())
"""

from __future__ import annotations

import gc
import logging
import math
import platform
import sys
import time
import warnings
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import torch

# NumPy 2.x → 1.x checkpoint compatibility shim. Some checkpoints (e.g. the
# right_side.pth retrain done 2026-04) were pickled in a NumPy 2.x training
# env where the internal module path is `numpy._core`. This inference env
# pins NumPy 1.24 (where it's `numpy.core`), so torch.load → unpickle fails
# with ModuleNotFoundError. Aliasing here lets the unpickler resolve symbols
# without requiring a numpy upgrade (which would risk breaking OpenCV/MMPose).
import sys as _sys
if "numpy._core" not in _sys.modules:
    try:
        import numpy.core as _np_core
        _sys.modules["numpy._core"] = _np_core
        for _sub in ("multiarray", "umath", "_multiarray_umath", "numeric"):
            try:
                _sys.modules[f"numpy._core.{_sub}"] = __import__(f"numpy.core.{_sub}", fromlist=[_sub])
            except Exception:
                pass
    except Exception:
        pass

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("foot_pipeline")

DEVICE   = "cuda" if torch.cuda.is_available() else "cpu"
MAX_SIZE = 1024
log.info(f"Device: {DEVICE}  |  MAX_SIZE: {MAX_SIZE}px")


def _log_pkg_version(name: str) -> None:
    try:
        version = importlib_metadata.version(name)
        log.info("Package %s: %s", name, version)
    except importlib_metadata.PackageNotFoundError:
        log.warning("Package %s: not installed", name)
    except Exception as e:
        log.warning("Package %s: version lookup failed (%s)", name, e)


@lru_cache(maxsize=1)
def _log_environment() -> None:
    log.info("Python: %s", sys.version.split()[0])
    log.info("Platform: %s", platform.platform())
    log.info("OpenCV: %s", cv2.__version__)
    log.info("NumPy: %s", np.__version__)
    log.info("Torch: %s", torch.__version__)
    log.info("Torch CUDA: %s", torch.version.cuda)
    if torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        vram_gb = props.total_memory / (1024 ** 3)
        log.info("GPU: %s | VRAM: %.1f GB", props.name, vram_gb)
    _log_pkg_version("ultralytics")
    _log_pkg_version("mmpose")
    _log_pkg_version("mmengine")
    _log_pkg_version("mmcv")


@lru_cache(maxsize=4)
def _load_calibration(calib_path: Optional[str]) -> Optional[dict]:
    if not calib_path:
        return None
    path = Path(calib_path)
    if not path.exists():
        return None
    try:
        import json
        data = json.loads(path.read_text())
        k = data.get("camera_matrix") or data.get("K")
        dist = data.get("dist_coeffs") or data.get("dist")
        if k is None:
            return None
        k = np.array(k, dtype=np.float32)
        if k.shape != (3, 3):
            return None
        dist_arr = None
        if dist is not None:
            dist_arr = np.array(dist, dtype=np.float32).reshape(-1)
        return {"K": k, "dist": dist_arr}
    except Exception:
        return None


def _load_json(path: str):
    import json

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"JSON not found: {path}")
    return json.loads(p.read_text())


def _dump_json(path: str, data: dict) -> None:
    import json

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as f:
        json.dump(data, f, indent=2)


def _scale_intrinsics(K: np.ndarray, scale_x: float, scale_y: float) -> np.ndarray:
    K = K.copy().astype(np.float32)
    K[0, 0] *= scale_x
    K[1, 1] *= scale_y
    K[0, 2] *= scale_x
    K[1, 2] *= scale_y
    return K


# ═══════════════════════════════════════════════════════════
# LANDMARK DEFINITIONS
# Order must match your MMPose annotation JSON exactly
# ═══════════════════════════════════════════════════════════

LANDMARK_NAMES = {
    "plantar": [
        "toe_tip",   # tip of longest toe
        "met1",      # 1st metatarsal head
        "met5",      # 5th metatarsal head
        "pternion",  # most posterior point of heel
    ],
    "dorsal": [
        # Superset across left+right top models. left_top emits pternion at
        # idx 5; right_top (retrained 2026-04) emits met5_apex at idx 3 instead
        # of pternion (top-down view doesn't see heel back well).
        "toe_tip",      # tip of longest toe
        "met1",         # 1st metatarsal head
        "met1_apex",    # highest point of 1st metatarsal head
        "met5",         # 5th metatarsal head
        "met5_apex",    # highest point of 5th metatarsal head (right_top only)
        "foot_leg_jxn", # where foot meets leg
        "pternion",     # most posterior point of heel (left_top only)
    ],
    "medial": [
        "toe_tip",           # tip of longest toe
        "met1",              # 1st metatarsal head (ground contact)
        "met1_apex",         # highest point of 1st metatarsal head
        "arch_low",          # lowest point of medial arch
        "pternion",          # most posterior point of heel
        "foot_leg_jxn",      # where foot meets leg (ankle reference)
        "lateral_malleolus", # outer ankle bone bump (added 2026-04 retrain)
        "heel_base",         # bottom-rear of heel where it contacts ground (added 2026-04 retrain)
    ],
}

# Map model output index -> canonical landmark name.
# These orders are based on the configs in /configs.
LANDMARK_INDEX_MAP = {
    ("left", "plantar"): [
        "met5", "met1", "toe_tip", "pternion",
    ],
    ("right", "plantar"): [
        "toe_tip", "met5", "pternion", "met1",
    ],
    ("left", "dorsal"): [
        # Retrained 2026-05: now mirrors right_top schema (6 keypoints, no
        # pternion — heel back not visible from above; met5_apex added).
        "toe_tip", "met1", "met1_apex", "met5_apex", "met5", "foot_leg_jxn",
    ],
    ("right", "dorsal"): [
        # Retrained 2026-04: index 3 changed from pternion -> met5_apex.
        # The right_top model no longer predicts pternion (not visible from above).
        "toe_tip", "met1", "met1_apex", "met5_apex", "met5", "foot_leg_jxn",
    ],
    ("left", "medial"): [
        # Retrained 2026-04: 6 -> 8 keypoints. Indices 0-5 unchanged.
        "pternion", "arch_low", "met1", "met1_apex", "toe_tip", "foot_leg_jxn",
        "lateral_malleolus", "heel_base",
    ],
    ("right", "medial"): [
        # Retrained 2026-04: 6 -> 8 keypoints. Indices 0-5 unchanged.
        "pternion", "arch_low", "met1", "met1_apex", "toe_tip", "foot_leg_jxn",
        "lateral_malleolus", "heel_base",
    ],
}

# Confidence threshold — landmarks below this are ignored
CONF_MIN = 0.30

# View-level QC / reliability gates
MASK_CONF_MIN_BY_VIEW = {"plantar": 0.22, "dorsal": 0.24, "medial": 0.24}
MASK_QC_MAX_ROWS_REMOVED_RATIO = {"plantar": 0.65, "dorsal": 0.40, "medial": 0.48}
PRIMARY_LANDMARKS = {
    "plantar": ("toe_tip", "met1", "met5", "pternion"),
    # Dropped pternion: neither left_top (2026-05 retrain) nor right_top
    # (2026-04 retrain) predicts it — heel back is not visible from above.
    "dorsal": ("toe_tip", "met1", "met5"),
    "medial": ("toe_tip", "met1", "met1_apex", "arch_low", "pternion", "foot_leg_jxn"),
}
MIN_PRIMARY_LANDMARKS = {"plantar": 2, "dorsal": 2, "medial": 2}

# Fusion weights — 1.0 = primary source, 0.85 = confirmatory
FUSION_WEIGHTS = {
    "foot_length_mm":     {"plantar": 1.0,  "dorsal": 0.85, "medial": 0.85},
    "forefoot_width_mm":  {"plantar": 1.0,  "dorsal": 0.85},
    "midfoot_width_mm":   {"plantar": 1.0,  "dorsal": 0.85},
    "heel_width_mm":      {"plantar": 1.0,  "dorsal": 0.85},
    "arch_height_mm":     {"medial": 1.0},
    "met1_height_mm":     {"medial": 1.0},
    "malleoli_height_mm": {"medial": 1.0},
    "foot_leg_angle_deg": {"medial": 1.0},
    "toe_axis_angle_deg": {"plantar": 1.0,  "dorsal": 0.85},
}

# ── Phase 1+2 calibration constants ───────────────────────────────────────
# Source: ORIENTATION_AND_CALIBRATION.md (LEPRA 131-patient cohort, 50/50 split).
# Applied only to (field, view) pairs listed in PHASE12_PER_VIEW_STATS;
# everything else falls through to the legacy FUSION_WEIGHTS + _estimate_sigma path.
# Caveat 1 (doc §Caveat 1): bin lookup MUST use raw landmark_conf_mean, NOT
# the blended _view_quality() score.
PHASE12_CONF_BIN_EDGES = [0.0, 0.30, 0.55, 1.01]
PHASE12_CONF_BIN_NAMES = ["low", "med", "high"]

PHASE12_PER_VIEW_STATS = {
    "foot_length/plantar": {
        "bias_mm":  -1.71,
        "sigma_mm": 55.627,
        "sigma_by_conf_bin": {"low": 44.730, "med": 59.467, "high": 53.855},
    },
    "foot_length/dorsal": {
        "bias_mm":  -12.53,
        "sigma_mm": 64.863,
        "sigma_by_conf_bin": {"low": 79.119, "med": 59.059, "high": 59.749},
    },
    "foot_length/medial": {
        "bias_mm":  -43.68,
        "sigma_mm": 41.557,
        "sigma_by_conf_bin": {"low": 56.027, "med": 46.954, "high": 35.998},
    },
    "malleoli_height/medial": {
        "bias_mm":  -4.41,
        "sigma_mm": 20.134,
        "sigma_by_conf_bin": {"low": 23.633, "med": 23.099, "high": 18.607},
    },
}

PHASE12_FUSION_WEIGHTS = {
    "foot_length":     {"plantar": 0.5581, "dorsal": 0.4105, "medial": 1.0},
    "malleoli_height": {"medial": 1.0},
}

PHASE12_GIRTH_FORMULA = {
    "ball_girth":   {"coef": 0.15929501883300753, "intercept": 146.23076505759752},
    "instep_girth": {"coef": 0.01955127450160462,  "intercept": 203.51614724817875},
}

PHASE12_GIRTH_INPUT_RANGES = {
    "width_mm":       (30.0, 220.0),   # leprosy resorption can give genuinely narrow forefeet
    "foot_length_mm": (140.0, 360.0),
}

PHASE12_ISOTONIC_KNOTS = {
    "foot_length": {
        "x": [140.07, 140.71, 144.91, 152.43, 152.75, 159.465, 159.98,
              197.73031299481988, 197.966089493869, 210.22, 210.43,
              271.61, 271.95, 285.9, 286.75333333333333,
              316.78, 317.09, 317.69, 317.76, 322.83, 324.88, 359.17],
        "y": [195.0, 195.0, 235.0, 235.0, 242.0, 242.0,
              247.27777777777777, 247.27777777777777, 251.8181818181818,
              251.8181818181818, 254.10788381742736, 254.10788381742736,
              254.73684210526315, 254.73684210526315, 260.4761904761905,
              260.4761904761905, 265.0, 265.0, 272.0, 272.0, 280.0, 280.0],
    },
    "malleoli_height": {
        "x": [27.22, 27.94, 44.71, 45.04, 59.67, 59.74,
              63.48, 63.62, 105.59, 105.75, 106.55, 112.57, 117.81, 119.79],
        "y": [60.0, 65.0, 65.0, 65.95890410958904, 65.95890410958904,
              66.11111111111111, 66.11111111111111, 68.53932584269663,
              68.53932584269663, 70.0, 75.0, 75.0, 80.0, 80.0],
    },
}


def _phase12_bin(landmark_conf_mean: float) -> str:
    """Bucket landmark_conf_mean into low/med/high per PHASE12_CONF_BIN_EDGES."""
    if landmark_conf_mean < 0.30:
        return "low"
    if landmark_conf_mean < 0.55:
        return "med"
    return "high"


# ═══════════════════════════════════════════════════════════
# STAGE 1 — PREPROCESSING
# ═══════════════════════════════════════════════════════════

def _read_oriented_bgr(image_path: str) -> np.ndarray:
    """
    Load image and apply EXIF rotation in a single trusted step.
    PIL.ImageOps.exif_transpose handles all 8 EXIF orientation tags and
    matches browser thumbnail behaviour, so what the user uploads is what
    the pipeline sees.
    """
    try:
        from PIL import Image, ImageOps
        pil = ImageOps.exif_transpose(Image.open(image_path)).convert("RGB")
        return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    except Exception as e:
        log.warning("[ORIENT] exif_transpose failed (%s); falling back to cv2.imread", e)
        bgr = cv2.imread(image_path)
        if bgr is None:
            raise FileNotFoundError(f"Cannot read: {image_path}")
        return bgr


def preprocess(image_path: str, camera_calib: Optional[str] = None) -> tuple[np.ndarray, np.ndarray, float]:
    """
    Load image, fix EXIF orientation, resize longest edge to MAX_SIZE.

    Returns
    -------
    bgr_orig  : original resolution (H, W, 3) BGR
    bgr_small : resized (H', W', 3) BGR — fed to all models
    scale     : float — bgr_small / bgr_orig pixel ratio
    """
    bgr = _read_oriented_bgr(image_path)
    if camera_calib:
        bgr = _undistort_if_available(bgr, camera_calib)
    h, w  = bgr.shape[:2]
    scale = min(MAX_SIZE / max(h, w), 1.0)

    bgr_small = (
        cv2.resize(bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        if scale < 1.0 else bgr.copy()
    )
    return bgr, bgr_small, scale


def _undistort_if_available(bgr: np.ndarray, calib_path: str) -> np.ndarray:
    """Apply lens distortion correction if calibration is provided."""
    if not calib_path:
        return bgr
    if not Path(calib_path).exists():
        log.warning("Calibration file not found: %s", calib_path)
        return bgr
    try:
        import json
        data = json.loads(Path(calib_path).read_text())
        k = np.array(data.get("camera_matrix", []), dtype=np.float32)
        dist = np.array(data.get("dist_coeffs", []), dtype=np.float32).reshape(-1)
        if k.shape != (3, 3) or dist.size == 0:
            log.warning("Invalid calibration format in %s", calib_path)
            return bgr
        return cv2.undistort(bgr, k, dist)
    except Exception as e:
        log.warning("Calibration load failed (%s): %s", calib_path, e)
        return bgr


# ═══════════════════════════════════════════════════════════
# STAGE 2 — SEGMENTATION  (UNet fine-tuned, SAM fallback; DeepLabV3 legacy)
# Load → run → unload before next model
# ═══════════════════════════════════════════════════════════

# ── UNet-MobileNetV2 foot segmentation (primary) ───────────

_UNET_IMG_SIZE = 384
_UNET_MEAN = (0.485, 0.456, 0.406)
_UNET_STD  = (0.229, 0.224, 0.225)

_DEFAULT_UNET_PATH = "checkpoints/unet_mobilenet_v2_best.pt"


def _load_unet(ckpt_path: str, device: str = DEVICE):
    """Load the fine-tuned UNet-MobileNetV2 foot segmentation model."""
    import segmentation_models_pytorch as _smp
    model = _smp.Unet(encoder_name="mobilenet_v2", encoder_weights=None, in_channels=3, classes=1)
    ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
    model.load_state_dict(ckpt["model_state_dict"])
    model.to(device)
    model.eval()
    return model


# ── DeepLabV3-MobileNetV3 foot segmentation (legacy, kept for reference) ───

_DEEPLABV3_IMG_SIZE = 384
_DEEPLABV3_MEAN = (0.485, 0.456, 0.406)
_DEEPLABV3_STD  = (0.229, 0.224, 0.225)


def _build_deeplabv3_model():
    """Build the DeepLabV3-MobileNetV3 architecture (with aux_classifier)."""
    import torch.nn as _nn
    import torchvision as _tv
    # weights="DEFAULT" ensures aux_classifier is created (None omits it).
    # Our checkpoint will overwrite all weights immediately after.
    base = _tv.models.segmentation.deeplabv3_mobilenet_v3_large(weights="DEFAULT")
    base.classifier[-1] = _nn.Conv2d(256, 1, kernel_size=1)
    base.aux_classifier[-1] = _nn.Conv2d(10, 1, kernel_size=1)

    class _Wrapper(_nn.Module):
        def __init__(self, m):
            super().__init__()
            self.model = m
        def forward(self, x):
            return self.model(x)["out"]

    return _Wrapper(base)


def _load_deeplabv3(ckpt_path: str, device: str = DEVICE):
    """Load the fine-tuned DeepLabV3 foot segmentation model."""
    model = _build_deeplabv3_model()
    ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
    model.load_state_dict(ckpt["model_state_dict"])
    model.to(device)
    model.eval()
    return model


def run_segmentation_deeplabv3(
    bgr_small: np.ndarray,
    seg_model=None,
    seg_model_path: str = "",
    return_meta: bool = False,
    bgr_full: np.ndarray = None,
) -> tuple:
    """
    Segment foot using fine-tuned DeepLabV3-MobileNetV3.
    ~50ms per image vs SAM's ~1-2s.

    Parameters
    ----------
    bgr_small     : resized BGR image (downstream pipeline coordinate frame)
    seg_model     : pre-loaded model (skips load/unload)
    seg_model_path: path to .pt checkpoint (used if seg_model is None)
    return_meta   : if True, return (mask, conf, meta) else (mask, conf)
    bgr_full      : full-resolution BGR. If provided, inference runs on this
                    image and the mask is downsampled back to bgr_small's
                    resolution. Matches the standalone infer_deeplab.py path
                    and avoids the INTER_AREA shrink-to-1024 destroying foot
                    edges on dark-skin/dark-background photos.

    Returns same format as run_segmentation() for drop-in compatibility.
    """
    h, w = bgr_small.shape[:2]
    _own_model = seg_model is None
    if _own_model:
        if not Path(seg_model_path).exists():
            log.error("  [DeepLabV3] Checkpoint not found: %s", seg_model_path)
            return (np.zeros((h, w), dtype=np.uint8), 0.0, {}) if return_meta else (np.zeros((h, w), dtype=np.uint8), 0.0)
        log.info("  [DeepLabV3] Loading...")
        model = _load_deeplabv3(seg_model_path)
    else:
        model = seg_model

    # Preprocess: resize to model input, normalise. Use bgr_full when available
    # so the network sees native edge detail; otherwise fall back to bgr_small.
    seg_src = bgr_full if bgr_full is not None else bgr_small
    src_h, src_w = seg_src.shape[:2]
    rgb = cv2.cvtColor(seg_src, cv2.COLOR_BGR2RGB)
    img_resized = cv2.resize(rgb, (_DEEPLABV3_IMG_SIZE, _DEEPLABV3_IMG_SIZE))
    img_float = img_resized.astype(np.float32) / 255.0
    for c in range(3):
        img_float[:, :, c] = (img_float[:, :, c] - _DEEPLABV3_MEAN[c]) / _DEEPLABV3_STD[c]
    tensor = torch.from_numpy(img_float.transpose(2, 0, 1)).unsqueeze(0).to(DEVICE)

    # Inference
    with torch.inference_mode():
        logits = model(tensor)                        # (1, 1, 384, 384)
        prob = torch.sigmoid(logits)[0, 0].cpu().numpy()  # (384, 384)

    if _own_model:
        del model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()
        log.info("  [DeepLabV3] Unloaded.")

    # Resize probability map back to inference-src resolution, threshold there
    # (matches standalone), then downsample binary mask to bgr_small frame for
    # the rest of the pipeline.
    prob_src = cv2.resize(prob, (src_w, src_h), interpolation=cv2.INTER_LINEAR)
    mask_src = (prob_src >= 0.5).astype(np.uint8)
    if (src_h, src_w) != (h, w):
        mask = cv2.resize(mask_src, (w, h), interpolation=cv2.INTER_NEAREST)
    else:
        mask = mask_src

    # Post-process (same as SAM path)
    mask = _postprocess_mask(mask)
    conf = _mask_confidence(mask)

    if return_meta:
        soft = _soft_mask(mask)
        contour = _contour_prob(mask)
        seg_meta = {
            "soft_mask_mean": float(soft.mean()) if soft is not None else 0.0,
            "soft_mask_max":  float(soft.max()) if soft is not None else 0.0,
            "contour_ratio":  float(contour.mean()) if contour is not None else 0.0,
            "model": "deeplabv3_mobilenet_v3",
        }
        return mask, conf, seg_meta
    return mask, conf


# ── UNet-MobileNetV2 inference ─────────────────────────────

def run_segmentation_unet(
    bgr_small: np.ndarray,
    seg_model=None,
    seg_model_path: str = "",
    return_meta: bool = False,
    bgr_full: np.ndarray = None,
) -> tuple:
    """
    Segment foot using fine-tuned UNet-MobileNetV2 (primary model).
    Drop-in replacement for run_segmentation_deeplabv3.
    Dice=0.953 on training set, same 384×384 ImageNet normalisation.
    """
    h, w = bgr_small.shape[:2]
    _own_model = seg_model is None
    if _own_model:
        if not Path(seg_model_path).exists():
            log.error("  [UNet] Checkpoint not found: %s", seg_model_path)
            return (np.zeros((h, w), dtype=np.uint8), 0.0, {}) if return_meta else (np.zeros((h, w), dtype=np.uint8), 0.0)
        log.info("  [UNet] Loading...")
        model = _load_unet(seg_model_path)
    else:
        model = seg_model

    seg_src = bgr_full if bgr_full is not None else bgr_small
    src_h, src_w = seg_src.shape[:2]
    rgb = cv2.cvtColor(seg_src, cv2.COLOR_BGR2RGB)
    img_resized = cv2.resize(rgb, (_UNET_IMG_SIZE, _UNET_IMG_SIZE))
    img_float = img_resized.astype(np.float32) / 255.0
    for c in range(3):
        img_float[:, :, c] = (img_float[:, :, c] - _UNET_MEAN[c]) / _UNET_STD[c]
    tensor = torch.from_numpy(img_float.transpose(2, 0, 1)).unsqueeze(0).to(DEVICE)

    with torch.inference_mode():
        logits = model(tensor)                              # (1, 1, 384, 384)
        prob = torch.sigmoid(logits)[0, 0].cpu().numpy()   # (384, 384)

    if _own_model:
        del model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()
        log.info("  [UNet] Unloaded.")

    prob_src = cv2.resize(prob, (src_w, src_h), interpolation=cv2.INTER_LINEAR)
    mask_src = (prob_src >= 0.5).astype(np.uint8)
    if (src_h, src_w) != (h, w):
        mask = cv2.resize(mask_src, (w, h), interpolation=cv2.INTER_NEAREST)
    else:
        mask = mask_src

    mask = _postprocess_mask(mask)
    conf = _mask_confidence(mask)

    if return_meta:
        soft = _soft_mask(mask)
        contour = _contour_prob(mask)
        seg_meta = {
            "soft_mask_mean": float(soft.mean()) if soft is not None else 0.0,
            "soft_mask_max":  float(soft.max()) if soft is not None else 0.0,
            "contour_ratio":  float(contour.mean()) if contour is not None else 0.0,
            "model": "unet_mobilenet_v2",
        }
        return mask, conf, seg_meta
    return mask, conf


# ── SAM segmentation (legacy / fallback) ───────────────────

def run_segmentation(
    bgr_small: np.ndarray,
    sam_path: str,
    return_meta: bool = False,
    sam_model=None,
) -> tuple:
    """
    Segment foot using SAM (unprompted, best-mask heuristic).
    If sam_model is provided the model is used directly and not loaded/unloaded.
    Otherwise SAM is loaded, run, and unloaded within this function.

    Returns
    -------
    binary_mask : (H, W) uint8 {0, 1}
    confidence  : float [0, 1]  distance-transform proxy
    """
    h, w = bgr_small.shape[:2]
    _own_model = sam_model is None
    if _own_model:
        try:
            from ultralytics import SAM
        except Exception as e:
            log.error("  [SAM] Import failed: %s", e)
            return np.zeros((h, w), dtype=np.uint8), 0.0
        if not Path(sam_path).exists():
            log.error("  [SAM] Model not found: %s", sam_path)
            return np.zeros((h, w), dtype=np.uint8), 0.0
        log.info("  [SAM] Loading...")
        sam = SAM(sam_path)
        sam.to(DEVICE)
    else:
        sam = sam_model

    rgb  = cv2.cvtColor(bgr_small, cv2.COLOR_BGR2RGB)
    results = None
    ctx = torch.inference_mode if hasattr(torch, "inference_mode") else torch.no_grad
    with ctx():
        try:
            results = sam(rgb, device=DEVICE, verbose=False, retina_masks=False)
        except RuntimeError:
            log.warning("  [SAM] CUDA OOM — retrying on CPU")
            results = sam(rgb, device="cpu", verbose=False, retina_masks=False)
        except Exception as e:
            log.error("  [SAM] Inference failed: %s", e)

    if _own_model:
        del sam
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()
        log.info("  [SAM] Unloaded.")

    if results is None or results[0].masks is None or results[0].masks.data.shape[0] == 0:
        log.warning("  [SAM] No masks returned.")
        return np.zeros((h, w), dtype=np.uint8), 0.0

    masks = results[0].masks.data.cpu().numpy()
    best  = _select_foot_mask(masks, h, w, bgr_small)
    best  = _postprocess_mask(best)
    conf  = _mask_confidence(best)
    if return_meta:
        soft = _soft_mask(best)
        contour = _contour_prob(best)
        seg_meta = {
            "soft_mask_mean": float(soft.mean()) if soft is not None else 0.0,
            "soft_mask_max":  float(soft.max()) if soft is not None else 0.0,
            "contour_ratio":  float(contour.mean()) if contour is not None else 0.0,
        }
        return best, conf, seg_meta
    return best, conf


def _select_foot_mask(masks, h, w, bgr):
    """
    Pick the most foot-like mask from SAM's output.

    Scoring (robust to green mats/background):
      area prior, centrality, skin-likelihood (HSV + YCrCb),
      green-background penalty, border-spill penalty.
    """
    img_area = h * w
    cx_img   = w / 2.0
    cy_img   = h / 2.0
    hsv      = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    ycrcb    = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)

    best_mask, best_score = np.zeros((h, w), dtype=np.uint8), -1.0

    for m in masks:
        mask = m.astype(np.uint8)
        area = int(mask.sum())
        area_ratio = float(area / float(img_area + 1e-6))
        if area_ratio < 0.03 or area_ratio > 0.80:
            continue

        ys, xs = np.where(mask > 0)
        if len(xs) == 0:
            continue

        aspect = (int(ys.max()) - int(ys.min()) + 1) / \
                 (int(xs.max()) - int(xs.min()) + 1e-6)
        if not (0.25 < aspect < 4.0):
            continue

        cx_mask = float(xs.mean())
        cy_mask = float(ys.mean())
        if abs(cx_mask - cx_img) / (w / 2.0) > 0.70:
            continue
        if abs(cy_mask - cy_img) / (h / 2.0) > 0.70:
            continue

        centrality = 1.0 - (
            abs(cx_mask - cx_img) / (w / 2.0) +
            abs(cy_mask - cy_img) / (h / 2.0)
        ) / 2.0

        x1, x2 = int(xs.min()), int(xs.max())
        y1, y2 = int(ys.min()), int(ys.max())
        bbox_area = float((x2 - x1 + 1) * (y2 - y1 + 1))
        fill_ratio = float(area / (bbox_area + 1e-6))
        bbox_aspect = float(max((y2 - y1 + 1), (x2 - x1 + 1)) / (min((y2 - y1 + 1), (x2 - x1 + 1)) + 1e-6))

        h_chan = hsv[:, :, 0][mask > 0].astype(np.float32)
        s_chan = hsv[:, :, 1][mask > 0].astype(np.float32)
        v_chan = hsv[:, :, 2][mask > 0].astype(np.float32)
        skin_hsv = ((h_chan < 25) | (h_chan > 160)) & (s_chan > 15) & (v_chan > 30)

        cr = ycrcb[:, :, 1][mask > 0].astype(np.float32)
        cb = ycrcb[:, :, 2][mask > 0].astype(np.float32)
        skin_ycc = (cr > 135) & (cr < 180) & (cb > 85) & (cb < 140)
        skin_ratio = float(np.mean(skin_hsv | skin_ycc))

        green_ratio = float(np.mean((h_chan > 35) & (h_chan < 95) & (s_chan > 45) & (v_chan > 35)))

        border_top = int(mask[0, :].sum()) if h > 0 else 0
        border_bot = int(mask[-1, :].sum()) if h > 0 else 0
        border_lft = int(mask[:, 0].sum()) if w > 0 else 0
        border_rgt = int(mask[:, -1].sum()) if w > 0 else 0
        border_count = int(border_top > 0) + int(border_bot > 0) + int(border_lft > 0) + int(border_rgt > 0)
        border_ratio = float((border_top + border_bot + border_lft + border_rgt) / (2.0 * (h + w) + 1e-6))

        if border_count >= 3 and area_ratio > 0.35:
            continue

        # Reject card-like masks that can appear as SAM false positives.
        rectangularity = 0.0
        card_like = False
        contours, _ = _find_contours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            cnt = max(contours, key=cv2.contourArea)
            cnt_area = float(cv2.contourArea(cnt))
            if len(cnt) >= 3 and cnt_area > 1.0:
                _, (rw, rh), _ = cv2.minAreaRect(cnt)
                if rw > 1 and rh > 1:
                    rect_area = float(rw * rh)
                    rectangularity = float(cnt_area / (rect_area + 1e-6))
                    rect_aspect = float(max(rw, rh) / (min(rw, rh) + 1e-6))
                    card_ar = CARD_LONG_MM / CARD_SHORT_MM
                    aspect_err = abs(rect_aspect - card_ar) / card_ar
                    card_like = (
                        area_ratio < 0.25
                        and rectangularity > 0.82
                        and aspect_err < 0.18
                    )
        if card_like or (area_ratio < 0.10 and fill_ratio > 0.82 and abs(bbox_aspect - 1.58) < 0.35):
            continue

        # Broad prior: foot usually occupies moderate area, not full frame.
        area_prior = math.exp(-((area_ratio - 0.22) ** 2) / (2.0 * (0.16 ** 2)))
        score = (
            2.2 * skin_ratio +
            1.1 * centrality +
            0.8 * area_prior +
            0.4 * float(np.clip(fill_ratio, 0.0, 1.0)) -
            1.9 * green_ratio -
            1.0 * border_ratio -
            0.5 * rectangularity -
            0.35 * max(0, border_count - 1)
        )

        if score > best_score:
            best_score = score
            best_mask  = mask

    if best_mask.sum() == 0:
        return _skin_component_fallback(bgr)
    if best_score < 0.35:
        fallback = _skin_component_fallback(bgr)
        if fallback.sum() > 0:
            return fallback
    return best_mask


def _skin_component_fallback(bgr: np.ndarray) -> np.ndarray:
    """Fallback mask from skin-likelihood map when SAM picks background."""
    h, w = bgr.shape[:2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    ycrcb = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
    h_ch, s_ch, v_ch = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    cr, cb = ycrcb[:, :, 1], ycrcb[:, :, 2]

    skin_hsv = (((h_ch < 25) | (h_ch > 160)) & (s_ch > 15) & (v_ch > 30))
    skin_ycc = ((cr > 135) & (cr < 180) & (cb > 85) & (cb < 140))
    skin = (skin_hsv | skin_ycc).astype(np.uint8)

    if skin.sum() == 0:
        return np.zeros((h, w), dtype=np.uint8)
    skin = cv2.morphologyEx(skin, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    skin = cv2.morphologyEx(skin, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    skin = _largest_component(skin)

    area_ratio = float(skin.sum() / float(h * w + 1e-6))
    if area_ratio < 0.02 or area_ratio > 0.65:
        return np.zeros((h, w), dtype=np.uint8)
    return skin.astype(np.uint8)


def _postprocess_mask(mask):
    if mask.sum() == 0:
        return mask
    kernel = np.ones((7, 7), np.uint8)
    mask   = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if n <= 1:
        return mask
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    clean   = np.zeros_like(mask)
    clean[labels == largest] = 1
    return clean


def _mask_confidence(mask):
    if mask.sum() == 0:
        return 0.0
    dist = cv2.distanceTransform(
        (mask * 255).astype(np.uint8), cv2.DIST_L2, 5
    ).astype(np.float32)
    mx = dist.max()
    if mx > 0:
        dist /= mx
    return float(dist[mask > 0].mean())


def _soft_mask(mask: np.ndarray) -> Optional[np.ndarray]:
    if mask.sum() == 0:
        return None
    dist = cv2.distanceTransform(
        (mask * 255).astype(np.uint8), cv2.DIST_L2, 5
    ).astype(np.float32)
    mx = dist.max()
    if mx > 0:
        dist /= mx
    return dist


def _contour_prob(mask: np.ndarray) -> Optional[np.ndarray]:
    if mask.sum() == 0:
        return None
    edges = cv2.Canny((mask * 255).astype(np.uint8), 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    return edges.astype(np.float32) / 255.0


def _find_contours(*args, **kwargs):
    """OpenCV 3/4 compatible wrapper for findContours."""
    res = cv2.findContours(*args, **kwargs)
    if len(res) == 3:
        _, contours, hierarchy = res
    else:
        contours, hierarchy = res
    return contours, hierarchy


def _largest_component(mask: np.ndarray) -> np.ndarray:
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
    if n <= 1:
        return mask.astype(np.uint8)
    idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    out = np.zeros_like(mask, dtype=np.uint8)
    out[labels == idx] = 1
    return out


def _estimate_mask_long_edge_px(mask: np.ndarray) -> Optional[float]:
    contours, _ = _find_contours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    cnt = max(contours, key=cv2.contourArea)
    if len(cnt) < 3:
        return None
    _, (w, h), _ = cv2.minAreaRect(cnt)
    if w <= 1 or h <= 1:
        return None
    return float(max(w, h))


# ── Upload-time image quality gate ─────────────────────────────
# Cheap pre-segmentation checks that catch blur, lighting, contrast,
# and noise problems BEFORE the user submits. Run inside
# validate_image_view so the SPA can refuse the photo at upload time
# while the patient is still in front of the clinician.

# Thresholds — calibrated for phone captures of bare feet on indoor
# surfaces. Tighten or relax based on field-data feedback.
_QC_MIN_BLUR_VAR        = 30.0   # Laplacian variance — below this the foot
                                 # edges blur out and segmentation degrades.
_QC_MIN_BRIGHTNESS      = 60.0
_QC_MAX_BRIGHTNESS      = 215.0
_QC_MIN_RMS_CONTRAST    = 35.0
_QC_MIN_DYNAMIC_RANGE   = 150.0
_QC_MAX_NOISE_SIGMA     = 12.0
_QC_MAX_BILATERAL_RES   = 10.0
_QC_IMMERKAER_KERNEL    = np.array(
    [[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float32,
)


def _image_quality_layer1_3(bgr_small: np.ndarray) -> dict:
    """
    Cheap pre-segmentation quality gate.
    Returns a dict with metrics + a list of issue codes for any
    threshold violations. Issue codes match the SPA's _retakeMsg
    branches so they render as clinician-friendly retake guidance.
    """
    issues: list[str] = []
    metrics: dict = {}
    if bgr_small is None or bgr_small.size == 0:
        return {"metrics": {}, "issues": ["empty_image"], "failed": True}

    gray = cv2.cvtColor(bgr_small, cv2.COLOR_BGR2GRAY)

    # Layer 1: blur (Laplacian variance) + brightness (mean)
    blur_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(gray.mean())
    metrics["blur_var"] = round(blur_var, 2)
    metrics["brightness"] = round(brightness, 2)
    if blur_var < _QC_MIN_BLUR_VAR:
        issues.append("blurry")
    if brightness < _QC_MIN_BRIGHTNESS:
        issues.append("too_dark")
    elif brightness > _QC_MAX_BRIGHTNESS:
        issues.append("overexposed")

    # Layer 2: contrast via CLAHE-relevant L-channel statistics.
    # We don't apply CLAHE for downstream; we just measure the L
    # channel's spread to flag tonally flat captures.
    lab = cv2.cvtColor(bgr_small, cv2.COLOR_BGR2LAB)
    L = lab[:, :, 0]
    rms_contrast = float(L.std())
    dyn_range = float(np.percentile(L, 99) - np.percentile(L, 1))
    metrics["rms_contrast"] = round(rms_contrast, 2)
    metrics["dynamic_range"] = round(dyn_range, 2)
    if rms_contrast < _QC_MIN_RMS_CONTRAST:
        issues.append("low_contrast")
    if dyn_range < _QC_MIN_DYNAMIC_RANGE:
        if "low_contrast" not in issues:
            issues.append("tonally_flat")

    # Layer 3: noise — Immerkaer sigma + bilateral residual std.
    h, w = gray.shape
    if h > 4 and w > 4:
        conv = cv2.filter2D(gray.astype(np.float32), -1, _QC_IMMERKAER_KERNEL)
        sigma = float(
            np.sum(np.abs(conv)) * np.sqrt(np.pi / 2.0)
            / (6.0 * (w - 2) * (h - 2))
        )
    else:
        sigma = 0.0
    denoised = cv2.bilateralFilter(gray, d=7, sigmaColor=35, sigmaSpace=7)
    residual = float((gray.astype(np.int16) - denoised.astype(np.int16)).std())
    metrics["noise_sigma"] = round(sigma, 2)
    metrics["noise_residual"] = round(residual, 2)
    if sigma > _QC_MAX_NOISE_SIGMA:
        issues.append("noisy")
    if residual > _QC_MAX_BILATERAL_RES:
        if "noisy" not in issues:
            issues.append("noisy_structural")

    return {"metrics": metrics, "issues": issues, "failed": bool(issues)}


def _trim_mask_to_foot(mask_small: np.ndarray, view: str) -> tuple[np.ndarray, dict]:
    """
    Trim leg/object pixels from the mask so the bbox sent to MMPose is foot-only.

    Anatomically grounded: the foot has a wide ball/midfoot region, and the leg
    above is narrower (the ankle is the constriction). For dorsal/medial views
    where the leg is often visible at the top of the frame, find the widest
    horizontal slice of the mask and clip everything ABOVE the y-position where
    the slice has narrowed to a fraction of the widest. This drops the leg
    while leaving the foot intact.

    Background: VJARAC-7-24 right_dorsal probe found the DeepLab mask spans
    y=0..3003 because the leg reaches the frame top, producing a 1086×3003
    bbox whose foot fraction is ~30% after MMPose's TopdownAffine resize to
    256×256. With this trim, the bbox shrinks to the foot only and pose
    confidence on the same image jumps from 2/6 to 4/6 in-foot keypoints.

    Skipped for plantar — sole view never has the leg in frame.
    """
    out_meta = {"trimmed": False, "rows_removed": 0, "narrow_y": None,
                "widest_y": None, "widest_w": 0}
    if view not in ("dorsal", "medial"):
        return mask_small, out_meta
    if mask_small is None or mask_small.size == 0 or int(mask_small.sum()) == 0:
        return mask_small, out_meta

    h, w = mask_small.shape[:2]
    m = (mask_small > 0).astype(np.uint8)
    row_widths = m.sum(axis=1)
    ys = np.where(row_widths > 0)[0]
    if len(ys) < 10:
        return mask_small, out_meta
    y0 = int(ys[0])
    y1 = int(ys[-1])
    span = max(1, y1 - y0)

    # Widest horizontal slice — typically the ball/midfoot region.
    widest_y = int(np.argmax(row_widths))
    widest_w = int(row_widths[widest_y])
    if widest_w < 20:
        return mask_small, out_meta

    # Only trim if the leg is plausibly attached at the top — i.e. the topmost
    # mask row is reasonably far above the widest slice.
    if widest_y - y0 < max(20, int(0.05 * h)):
        return mask_small, out_meta

    # Find the ankle constriction. Two strategies:
    # 1. STRICT (preferred): the first row above the widest slice that's
    #    narrower than 60% of widest_w. Catches dramatic narrowing.
    # 2. LOCAL MIN (fallback): when the leg is roughly as wide as the ball
    #    (e.g. the VJARAC right_dorsal case where leg=165, ball=166), there's
    #    no <60% narrowing — but there's still a local minimum in row width
    #    between leg and ball that marks the ankle. Find it by smoothing the
    #    row-width profile in the upper half and taking its argmin, requiring
    #    it to be at least ~12% below the segment max in that region.
    NARROW_FRAC = 0.60
    threshold = NARROW_FRAC * widest_w
    narrow_y = None
    for y in range(widest_y - 1, y0 - 1, -1):
        if row_widths[y] < threshold:
            narrow_y = y
            break
    if narrow_y is None:
        # Fallback: look for a local minimum between top and widest_y. Use a
        # smoothed profile (rolling mean over ~3% of mask span) so single-row
        # noise doesn't dominate.
        upper_widths = row_widths[y0:widest_y + 1].astype(np.float32)
        if len(upper_widths) >= 8:
            kernel = max(3, int(round(0.03 * span)))
            if kernel % 2 == 0:
                kernel += 1
            half = kernel // 2
            padded = np.pad(upper_widths, half, mode="edge")
            smoothed = np.convolve(padded, np.ones(kernel) / kernel, mode="valid")
            local_min_idx = int(np.argmin(smoothed))
            local_min_w = float(smoothed[local_min_idx])
            local_max_w = float(smoothed.max())
            # Only trust the local min if it's at least 12% below the local
            # max AND the upper segment is long enough that there's room for a
            # genuine ankle. Avoids trimming when the leg+foot is one
            # uniformly-wide blob (which usually means the mask is broken
            # rather than there being a leg attached).
            if (local_max_w - local_min_w) / max(local_max_w, 1.0) >= 0.12 and len(upper_widths) >= 30:
                narrow_y = y0 + local_min_idx
    if narrow_y is None or narrow_y <= y0:
        return mask_small, out_meta

    # Safety: don't trim more than 60% of the mask height — that's a sign
    # the heuristic is mis-firing (e.g. very strange foot shape).
    rows_removed = (narrow_y + 1) - y0
    if rows_removed > 0.60 * span:
        return mask_small, out_meta

    trimmed = m.copy()
    trimmed[: narrow_y + 1, :] = 0
    trimmed = _largest_component(trimmed)

    out_meta.update({
        "trimmed": True,
        "rows_removed": int(rows_removed),
        "narrow_y": int(narrow_y),
        "widest_y": int(widest_y),
        "widest_w": int(widest_w),
    })
    return trimmed.astype(mask_small.dtype), out_meta


def apply_mask_qc(mask_small: np.ndarray, view: str) -> tuple[np.ndarray, dict]:
    """
    Quality gate for segmentation mask:
    - crop likely leg segment attached at top when safe
    - reject severe spill/leg masks that cannot be cleaned safely
    """
    mask = (mask_small > 0).astype(np.uint8)
    h, w = mask.shape[:2]
    qc = {
        "cropped": False,
        "rows_removed": 0,
        "rows_removed_ratio": 0.0,
        "top_touch_before": bool(mask[0, :].any()) if h > 0 else False,
        "top_touch_after": False,
        "reject": False,
        "reason": None,
    }

    area = int(mask.sum())
    if area == 0:
        qc["reject"] = True
        qc["reason"] = "empty_mask"
        return mask, qc

    rows = mask.sum(axis=1).astype(np.float32)
    ys = np.where(rows > 0)[0]
    if len(ys) == 0:
        qc["reject"] = True
        qc["reason"] = "empty_rows"
        return mask, qc
    y0, y1 = int(ys[0]), int(ys[-1])
    span_before = max(1, y1 - y0 + 1)

    span = max(1, y1 - y0 + 1)
    top_band = rows[y0:min(y1 + 1, y0 + max(5, int(0.08 * span)))]
    mid_lo = y0 + int(0.35 * span)
    mid_hi = y0 + int(0.65 * span)
    mid_band = rows[mid_lo:max(mid_lo + 1, mid_hi)]
    top_mean = float(np.mean(top_band)) if len(top_band) else 0.0
    mid_mean = float(np.mean(mid_band)) if len(mid_band) else max(top_mean, 1.0)
    top_width_ratio = top_mean / (mid_mean + 1e-6)
    qc["top_width_ratio"] = float(top_width_ratio)

    xs = np.where(mask > 0)[1]
    bbox_w = int(xs.max()) - int(xs.min()) + 1 if len(xs) else 0
    area_ratio = float(mask.sum()) / float(h * w + 1e-6)
    qc["area_ratio"] = area_ratio
    qc["bbox_width_ratio"] = float(bbox_w / float(w + 1e-6))

    # Leg-crop only fires when the mask actually touches the top edge of the
    # frame. The earlier OR-form also triggered on any dorsal/medial mask
    # with a narrow top band relative to its midsection — which is exactly
    # what a *rotated* (diagonal) foot looks like, so the crop chopped off
    # the heel and the rest of the foot got rejected as a fragment.
    crop_needed = qc["top_touch_before"]
    if crop_needed:
        max_row = float(np.max(rows[ys])) if len(ys) else 0.0
        target = 0.55 * max_row
        win = max(5, int(0.01 * h))
        y_cut = None
        for y in range(y0, max(y0, y1 - win + 1)):
            if float(np.median(rows[y:y + win])) >= target:
                y_cut = y
                break
        if y_cut is not None:
            min_remove = max(3, int(0.02 * h))
            if y_cut - y0 >= min_remove:
                mask[:y_cut, :] = 0
                mask = _largest_component(mask)
                qc["cropped"] = True
                qc["rows_removed"] = int(y_cut - y0)
                qc["rows_removed_ratio"] = float(qc["rows_removed"] / float(span_before))

    qc["top_touch_after"] = bool(mask[0, :].any()) if h > 0 else False
    area_after = int(mask.sum())
    area_ratio_after = float(area_after) / float(h * w + 1e-6)
    qc["area_ratio_after"] = area_ratio_after

    if area_after == 0 or area_ratio_after < 0.02:
        qc["reject"] = True
        qc["reason"] = "tiny_after_qc"
        return mask, qc

    xs_after = np.where(mask > 0)[1]
    bbox_w_after = int(xs_after.max()) - int(xs_after.min()) + 1 if len(xs_after) else 0
    qc["bbox_width_ratio_after"] = float(bbox_w_after / float(w + 1e-6))
    edge_band = max(1, int(round(0.01 * w)))
    left_touch_ratio = float(np.mean(np.any(mask[:, :edge_band] > 0, axis=1)))
    right_touch_ratio = float(np.mean(np.any(mask[:, max(0, w - edge_band):] > 0, axis=1)))
    qc["left_touch_ratio"] = left_touch_ratio
    qc["right_touch_ratio"] = right_touch_ratio

    if qc["top_touch_after"] and qc["bbox_width_ratio_after"] > 0.95 and area_ratio_after > 0.55:
        qc["reject"] = True
        qc["reason"] = "top_spill"
        return mask, qc

    if (view in ("dorsal", "medial")
            and qc["top_touch_after"]
            and not qc["cropped"]
            and top_width_ratio < 0.40):
        qc["reject"] = True
        qc["reason"] = "leg_segment_unresolved"
        return mask, qc

    lateral_area_min = 0.35 if view == "dorsal" else 0.42
    if (
        view in ("dorsal", "medial")
        and qc["bbox_width_ratio_after"] > 0.92
        and area_ratio_after > lateral_area_min
        and max(left_touch_ratio, right_touch_ratio) > 0.30
    ):
        qc["reject"] = True
        qc["reason"] = "lateral_spill"
        return mask, qc

    # ── Bounding-box aspect ratio gate ──────────────────────
    # A foot mask should be elongated; a nearly-square bbox
    # suggests the mask includes non-foot regions (e.g. face).
    ys_all = np.where(mask > 0)[0]
    xs_all = np.where(mask > 0)[1]
    if len(ys_all) > 0 and len(xs_all) > 0:
        bbox_h_px = int(ys_all.max()) - int(ys_all.min()) + 1
        bbox_w_px = int(xs_all.max()) - int(xs_all.min()) + 1
        bbox_aspect = float(max(bbox_h_px, bbox_w_px)) / (min(bbox_h_px, bbox_w_px) + 1e-6)
        qc["bbox_aspect"] = bbox_aspect
        # Plantar/dorsal feet are elongated (aspect ~1.8-3.5);
        # a value below 1.3 is suspicious. Medial view also produces
        # an elongated mask in correctly-oriented field photos (the
        # auto-orient pass rotates landscape captures to portrait
        # before this runs). A near-square (~1.0) mask on medial means
        # segmentation captured only a fragment of the foot — reject
        # it loudly rather than silently passing partial detections
        # through to landmark inference (where they yank keypoints
        # into the wrong region).
        min_aspect = 1.4 if view == "plantar" else 1.2
        if bbox_aspect < min_aspect:
            qc["reject"] = True
            qc["reason"] = f"squat_mask_{bbox_aspect:.2f}"
            return mask, qc

    # ── Solidity gate ───────────────────────────────────────
    # Solidity = contour area / convex-hull area.  A clean foot
    # shape has solidity 0.55-0.85; a multi-blob mask bridged
    # through arm/leg skin gives much lower values.
    cnts, _ = _find_contours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if cnts:
        cnt = max(cnts, key=cv2.contourArea)
        hull = cv2.convexHull(cnt)
        hull_area = float(cv2.contourArea(hull))
        if hull_area > 0:
            solidity = float(cv2.contourArea(cnt)) / hull_area
            qc["solidity"] = solidity
            if solidity < 0.40:
                qc["reject"] = True
                qc["reason"] = f"low_solidity_{solidity:.2f}"
                return mask, qc

    return mask, qc


# ═══════════════════════════════════════════════════════════
# VIEW CLASSIFICATION & VALIDATION
# Auto-detect foot view (plantar / dorsal / medial) and side
# (left / right) from a single uploaded image, plus check
# that a calibration card is visible in frame.
# ═══════════════════════════════════════════════════════════

def _resize_to_max(bgr: np.ndarray, max_side: int = 512) -> np.ndarray:
    h, w = bgr.shape[:2]
    longest = max(h, w)
    if longest <= max_side:
        return bgr
    scale = max_side / longest
    return cv2.resize(bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)


def _fix_exif_bytes(image_bytes: bytes) -> np.ndarray:
    """Decode image bytes and apply EXIF rotation using PIL.

    Defensive heuristic: if EXIF orientation would flip an already-portrait
    image into landscape, the file was pre-rotated by some intermediate
    processor — skip the rotation.
    """
    try:
        from PIL import Image as _PILImage, ImageOps
        import io
        pil = _PILImage.open(io.BytesIO(image_bytes))
        w_in, h_in = pil.size                       # PIL is (W, H)
        input_is_portrait = h_in > w_in * 1.05
        try:
            pil_rot = ImageOps.exif_transpose(pil)
            w_out, h_out = pil_rot.size
            output_is_landscape = w_out > h_out * 1.05
            if input_is_portrait and output_is_landscape:
                # EXIF tag is stale (pre-rotated file). Keep raw pixels.
                pil_final = pil
            else:
                pil_final = pil_rot
        except Exception:
            pil_final = pil
        pil_final = pil_final.convert("RGB")
        bgr = cv2.cvtColor(np.array(pil_final), cv2.COLOR_RGB2BGR)
        return bgr
    except Exception:
        arr = np.frombuffer(image_bytes, np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def classify_foot_view(
    bgr_small: np.ndarray,
    seg_model=None,
    seg_model_path: str = _DEFAULT_UNET_PATH,
) -> dict:
    """
    Classify foot view (plantar/dorsal/medial) and side (left/right)
    from a small BGR image using mask shape heuristics.

    Key insight:
    - Medial (side view): foot lies HORIZONTALLY in the image.
      The axis-aligned bounding box of the mask has width > height.
    - Plantar / Dorsal (top-down or bottom-up): foot lies VERTICALLY.
      The bounding box has height > width.
    - Plantar vs Dorsal: distinguished by ORB reference matching only
      (both look similar from geometry alone).
    - Left/Right: from which side the wider (big-toe) end is on.

    Returns dict with keys: view, side, confidence, features
    """
    # --- Segmentation ---
    mask, conf, _ = run_segmentation_unet(
        bgr_small,
        seg_model=seg_model,
        seg_model_path=seg_model_path,
        return_meta=True,
    )
    mask = (mask > 0).astype(np.uint8)
    if mask.sum() == 0:
        return {"view": "plantar", "side": "left", "confidence": 0.0,
                "features": {"reason": "empty_mask"}}

    # Keep only largest component
    mask = _largest_component(mask)
    img_h, img_w = mask.shape[:2]

    # --- Axis-aligned bounding box ---
    ys = np.where(mask.any(axis=1))[0]
    xs = np.where(mask.any(axis=0))[0]
    if len(ys) < 4 or len(xs) < 4:
        return {"view": "plantar", "side": "left", "confidence": 0.0,
                "features": {"reason": "tiny_mask"}}

    y0, y1 = int(ys[0]), int(ys[-1])
    x0, x1 = int(xs[0]), int(xs[-1])
    bbox_h = max(1, y1 - y0)
    bbox_w = max(1, x1 - x0)
    aspect = bbox_h / bbox_w   # >1 = portrait (vertical foot), <1 = landscape (horizontal)

    # --- Solidity ---
    cnts, _ = _find_contours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    solidity = 1.0
    if cnts:
        cnt = max(cnts, key=cv2.contourArea)
        hull = cv2.convexHull(cnt)
        hull_area = float(cv2.contourArea(hull))
        if hull_area > 0:
            solidity = float(cv2.contourArea(cnt)) / hull_area

    features = {
        "bbox_aspect": float(aspect),   # h/w ratio
        "solidity": float(solidity),
        "mask_conf": float(conf),
        "bbox_h": bbox_h,
        "bbox_w": bbox_w,
    }

    # --- View heuristic ---
    # Medial: landscape (width >> height), aspect < ~0.7
    # Plantar/Dorsal: portrait (height >> width), aspect > ~1.2
    if aspect < 0.75:
        # Horizontal foot → medial
        view = "medial"
        # Confidence scales with how strongly horizontal it is
        view_conf = float(np.clip(0.55 + 0.3 * (0.75 - aspect) / 0.75, 0.0, 0.85))
    elif aspect > 1.2:
        # Vertical foot → plantar or dorsal.
        # Key discriminator: toe_convex = mask_width at top-5% / mask_width at top-15%
        # Plantar: toes are spread/separated → very tip is narrow vs 15% slice → ratio < 0.70
        # Dorsal:  toes are fused/tapered   → tip width ≈ 15% width            → ratio > 0.70
        top5_rows  = mask[y0: y0 + max(1, bbox_h // 20), :]
        top15_rows = mask[y0: y0 + max(1, bbox_h // 7),  :]
        top5_w  = float(top5_rows.sum(axis=1).mean())  if top5_rows.sum()  > 0 else 1.0
        top15_w = float(top15_rows.sum(axis=1).mean()) if top15_rows.sum() > 0 else 1.0
        toe_convex = top5_w / max(1.0, top15_w)
        features["toe_convex"] = toe_convex
        if toe_convex < 0.70:
            view = "plantar"
            view_conf = 0.55 + 0.20 * (0.70 - toe_convex) / 0.70
        else:
            view = "dorsal"
            view_conf = 0.55 + 0.20 * (toe_convex - 0.70) / 0.30
    else:
        # Ambiguous aspect ratio — use toe_convex as tiebreak
        top5_rows  = mask[y0: y0 + max(1, bbox_h // 20), :]
        top15_rows = mask[y0: y0 + max(1, bbox_h // 7),  :]
        top5_w  = float(top5_rows.sum(axis=1).mean())  if top5_rows.sum()  > 0 else 1.0
        top15_w = float(top15_rows.sum(axis=1).mean()) if top15_rows.sum() > 0 else 1.0
        toe_convex = top5_w / max(1.0, top15_w)
        features["toe_convex"] = toe_convex
        view = "plantar" if toe_convex < 0.70 else "dorsal"
        view_conf = 0.35

    view_conf = float(np.clip(view_conf * min(1.0, float(conf) + 0.3), 0.0, 1.0))

    # --- Left/Right heuristic ---
    # For medial: foot is horizontal. Find which end has the toe (narrower vertical profile).
    # For plantar/dorsal: foot is vertical. Big toe (hallux) makes one side wider.
    side = "left"
    side_conf = 0.40  # geometry side detection is unreliable — keep low

    if view == "medial":
        # In a medial (inner-side) photo:
        #   Right foot medial: foot faces LEFT in the frame (toe on left, heel on right)
        #   Left foot medial:  foot faces RIGHT in the frame (toe on right, heel on left)
        # The toe end is NARROWER (fewer mask pixels in that column slice).
        toe_slice_w = max(1, bbox_w // 7)
        left_pixels  = int(mask[:, x0: x0 + toe_slice_w].sum())
        right_pixels = int(mask[:, x1 - toe_slice_w: x1].sum())
        # Fewer pixels → that end is the toe
        if left_pixels < right_pixels:
            # Toe is on the LEFT side of frame → right foot medial
            side = "right"
        else:
            # Toe is on the RIGHT side of frame → left foot medial
            side = "left"
        side_conf = 0.55
    else:
        # Plantar/Dorsal: left/right from geometry is unreliable (big-toe asymmetry
        # margin is only ~10% of mask width in real field photos).
        # Keep side_conf low so low_confidence=True triggers the reassign dropdown.
        side = "left"   # placeholder — user will confirm via dropdown
        side_conf = 0.25

    features["side_conf"] = side_conf
    final_conf = float(np.clip((view_conf + side_conf) / 2, 0.0, 1.0))
    return {"view": view, "side": side, "confidence": final_conf, "features": features}


@lru_cache(maxsize=1)
def _load_dinov2_model():
    """Load and cache DINOv2 ViT-S/14 (84MB). Runs on CPU."""
    import torch as _torch
    try:
        m = _torch.hub.load(
            "facebookresearch/dinov2", "dinov2_vits14",
            verbose=False, trust_repo=True,
        )
        m.eval()
        log.info("[DINO] dinov2_vits14 loaded (22M params)")
        return m
    except Exception as e:
        log.warning("[DINO] Could not load DINOv2: %s", e)
        return None


def _dino_features(bgr: np.ndarray, model) -> Optional[np.ndarray]:
    """Extract 384-dim DINOv2 feature vector from a BGR image."""
    import torch as _torch
    _MEAN = _torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
    _STD  = _torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)
    try:
        rgb = cv2.cvtColor(cv2.resize(bgr, (518, 518)), cv2.COLOR_BGR2RGB)
        t = _torch.from_numpy(rgb).permute(2, 0, 1).float() / 255.0
        t = (t - _MEAN) / _STD
        with _torch.no_grad():
            feat = model(t.unsqueeze(0)).squeeze(0).numpy()
        norm = float(np.linalg.norm(feat))
        return feat / norm if norm > 0 else feat
    except Exception as e:
        log.warning("[DINO] feature extraction failed: %s", e)
        return None


@lru_cache(maxsize=4)
def _load_reference_dino_features(samples_dir: str):
    """
    Load and cache DINOv2 features for all 6 reference images.
    Returns dict: key → normalised 384-dim np.ndarray
    """
    model = _load_dinov2_model()
    if model is None:
        return {}
    keys = [
        "left_plantar", "left_dorsal", "left_medial",
        "right_plantar", "right_dorsal", "right_medial",
    ]
    refs = {}
    for key in keys:
        for ext in (".jpeg", ".jpg", ".png"):
            p = Path(samples_dir) / f"{key}{ext}"
            if p.exists():
                img = cv2.imread(str(p))
                if img is not None:
                    feat = _dino_features(img, model)
                    if feat is not None:
                        refs[key] = feat
                    break
    log.info("[DINO] Reference features loaded for: %s", list(refs.keys()))
    return refs


def match_reference_image(bgr_small: np.ndarray, samples_dir: str = "samples") -> dict:
    """
    Match bgr_small against 6 reference images using DINOv2 cosine similarity.

    DINOv2 is a semantic vision model — it understands foot anatomy, not just
    colour distribution, making it robust to lighting/background variation.

    KEY INSIGHT: DINOv2 reliably identifies VIEW TYPE (plantar/dorsal/medial)
    but left/right is ambiguous from a single image with 6 reference examples.
    The returned best_key reflects the best VIEW match; ambiguous=True when
    the left/right margin < 0.03 (i.e. both sides score nearly equally).

    Returns dict: best_key, best_score, all_scores, ambiguous, best_view
    """
    model = _load_dinov2_model()
    ref_feats = _load_reference_dino_features(samples_dir)
    if not ref_feats or model is None:
        return {"best_key": None, "best_score": 0.0, "all_scores": {}, "ambiguous": True, "best_view": None}

    q_feat = _dino_features(bgr_small, model)
    if q_feat is None:
        return {"best_key": None, "best_score": 0.0, "all_scores": {}, "ambiguous": True, "best_view": None}

    # Cosine similarity (features already L2-normalised)
    scores = {k: float(np.dot(q_feat, v)) for k, v in ref_feats.items()}

    # ── View-level scores (pool left+right per view type) ──────────────────
    view_scores: dict[str, float] = {}
    for k, v in scores.items():
        _, vtype = k.split("_", 1)
        view_scores[vtype] = max(view_scores.get(vtype, 0.0), v)
    best_view = max(view_scores, key=lambda x: view_scores[x])

    # ── Among the two keys for the best view, check left/right margin ──────
    view_keys = [k for k in scores if k.endswith(best_view)]
    view_keys_sorted = sorted(view_keys, key=lambda k: scores[k], reverse=True)
    best_key = view_keys_sorted[0]
    best_score = scores[best_key]

    # Left/right ambiguous when margin < 0.03 (mirror images look nearly identical)
    lr_margin = scores[view_keys_sorted[0]] - scores[view_keys_sorted[1]] if len(view_keys_sorted) > 1 else 1.0
    ambiguous = lr_margin < 0.03

    return {
        "best_key": best_key,
        "best_score": best_score,
        "all_scores": scores,
        "ambiguous": ambiguous,
        "best_view": best_view,
        "lr_margin": round(lr_margin, 4),
    }


def assign_sides_from_batch(results: list[dict]) -> list[dict]:
    """
    When multiple images are validated together (e.g. all 6 foot images dropped
    at once), use cross-image logic to resolve left/right ambiguity.

    Strategy: for each view type (plantar, dorsal, medial), if exactly 2 images
    were detected as that view, assign left/right by comparing their DINOv2
    feature similarity to left vs right references.  When one already has a
    confident side assignment (medial via geometry), keep it and assign the
    other as the opposite.

    Modifies results in-place and returns them.
    """
    from itertools import groupby

    # Group by detected view
    by_view: dict[str, list[int]] = {}
    for i, r in enumerate(results):
        v = r.get("detected_view")
        if v:
            by_view.setdefault(v, []).append(i)

    for view, idxs in by_view.items():
        if len(idxs) != 2:
            continue  # Can only resolve pairs
        i0, i1 = idxs
        r0, r1 = results[i0], results[i1]

        # If medial — geometry already gave a reliable side; assign opposite to partner
        if view == "medial":
            s0 = r0.get("detected_side")
            s1 = r1.get("detected_side")
            if s0 and s1 and s0 != s1:
                continue  # Already correctly assigned
            if s0 in ("left", "right"):
                opposite = "right" if s0 == "left" else "left"
                results[i1]["detected_side"] = opposite
                results[i1]["confidence"] = max(results[i1]["confidence"], 0.65)
                results[i1]["low_confidence"] = False
                results[i1]["side_resolved_by"] = "pair"
            elif s1 in ("left", "right"):
                opposite = "right" if s1 == "left" else "left"
                results[i0]["detected_side"] = opposite
                results[i0]["confidence"] = max(results[i0]["confidence"], 0.65)
                results[i0]["low_confidence"] = False
                results[i0]["side_resolved_by"] = "pair"
        else:
            # Plantar/Dorsal: use DINOv2 scores from match_reference_image
            # Whichever image scored higher vs left reference → left foot
            all_scores_0 = r0.get("_all_scores", {})
            all_scores_1 = r1.get("_all_scores", {})
            left_key  = f"left_{view}"
            right_key = f"right_{view}"
            if not all_scores_0 or not all_scores_1:
                continue
            # Score difference: positive = more similar to left reference
            diff0 = all_scores_0.get(left_key, 0) - all_scores_0.get(right_key, 0)
            diff1 = all_scores_1.get(left_key, 0) - all_scores_1.get(right_key, 0)
            # Assign: higher left-affinity → left; lower → right
            if diff0 >= diff1:
                results[i0]["detected_side"] = "left"
                results[i1]["detected_side"] = "right"
            else:
                results[i0]["detected_side"] = "right"
                results[i1]["detected_side"] = "left"
            # Boost confidence only when margin is meaningful
            margin = abs(diff0 - diff1)
            if margin > 0.02:
                for idx in [i0, i1]:
                    results[idx]["confidence"] = min(0.80, results[idx]["confidence"] + 0.15)
                    results[idx]["low_confidence"] = results[idx]["confidence"] < 0.50
                    results[idx]["side_resolved_by"] = "pair"

    return results


def check_card_placement(
    bgr_small: np.ndarray,
    card_model_path: str = "checkpoints/card_detector.pt",
    yolo_model=None,
) -> dict:
    """
    Check whether a calibration card (ArUco or plain) is visible and properly placed.

    Returns dict with keys: card_detected, card_placement_ok, card_conf
    """
    try:
        # Try ArUco first
        px_per_mm, aruco_conf, aruco_meta = _run_aruco_detector(bgr_small, return_meta=True)
        if not math.isnan(px_per_mm) and aruco_conf >= ARUCO_CONF_MIN:
            return {
                "card_detected": True,
                "card_placement_ok": True,
                "card_conf": float(aruco_conf),
            }
        # Fall back to card YOLO
        px_per_mm, card_conf, meta = _run_card_detector(
            bgr_small,
            card_model_path,
            foot_mask=None,
            return_meta=True,
            yolo_model=yolo_model,
        )
        detected = not math.isnan(px_per_mm)
        ok = detected and float(card_conf) >= DETECTION_CONF_MIN
        return {
            "card_detected": detected,
            "card_placement_ok": ok,
            "card_conf": float(card_conf) if not math.isnan(card_conf) else 0.0,
        }
    except Exception as e:
        log.warning("[VALIDATE] card check error: %s", e)
        return {"card_detected": False, "card_placement_ok": False, "card_conf": 0.0}


def validate_image_view(
    image_bytes: bytes,
    seg_model=None,
    seg_model_path: str = _DEFAULT_UNET_PATH,
    card_model_path: str = "checkpoints/card_detector.pt",
    yolo_model=None,
    samples_dir: str = "samples",
) -> dict:
    """
    Full validation pipeline for a single uploaded image.

    Returns dict with:
      detected_view, detected_side, confidence,
      card_detected, card_placement_ok, card_conf,
      match_score, match_key, low_confidence
    """
    # Decode + EXIF fix
    bgr = _fix_exif_bytes(image_bytes)
    if bgr is None or bgr.size == 0:
        return {
            "detected_view": None, "detected_side": None, "confidence": 0.0,
            "card_detected": False, "card_placement_ok": False, "card_conf": 0.0,
            "match_score": 0.0, "match_key": None, "low_confidence": True,
            "error": "could_not_decode",
        }

    bgr_small = _resize_to_max(bgr, MAX_SIZE)

    # Step 0: cheap image quality gate (blur, lighting, contrast, noise)
    # ~30ms; runs BEFORE segmentation so a hopelessly blurry image
    # doesn't waste the DeepLabV3 forward pass.
    qc_l13 = _image_quality_layer1_3(bgr_small)

    # Step 1: heuristic view classification
    heur = classify_foot_view(bgr_small, seg_model=seg_model, seg_model_path=seg_model_path)
    mask_conf = float(heur.get("features", {}).get("mask_conf", 0.0))

    # Step 2: reference image matching
    ref = match_reference_image(bgr_small, samples_dir=samples_dir)

    # Step 3: fuse results
    h_view = heur["view"]
    h_side = heur["side"]
    h_conf = heur["confidence"]
    r_key  = ref["best_key"]     # e.g. "left_plantar"
    r_score = ref["best_score"]

    if r_key:
        r_side, r_view = r_key.split("_", 1)
    else:
        r_side, r_view = h_side, h_view

    # Fusion strategy:
    # 1. MEDIAL detection is purely geometric (horizontal bbox) — very reliable.
    #    Side comes from toe-pixel-count heuristic.
    # 2. PLANTAR vs DORSAL — geometry alone cannot separate them.
    #    Colour histogram match against reference images is the primary signal.
    # 3. LEFT vs RIGHT for plantar/dorsal — big-toe asymmetry heuristic is weak.
    #    When histogram match is unambiguous, trust its side. When ambiguous, use heuristic.
    r_ambiguous = ref.get("ambiguous", False)

    # ── VIEW FUSION (no side detection — user pairs left/right via UI) ────────
    # Geometry is authoritative for medial (aspect ratio is unambiguous).
    # For plantar/dorsal, geometry (toe_convex) is primary, DINOv2 confirms.
    dino_view = ref.get("best_view")   # "plantar" | "dorsal" | "medial" | None

    if h_view == "medial":
        final_view = "medial"
        if dino_view == "medial":
            final_conf = float(np.clip(0.65 * h_conf + 0.35 * r_score, 0.0, 1.0))
        else:
            final_conf = float(np.clip(h_conf * 0.85, 0.0, 1.0))
    else:
        toe_convex = heur["features"].get("toe_convex", 0.5)
        ambiguous_geometry = 0.60 <= toe_convex <= 0.80
        if dino_view and dino_view == h_view:
            final_view = h_view
            final_conf = float(np.clip(0.55 * h_conf + 0.45 * r_score, 0.0, 1.0))
        elif dino_view and ambiguous_geometry:
            final_view = dino_view
            final_conf = float(np.clip(r_score * 0.65, 0.0, 1.0))
        else:
            final_view = h_view
            final_conf = float(np.clip(h_conf * 0.80, 0.0, 1.0))

    # Step 4: card placement
    card = check_card_placement(bgr_small, card_model_path=card_model_path, yolo_model=yolo_model)

    # Step 5: marker size (distance/framing proxy). Ask the ArUco detector
    # directly so we can read the marker pixel size; if it's too small the
    # camera is too far from the foot.
    marker_side_px = 0.0
    try:
        _ap, _ac, _am = _run_aruco_detector(bgr_small, return_meta=True)
        marker_side_px = float(_am.get("marker_side_px", 0.0)) if isinstance(_am, dict) else 0.0
    except Exception:
        marker_side_px = 0.0

    # Diagnose specific issues
    issues = list(qc_l13.get("issues", []))   # blur/light/contrast/noise
    if mask_conf < 0.25:
        issues.append("low_mask_conf")
    # Only flag no_reference_match if DINOv2 actually loaded and scored (r_score > 0 means it ran)
    if r_score > 0 and r_score < 0.3 and final_conf < 0.55:
        issues.append("no_reference_match")
    if not card["card_detected"]:
        issues.append("no_card")
    elif not card["card_placement_ok"]:
        issues.append("card_misplaced")
    # Distance/framing: if a marker was found but appears very small in the
    # image, the camera is likely too far from the foot. The hard ArUco
    # floor is 30px; we warn at 60px so the user can fix it before submit.
    if marker_side_px and marker_side_px < 60:
        issues.append("marker_too_small")

    # When DINOv2 is unavailable (r_score==0), trust heuristic mask_conf alone.
    # Threshold lowered from 0.55 -> 0.40 because DINOv2 scores naturally fall
    # in the 0.40-0.60 range for plausible field photos. 0.55 caused false
    # "Low confidence" popups on visually-good images where the view was
    # detected correctly.
    dino_available = r_score > 0
    is_low_confidence = (final_conf < 0.40) if dino_available else (mask_conf < 0.18)
    # Quality issues should also push the user to retake — set low_confidence
    # whenever any Layer 1/2/3 issue or marker_too_small fires.
    if qc_l13.get("failed") or "marker_too_small" in issues:
        is_low_confidence = True

    return {
        "detected_view": final_view,
        "confidence": round(final_conf, 3),
        "mask_conf": round(mask_conf, 3),
        "card_detected": card["card_detected"],
        "card_placement_ok": card["card_placement_ok"],
        "card_conf": round(card["card_conf"], 3),
        "match_score": round(r_score, 3),
        "low_confidence": is_low_confidence,
        "issues": issues,
        "quality_metrics": {
            **qc_l13.get("metrics", {}),
            "marker_side_px": round(marker_side_px, 1),
        },
    }


# ═══════════════════════════════════════════════════════════
# STAGE 3 — REFERENCE OBJECT ANALYSIS
# Two separate YOLO models:
#   card_detector.pt  — ISO ID-1 credit/debit card (85.6 × 53.98 mm)
#   coin_detector.pt  — Indian coins ₹1 / ₹2 / ₹5 / ₹10
# ArUco detector runs first (pixel-perfect corners).
# Card YOLO detector runs if ArUco fails.
# Coin detector runs only if both ArUco and card fail.
# ═══════════════════════════════════════════════════════════

# ── ArUco marker card dimensions ──
# The ArUco marker is printed on a standard ISO credit-card-sized card
# (85.6 × 53.98 mm). OpenCV detects the outer corners of the marker
# pattern. We use BOTH the marker AND the card edge for scale:
# - ArUco corners → precise orientation + homography
# - Card long edge (85.6mm) → scale reference (same as credit card)
# ARUCO_MARKER_SIZE_MM should match the printed marker's outer black
# boundary side length. Adjust this if your print differs.
ARUCO_MARKER_SIZE_MM = 50.0   # physical side length of ArUco marker square (5cm × 5cm)
ARUCO_CARD_LONG_MM  = 85.6    # the card substrate is credit-card-sized
ARUCO_CARD_SHORT_MM = 53.98
ARUCO_CONF_MIN = 0.55
ARUCO_SQUARENESS_MIN = 0.45
ARUCO_ANGLE_QUALITY_MIN = 0.45

def _run_aruco_detector(
    bgr: np.ndarray,
    marker_size_mm: float = ARUCO_MARKER_SIZE_MM,
    return_meta: bool = False,
    focal_length_px: float = None,
) -> tuple:
    """
    Detect ArUco markers using OpenCV's built-in detector.
    Returns pixel-perfect corner positions → px_per_mm.

    Tries multiple ArUco dictionaries (4x4, 5x5, 6x6, ORIGINAL).
    Uses the marker with the most confident detection.

    Returns
    -------
    px_per_mm  : float (NaN if no marker found)
    confidence : float [0, 1]
    meta       : dict (if return_meta)
    """
    try:
        aruco = cv2.aruco
    except AttributeError:
        log.warning("  [ARUCO] cv2.aruco not available")
        meta = {"source": "aruco", "status": "fail", "reason": "cv2_aruco_missing"}
        return (float("nan"), 0.0, meta) if return_meta else (float("nan"), 0.0)

    # LEPRA field cards use DICT_6X6_1000 (marker id 0). Scan only the 6x6
    # family — DICT_6X6_1000 first, with DICT_6X6_250 + DICT_6X6_50 as safety
    # nets for any older print runs. Dropping the 4x4 / 5x5 / ORIGINAL
    # dictionaries cuts ArUco wall time by ~25% per view; dropping bgr_orig
    # cost is handled by the caller pre-resizing to ARUCO_MAX_SIZE.
    dict_types = [
        aruco.DICT_6X6_1000,
        aruco.DICT_6X6_250,
        aruco.DICT_6X6_50,
    ]

    best_corners = None
    best_side_px = 0.0
    best_dict_name = ""
    best_marker_id = -1
    best_n_markers = 0

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if len(bgr.shape) == 3 else bgr

    # Detector parameters tuned for field conditions (variable lighting,
    # phone cameras, ArUco card at various distances)
    params = aruco.DetectorParameters()
    params.adaptiveThreshWinSizeMin = 3
    params.adaptiveThreshWinSizeMax = 53
    params.adaptiveThreshWinSizeStep = 4
    params.minMarkerPerimeterRate = 0.01
    params.maxMarkerPerimeterRate = 4.0
    params.polygonalApproxAccuracyRate = 0.05
    params.minCornerDistanceRate = 0.02
    params.minDistanceToBorder = 1
    if hasattr(params, "cornerRefinementMethod"):
        params.cornerRefinementMethod = aruco.CORNER_REFINE_SUBPIX

    dict_names = ["6x6_1000", "6x6_250", "6x6_50"]

    for dt, name in zip(dict_types, dict_names):
        dictionary = aruco.getPredefinedDictionary(dt)

        # Try both old and new API
        try:
            detector = aruco.ArucoDetector(dictionary, params)
            corners, ids, rejected = detector.detectMarkers(gray)
        except AttributeError:
            corners, ids, rejected = aruco.detectMarkers(gray, dictionary, parameters=params)

        if ids is None or len(ids) == 0:
            continue

        # Pick the largest detected marker (most reliable). Break out of
        # the dict-scan loop on first successful match — primary dict
        # (6x6_1000) succeeds in ~99% of LEPRA field photos; running the
        # fallback dicts after a successful detect is pure wasted CPU.
        _found_in_this_dict = False
        for i, c in enumerate(corners):
            pts = c[0]   # shape (4, 2) — four corner points
            # Compute side lengths
            sides = [
                np.linalg.norm(pts[(j + 1) % 4] - pts[j]) for j in range(4)
            ]
            mean_side = float(np.mean(sides))
            if mean_side > best_side_px:
                best_side_px = mean_side
                best_corners = pts
                best_dict_name = name
                best_marker_id = int(ids[i][0])
                best_n_markers = len(ids)
                _found_in_this_dict = True
        if _found_in_this_dict:
            break

    if best_corners is None:
        meta = {"source": "aruco", "status": "fail", "reason": "no_markers_detected"}
        return (float("nan"), 0.0, meta) if return_meta else (float("nan"), 0.0)

    # Reject markers that are too small in the image — unreliable at < 30px
    if best_side_px < 30:
        log.info(f"  [ARUCO] Marker too small ({best_side_px:.1f}px < 30px) — skipping.")
        meta = {"source": "aruco", "status": "fail", "reason": "marker_too_small",
                "marker_side_px": float(best_side_px)}
        return (float("nan"), 0.0, meta) if return_meta else (float("nan"), 0.0)

    # Compute px_per_mm from known marker size
    px_per_mm = best_side_px / marker_size_mm

    # Confidence based on geometric quality
    pts = best_corners
    sides = [np.linalg.norm(pts[(j + 1) % 4] - pts[j]) for j in range(4)]
    side_std = float(np.std(sides) / (np.mean(sides) + 1e-6))
    # Perfect square → side_std ≈ 0, perspective distortion increases it
    squareness = max(0.0, 1.0 - side_std * 5.0)

    # Check angles — should be close to 90°
    angles = []
    for j in range(4):
        v1 = pts[(j - 1) % 4] - pts[j]
        v2 = pts[(j + 1) % 4] - pts[j]
        cos_a = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-6))
        angles.append(abs(cos_a))
    angle_quality = max(0.0, 1.0 - float(np.mean(angles)) * 3.0)

    # Hard reject degenerate quads — the marker code was decoded but the
    # detected corners don't form a real square. Side length measured from
    # such a quad gives meaningless px/mm. Better to fall through to card YOLO.
    if squareness < 0.30:
        log.warning(
            "  [ARUCO] Degenerate quad (squareness=%.2f, angles=%.2f) — rejected, "
            "marker side measurement unreliable.",
            squareness, angle_quality,
        )
        meta = {
            "source": "aruco",
            "status": "fail",
            "reason": "degenerate_quad",
            "marker_side_px": float(best_side_px),
            "squareness": squareness,
            "angle_quality": angle_quality,
        }
        return (float("nan"), 0.0, meta) if return_meta else (float("nan"), 0.0)

    conf = 0.5 * squareness + 0.5 * angle_quality
    conf = max(0.10, min(1.0, conf))

    # A decoded marker is not automatically a trustworthy measuring ruler.
    # In field photos, strongly oblique or motion-blurred ArUco cards can still
    # decode while their side length gives a biased px/mm scale.
    if (
        conf < ARUCO_CONF_MIN
        or squareness < ARUCO_SQUARENESS_MIN
        or angle_quality < ARUCO_ANGLE_QUALITY_MIN
    ):
        log.warning(
            "  [ARUCO] Low-quality marker geometry (conf=%.2f, squareness=%.2f, angles=%.2f) "
            "- rejected for measurement scale.",
            conf, squareness, angle_quality,
        )
        meta = {
            "source": "aruco",
            "status": "fail",
            "reason": "low_quality_quad",
            "marker_side_px": float(best_side_px),
            "marker_size_mm": marker_size_mm,
            "squareness": squareness,
            "angle_quality": angle_quality,
            "scale_conf": conf,
        }
        return (float("nan"), 0.0, meta) if return_meta else (float("nan"), 0.0)

    # Build homography from marker corners to real-world mm
    dst_pts = np.array([
        [0, 0],
        [marker_size_mm, 0],
        [marker_size_mm, marker_size_mm],
        [0, marker_size_mm],
    ], dtype=np.float32)
    homography, _ = cv2.findHomography(pts.astype(np.float32), dst_pts)
    hom_conf = conf * 0.95  # ArUco homography is very reliable

    # PnP pose recovery — estimates card 3D depth from camera.
    # Used downstream (fuse_measurements) for cross-view parallax correction.
    # focal_length_px defaults to image_width × 0.85 (~68° FOV, typical smartphone).
    _pnp_card_z = None
    _pnp_tilt_deg = None
    try:
        _bh, _bw = bgr.shape[:2]
        # Use min(W,H) so portrait and landscape views get the same focal estimate.
        # image_width × 0.85 would differ 33% between 768-wide portrait and 1024-wide
        # landscape of the same camera, making cross-view z comparisons meaningless.
        _f = focal_length_px if focal_length_px else min(_bw, _bh) * 1.1
        _K = np.array([[_f, 0, _bw / 2.0],
                       [0, _f, _bh / 2.0],
                       [0,  0,       1.0]], dtype=np.float64)
        _obj3d = np.array([[0, 0, 0],
                           [marker_size_mm, 0, 0],
                           [marker_size_mm, marker_size_mm, 0],
                           [0, marker_size_mm, 0]], dtype=np.float64)
        _ok, _rvec, _tvec = cv2.solvePnP(
            _obj3d, pts.astype(np.float64), _K, None,
            flags=cv2.SOLVEPNP_IPPE,  # IPPE works for any planar 4-pt; IPPE_SQUARE requires centered pts
        )
        _tz = float(_tvec.ravel()[2])
        if _ok and _tz > 50:   # sanity: card >50 mm from camera
            _pnp_card_z = _tz
            _pnp_tilt_deg = float(np.degrees(np.linalg.norm(_rvec)))
            log.info("  [ARUCO-PNP] card_z=%.0fmm tilt=%.1f°", _pnp_card_z, _pnp_tilt_deg)
    except Exception as _pnp_err:
        log.debug("  [ARUCO-PNP] solvePnP failed: %s", _pnp_err)

    log.info(
        "  [ARUCO] Detected dict=%s id=%d side=%.1fpx=%.1fmm → %.2f px/mm  "
        "conf=%.2f (squareness=%.2f, angles=%.2f) n_markers=%d",
        best_dict_name, best_marker_id, best_side_px, marker_size_mm,
        px_per_mm, conf, squareness, angle_quality, best_n_markers,
    )

    meta = {
        "source": "aruco",
        "status": "ok",
        "dict_type": best_dict_name,
        "marker_id": best_marker_id,
        "marker_side_px": float(best_side_px),
        "marker_size_mm": marker_size_mm,
        "n_markers_detected": best_n_markers,
        "squareness": squareness,
        "angle_quality": angle_quality,
        "homography": homography.tolist() if homography is not None else None,
        "homography_conf": hom_conf,
        "corners": best_corners.tolist(),
        "selected": True,
        "scale_conf": conf,
        "plane_conf": conf,
        "perspective_score": squareness,
        "parallax_score": conf,
        "transform_used": "homography" if homography is not None else "scale",
        "pnp_card_z_mm": _pnp_card_z,
        "pnp_tilt_deg": _pnp_tilt_deg,
    }
    return (px_per_mm, conf, meta) if return_meta else (px_per_mm, conf)


CARD_LONG_MM  = 85.6
CARD_SHORT_MM = 53.98
CARD_ASPECT_TOL = 0.20

# Class IDs must match your coin model training label order
COIN_CLASS_MAP = {
    0: ("coin_1_rupee",  25.0),
    1: ("coin_2_rupee",  25.0),
    2: ("coin_5_rupee",  23.0),
    3: ("coin_10_rupee", 27.0),   # largest, most reliable
}

DETECTION_CONF_MIN = 0.50
HOMOGRAPHY_CONF_MIN = 0.25
RECTANGULARITY_MIN = 0.50
PERSPECTIVE_SCORE_MIN = 0.15
CARD_COPLANAR_SCORE_MIN = 0.45
CARD_OVERLAP_MAX = 0.12
FOOT_LENGTH_MM_MIN = 170.0
FOOT_LENGTH_MM_MAX = 360.0


def run_reference_analysis(
    bgr_small:       np.ndarray,
    card_model_path: str,
    coin_model_path: str,
    foot_mask:       Optional[np.ndarray] = None,
    return_meta:     bool = False,
) -> tuple:
    """
    Detect reference object to establish px/mm scale.
    Priority: ArUco marker → Card YOLO → Coin YOLO.

    Returns
    -------
    px_per_mm  : float  (NaN if all fail)
    confidence : float [0, 1]
    """
    # 1. Try ArUco marker detection first (pixel-perfect, no ML model needed)
    px_per_mm, conf, meta = _run_aruco_detector(bgr_small, return_meta=True)
    if not math.isnan(px_per_mm) and conf >= ARUCO_CONF_MIN:
        log.info(f"  [REF] ArUco used — {px_per_mm:.2f} px/mm  conf={conf:.2f}")
        return (px_per_mm, conf, meta) if return_meta else (px_per_mm, conf)

    # 2. Fall back to card YOLO detector
    log.info("  [REF] ArUco not found — trying card detector...")
    px_per_mm, conf, meta = _run_card_detector(
        bgr_small,
        card_model_path,
        foot_mask=foot_mask,
        return_meta=True,
    )
    if not math.isnan(px_per_mm):
        hom_conf = float(meta.get("homography_conf", 0.0) or 0.0)
        if conf >= DETECTION_CONF_MIN or hom_conf >= HOMOGRAPHY_CONF_MIN:
            conf_used = max(conf, hom_conf)
            log.info(f"  [REF] Card used — {px_per_mm:.2f} px/mm  conf={conf_used:.2f}")
            meta["selected"] = True
            meta["scale_conf"] = conf_used
            return (px_per_mm, conf_used, meta) if return_meta else (px_per_mm, conf_used)

    # 3. Fall back to coin detector
    log.info("  [REF] Card not found — trying coin detector...")
    px_per_mm, conf, meta = _run_coin_detector(bgr_small, coin_model_path, return_meta=True)
    if not math.isnan(px_per_mm) and conf >= DETECTION_CONF_MIN:
        log.info(f"  [REF] Coin used — {px_per_mm:.2f} px/mm  conf={conf:.2f}")
        meta["selected"] = True
        meta["scale_conf"] = conf
        return (px_per_mm, conf, meta) if return_meta else (px_per_mm, conf)

    log.warning("  [REF] Neither ArUco, card, nor coin detected — scale unknown.")
    meta = {"source": None, "selected": False}
    return (float("nan"), 0.0, meta) if return_meta else (float("nan"), 0.0)


def _run_card_detector(
    bgr_small: np.ndarray,
    model_path: str,
    foot_mask: Optional[np.ndarray] = None,
    return_meta: bool = False,
    yolo_model=None,
) -> tuple:
    """
    Card YOLO model — one class: card.
    Scale from long edge. Validates ISO aspect ratio (85.6/53.98 = 1.585).
    If yolo_model is provided the model is used directly and not loaded/unloaded.
    """
    _own_model = yolo_model is None
    if _own_model:
        if not Path(model_path).exists():
            log.error("  [CARD] Model not found: %s", model_path)
            meta = {"source": "card", "status": "fail", "reason": "model_missing"}
            return (float("nan"), 0.0, meta) if return_meta else (float("nan"), 0.0)
        try:
            from ultralytics import YOLO
        except Exception as e:
            log.error("  [CARD] Import failed: %s", e)
            meta = {"source": "card", "status": "fail", "reason": "import_failed"}
            return (float("nan"), 0.0, meta) if return_meta else (float("nan"), 0.0)
        log.info("  [CARD] Loading...")
        model = YOLO(model_path)
        model.to(DEVICE)
    else:
        model = yolo_model

    results = None
    ctx = torch.inference_mode if hasattr(torch, "inference_mode") else torch.no_grad
    with ctx():
        try:
            results = model(bgr_small, verbose=False)[0]
        except RuntimeError as e:
            if "out of memory" in str(e).lower() and DEVICE == "cuda":
                log.warning("  [CARD] CUDA OOM - retrying on CPU")
                results = model(bgr_small, device="cpu", verbose=False)[0]
            else:
                log.error("  [CARD] Inference failed: %s", e)
    if _own_model:
        del model
        if torch.cuda.is_available(): torch.cuda.empty_cache()
        gc.collect()
        log.info("  [CARD] Unloaded.")

    if results is None or results.boxes is None or len(results.boxes) == 0:
        meta = {"source": "card", "status": "fail", "reason": "no_detections"}
        return (float("nan"), 0.0, meta) if return_meta else (float("nan"), 0.0)

    best = max(results.boxes, key=lambda b: float(b.conf[0]))
    conf = float(best.conf[0])
    x1, y1, x2, y2 = map(float, best.xyxy[0].tolist())

    h_img, w_img = bgr_small.shape[:2]
    pad = 0.05
    dx = (x2 - x1) * pad
    dy = (y2 - y1) * pad
    x1p = max(0, int(x1 - dx))
    y1p = max(0, int(y1 - dy))
    x2p = min(w_img, int(x2 + dx))
    y2p = min(h_img, int(y2 + dy))
    roi = bgr_small[y1p:y2p, x1p:x2p]

    rect_geom = _fit_card_rect(roi, offset=(x1p, y1p))
    if rect_geom:
        long_px, short_px = rect_geom["dims"]
        method = "rect"
    else:
        long_px  = max(x2 - x1, y2 - y1)
        short_px = min(x2 - x1, y2 - y1)
        method = "bbox"

    detected_aspect = long_px / (short_px + 1e-6)
    target_aspect   = CARD_LONG_MM / CARD_SHORT_MM
    aspect_error    = abs(detected_aspect - target_aspect) / target_aspect

    homography = None
    rectangularity = rect_geom["rectangularity"] if rect_geom else 0.0
    plane_conf = conf * rectangularity * max(0.0, 1.0 - aspect_error)
    homography_conf = 0.0
    perspective_score = 0.0
    if rect_geom and rect_geom.get("box") is not None:
        box = _order_box_points(rect_geom["box"])
        w_edge = float(np.linalg.norm(box[1] - box[0]))
        h_edge = float(np.linalg.norm(box[3] - box[0]))
        if w_edge > 1 and h_edge > 1:
            if w_edge >= h_edge:
                dst = np.array(
                    [[0, 0], [CARD_LONG_MM, 0], [CARD_LONG_MM, CARD_SHORT_MM], [0, CARD_SHORT_MM]],
                    dtype=np.float32
                )
            else:
                dst = np.array(
                    [[0, 0], [CARD_SHORT_MM, 0], [CARD_SHORT_MM, CARD_LONG_MM], [0, CARD_LONG_MM]],
                    dtype=np.float32
                )
            homography = cv2.getPerspectiveTransform(box.astype(np.float32), dst)
            perspective_score = _perspective_score(homography)
            homography_conf = plane_conf * (0.5 + 0.5 * perspective_score)

    rect_ok = rectangularity >= RECTANGULARITY_MIN
    aspect_ok = aspect_error <= CARD_ASPECT_TOL and rect_ok
    homography_ok = (
        homography is not None
        and rect_ok
        and homography_conf >= HOMOGRAPHY_CONF_MIN
    )

    if not aspect_ok and not homography_ok:
        log.warning(
            "  [CARD] Aspect error %.1f%% > %.0f%% (%s) - rejected.",
            aspect_error * 100.0, CARD_ASPECT_TOL * 100.0, method
        )
        meta = {
            "source": "card",
            "status": "fail",
            "object_class": "card",
            "method": method,
            "aspect_error": aspect_error,
            "rectangularity": rectangularity,
            "plane_conf": plane_conf,
            "perspective_score": perspective_score,
            "parallax_score": max(0.0, 1.0 - aspect_error),
            "homography_conf": homography_conf,
            "coplanarity_score": 0.0,
        }
        return (float("nan"), 0.0, meta) if return_meta else (float("nan"), 0.0)

    if homography_ok and not aspect_ok:
        log.warning(
            "  [CARD] Aspect error %.1f%% > %.0f%% (%s) - using homography.",
            aspect_error * 100.0, CARD_ASPECT_TOL * 100.0, method
        )

    px_per_mm = long_px / CARD_LONG_MM
    cop = _card_coplanarity_gate(foot_mask, (x1, y1, x2, y2), px_per_mm)
    if not cop["passed"]:
        log.warning(
            "  [CARD] Coplanarity gate failed (score=%.2f, overlap=%.2f, est_len=%.1fmm) - rejected.",
            float(cop.get("coplanarity_score", 0.0)),
            float(cop.get("overlap_ratio", 0.0)),
            float(cop.get("estimated_foot_length_mm") or float("nan")),
        )
        meta = {
            "source": "card",
            "status": "fail",
            "object_class": "card",
            "method": method,
            "aspect_error": aspect_error,
            "rectangularity": rectangularity,
            "plane_conf": plane_conf,
            "perspective_score": perspective_score,
            "parallax_score": max(0.0, 1.0 - aspect_error),
            "homography": homography.tolist() if homography is not None else None,
            "homography_conf": homography_conf,
            "coplanarity_score": float(cop.get("coplanarity_score", 0.0)),
            "overlap_ratio": float(cop.get("overlap_ratio", 0.0)),
            "estimated_foot_length_mm": cop.get("estimated_foot_length_mm"),
            "reason": "coplanarity_gate",
        }
        return (float("nan"), 0.0, meta) if return_meta else (float("nan"), 0.0)

    if aspect_ok:
        conf_adj = conf * rectangularity * (1.0 - aspect_error)
    else:
        conf_adj = conf * rectangularity * (1.0 - min(aspect_error, 0.50))
    conf_adj *= float(cop.get("coplanarity_score", 1.0))
    log.info(
        "  [CARD] %s %.1f×%.1fpx -> %.2f px/mm  conf=%.2f",
        method, long_px, short_px, px_per_mm, conf_adj
    )
    meta = {
        "source": "card",
        "status": "ok",
        "object_class": "card",
        "method": method,
        "aspect_error": aspect_error,
        "rectangularity": rectangularity,
        "plane_conf": plane_conf,
        "perspective_score": perspective_score,
        "parallax_score": max(0.0, 1.0 - aspect_error),
        "homography": homography.tolist() if homography is not None else None,
        "homography_conf": homography_conf,
        "coplanarity_score": float(cop.get("coplanarity_score", 0.0)),
        "overlap_ratio": float(cop.get("overlap_ratio", 0.0)),
        "estimated_foot_length_mm": cop.get("estimated_foot_length_mm"),
    }
    return (px_per_mm, conf_adj, meta) if return_meta else (px_per_mm, conf_adj)


def _fit_card_rect(
    roi_bgr: np.ndarray,
    offset: tuple[int, int] = (0, 0),
) -> Optional[dict]:
    """Estimate card geometry from edges inside the ROI."""
    if roi_bgr.size == 0:
        return None
    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = _find_contours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    cnt = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(cnt)
    if area < 0.05 * roi_bgr.shape[0] * roi_bgr.shape[1]:
        return None
    rect = cv2.minAreaRect(cnt)
    _, (w, h), _ = rect
    if w <= 1 or h <= 1:
        return None
    box = cv2.boxPoints(rect)
    box[:, 0] += float(offset[0])
    box[:, 1] += float(offset[1])
    rectangularity = float(area / (w * h + 1e-6))
    return {
        "dims": (max(w, h), min(w, h)),
        "box": box,
        "rectangularity": rectangularity,
        "area": float(area),
    }


def _order_box_points(pts: np.ndarray) -> np.ndarray:
    """Order 4 points as top-left, top-right, bottom-right, bottom-left."""
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1).reshape(-1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def _perspective_score(h: Optional[np.ndarray]) -> float:
    """Heuristic perspective score from homography terms. Higher is better."""
    if h is None:
        return 0.0
    try:
        h = np.array(h, dtype=np.float32)
        if h.shape != (3, 3):
            return 0.0
        persp = float(np.linalg.norm(h[2, :2]))
        score = 1.0 / (1.0 + 50.0 * persp)
        return float(np.clip(score, 0.0, 1.0))
    except Exception:
        return 0.0


def _card_coplanarity_gate(
    foot_mask: Optional[np.ndarray],
    card_xyxy: tuple[float, float, float, float],
    px_per_mm: float,
) -> dict:
    """
    Heuristic coplanarity gate:
    - card/foot overlap should be low
    - implied foot length (from mask + card scale) should be plausible
    """
    out = {
        "coplanarity_score": 0.5,
        "overlap_ratio": 0.0,
        "estimated_foot_length_mm": None,
        "length_plausible": True,
        "passed": True,
    }
    if foot_mask is None or foot_mask.sum() == 0 or not np.isfinite(px_per_mm) or px_per_mm <= 0:
        return out

    mask = (foot_mask > 0).astype(np.uint8)
    h, w = mask.shape[:2]
    x1, y1, x2, y2 = card_xyxy
    x1i = int(np.clip(np.floor(x1), 0, max(w - 1, 0)))
    y1i = int(np.clip(np.floor(y1), 0, max(h - 1, 0)))
    x2i = int(np.clip(np.ceil(x2), 0, w))
    y2i = int(np.clip(np.ceil(y2), 0, h))
    card_area = max(0, (x2i - x1i)) * max(0, (y2i - y1i))

    overlap_ratio = 0.0
    if card_area > 0:
        inter = int(mask[y1i:y2i, x1i:x2i].sum())
        overlap_ratio = float(inter / float(card_area))

    foot_len_px = _estimate_mask_long_edge_px(mask)
    est_len_mm = None
    length_score = 0.6
    length_plausible = True
    if foot_len_px is not None:
        est_len_mm = float(foot_len_px / px_per_mm)
        if FOOT_LENGTH_MM_MIN <= est_len_mm <= FOOT_LENGTH_MM_MAX:
            length_score = 1.0
            length_plausible = True
        else:
            length_plausible = False
            if est_len_mm < FOOT_LENGTH_MM_MIN:
                delta = (FOOT_LENGTH_MM_MIN - est_len_mm) / FOOT_LENGTH_MM_MIN
            else:
                delta = (est_len_mm - FOOT_LENGTH_MM_MAX) / FOOT_LENGTH_MM_MAX
            length_score = float(np.clip(1.0 - 1.5 * delta, 0.0, 1.0))

    overlap_score = float(np.clip(1.0 - overlap_ratio / max(CARD_OVERLAP_MAX, 1e-6), 0.0, 1.0))
    cop_score = 0.65 * length_score + 0.35 * overlap_score
    passed = bool((overlap_ratio <= CARD_OVERLAP_MAX) and (cop_score >= CARD_COPLANAR_SCORE_MIN) and length_plausible)

    out.update({
        "coplanarity_score": float(cop_score),
        "overlap_ratio": float(overlap_ratio),
        "estimated_foot_length_mm": est_len_mm,
        "length_plausible": bool(length_plausible),
        "passed": passed,
    })
    return out


def _run_coin_detector(
    bgr_small: np.ndarray,
    model_path: str,
    return_meta: bool = False,
    yolo_model=None,
) -> tuple:
    """
    Coin YOLO model — 4 classes: ₹1/₹2/₹5/₹10.
    Prefers ₹10 (largest, most reliable). Scale from circle fitting.
    If yolo_model is provided the model is used directly and not loaded/unloaded.
    """
    _own_model = yolo_model is None
    if _own_model:
        if not Path(model_path).exists():
            log.error("  [COIN] Model not found: %s", model_path)
            meta = {"source": "coin", "status": "fail", "reason": "model_missing"}
            return (float("nan"), 0.0, meta) if return_meta else (float("nan"), 0.0)
        try:
            from ultralytics import YOLO
        except Exception as e:
            log.error("  [COIN] Import failed: %s", e)
            meta = {"source": "coin", "status": "fail", "reason": "import_failed"}
            return (float("nan"), 0.0, meta) if return_meta else (float("nan"), 0.0)
        log.info("  [COIN] Loading...")
        model = YOLO(model_path)
        model.to(DEVICE)
    else:
        model = yolo_model

    results = None
    ctx = torch.inference_mode if hasattr(torch, "inference_mode") else torch.no_grad
    with ctx():
        try:
            results = model(bgr_small, verbose=False)[0]
        except RuntimeError as e:
            if "out of memory" in str(e).lower() and DEVICE == "cuda":
                log.warning("  [COIN] CUDA OOM - retrying on CPU")
                results = model(bgr_small, device="cpu", verbose=False)[0]
            else:
                log.error("  [COIN] Inference failed: %s", e)
    if _own_model:
        del model
        if torch.cuda.is_available(): torch.cuda.empty_cache()
        gc.collect()
        log.info("  [COIN] Unloaded.")

    if results is None or results.boxes is None or len(results.boxes) == 0:
        meta = {"source": "coin", "status": "fail", "reason": "no_detections"}
        return (float("nan"), 0.0, meta) if return_meta else (float("nan"), 0.0)

    boxes     = list(results.boxes)
    ten_rupee = [b for b in boxes if int(b.cls[0]) == 3]
    best      = max(ten_rupee, key=lambda b: float(b.conf[0])) if ten_rupee                 else max(boxes, key=lambda b: float(b.conf[0]))

    cls_id  = int(best.cls[0])
    conf    = float(best.conf[0])
    x1, y1, x2, y2 = map(float, best.xyxy[0].tolist())

    coin_info = COIN_CLASS_MAP.get(cls_id)
    if coin_info is None:
        meta = {"source": "coin", "status": "fail", "reason": "class_unknown"}
        return (float("nan"), 0.0, meta) if return_meta else (float("nan"), 0.0)

    coin_name, known_mm = coin_info
    roi         = bgr_small[int(y1):int(y2), int(x1):int(x2)]
    diameter_px = _fit_coin_circle(roi) or math.hypot(x2 - x1, y2 - y1)

    # Circularity check
    bbox_diam   = max(x2 - x1, y2 - y1)
    circularity = diameter_px / (bbox_diam + 1e-6)
    if not (0.80 < circularity < 1.20):
        log.warning(f"  [COIN] Circularity {circularity:.2f} out of range.")
        conf *= 0.70

    px_per_mm = diameter_px / known_mm
    plane_conf = conf * max(0.0, 1.0 - abs(circularity - 1.0))
    log.info(f"  [COIN] {coin_name}: {diameter_px:.1f}px={known_mm}mm → {px_per_mm:.2f} px/mm  conf={conf:.2f}")
    meta = {
        "source": "coin",
        "status": "ok",
        "object_class": coin_name,
        "circularity": circularity,
        "plane_conf": plane_conf,
        "parallax_score": plane_conf,
    }
    return (px_per_mm, conf, meta) if return_meta else (px_per_mm, conf)


def _fit_coin_circle(roi_bgr: np.ndarray) -> Optional[float]:
    """Circle fit on coin ROI. Returns diameter px or None."""
    if roi_bgr.size == 0:
        return None
    gray    = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    contours, _ = _find_contours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    cnt        = max(contours, key=cv2.contourArea)
    area       = cv2.contourArea(cnt)
    perimeter  = cv2.arcLength(cnt, True)
    if perimeter == 0:
        return None
    if 4 * math.pi * area / (perimeter ** 2) < 0.70:
        return None   # not circular enough
    _, radius = cv2.minEnclosingCircle(cnt)
    return float(radius * 2)


# ═══════════════════════════════════════════════════════════
# STAGE 4 — LANDMARK DETECTION  (MMPose HRNet)
# Load → run → unload
# ═══════════════════════════════════════════════════════════

def _empty_landmarks(view: str) -> dict[str, dict]:
    return {
        name: {"x": 0.0, "y": 0.0, "conf": 0.0}
        for name in LANDMARK_NAMES.get(view, [])
    }


def run_landmark_detection(
    image:       np.ndarray | str,
    config_path: str,
    ckpt_path:   str,
    view:        str,
    foot_side:   str,
    mask_small:  np.ndarray,
    scale:       float,
    lenient_mode: bool = False,
    pose_model=None,
) -> dict[str, dict]:
    """
    Run MMPose HRNet landmark detection.
    If pose_model is provided it is used directly and not loaded/unloaded.
    Otherwise the model is loaded, run, and unloaded within this function.

    Parameters
    ----------
    image       : ORIGINAL image array (preferred) or path
    config_path : MMPose .py config
    ckpt_path   : .pth checkpoint
    view        : "plantar" | "dorsal" | "medial"
    foot_side   : "left" | "right"
    mask_small  : SAM mask at small-image resolution
    scale       : small/original pixel ratio
    lenient_mode: relax out-of-mask landmark suppression
    pose_model  : optional pre-loaded MMPose model

    Returns
    -------
    { landmark_name: {"x": px, "y": px, "conf": float} }
    Coordinates in ORIGINAL image pixel space.
    """
    if view not in LANDMARK_NAMES:
        log.error("  [MMPose] Unknown view: %s", view)
        return {}
    if isinstance(image, str) and not Path(image).exists():
        log.error("  [MMPose] Image not found: %s", image)
        return _empty_landmarks(view)

    _own_model = pose_model is None
    if _own_model:
        if not Path(config_path).exists():
            log.error("  [MMPose] Config not found: %s", config_path)
            return _empty_landmarks(view)
        if not Path(ckpt_path).exists():
            log.error("  [MMPose] Checkpoint not found: %s", ckpt_path)
            return _empty_landmarks(view)
        try:
            from mmpose.apis import inference_topdown, init_model
            from mmpose.structures import merge_data_samples
            from mmpose.utils import register_all_modules
        except Exception as e:
            log.error("  [MMPose] Import failed: %s", e)
            return _empty_landmarks(view)
        register_all_modules()
        log.info(f"  [MMPose] Loading {view} model...")
        model = init_model(config_path, ckpt_path, device=DEVICE)
    else:
        try:
            from mmpose.apis import inference_topdown
            from mmpose.structures import merge_data_samples
        except Exception as e:
            log.error("  [MMPose] Import failed: %s", e)
            return _empty_landmarks(view)
        model = pose_model

    image_for_pose = image
    if isinstance(image, np.ndarray):
        mask_orig = cv2.resize(
            (mask_small > 0).astype(np.uint8),
            (image.shape[1], image.shape[0]),
            interpolation=cv2.INTER_NEAREST,
        )
        image_for_pose = image.copy()
        image_for_pose[mask_orig == 0] = 0
    bbox_xywh  = _mask_to_bbox(mask_small, scale)
    bbox_xyxy  = _xywh_to_xyxy(bbox_xywh) if bbox_xywh is not None else None

    try:
        if bbox_xywh is not None:
            try:
                result = inference_topdown(
                    model, image_for_pose, bboxes=bbox_xywh, bbox_format="xywh"
                )
            except TypeError:
                # Older MMPose expects xyxy if bbox_format is unsupported.
                result = inference_topdown(model, image_for_pose, bboxes=bbox_xyxy)
        else:
            result = inference_topdown(model, image_for_pose)

        result    = merge_data_samples(result)
        keypoints = result.pred_instances.keypoints[0]       # (K, 2)
        scores    = result.pred_instances.keypoint_scores[0] # (K,)

    except Exception as e:
        log.error(f"  [MMPose] Failed: {e}")
        k         = len(LANDMARK_NAMES[view])
        keypoints = np.zeros((k, 2))
        scores    = np.zeros(k)

    finally:
        if _own_model:
            del model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()
            log.info(f"  [MMPose] {view} model unloaded.")

    index_map = LANDMARK_INDEX_MAP.get((foot_side, view))
    if index_map:
        if "toe_tip" in LANDMARK_NAMES.get(view, []) and "toe_tip" not in index_map:
            log.warning(
                "  [MMPose] %s/%s model has no toe_tip output; using mask fallback for toe-based metrics.",
                foot_side, view
            )
        out = {}
        for i, name in enumerate(index_map):
            if i >= len(keypoints) or name is None:
                continue
            val = {
                "x":    float(keypoints[i][0]),
                "y":    float(keypoints[i][1]),
                "conf": float(scores[i]),
            }
            if name in out:
                if val["conf"] > out[name]["conf"]:
                    out[name] = val
            else:
                out[name] = val
        out = _suppress_landmarks_outside_mask(
            out,
            mask_small,
            scale,
            view=view,
            lenient_mode=lenient_mode,
        )
        return out

    out = {
        name: {
            "x":    float(keypoints[i][0]),
            "y":    float(keypoints[i][1]),
            "conf": float(scores[i]),
        }
        for i, name in enumerate(LANDMARK_NAMES[view])
        if i < len(keypoints)
    }
    out = _suppress_landmarks_outside_mask(
        out,
        mask_small,
        scale,
        view=view,
        lenient_mode=lenient_mode,
    )
    return out


def _suppress_landmarks_outside_mask(
    landmarks: dict[str, dict],
    mask_small: np.ndarray,
    scale: float,
    margin_px: float = 10.0,
    view: Optional[str] = None,
    lenient_mode: bool = False,
) -> dict[str, dict]:
    """
    Reduce confidence of landmarks far outside foot mask.
    Prevents points jumping to card/background when pose model fails.
    """
    if not landmarks:
        return landmarks
    if mask_small is None or mask_small.size == 0 or scale <= 0:
        return landmarks

    hard_drop_extra_px = 18.0
    soften_factor = 0.2
    if view in ("dorsal", "medial"):
        margin_px = max(margin_px, 14.0)
        hard_drop_extra_px = 28.0
        soften_factor = 0.35
    if lenient_mode:
        margin_px += 6.0
        hard_drop_extra_px += 12.0
        soften_factor = min(0.65, soften_factor + 0.20)
        if view in ("dorsal", "medial"):
            margin_px = max(margin_px, 20.0)
            hard_drop_extra_px = max(hard_drop_extra_px, 44.0)
            soften_factor = max(soften_factor, 0.55)

    h_s, w_s = mask_small.shape[:2]
    w_o = max(1, int(round(w_s / scale)))
    h_o = max(1, int(round(h_s / scale)))
    mask_o = cv2.resize((mask_small > 0).astype(np.uint8), (w_o, h_o), interpolation=cv2.INTER_NEAREST)

    k = max(3, int(round(max(h_o, w_o) * 0.01)))
    if k % 2 == 0:
        k += 1
    mask_d = cv2.dilate(mask_o, np.ones((k, k), np.uint8), iterations=1)
    outside = (mask_d == 0).astype(np.uint8) * 255
    dist_to_mask = cv2.distanceTransform(outside, cv2.DIST_L2, 5).astype(np.float32)

    dropped = 0
    softened = 0
    for name, d in landmarks.items():
        try:
            conf = float(d.get("conf", 0.0))
            if conf <= 0:
                continue
            x = int(round(float(d["x"])))
            y = int(round(float(d["y"])))
        except Exception:
            continue
        if x < 0 or y < 0 or x >= w_o or y >= h_o:
            d["conf"] = 0.0
            dropped += 1
            continue
        dist = float(dist_to_mask[y, x])
        if dist <= margin_px:
            continue
        if dist >= margin_px + hard_drop_extra_px:
            d["conf"] = 0.0
            dropped += 1
        else:
            # Soften: penalize confidence to signal uncertainty.
            # Floor at CONF_MIN to avoid dropping landmarks that were just
            # barely above CONF_MIN but get crushed by multiplication
            # (e.g., 0.32 * 0.35 = 0.11, below the 0.30 cutoff).
            # The soften factor still reduces confidence in the heatmap-export
            # / fusion sense; we just don't want to gate them out entirely
            # here when the segmentation might be the inaccurate party.
            softened_conf = float(conf * soften_factor)
            d["conf"] = max(softened_conf, CONF_MIN)
            softened += 1

    if dropped > 0 or softened > 0:
        mode_txt = " [lenient]" if lenient_mode else ""
        log.info(
            "  [MMPose] Mask-consistency filter%s: dropped=%d softened=%d",
            mode_txt,
            dropped,
            softened,
        )
    return landmarks


def _mask_to_bbox(mask: np.ndarray, scale: float, pad: float = 0.05):
    """SAM mask (small coords) → xywh bbox (original coords) for MMPose."""
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return None
    x1, y1 = float(xs.min()) / scale, float(ys.min()) / scale
    x2, y2 = float(xs.max()) / scale, float(ys.max()) / scale
    w, h   = x2 - x1, y2 - y1
    x1     = max(0.0, x1 - w * pad)
    y1     = max(0.0, y1 - h * pad)
    return np.array([[x1, y1, w * (1 + 2 * pad), h * (1 + 2 * pad)]], dtype=np.float32)


def _xywh_to_xyxy(bbox_xywh: np.ndarray) -> np.ndarray:
    """Convert xywh to xyxy for older MMPose inference APIs."""
    x1 = bbox_xywh[:, 0]
    y1 = bbox_xywh[:, 1]
    w  = bbox_xywh[:, 2]
    h  = bbox_xywh[:, 3]
    return np.stack([x1, y1, x1 + w, y1 + h], axis=1).astype(np.float32)


# ═══════════════════════════════════════════════════════════
# STAGE 5 — GEOMETRY ENGINE
# Pure CPU — no models, no GPU
# ═══════════════════════════════════════════════════════════

def run_geometry(
    view:       str,
    mask_small: np.ndarray,
    scale:      float,
    px_per_mm:  float,
    landmarks:  dict[str, dict],
    ref_meta:   Optional[dict] = None,
    allow_mask_fallback: bool = True,
) -> dict[str, float]:
    """
    Compute physical measurements in mm from mask + landmarks + scale.

    Parameters
    ----------
    view        : "plantar" | "dorsal" | "medial"
    mask_small  : SAM binary mask at small resolution
    scale       : small/original pixel ratio
    px_per_mm   : pixels per mm in small-image space
    landmarks   : output of run_landmark_detection()
    ref_meta    : reference geometry metadata (optional)

    Returns
    -------
    { measurement_name: value }
    Linear measurements in mm, angular in degrees (_deg suffix).
    """

    use_h = False
    H = None
    if ref_meta and ref_meta.get("homography") is not None and view in ("plantar", "dorsal", "medial"):
        try:
            H = np.array(ref_meta["homography"], dtype=np.float32)
            perspective_score = ref_meta.get("perspective_score", 1.0)
            homography_conf_min = HOMOGRAPHY_CONF_MIN if view in ("plantar", "dorsal") else max(HOMOGRAPHY_CONF_MIN, 0.35)
            perspective_min = PERSPECTIVE_SCORE_MIN if view in ("plantar", "dorsal") else max(PERSPECTIVE_SCORE_MIN, 0.20)
            if (
                H.shape == (3, 3)
                and ref_meta.get("homography_conf", 0.0) >= homography_conf_min
                and perspective_score >= perspective_min
            ):
                use_h = True
        except Exception:
            use_h = False
    if ref_meta is not None:
        ref_meta["transform_used"] = "homography" if use_h else "scale"

    def _apply_homography(pts: np.ndarray) -> np.ndarray:
        pts = pts.reshape(-1, 1, 2).astype(np.float32)
        out = cv2.perspectiveTransform(pts, H).reshape(-1, 2)
        return out.astype(np.float32, copy=False)

    def _to_mm_point(p: Optional[dict]) -> Optional[dict]:
        if p is None or not use_h:
            return p
        pt = np.array([[[p["x"], p["y"]]]], dtype=np.float32)
        dst = cv2.perspectiveTransform(pt, H)[0][0]
        if not np.isfinite(dst).all():
            return p
        return {"x": float(dst[0]), "y": float(dst[1]), "conf": p["conf"]}

    def _mask_points() -> Optional[np.ndarray]:
        ys, xs = np.where(mask_small > 0)
        if len(xs) == 0:
            return None
        pts = np.column_stack([xs, ys]).astype(np.float32)
        if len(pts) > 50000:
            step = max(1, len(pts) // 50000)
            pts = pts[::step]
        if use_h:
            pts = _apply_homography(pts)
            pts = pts[np.isfinite(pts).all(axis=1)]
            if len(pts) == 0:
                return None
        return pts.astype(np.float32, copy=False)

    def _mask_toe_proxy(pter: Optional[dict]) -> Optional[dict]:
        """Estimate toe as mask point farthest from pternion when toe landmark is absent."""
        if pter is None:
            return None
        ys, xs = np.where(mask_small > 0)
        if len(xs) < 20:
            return None
        pts = np.column_stack([xs, ys]).astype(np.float32)
        p = np.array([float(pter["x"]), float(pter["y"])], dtype=np.float32)
        d2 = np.sum((pts - p) ** 2, axis=1)
        idx = int(np.argmax(d2))
        return {"x": float(pts[idx, 0]), "y": float(pts[idx, 1]), "conf": float(CONF_MIN - 1e-3)}

    def lm(name: str) -> Optional[dict]:
        """Return landmark in small-image coords if confident, else None."""
        d = landmarks.get(name)
        if d is None or d["conf"] < CONF_MIN:
            return None
        return {"x": d["x"] * scale, "y": d["y"] * scale, "conf": d["conf"]}

    def dist(a: dict, b: dict) -> float:
        a1 = _to_mm_point(a) if use_h else a
        b1 = _to_mm_point(b) if use_h else b
        d = math.hypot(b1["x"] - a1["x"], b1["y"] - a1["y"])
        return d if use_h else d / px_per_mm

    def vdist(a: dict, b: dict) -> float:
        a1 = _to_mm_point(a) if use_h else a
        b1 = _to_mm_point(b) if use_h else b
        d = abs(b1["y"] - a1["y"])
        return d if use_h else d / px_per_mm

    def angle(p1: dict, vertex: dict, p2: dict) -> float:
        if use_h:
            p1 = _to_mm_point(p1)
            vertex = _to_mm_point(vertex)
            p2 = _to_mm_point(p2)
        v1 = np.array([p1["x"] - vertex["x"], p1["y"] - vertex["y"]])
        v2 = np.array([p2["x"] - vertex["x"], p2["y"] - vertex["y"]])
        n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
        if n1 == 0 or n2 == 0:
            return 0.0
        return float(math.degrees(math.acos(
            np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0)
        )))

    def obb_dims() -> tuple[Optional[float], Optional[float]]:
        """Oriented bounding box → (length_mm, width_mm). Fallback when landmarks missing."""
        pts = _mask_points()
        if pts is None or len(pts) < 3:
            return None, None
        pts = np.ascontiguousarray(pts, dtype=np.float32)
        if pts.ndim == 2 and pts.shape[1] == 2:
            pts_in = pts
        else:
            pts_in = pts.reshape(-1, 2)
        try:
            _, (wp, hp), _ = cv2.minAreaRect(pts_in)
        except cv2.error as e:
            log.warning("minAreaRect failed: %s", e)
            return None, None
        if use_h:
            return max(wp, hp), min(wp, hp)
        return max(wp, hp) / px_per_mm, min(wp, hp) / px_per_mm

    def _mask_contour() -> Optional[np.ndarray]:
        mask_u8 = (mask_small > 0).astype(np.uint8)
        contours, _ = _find_contours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        return max(contours, key=cv2.contourArea)

    def _mask_area_perimeter() -> tuple[Optional[float], Optional[float], Optional[float]]:
        cnt = _mask_contour()
        if cnt is None:
            return None, None, None
        if use_h:
            pts = cnt.reshape(-1, 2).astype(np.float32)
            pts = _apply_homography(pts)
            if len(pts) < 3:
                return None, None, None
            area = float(abs(cv2.contourArea(pts)))
            peri = float(cv2.arcLength(pts, True))
        else:
            area = float(cv2.contourArea(cnt)) / (px_per_mm ** 2)
            peri = float(cv2.arcLength(cnt, True)) / px_per_mm
        compact = None
        if peri > 1e-6:
            compact = float(4.0 * math.pi * area / (peri ** 2))
        return area, peri, compact

    def _axis_basis(
        toe: Optional[dict],
        pter: Optional[dict],
        pts: np.ndarray,
    ) -> Optional[tuple[np.ndarray, np.ndarray, np.ndarray]]:
        if use_h:
            toe = _to_mm_point(toe)
            pter = _to_mm_point(pter)

        axis = None
        origin = None
        if toe and pter:
            axis = np.array([toe["x"] - pter["x"], toe["y"] - pter["y"]], dtype=np.float32)
            if np.linalg.norm(axis) > 1e-6:
                origin = np.array([pter["x"], pter["y"]], dtype=np.float32)
            else:
                axis = None

        if axis is None:
            mean = pts.mean(axis=0)
            cov = np.cov(pts.T)
            eigvals, eigvecs = np.linalg.eigh(cov)
            axis = eigvecs[:, int(np.argmax(eigvals))]
            origin = mean

        axis_norm = np.linalg.norm(axis)
        if axis_norm <= 1e-6:
            return None
        unit_axis = axis / axis_norm
        unit_perp = np.array([-unit_axis[1], unit_axis[0]], dtype=np.float32)
        return origin, unit_axis, unit_perp

    def _band_width(
        toe: Optional[dict],
        pter: Optional[dict],
        frac_lo: float,
        frac_hi: float,
        min_pts: int = 20,
    ) -> Optional[float]:
        pts = _mask_points()
        if pts is None or len(pts) < 3:
            return None
        pts = np.ascontiguousarray(pts, dtype=np.float32)
        basis = _axis_basis(toe, pter, pts)
        if basis is None:
            return None
        origin, unit_axis, unit_perp = basis

        proj = (pts - origin) @ unit_axis
        foot_len_px = float(proj.max() - proj.min())
        if foot_len_px <= 1e-6:
            return None

        lo = float(proj.min() + frac_lo * foot_len_px)
        hi = float(proj.min() + frac_hi * foot_len_px)
        band_pts = pts[(proj >= lo) & (proj <= hi)]
        if len(band_pts) < min_pts:
            return None

        perp = (band_pts - origin) @ unit_perp
        width_px = float(perp.max() - perp.min())
        if width_px <= 0:
            return None
        return width_px if use_h else width_px / px_per_mm

    def heel_width(toe: Optional[dict], pter: Optional[dict]) -> Optional[float]:
        """Orientation-invariant heel width using toe->heel axis or mask PCA."""
        return _band_width(toe, pter, frac_lo=0.00, frac_hi=0.18, min_pts=12)

    def forefoot_width(toe: Optional[dict], pter: Optional[dict]) -> Optional[float]:
        """Mask-based forefoot width around metatarsal region (not distal toe tips)."""
        return _band_width(toe, pter, frac_lo=0.62, frac_hi=0.86, min_pts=20)

    def midfoot_width(toe: Optional[dict], pter: Optional[dict]) -> Optional[float]:
        """Mask-based midfoot/instep width."""
        return _band_width(toe, pter, frac_lo=0.40, frac_hi=0.62, min_pts=20)

    def mask_length_envelope(toe: Optional[dict], pter: Optional[dict]) -> Optional[float]:
        """
        Long-axis mask envelope length.
        Uses toe->heel axis when landmarks are available, else PCA axis.
        This makes sure toe extremities from contour are considered.
        """
        pts = _mask_points()
        if pts is None or len(pts) < 3:
            return None
        pts = np.ascontiguousarray(pts, dtype=np.float32)
        basis = _axis_basis(toe, pter, pts)
        if basis is None:
            return None
        origin, unit_axis, _ = basis
        proj = (pts - origin) @ unit_axis
        length_px = float(proj.max() - proj.min())
        if length_px <= 0:
            return None
        return length_px if use_h else length_px / px_per_mm

    obb_len, obb_wid = obb_dims()
    mask_area_mm2, mask_perimeter_mm, mask_compactness = _mask_area_perimeter()

    out = {}
    if obb_len is not None and obb_wid is not None:
        out["mask_length_mm"] = obb_len
        out["mask_width_mm"] = obb_wid
    if mask_area_mm2 is not None:
        out["mask_area_mm2"] = mask_area_mm2
    if mask_perimeter_mm is not None:
        out["mask_perimeter_mm"] = mask_perimeter_mm
    if mask_compactness is not None:
        out["mask_compactness"] = mask_compactness

    # ── PLANTAR ────────────────────────────────────────────────
    # 4 landmarks: toe_tip, met1, met5, pternion
    if view == "plantar":
        toe  = lm("toe_tip")
        met1 = lm("met1")
        met5 = lm("met5")
        pter = lm("pternion")
        env_len = mask_length_envelope(toe, pter)

        # Foot length — primary source
        if toe and pter:
            lm_len = dist(toe, pter)
            if env_len and env_len > lm_len * 1.01:
                out["foot_length_mm"] = env_len
                out["foot_length_source"] = "mask_envelope_snap"
            else:
                out["foot_length_mm"] = lm_len
        else:
            if allow_mask_fallback:
                if env_len:
                    out["foot_length_mm"] = env_len
                    out["foot_length_source"] = "mask_envelope_fallback"
                elif obb_len:
                    out["foot_length_mm"] = obb_len
                    out["foot_length_source"] = "mask_obb_fallback"

        # Forefoot width — primary source
        if met1 and met5:
            out["forefoot_width_mm"] = dist(met1, met5)
        elif allow_mask_fallback:
            fw = forefoot_width(toe, pter)
            if fw:
                out["forefoot_width_mm"] = fw

        # Heel width — mask based
        if allow_mask_fallback or (toe and pter):
            hw = heel_width(toe, pter)
            if hw:
                out["heel_width_mm"] = hw
            mw = midfoot_width(toe, pter)
            if mw:
                out["midfoot_width_mm"] = mw

        # Toe axis angle
        if toe and pter:
            out["toe_axis_angle_deg"] = math.degrees(
                math.atan2(abs(toe["y"] - pter["y"]),
                           abs(toe["x"] - pter["x"]) + 1e-6)
            )

    # ── DORSAL ─────────────────────────────────────────────────
    # 4 landmarks: toe_tip, met1, met5, pternion
    elif view == "dorsal":
        toe  = lm("toe_tip")
        met1 = lm("met1")
        met5 = lm("met5")
        pter = lm("pternion")
        env_len = mask_length_envelope(toe, pter)

        # Foot length — confirmatory (0.85 weight in fusion)
        if toe and pter:
            lm_len = dist(toe, pter)
            if env_len and env_len > lm_len * 1.01:
                out["foot_length_mm"] = env_len
                out["foot_length_source"] = "mask_envelope_snap"
            else:
                out["foot_length_mm"] = lm_len
        else:
            if allow_mask_fallback:
                if env_len:
                    out["foot_length_mm"] = env_len
                    out["foot_length_source"] = "mask_envelope_fallback"
                elif obb_len:
                    out["foot_length_mm"] = obb_len
                    out["foot_length_source"] = "mask_obb_fallback"

        # Forefoot width — confirmatory
        if met1 and met5:
            out["forefoot_width_mm"] = dist(met1, met5)
        elif allow_mask_fallback:
            fw = forefoot_width(toe, pter)
            if fw:
                out["forefoot_width_mm"] = fw

        # Heel width — confirmatory
        if allow_mask_fallback or (toe and pter):
            hw = heel_width(toe, pter)
            if hw:
                out["heel_width_mm"] = hw
            mw = midfoot_width(toe, pter)
            if mw:
                out["midfoot_width_mm"] = mw

        # Toe axis angle — confirmatory
        if toe and pter:
            out["toe_axis_angle_deg"] = math.degrees(
                math.atan2(abs(toe["y"] - pter["y"]),
                           abs(toe["x"] - pter["x"]) + 1e-6)
            )

    # ── MEDIAL ─────────────────────────────────
    # 6 landmarks: toe_tip, met1, met1_apex, arch_low, pternion, foot_leg_jxn
    elif view == "medial":
        toe       = lm("toe_tip")
        met1      = lm("met1")
        met1_apex = lm("met1_apex")
        arch_low  = lm("arch_low")
        pter      = lm("pternion")
        jxn       = lm("foot_leg_jxn")
        toe_for_length = toe
        if toe_for_length is None and allow_mask_fallback and pter:
            toe_for_length = _mask_toe_proxy(pter)
            if toe_for_length is not None:
                out["toe_tip_source"] = "mask_proxy"

        # Foot length — confirmatory
        if toe_for_length and pter:
            out["foot_length_mm"] = dist(toe_for_length, pter)

        # Arch height
        # Ground plane = mean y of met1 + pternion (both contact ground)
        if arch_low and met1:
            ground_pts = [met1] + ([pter] if pter else [])
            if use_h:
                arch_low_t = _to_mm_point(arch_low)
                ground_t = [_to_mm_point(p) for p in ground_pts]
                ground_y = float(np.mean([p["y"] for p in ground_t]))
                out["arch_height_mm"] = abs(ground_y - arch_low_t["y"])
            else:
                ground_y = float(np.mean([p["y"] for p in ground_pts]))
                out["arch_height_mm"] = abs(ground_y - arch_low["y"]) / px_per_mm

        # 1st metatarsal head height above ground
        if met1_apex and met1:
            out["met1_height_mm"] = vdist(met1_apex, met1)

        # Foot-leg angle: angle at pternion between toe direction and leg direction
        if toe and pter and jxn:
            out["foot_leg_angle_deg"] = angle(toe, pter, jxn)

        # Malleoli height: vertical distance from heel_base (ground) to
        # lateral_malleolus (outer ankle bump). Used by shoe technicians to
        # set shoe collar height. Both keypoints come from the 2026-04 medial
        # retrain (8-keypoint model).
        mal = lm("lateral_malleolus")
        hbase = lm("heel_base")
        if mal and hbase:
            out["malleoli_height_mm"] = vdist(mal, hbase)

    return {k: round(v, 2) if isinstance(v, float) else v for k, v in out.items()}


# ═══════════════════════════════════════════════════════════
# DEPTH REFINEMENT MODULE
# ═══════════════════════════════════════════════════════════

@dataclass
class RefineParams:
    perimeter_scales: tuple[float, ...] = (1.0, 0.75, 0.5, 0.25)
    clinical_scale: float = 0.5
    depth_max_size: int = 384
    depth_model_name: str = "DPT_Hybrid"
    curvature_low: float = 0.002
    curvature_high: float = 0.01
    region_fracs: Optional[dict[str, tuple[float, float]]] = None
    scale_rel_base: float = 0.02
    scale_rel_gain: float = 0.08
    landmark_sigma_base: float = 2.0
    boundary_sigma_gain: float = 0.15
    depth_sigma_gain: float = 1.0
    min_points: int = 1000

    def __post_init__(self):
        if self.region_fracs is None:
            self.region_fracs = {
                "heel": (0.00, 0.15),
                "arch": (0.35, 0.65),
                "forefoot": (0.85, 1.00),
            }


def _largest_contour(mask_u8: np.ndarray) -> Optional[np.ndarray]:
    contours, _ = _find_contours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    return max(contours, key=cv2.contourArea)


def _polyline_length(pts: np.ndarray) -> float:
    if len(pts) < 2:
        return 0.0
    diffs = np.diff(np.vstack([pts, pts[0]]), axis=0)
    return float(np.sum(np.linalg.norm(diffs, axis=1)))


def _fit_loglog(x, y):
    x = np.asarray(x, dtype=np.float32)
    y = np.asarray(y, dtype=np.float32)
    A = np.vstack([x, np.ones_like(x)]).T
    m, c = np.linalg.lstsq(A, y, rcond=None)[0]
    resid = y - (m * x + c)
    sigma = float(np.sqrt(np.mean(resid ** 2))) if len(resid) > 0 else 0.0
    return m, c, sigma


def _compute_multiscale_perimeter(
    mask_small: np.ndarray,
    px_per_mm: float,
    homography: Optional[np.ndarray],
    params: RefineParams,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    perims = []
    scales = []
    h, w = mask_small.shape[:2]

    for s in params.perimeter_scales:
        m = cv2.resize(mask_small, (int(w * s), int(h * s)), interpolation=cv2.INTER_NEAREST)
        cnt = _largest_contour((m > 0).astype(np.uint8))
        if cnt is None:
            continue
        pts = cnt[:, 0, :].astype(np.float32) / s

        if homography is not None:
            pts_mm = cv2.perspectiveTransform(pts.reshape(-1, 1, 2), homography).reshape(-1, 2)
            per = _polyline_length(pts_mm)
        else:
            per = _polyline_length(pts) / px_per_mm

        perims.append(per)
        scales.append(s)

    if len(perims) < 2:
        return None, None, None

    log_s = np.log(scales)
    log_p = np.log(np.maximum(perims, 1e-6))
    m, c, sigma_log = _fit_loglog(log_s, log_p)
    D = float(1.0 - m)
    P_clin = float(np.exp(c) * (params.clinical_scale ** (1.0 - D)))
    sigma_P = float(P_clin * sigma_log)
    return P_clin, D, sigma_P


def _homography_to_plane(H_img_to_plane: np.ndarray, K: np.ndarray) -> tuple[np.ndarray, float]:
    H_pi = np.linalg.inv(H_img_to_plane)
    h1, h2, h3 = H_pi[:, 0], H_pi[:, 1], H_pi[:, 2]
    K_inv = np.linalg.inv(K)
    lam = 1.0 / (np.linalg.norm(K_inv @ h1) + 1e-8)
    r1 = lam * (K_inv @ h1)
    r2 = lam * (K_inv @ h2)
    t = lam * (K_inv @ h3)
    n = np.cross(r1, r2)
    n = n / (np.linalg.norm(n) + 1e-8)
    d = float(np.dot(n, t))
    return n, d


def _depth_model_infer(image_bgr: np.ndarray, params: RefineParams) -> tuple[Optional[np.ndarray], Optional[float]]:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    try:
        midas = torch.hub.load("intel-isl/MiDaS", params.depth_model_name)
        midas.to(device).eval()
        transforms = torch.hub.load("intel-isl/MiDaS", "transforms")
        transform = transforms.dpt_transform if "DPT" in params.depth_model_name else transforms.small_transform
    except Exception as e:
        log.warning("  [DEPTH] Model load failed: %s", e)
        return None, None

    h, w = image_bgr.shape[:2]
    scale = min(params.depth_max_size / max(h, w), 1.0)
    new_w, new_h = int(w * scale), int(h * scale)
    image_resized = cv2.resize(image_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)

    img_rgb = cv2.cvtColor(image_resized, cv2.COLOR_BGR2RGB)
    input_t = transform(img_rgb).to(device)

    with torch.inference_mode():
        pred = midas(input_t)
        pred = torch.nn.functional.interpolate(
            pred.unsqueeze(1),
            size=(new_h, new_w),
            mode="bicubic",
            align_corners=False,
        ).squeeze()

    depth_rel = pred.detach().cpu().numpy().astype(np.float32)
    del midas
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    gc.collect()
    return depth_rel, scale


def _fit_depth_scale(depth_rel: np.ndarray, plane_Z: np.ndarray) -> Optional[tuple[float, float]]:
    z = plane_Z.reshape(-1)
    d = depth_rel.reshape(-1)
    valid = np.isfinite(z) & np.isfinite(d) & (z > 1e-6)
    z = z[valid]
    d = d[valid]
    if len(z) < 50:
        return None
    x = 1.0 / z
    A = np.vstack([x, np.ones_like(x)]).T
    a, b = np.linalg.lstsq(A, d, rcond=None)[0]
    return float(a), float(b)


def _metric_depth(depth_rel: np.ndarray, a: float, b: float) -> np.ndarray:
    denom = depth_rel - b
    denom = np.where(np.abs(denom) < 1e-6, np.sign(denom) * 1e-6, denom)
    return a / denom


def _to_3d(u: np.ndarray, v: np.ndarray, Z: np.ndarray, K: np.ndarray) -> np.ndarray:
    fx, fy, cx, cy = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
    X = (u - cx) / fx * Z
    Y = (v - cy) / fy * Z
    return np.stack([X, Y, Z], axis=-1)


def _axis_basis_xy(pts_xy: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = pts_xy.mean(axis=0)
    cov = np.cov(pts_xy.T)
    eigvals, eigvecs = np.linalg.eigh(cov)
    axis = eigvecs[:, int(np.argmax(eigvals))]
    axis = axis / (np.linalg.norm(axis) + 1e-8)
    perp = np.array([-axis[1], axis[0]], dtype=np.float32)
    return mean, axis, perp


def refine_geometry_with_depth(
    image: np.ndarray,
    mask: np.ndarray,
    landmarks: dict[str, dict],
    homography: Optional[np.ndarray],
    px_per_mm: float,
    camera_intrinsics: Optional[np.ndarray],
    params: RefineParams = RefineParams(),
) -> dict:
    """
    Depth-aware refinement of measurements with uncertainty.
    Returns a dict with measurement entries and diagnostic stats.
    """
    out: dict = {}

    H = None
    scale_conf = 0.5
    if isinstance(homography, dict):
        try:
            H = np.array(homography.get("H") or homography.get("homography"), dtype=np.float32)
            if H.shape != (3, 3):
                H = None
        except Exception:
            H = None
        scale_conf = float(homography.get("scale_conf", scale_conf))
    elif homography is not None:
        try:
            H = np.array(homography, dtype=np.float32)
            if H.shape != (3, 3):
                H = None
        except Exception:
            H = None

    # Coastline perimeter
    P_clin, D, sigma_P = _compute_multiscale_perimeter(mask, px_per_mm, H, params)
    out["fractal_dimension"] = float(D) if D is not None else None
    out["corrected_perimeter_mm"] = float(P_clin) if P_clin is not None else None
    out["perimeter_uncertainty"] = float(sigma_P) if sigma_P is not None else None

    if camera_intrinsics is None:
        out["confidence_score"] = 0.3
        return out

    depth_rel, depth_scale = _depth_model_infer(image, params)
    if depth_rel is None or depth_scale is None:
        out["confidence_score"] = 0.3
        return out

    # Scale K to depth resolution
    depth_h, depth_w = depth_rel.shape[:2]
    scale_x = depth_w / image.shape[1]
    scale_y = depth_h / image.shape[0]
    Kd = _scale_intrinsics(camera_intrinsics, scale_x, scale_y)

    # Estimate plane depth on card region using homography
    a = b = None
    if H is not None:
        S = np.array([[depth_scale, 0, 0], [0, depth_scale, 0], [0, 0, 1]], dtype=np.float32)
        H_img = H @ np.linalg.inv(S)
        n, d = _homography_to_plane(H_img, Kd)
        card = np.array([[0, 0], [CARD_LONG_MM, 0], [CARD_LONG_MM, CARD_SHORT_MM], [0, CARD_SHORT_MM]], dtype=np.float32)
        H_pi = np.linalg.inv(H_img)
        card_img = cv2.perspectiveTransform(card.reshape(-1, 1, 2), H_pi).reshape(-1, 2)
        card_mask = np.zeros((depth_h, depth_w), dtype=np.uint8)
        cv2.fillConvexPoly(card_mask, np.int32(card_img), 1)

        ys, xs = np.where(card_mask > 0)
        if len(xs) > 50:
            r = np.vstack([xs, ys, np.ones_like(xs)]).T
            r = (np.linalg.inv(Kd) @ r.T).T
            denom = (r @ n).reshape(-1)
            denom = np.where(np.abs(denom) < 1e-6, 1e-6, denom)
            s = d / denom
            Z_plane = s * r[:, 2]
            a_b = _fit_depth_scale(depth_rel[ys, xs], Z_plane)
            if a_b:
                a, b = a_b

    if a is None:
        out["confidence_score"] = 0.3
        return out

    Z = _metric_depth(depth_rel, a, b)

    # Foot region in depth space
    mask_depth = cv2.resize(mask, (depth_w, depth_h), interpolation=cv2.INTER_NEAREST)
    ys, xs = np.where(mask_depth > 0)
    if len(xs) < params.min_points:
        out["confidence_score"] = 0.3
        return out

    Zf = Z[ys, xs]
    pts3 = _to_3d(xs.astype(np.float32), ys.astype(np.float32), Zf, Kd)
    pts2 = pts3[:, :2]
    origin, axis, perp = _axis_basis_xy(pts2)
    t = (pts2 - origin) @ axis
    t_min, t_max = float(t.min()), float(t.max())
    t_norm = (t - t_min) / (t_max - t_min + 1e-8)

    def _region_stats(frac_lo: float, frac_hi: float):
        sel = (t_norm >= frac_lo) & (t_norm <= frac_hi)
        if sel.sum() < 50:
            return None, None, None, None
        pts = pts3[sel]
        mean_z = float(np.mean(pts[:, 2]))
        var_z = float(np.var(pts[:, 2]))
        return pts, mean_z, var_z

    # 3D length by polyline along axis
    bins = 32
    edges = np.linspace(t_min, t_max, bins + 1)
    centers = []
    for i in range(bins):
        sel = (t >= edges[i]) & (t < edges[i + 1])
        if sel.sum() < 20:
            continue
        centers.append(pts3[sel].mean(axis=0))
    centers = np.array(centers, dtype=np.float32)
    length_3d = 0.0
    if len(centers) >= 2:
        length_3d = float(np.sum(np.linalg.norm(np.diff(centers, axis=0), axis=1)))

    # Widths
    widths_3d = {}
    for region, (lo, hi) in params.region_fracs.items():
        pts_r, _, _ = _region_stats(lo, hi)
        if pts_r is None:
            continue
        proj = (pts_r[:, :2] - origin) @ perp
        i_min = int(np.argmin(proj))
        i_max = int(np.argmax(proj))
        widths_3d[region] = float(np.linalg.norm(pts_r[i_max] - pts_r[i_min]))

    # Arch height from landmark depth
    arch_height = None
    if "arch_low" in landmarks:
        u = int(landmarks["arch_low"]["x"] * scale_x)
        v = int(landmarks["arch_low"]["y"] * scale_y)
        if 0 <= v < Z.shape[0] and 0 <= u < Z.shape[1]:
            z = Z[v, u]
            X = _to_3d(np.array([u], dtype=np.float32), np.array([v], dtype=np.float32), np.array([z], dtype=np.float32), Kd)[0]
            if H is not None:
                n, d = _homography_to_plane(H @ np.linalg.inv(np.array([[depth_scale, 0, 0], [0, depth_scale, 0], [0, 0, 1]], dtype=np.float32)), Kd)
                arch_height = float(abs(n @ X - d))

    # Curvature metrics
    curv = {}
    for region, (lo, hi) in params.region_fracs.items():
        _, mean_z, var_z = _region_stats(lo, hi)
        if mean_z is None:
            curv[region] = 0.0
        else:
            curv[region] = float(var_z / (mean_z ** 2 + 1e-8))

    def _blend(planar_val: Optional[float], depth_val: Optional[float], region_key: str):
        if depth_val is None:
            return planar_val, 0.0
        if planar_val is None:
            return depth_val, 1.0
        k = curv.get(region_key, 0.0)
        alpha = (k - params.curvature_low) / (params.curvature_high - params.curvature_low + 1e-8)
        alpha = float(np.clip(alpha, 0.0, 1.0))
        return (1.0 - alpha) * planar_val + alpha * depth_val, alpha

    # Use planar values if caller provided them in landmarks["__planar"]
    planar = {}
    if isinstance(landmarks.get("__planar"), dict):
        planar.update(landmarks["__planar"])
    for k in ("foot_length_mm", "forefoot_width_mm", "heel_width_mm", "arch_height_mm"):
        planar.setdefault(k, None)

    out_vals = {}
    out_vals["foot_length_mm"], _ = _blend(planar["foot_length_mm"], length_3d, "arch")
    out_vals["forefoot_width_mm"], _ = _blend(planar["forefoot_width_mm"], widths_3d.get("forefoot"), "forefoot")
    out_vals["heel_width_mm"], _ = _blend(planar["heel_width_mm"], widths_3d.get("heel"), "heel")
    out_vals["arch_height_mm"], _ = _blend(planar["arch_height_mm"], arch_height, "arch")

    # Uncertainty
    scale_rel = params.scale_rel_base + params.scale_rel_gain * (1.0 - scale_conf)
    for key, region in [("foot_length_mm", "arch"), ("forefoot_width_mm", "forefoot"),
                        ("heel_width_mm", "heel"), ("arch_height_mm", "arch")]:
        val = out_vals.get(key)
        if val is None:
            continue
        sigma_scale = abs(val) * scale_rel
        sigma_depth = params.depth_sigma_gain * math.sqrt(curv.get(region, 0.0)) * abs(val)
        sigma_lm = params.landmark_sigma_base
        sigma_boundary = params.boundary_sigma_gain * (sigma_P or 0.0)
        sigma = math.sqrt(sigma_scale ** 2 + sigma_depth ** 2 + sigma_lm ** 2 + sigma_boundary ** 2)
        out[key] = {
            "value_mm": round(float(val), 2),
            "uncertainty_mm": round(float(sigma), 2),
            "ci95_mm": round(float(1.96 * sigma), 2),
        }

    confs = []
    for key in ("foot_length_mm", "forefoot_width_mm", "heel_width_mm", "arch_height_mm"):
        if key in out and isinstance(out[key], dict):
            v = out[key]["value_mm"]
            s = out[key]["uncertainty_mm"]
            confs.append(1.0 / (1.0 + s / (abs(v) + 1e-6)))
    out["confidence_score"] = float(np.mean(confs)) if confs else 0.0
    return out


def _landmark_to_small(
    landmarks: dict[str, dict],
    name: str,
    scale: float,
) -> tuple[Optional[tuple[int, int]], float]:
    d = landmarks.get(name)
    if not isinstance(d, dict):
        return None, 0.0
    try:
        x = int(round(float(d["x"]) * scale))
        y = int(round(float(d["y"]) * scale))
        conf = float(d.get("conf", 0.0))
        return (x, y), conf
    except Exception:
        return None, 0.0


def _mask_length_line_endpoints(
    mask_u8: np.ndarray,
    toe_pt: Optional[tuple[int, int]] = None,
    pter_pt: Optional[tuple[int, int]] = None,
) -> Optional[tuple[tuple[int, int], tuple[int, int]]]:
    ys, xs = np.where(mask_u8 > 0)
    if len(xs) < 20:
        return None
    pts = np.column_stack([xs, ys]).astype(np.float32)

    axis = None
    origin = None
    if toe_pt is not None and pter_pt is not None:
        axis = np.array([float(toe_pt[0] - pter_pt[0]), float(toe_pt[1] - pter_pt[1])], dtype=np.float32)
        if np.linalg.norm(axis) > 1e-6:
            origin = np.array([float(pter_pt[0]), float(pter_pt[1])], dtype=np.float32)
        else:
            axis = None

    if axis is None:
        mean = pts.mean(axis=0)
        cov = np.cov(pts.T)
        eigvals, eigvecs = np.linalg.eigh(cov)
        axis = eigvecs[:, int(np.argmax(eigvals))].astype(np.float32)
        origin = mean.astype(np.float32)

    norm = float(np.linalg.norm(axis))
    if norm <= 1e-6:
        return None
    unit_axis = axis / norm
    proj = (pts - origin) @ unit_axis
    p0 = pts[int(np.argmin(proj))]
    p1 = pts[int(np.argmax(proj))]
    return (int(round(p0[0])), int(round(p0[1]))), (int(round(p1[0])), int(round(p1[1])))


def save_view_visualization(
    viz_dir: Optional[str],
    patient_id: str,
    foot_side: str,
    view: str,
    image_small: np.ndarray,
    mask_small: np.ndarray,
    landmarks: dict[str, dict],
    scale: float,
    measurements: dict[str, float],
    mask_qc: Optional[dict] = None,
) -> Optional[str]:
    """
    Save per-view visualization with mask and measurement lines.
    Landmarks are used internally for line construction but are not drawn.
    """
    if not viz_dir:
        return None

    out_dir = Path(viz_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    vis = image_small.copy()
    mask_u8 = (mask_small > 0).astype(np.uint8)
    rejected_mask = bool(isinstance(mask_qc, dict) and mask_qc.get("reject"))
    if mask_u8.any():
        tint = np.array([0, 64, 255], dtype=np.float32) if rejected_mask else np.array([0, 255, 0], dtype=np.float32)
        m = mask_u8 > 0
        vis[m] = np.clip(0.75 * vis[m].astype(np.float32) + 0.25 * tint, 0, 255).astype(np.uint8)
        contours, _ = _find_contours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            contour_color = (0, 0, 255) if rejected_mask else (0, 220, 0)
            cv2.drawContours(vis, contours, -1, contour_color, 2)

    points: dict[str, tuple[int, int]] = {}
    confs: dict[str, float] = {}
    for name in LANDMARK_NAMES.get(view, []):
        pt, conf = _landmark_to_small(landmarks, name, scale)
        if pt is None:
            continue
        points[name] = pt
        confs[name] = conf

    foot_length = measurements.get("foot_length_mm")
    length_line_ok = (
        "toe_tip" in points
        and "pternion" in points
        and confs.get("toe_tip", 0.0) >= CONF_MIN
        and confs.get("pternion", 0.0) >= CONF_MIN
    )
    if length_line_ok:
        endpoints = _mask_length_line_endpoints(
            mask_u8,
            toe_pt=points["toe_tip"],
            pter_pt=points["pternion"],
        )
        if endpoints is None:
            endpoints = (points["toe_tip"], points["pternion"])
        cv2.line(vis, endpoints[0], endpoints[1], (255, 0, 0), 2, cv2.LINE_AA)
        if isinstance(foot_length, (int, float)):
            mx = (endpoints[0][0] + endpoints[1][0]) // 2
            my = (endpoints[0][1] + endpoints[1][1]) // 2
            cv2.putText(
                vis,
                f"foot_length={foot_length:.1f} mm",
                (mx + 6, my - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 0, 0),
                2,
                cv2.LINE_AA,
            )
    elif isinstance(foot_length, (int, float)):
        cv2.putText(
            vis,
            f"foot_length={foot_length:.1f} mm (fallback)",
            (12, 58),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 0, 0),
            2,
            cv2.LINE_AA,
        )

    forefoot = measurements.get("forefoot_width_mm")
    forefoot_line_ok = (
        "met1" in points
        and "met5" in points
        and confs.get("met1", 0.0) >= CONF_MIN
        and confs.get("met5", 0.0) >= CONF_MIN
    )
    if forefoot_line_ok:
        cv2.line(vis, points["met1"], points["met5"], (255, 255, 0), 2, cv2.LINE_AA)
        if isinstance(forefoot, (int, float)):
            mx = (points["met1"][0] + points["met5"][0]) // 2
            my = (points["met1"][1] + points["met5"][1]) // 2
            cv2.putText(
                vis,
                f"forefoot={forefoot:.1f} mm",
                (mx + 6, my - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 0),
                2,
                cv2.LINE_AA,
            )
    elif isinstance(forefoot, (int, float)):
        cv2.putText(
            vis,
            f"forefoot={forefoot:.1f} mm (fallback)",
            (12, 82),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 0),
            2,
            cv2.LINE_AA,
        )

    cv2.putText(
        vis,
        f"{patient_id}  {foot_side}/{view}",
        (12, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    if rejected_mask:
        reason = str(mask_qc.get("reason", "qc_reject"))
        cv2.putText(
            vis,
            f"MASK REJECTED: {reason}",
            (12, 46),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )

    out_path = out_dir / f"{patient_id}_{foot_side}_{view}_viz.jpg"
    cv2.imwrite(str(out_path), vis)

    # ── Separate segmentation overlay ──
    seg_vis = image_small.copy()
    if mask_u8.any():
        tint_seg = np.array([0, 64, 255], dtype=np.float32) if rejected_mask else np.array([0, 255, 0], dtype=np.float32)
        m_seg = mask_u8 > 0
        seg_vis[m_seg] = np.clip(0.75 * seg_vis[m_seg].astype(np.float32) + 0.25 * tint_seg, 0, 255).astype(np.uint8)
        contours_seg, _ = _find_contours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours_seg:
            c_color = (0, 0, 255) if rejected_mask else (0, 220, 0)
            cv2.drawContours(seg_vis, contours_seg, -1, c_color, 2)
    cv2.putText(seg_vis, f"{patient_id}  {foot_side}/{view}", (12, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    if rejected_mask:
        reason = str(mask_qc.get("reason", "qc_reject"))
        cv2.putText(seg_vis, f"MASK REJECTED: {reason}", (12, 46),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2, cv2.LINE_AA)
    seg_path = out_dir / f"{patient_id}_{foot_side}_{view}_seg.jpg"
    cv2.imwrite(str(seg_path), seg_vis)

    # ── Separate landmarks overlay ──
    lm_vis = image_small.copy()
    LM_COLORS = {
        "toe_tip": (0, 0, 255), "pternion": (255, 0, 0),
        "met1": (0, 255, 0), "met5": (0, 255, 255),
        "met1_apex": (255, 0, 255), "arch_low": (255, 128, 0),
        "foot_leg_jxn": (128, 0, 255),
    }
    for name, pt in points.items():
        conf = confs.get(name, 0.0)
        color = LM_COLORS.get(name, (255, 255, 255))
        radius = 7 if conf >= CONF_MIN else 4
        thickness = -1 if conf >= CONF_MIN else 1
        cv2.circle(lm_vis, pt, radius, color, thickness, cv2.LINE_AA)
        label_y = pt[1] - 12 if pt[1] > 20 else pt[1] + 20
        cv2.putText(lm_vis, f"{name} ({conf:.2f})", (pt[0] + 10, label_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1, cv2.LINE_AA)
    cv2.putText(lm_vis, f"{patient_id}  {foot_side}/{view}", (12, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    lm_path = out_dir / f"{patient_id}_{foot_side}_{view}_lm.jpg"
    cv2.imwrite(str(lm_path), lm_vis)

    return str(out_path)


# ═══════════════════════════════════════════════════════════
# STAGE 6 — MULTI-VIEW FUSION
# ═══════════════════════════════════════════════════════════

def _lm_mask_consistency(landmarks: dict, mask: np.ndarray, view: str) -> float:
    """
    Score [0,1]: are toe_tip and heel landmarks in plausible anterior/posterior
    zones of the foot mask? Only meaningful for plantar and dorsal views.
    Returns 1.0 (no penalty) for medial and unknown views.
    """
    if view not in ("plantar", "dorsal") or mask is None or mask.sum() == 0:
        return 1.0
    ys, _ = np.where(mask > 0)
    if len(ys) < 50:
        return 0.5
    y_min = int(ys.min())
    y_max = int(ys.max())
    span  = max(y_max - y_min, 1)
    zone  = span * 0.30   # anterior/posterior zone = 30% of mask length from each end

    score  = 0.0
    weight = 0.0

    toe = landmarks.get("toe_tip") or landmarks.get("toe_tip_1")
    if toe and toe.get("conf", 0) > 0.1:
        ty = float(toe["y"])
        in_zone = (ty < y_min + zone) or (ty > y_max - zone)
        score  += float(in_zone) * toe["conf"]
        weight += toe["conf"]

    for hk in ("pternion", "heel_center", "heel_post"):
        h = landmarks.get(hk)
        if h and h.get("conf", 0) > 0.1:
            hy = float(h["y"])
            in_zone = (hy < y_min + zone) or (hy > y_max - zone)
            if toe:
                toe_top  = float(toe["y"]) < (y_min + y_max) / 2.0
                heel_top = hy < (y_min + y_max) / 2.0
                opposite = (toe_top != heel_top)
                score  += float(in_zone and opposite) * h["conf"]
            else:
                score  += float(in_zone) * h["conf"]
            weight += h["conf"]
            break

    return float(score / weight) if weight > 0 else 0.5


def _view_quality(view_details: Optional[dict], key: tuple[str, str]) -> float:
    """Heuristic view quality score in [0, 1] based on conf signals."""
    if not view_details or key not in view_details:
        return 1.0
    d = view_details.get(key, {})
    mask_conf = float(d.get("mask_conf", 0.0) or 0.0)
    scale_conf = float(d.get("scale_conf", 0.0) or 0.0)
    lm_conf = float(d.get("landmark_conf_mean", 0.0) or 0.0)
    plane_conf = 0.0
    ref_meta = d.get("ref_meta") or {}
    if isinstance(ref_meta, dict):
        plane_conf = float(ref_meta.get("plane_conf", 0.0) or 0.0)
    q = 0.4 * mask_conf + 0.4 * scale_conf + 0.2 * lm_conf
    if plane_conf > 0.0:
        q = 0.7 * q + 0.3 * plane_conf
    scale_source = str(d.get("scale_source", "unknown"))
    if scale_source == "borrowed":
        q *= 0.70
    elif scale_source in ("missing", "mask_reject"):
        q *= 0.50
    if isinstance(d.get("mask_qc"), dict) and d["mask_qc"].get("reject"):
        q *= 0.40
    return float(np.clip(q, 0.05, 1.0))


def _estimate_sigma(value: float, quality: float, is_angle: bool) -> float:
    """Estimate 1-sigma uncertainty for a measurement."""
    if is_angle:
        base = 2.0
        span = 10.0
        return float(base + span * (1.0 - quality))
    rel = 0.03 + 0.12 * (1.0 - quality)
    return float(abs(value) * rel + 0.5)


def _ellipse_circumference_ramanujan(width_mm: float, height_mm: float) -> float:
    """Ramanujan-II approximation for ellipse circumference from diameters."""
    w = max(float(width_mm), 1e-6)
    h = max(float(height_mm), 1e-6)
    a = 0.5 * w
    b = 0.5 * h
    h_r = ((a - b) ** 2) / (((a + b) ** 2) + 1e-12)
    return float(math.pi * (a + b) * (1.0 + (3.0 * h_r) / (10.0 + math.sqrt(max(4.0 - 3.0 * h_r, 1e-6)))))


def _phase12_apply_girth_formula(
    field: str,
    ramanujan_mm: float,
    width_mm: float,
    foot_length_mm: Optional[float],
) -> float:
    """
    Apply the cohort-fit linear correction `coef * ramanujan + intercept`.
    Falls back to the bare Ramanujan value when inputs are out of the
    calibration range (defensive against sentinel widths from bad scale reads).
    """
    formula = PHASE12_GIRTH_FORMULA.get(field)
    if formula is None:
        return ramanujan_mm
    w_lo, w_hi = PHASE12_GIRTH_INPUT_RANGES["width_mm"]
    fl_lo, fl_hi = PHASE12_GIRTH_INPUT_RANGES["foot_length_mm"]
    if not (w_lo <= float(width_mm) <= w_hi):
        return ramanujan_mm
    if foot_length_mm is None or not (fl_lo <= float(foot_length_mm) <= fl_hi):
        return ramanujan_mm
    return float(formula["coef"]) * float(ramanujan_mm) + float(formula["intercept"])


def _metric_sigma(meas: Optional[dict], default_rel: float = 0.10) -> float:
    if not isinstance(meas, dict):
        return 0.0
    if "uncertainty_mm" in meas:
        return float(meas["uncertainty_mm"])
    if "value_mm" in meas:
        return float(abs(float(meas["value_mm"])) * default_rel + 0.5)
    return 0.0


def _circumference_sigma(width_mm: float, height_mm: float, sigma_w: float, sigma_h: float, model_rel: float) -> float:
    w = max(float(width_mm), 1e-4)
    h = max(float(height_mm), 1e-4)
    dw = max(1e-3, 0.005 * w)
    dh = max(1e-3, 0.005 * h)
    c0 = _ellipse_circumference_ramanujan(w, h)
    dc_dw = (_ellipse_circumference_ramanujan(w + dw, h) - _ellipse_circumference_ramanujan(max(w - dw, 1e-4), h)) / (2.0 * dw)
    dc_dh = (_ellipse_circumference_ramanujan(w, h + dh) - _ellipse_circumference_ramanujan(w, max(h - dh, 1e-4))) / (2.0 * dh)
    sigma_model = model_rel * c0
    return float(math.sqrt((dc_dw * sigma_w) ** 2 + (dc_dh * sigma_h) ** 2 + sigma_model ** 2))


GIRTH_MIN_VIEWS = 2
GIRTH_MAX_REL_CI95 = 0.30
GIRTH_REQUIRE_TRUSTED_WIDTH = True
GIRTH_REQUIRE_NON_RATIO_HEIGHT = True
GIRTH_INCLUDE_PROVISIONAL = True


def _girth_reliable(
    width_quality: str,
    n_views: int,
    height_source: str,
    value_mm: float,
    ci95_mm: float,
) -> bool:
    if GIRTH_REQUIRE_TRUSTED_WIDTH and width_quality != "trusted":
        return False
    if int(n_views) < GIRTH_MIN_VIEWS:
        return False
    if GIRTH_REQUIRE_NON_RATIO_HEIGHT and height_source == "ratio":
        return False
    rel_ci = float(ci95_mm / (abs(value_mm) + 1e-6))
    if rel_ci > GIRTH_MAX_REL_CI95:
        return False
    return True


def _girth_reliability_reason(
    width_quality: str,
    n_views: int,
    height_source: str,
    value_mm: float,
    ci95_mm: float,
) -> str:
    if GIRTH_REQUIRE_TRUSTED_WIDTH and width_quality != "trusted":
        return "width_not_trusted"
    if int(n_views) < GIRTH_MIN_VIEWS:
        return "insufficient_views"
    if GIRTH_REQUIRE_NON_RATIO_HEIGHT and height_source == "ratio":
        return "ratio_height_only"
    rel_ci = float(ci95_mm / (abs(value_mm) + 1e-6))
    if rel_ci > GIRTH_MAX_REL_CI95:
        return "high_relative_uncertainty"
    return "ok"


# ─────────────────────────────────────────────────────────────────────────────
# SANITY RANGES — LEPRA leprosy patient population
# ─────────────────────────────────────────────────────────────────────────────
# This app measures feet of patients with leprosy-related deformities. Tight
# "healthy adult" thresholds would systematically reject the very patients the
# app exists to serve. Real-world cases include:
#   • Toe resorption / amputation        → very short feet (down to ~7-10 cm)
#   • Charcot midfoot collapse           → midfoot width 2-3x normal
#   • Plantar ulcers, scarring, oedema   → inflated girths and widths
#   • Pediatric leprosy                  → small feet (children under 10)
#   • Severe bilateral asymmetry         → one foot can be drastically smaller
#                                          than the other (unilateral amputation)
#
# Therefore these ranges are intentionally WIDE. They catch only physically
# impossible values that signal a scale-detection failure (e.g., px/mm 2-3x
# wrong from a rotated image with degenerate ArUco corners), NOT anatomical
# extremes. Everything inside these ranges goes to the clinician for review.
#
# DO NOT TIGHTEN THESE without consulting the clinical team. Filtering out a
# real measurement on a deformed foot defeats the purpose of the app.
SANITY_RANGES_MM = {
    "foot_length_mm":              (70.0,  400.0),   # 7-40 cm: covers severe resorption + safety upper bound
    "forefoot_width_mm":           (30.0,  200.0),   # severe atrophy to extreme widening
    "heel_width_mm":               (25.0,  180.0),
    "midfoot_width_mm":            (30.0,  250.0),   # Charcot collapse legitimately widens midfoot
    "ball_girth_mm_provisional":   (80.0,  500.0),   # severe oedema can inflate girths
    "instep_girth_mm_provisional": (80.0,  500.0),
    "arch_height_mm":              (0.0,   120.0),   # 0 floor: collapsed arch is real
    "met1_height_mm":              (0.0,   100.0),
    "malleoli_height_mm":          (20.0,  120.0),   # paediatric leprosy floor through severe oedema
}


def apply_sanity_gates(fused: dict, patient_info: Optional[dict] = None) -> dict:
    """
    Scrub physically impossible measurements out of the fused dict.
    Sets quality="rejected_implausible" and drops value_mm to None for any
    measurement that falls outside SANITY_RANGES_MM. Other fields (uncertainty,
    n_views, etc.) are preserved so the report can show the rejection reason.

    The range bounds are intentionally WIDE to accommodate leprosy deformities
    — see SANITY_RANGES_MM comment above. We only catch egregious scale-
    detection failures here, not anatomical extremes.

    Demographic-aware widening (added 2026-05):
      - diabetes=="yes"            -> widen all girth/width upper bounds 20%
                                      (oedema common in diabetic neuropathy)
      - who_grade in {grade_1,2}   -> widen 20% (advanced leprosy = severe
                                      deformity / oedema possible)
      - amputated_toes=="yes"      -> drop toe_axis_angle entirely (no toes
                                      to define an axis); widen foot_length
                                      lower bound to 50mm (partial-foot post-
                                      amputation can be much shorter)

    Logs every drop so we can monitor frequency in production.
    """
    pi = patient_info or {}
    diab = str(pi.get("diabetes", "")).strip().lower() == "yes"
    amput = str(pi.get("amputated_toes", "")).strip().lower() == "yes"
    grade = str(pi.get("who_grade", "")).strip().lower()
    high_grade = grade in ("grade_1", "grade_2", "1", "2", "i", "ii")

    widen = diab or high_grade
    if widen or amput:
        log.info(
            "  [SANITY] Demographic-aware widening enabled: diabetes=%s "
            "high_grade=%s amputated=%s",
            diab, high_grade, amput,
        )

    for foot_side in ("left", "right"):
        foot = fused.get(foot_side, {})
        if not isinstance(foot, dict):
            continue

        # Skip toe_axis_angle for amputated patients — measurement is
        # meaningless without toes; the model often emits a wrong value
        # by extrapolating from the heel direction alone.
        if amput and "toe_axis_angle_deg" in foot:
            entry = foot["toe_axis_angle_deg"]
            if isinstance(entry, dict) and entry.get("value_mm") is not None:
                log.info(
                    "  [SANITY] %s/toe_axis_angle_deg suppressed — "
                    "patient amputated_toes=yes",
                    foot_side,
                )
                entry["value_mm"] = None
                entry["quality"] = "not_applicable"
                entry["reject_reason"] = (
                    "Toe axis angle requires toes to be present; "
                    "patient is recorded as having amputated toes."
                )

        for key, entry in list(foot.items()):
            if not isinstance(entry, dict):
                continue
            val = entry.get("value_mm")
            rng = SANITY_RANGES_MM.get(key)
            if val is None or rng is None:
                continue
            lo, hi = rng

            # Demographic widening: 20% higher upper bound for girth/width
            # measurements when oedema is plausible (diabetic or advanced
            # leprosy). Lower bound for foot_length relaxed when amputated.
            if widen and key in (
                "forefoot_width_mm", "heel_width_mm", "midfoot_width_mm",
                "ball_girth_mm_provisional", "instep_girth_mm_provisional",
                "malleoli_height_mm",
            ):
                hi = hi * 1.20
            if amput and key == "foot_length_mm":
                lo = min(lo, 50.0)
            try:
                v = float(val)
            except (TypeError, ValueError):
                continue
            if v < lo or v > hi:
                # Build a human-readable reason explaining the rejection.
                # Surfaced in the report so clinicians + agents understand
                # why the value was dropped (it's almost always a scale bug).
                v_cm = v / 10.0
                lo_cm, hi_cm = lo / 10.0, hi / 10.0
                if v < lo:
                    reason = (
                        f"Value {v_cm:.1f} cm is below plausible minimum "
                        f"{lo_cm:.1f} cm for any leprosy-affected foot — "
                        f"likely a scale-detection error (px/mm too large)."
                    )
                else:
                    reason = (
                        f"Value {v_cm:.1f} cm is above plausible maximum "
                        f"{hi_cm:.1f} cm even with severe oedema or Charcot "
                        f"deformity — likely a scale-detection error "
                        f"(px/mm too small, often from rotated upload)."
                    )
                log.warning(
                    "  [SANITY] %s/%s = %.2f mm outside [%.0f, %.0f] — drop. %s",
                    foot_side, key, v, lo, hi, reason,
                )
                entry["value_mm"] = None
                entry["original_value_mm"] = v
                entry["quality"] = "rejected_implausible"
                entry["sanity_range_mm"] = [lo, hi]
                entry["reject_reason"] = reason
    return fused


def apply_isotonic_correction(fused: dict) -> dict:
    """Apply post-fusion isotonic calibration to foot_length and malleoli_height.
    Values outside the knot range are left untouched (no numpy.interp clipping).
    """
    for foot_side in ("left", "right"):
        foot = fused.get(foot_side, {})
        if not isinstance(foot, dict):
            continue
        for field, knots in PHASE12_ISOTONIC_KNOTS.items():
            key = f"{field}_mm"
            meas = foot.get(key)
            if not isinstance(meas, dict) or "value_mm" not in meas:
                continue
            val = float(meas["value_mm"])
            x_min, x_max = knots["x"][0], knots["x"][-1]
            if not (x_min <= val <= x_max):
                log.debug(
                    "  [ISO] %s/%s val=%.1fmm outside knot range [%.1f, %.1f] — skipped",
                    foot_side, field, val, x_min, x_max,
                )
                continue
            corrected = float(np.interp(val, knots["x"], knots["y"]))
            log.debug(
                "  [ISO] %s/%s %.2f → %.2f mm",
                foot_side, field, val, corrected,
            )
            meas["value_mm"] = round(corrected, 2)
    return fused


def apply_bias_correction(fused: dict) -> dict:
    """
    Add derived girth metrics from fused linear measurements.
    This is geometric post-processing (no learned bias model yet).
    """
    for foot_side in ("left", "right"):
        foot = fused.get(foot_side, {})
        if not isinstance(foot, dict) or not foot:
            continue

        fore = foot.get("forefoot_width_mm")
        mid = foot.get("midfoot_width_mm")
        heel = foot.get("heel_width_mm")
        met1_h = foot.get("met1_height_mm")
        arch_h = foot.get("arch_height_mm")
        fl = foot.get("foot_length_mm")
        foot_length_mm_val = (
            float(fl["value_mm"]) if isinstance(fl, dict) and "value_mm" in fl else None
        )

        # Ball girth: ellipse around metatarsal heads.
        if isinstance(fore, dict) and "value_mm" in fore:
            w_ball = float(fore["value_mm"])
            sw_ball = _metric_sigma(fore, default_rel=0.08)
            h_source = "ratio"
            if isinstance(met1_h, dict) and "value_mm" in met1_h:
                h_ball = max(float(met1_h["value_mm"]), 0.18 * w_ball)
                sh_ball = _metric_sigma(met1_h, default_rel=0.12)
                h_source = "met1_height_mm"
                model_rel = 0.03
            elif isinstance(arch_h, dict) and "value_mm" in arch_h:
                h_ball = max(1.35 * float(arch_h["value_mm"]), 0.16 * w_ball)
                sh_ball = 1.35 * _metric_sigma(arch_h, default_rel=0.15)
                h_source = "arch_height_mm"
                model_rel = 0.05
            else:
                h_ball = 0.42 * w_ball
                sh_ball = 0.15 * h_ball
                model_rel = 0.08

            c_ball = _ellipse_circumference_ramanujan(w_ball, h_ball)
            c_ball = _phase12_apply_girth_formula("ball_girth", c_ball, w_ball, foot_length_mm_val)
            s_ball = _circumference_sigma(w_ball, h_ball, sw_ball, sh_ball, model_rel=model_rel)
            n_views_ball = int(fore.get("n_views", 1))
            q_ball = str(fore.get("quality", "degraded"))
            ci95_ball = float(1.96 * s_ball)
            ball_reason = _girth_reliability_reason(q_ball, n_views_ball, h_source, c_ball, ci95_ball)
            if ball_reason == "ok":
                foot["ball_girth_mm"] = {
                    "value_mm": round(c_ball, 2),
                    "n_views": n_views_ball,
                    "spread_mm": round(float(fore.get("spread_mm", 0.0)), 2),
                    "quality": q_ball,
                    "uncertainty_mm": round(s_ball, 2),
                    "ci95_mm": round(ci95_ball, 2),
                    "source": f"ellipse({h_source})",
                }
            elif GIRTH_INCLUDE_PROVISIONAL:
                foot["ball_girth_mm_provisional"] = {
                    "value_mm": round(c_ball, 2),
                    "n_views": n_views_ball,
                    "spread_mm": round(float(fore.get("spread_mm", 0.0)), 2),
                    "quality": "degraded",
                    "uncertainty_mm": round(s_ball, 2),
                    "ci95_mm": round(ci95_ball, 2),
                    "source": f"ellipse({h_source})",
                    "provisional": True,
                    "provisional_reason": ball_reason,
                    "base_width_quality": q_ball,
                }

        # Instep girth: ellipse at midfoot/instep section.
        if (isinstance(mid, dict) and "value_mm" in mid) or (isinstance(fore, dict) and "value_mm" in fore):
            has_fore = isinstance(fore, dict) and "value_mm" in fore
            if has_fore:
                w_fore = float(fore["value_mm"])
                sw_fore = _metric_sigma(fore, default_rel=0.10)
            if isinstance(mid, dict) and "value_mm" in mid:
                w_instep = float(mid["value_mm"])
                sw_instep = _metric_sigma(mid, default_rel=0.10)
                w_quality = str(mid.get("quality", "degraded"))
                n_views = int(mid.get("n_views", 1))
                spread = float(mid.get("spread_mm", 0.0))
                w_source = "midfoot_width_mm"
            elif has_fore and isinstance(heel, dict) and "value_mm" in heel:
                w_instep = 0.55 * w_fore + 0.45 * float(heel["value_mm"])
                sw_instep = math.sqrt((0.55 * sw_fore) ** 2 + (0.45 * _metric_sigma(heel, default_rel=0.10)) ** 2)
                w_quality = "trusted" if (fore.get("quality") == "trusted" and heel.get("quality") == "trusted") else "degraded"
                n_views = int(min(fore.get("n_views", 1), heel.get("n_views", 1)))
                spread = float(max(fore.get("spread_mm", 0.0), heel.get("spread_mm", 0.0)))
                w_source = "forefoot+heel"
            else:
                if not has_fore:
                    continue
                w_instep = 0.85 * w_fore
                sw_instep = 0.85 * sw_fore
                w_quality = str(fore.get("quality", "degraded"))
                n_views = int(fore.get("n_views", 1))
                spread = float(fore.get("spread_mm", 0.0))
                w_source = "forefoot_width_mm"

            h_source = "ratio"
            if isinstance(met1_h, dict) and "value_mm" in met1_h:
                h_instep = max(1.10 * float(met1_h["value_mm"]), 0.20 * w_instep)
                sh_instep = 1.10 * _metric_sigma(met1_h, default_rel=0.15)
                h_source = "met1_height_mm"
                model_rel = 0.04
            elif isinstance(arch_h, dict) and "value_mm" in arch_h:
                h_instep = max(2.00 * float(arch_h["value_mm"]), 0.18 * w_instep)
                sh_instep = 2.00 * _metric_sigma(arch_h, default_rel=0.20)
                h_source = "arch_height_mm"
                model_rel = 0.06
            else:
                h_instep = 0.35 * w_instep
                sh_instep = 0.18 * h_instep
                model_rel = 0.10

            c_instep = _ellipse_circumference_ramanujan(w_instep, h_instep)
            c_instep = _phase12_apply_girth_formula("instep_girth", c_instep, w_instep, foot_length_mm_val)
            s_instep = _circumference_sigma(w_instep, h_instep, sw_instep, sh_instep, model_rel=model_rel)
            ci95_instep = float(1.96 * s_instep)
            instep_reason = _girth_reliability_reason(w_quality, n_views, h_source, c_instep, ci95_instep)
            if instep_reason == "ok":
                foot["instep_girth_mm"] = {
                    "value_mm": round(c_instep, 2),
                    "n_views": n_views,
                    "spread_mm": round(spread, 2),
                    "quality": w_quality,
                    "uncertainty_mm": round(s_instep, 2),
                    "ci95_mm": round(ci95_instep, 2),
                    "source": f"ellipse(width={w_source},height={h_source})",
                }
            elif GIRTH_INCLUDE_PROVISIONAL:
                foot["instep_girth_mm_provisional"] = {
                    "value_mm": round(c_instep, 2),
                    "n_views": n_views,
                    "spread_mm": round(spread, 2),
                    "quality": "degraded",
                    "uncertainty_mm": round(s_instep, 2),
                    "ci95_mm": round(ci95_instep, 2),
                    "source": f"ellipse(width={w_source},height={h_source})",
                    "provisional": True,
                    "provisional_reason": instep_reason,
                    "base_width_quality": w_quality,
                }

    return fused


def fuse_measurements(
    view_measurements: dict[tuple[str, str], dict],
    view_details: Optional[dict] = None,
) -> dict[str, dict]:
    """
    Confidence-weighted fusion of all views for both feet.

    Parameters
    ----------
    view_measurements : { (foot_side, view): measurements_dict }
    view_details      : optional per-view metadata for uncertainty estimation

    Returns
    -------
    {
      "left":  { measurement: { value_mm, n_views, spread_mm, quality, ci95_* } },
      "right": { ... }
    }
    """
    results = {}

    # ── PnP cross-view parallax correction ─────────────────────────────────
    # Each view's ArUco card may be held at a different height above the foot.
    # A card elevated h mm above the floor appears larger in the image, so
    # px_per_mm is overestimated and all mm measurements are underestimated.
    # solvePnP gives card_z (camera→card distance).  The view with the largest
    # card_z had its card closest to the floor → use it as the scale reference.
    # Correct every other view's measurements: true_mm = measured_mm × z_max/z.
    for _foot_side in ("left", "right"):
        _pnp_depths = {}
        for (_s, _v), _d in (view_details or {}).items():
            if _s != _foot_side:
                continue
            _z = (_d.get("ref_meta") or {}).get("pnp_card_z_mm")
            if _z and float(_z) > 50:
                _pnp_depths[_v] = float(_z)
        if len(_pnp_depths) >= 2:
            _z_max = max(_pnp_depths.values())
            for _v, _z in _pnp_depths.items():
                _corr = _z_max / _z
                # Cap at 1.12 (12% max). Larger z-ratios between views are more
                # likely camera-distance variation than real card elevation, and
                # the focal-length estimate is approximate enough to make big
                # corrections unreliable.
                _corr = min(_corr, 1.12)
                if _corr > 1.03:   # only apply if correction exceeds 3%
                    _vm = view_measurements.get((_foot_side, _v), {})
                    for _k in list(_vm):
                        if isinstance(_vm[_k], float) and _k.endswith("_mm"):
                            _vm[_k] = round(_vm[_k] * _corr, 2)
                    if isinstance(view_details, dict) and (_foot_side, _v) in view_details:
                        view_details[(_foot_side, _v)]["pnp_parallax_corr"] = round(_corr, 4)
                    log.info(
                        "  [PNP-CORR] %s/%s card_z=%.0fmm z_max=%.0fmm → ×%.3f applied to all _mm fields",
                        _foot_side, _v, _z, _z_max, _corr,
                    )

    # Per-foot scale-consistency guardrail: compute median px/mm across this
    # foot's views, drop candidates from any view whose px/mm differs by >20%.
    # Marker-plane mismatches (e.g. PAT-001 right_plantar held by a person far
    # from the foot) get caught here before they corrupt the weighted average.
    SCALE_OUTLIER_RATIO = 0.20
    # Dorsal foot_length disagreement guardrail: dorsal models are currently
    # weak in field conditions (toe_tip lands on marker) — drop dorsal's
    # foot_length when it disagrees with plantar by >15%.
    DORSAL_FL_DISAGREE_RATIO = 0.15

    # Include all directly-measured scales in the median (not just ArUco) so
    # the outlier check works when one view's ArUco fell back to card-YOLO
    # while another view's ArUco succeeded. Excluding non-"detected" sources
    # let plantar's wrong-plane held-card scale slip through as the only
    # value in the median, defeating the guardrail. (PAT-001 failure.)
    _VALID_SCALE_SOURCES = {"detected", "card_yolo", "coin_fallback"}

    for foot_side in ("left", "right"):
        raw = {}   # measurement_name -> list of (value, weight, sigma, q, scale_source, view)

        # Pre-compute median px/mm for this foot across all directly-measured scales.
        side_scales = []
        for (s, v), d in (view_details or {}).items():
            if s != foot_side:
                continue
            if str(d.get("scale_source")) not in _VALID_SCALE_SOURCES:
                continue
            pxmm = d.get("px_per_mm")
            if isinstance(pxmm, (int, float)) and np.isfinite(pxmm) and pxmm > 0:
                side_scales.append(float(pxmm))
        median_pxmm = float(np.median(side_scales)) if side_scales else None

        for (s, view), meas in view_measurements.items():
            if s != foot_side:
                continue
            # Scale-outlier check: skip this whole view if its px/mm is far from median.
            if median_pxmm is not None:
                d_v = (view_details or {}).get((s, view), {})
                pxmm_v = d_v.get("px_per_mm")
                src_v = str(d_v.get("scale_source"))
                if (
                    src_v in _VALID_SCALE_SOURCES
                    and isinstance(pxmm_v, (int, float))
                    and np.isfinite(pxmm_v) and pxmm_v > 0
                    and abs(pxmm_v - median_pxmm) / median_pxmm > SCALE_OUTLIER_RATIO
                ):
                    log.warning(
                        "  [FUSE] %s/%s dropped — px/mm=%.2f off median %.2f by >%.0f%% (marker plane mismatch?)",
                        s, view, pxmm_v, median_pxmm, SCALE_OUTLIER_RATIO * 100,
                    )
                    # Record on view_details so quality_issues can surface this
                    # to the clinician (otherwise the drop is silent in the UI).
                    if isinstance(view_details, dict) and (s, view) in view_details:
                        view_details[(s, view)]["fuse_dropped"] = "scale_outlier"
                    continue
            # Mask-length sanity gate for plantar/dorsal foot_length.
            # For deformed feet (leprosy), toe_tip/pternion landmarks can be
            # badly misplaced, giving foot_length 30-50% of the true value.
            # The OBB mask_length_mm is landmark-independent and reliable.
            # When landmark foot_length < 60% of mask_length, substitute mask_length.
            _fl_raw  = meas.get("foot_length_mm")
            _ml_raw  = meas.get("mask_length_mm")
            if (
                view in ("plantar", "dorsal")
                and isinstance(_fl_raw, float)
                and isinstance(_ml_raw, float)
                and _ml_raw > 50
                and _fl_raw < 0.60 * _ml_raw
            ):
                log.warning(
                    "  [FUSE] %s/%s landmark foot_length=%.1fmm < 60%% mask_length=%.1fmm "
                    "→ substituting OBB mask_length (deformed foot / landmark failure)",
                    s, view, _fl_raw, _ml_raw,
                )
                meas = dict(meas)   # shallow copy — don't mutate original
                meas["foot_length_mm"] = _ml_raw
                if isinstance(view_details, dict) and (s, view) in view_details:
                    view_details[(s, view)]["foot_length_mask_substituted"] = True

            for key, value in meas.items():
                if not isinstance(value, float):
                    continue
                d = (view_details or {}).get((s, view), {})
                src = str(d.get("scale_source", "unknown"))

                # Phase 1+2 path: (field, view) pairs in PHASE12_PER_VIEW_STATS
                # get cohort-fit bias subtracted and an inverse-variance weight
                # built from the landmark_conf_mean bin sigma. Bin lookup uses
                # raw landmark_conf_mean, NOT _view_quality (doc §Caveat 1).
                base_key = key[:-3] if key.endswith("_mm") else key
                p12_stats = PHASE12_PER_VIEW_STATS.get(f"{base_key}/{view}")
                p12_base_w = PHASE12_FUSION_WEIGHTS.get(base_key, {}).get(view)
                if p12_stats is not None and p12_base_w is not None:
                    lm_conf = float(d.get("landmark_conf_mean", 0.0) or 0.0)
                    sigma = float(p12_stats["sigma_by_conf_bin"].get(
                        _phase12_bin(lm_conf), p12_stats["sigma_mm"]
                    ))
                    w = max(float(p12_base_w), 0.05) / max(sigma ** 2, 1e-6)
                    corrected = value - float(p12_stats["bias_mm"])
                    q = _view_quality(view_details, (s, view))
                    raw.setdefault(key, []).append((corrected, w, sigma, q, src, view))
                    continue

                # Legacy path.
                w = FUSION_WEIGHTS.get(key, {}).get(view, 0.0)
                if w > 0.0:
                    q = _view_quality(view_details, (s, view))
                    sigma = _estimate_sigma(value, q, "deg" in key)
                    raw.setdefault(key, []).append((value, w, sigma, q, src, view))

        # Dorsal-plantar disagreement guardrail (foot_length only).
        # Plantar is used as reference only when its landmark-mask spatial
        # consistency score is high (≥ 0.40).  If plantar landmarks are
        # misplaced (e.g. toe_tip at ball of foot), plantar is dropped instead.
        fl = raw.get("foot_length_mm")
        if fl:
            plantar_candidates = [c for c in fl if c[5] == "plantar"]
            dorsal_candidates  = [c for c in fl if c[5] == "dorsal"]
            plantar_consistency = float(
                (view_details or {})
                .get((foot_side, "plantar"), {})
                .get("lm_spatial_consistency", 1.0)
            )
            log.info(
                "  [FUSE] %s plantar lm_spatial_consistency=%.2f", foot_side, plantar_consistency
            )
            if plantar_candidates and plantar_consistency >= 0.40:
                plantar_ref = float(np.mean([c[0] for c in plantar_candidates]))
                kept = []
                for c in fl:
                    if c[5] == "dorsal" and abs(c[0] - plantar_ref) / max(plantar_ref, 1e-6) > DORSAL_FL_DISAGREE_RATIO:
                        log.warning(
                            "  [FUSE] %s/dorsal foot_length dropped — %.1fmm vs plantar %.1fmm (>%.0f%% disagreement)",
                            foot_side, c[0], plantar_ref, DORSAL_FL_DISAGREE_RATIO * 100,
                        )
                        if isinstance(view_details, dict) and (foot_side, "dorsal") in view_details:
                            view_details[(foot_side, "dorsal")]["fuse_dropped"] = "dorsal_foot_length_disagreement"
                        continue
                    kept.append(c)
                raw["foot_length_mm"] = kept
            elif plantar_candidates and plantar_consistency < 0.40:
                log.warning(
                    "  [FUSE] %s/plantar foot_length dropped — lm_spatial_consistency=%.2f < 0.40",
                    foot_side, plantar_consistency,
                )
                if isinstance(view_details, dict) and (foot_side, "plantar") in view_details:
                    view_details[(foot_side, "plantar")]["fuse_dropped"] = "plantar_lm_inconsistent"
                raw["foot_length_mm"] = dorsal_candidates + [
                    c for c in fl if c[5] not in ("plantar", "dorsal")
                ]

        fused = {}
        for key, candidates in raw.items():
            values  = np.array([v for v, _, _, _, _, _ in candidates], dtype=np.float32)
            weights = np.array([w for _, w, _, _, _, _ in candidates], dtype=np.float32)
            sigmas  = np.array([s for _, _, s, _, _, _ in candidates], dtype=np.float32)
            qs      = np.array([q for _, _, _, q, _, _ in candidates], dtype=np.float32)
            sources = [src for _, _, _, _, src, _ in candidates]
            total_w = weights.sum()
            if total_w == 0:
                continue
            fused_val = float(np.dot(weights / total_w, values))
            spread    = float(values.max() - values.min()) if len(values) > 1 else 0.0
            spread_ok = spread / (abs(fused_val) + 1e-6) < 0.08
            q_mean = float(np.mean(qs)) if len(qs) else 0.0
            direct_only = all(src == "detected" for src in sources)
            single_view_high_conf = (len(candidates) == 1 and q_mean >= 0.80 and direct_only)
            multi_view_ok = (len(candidates) >= 2 and spread_ok and q_mean >= 0.55)
            quality = "trusted" if (single_view_high_conf or multi_view_ok) else "degraded"
            sigma = None
            if len(sigmas) > 0:
                sigmas = np.maximum(sigmas, 1e-3)
                inv_var = float(np.sum(1.0 / (sigmas ** 2)))
                if inv_var > 0:
                    sigma = math.sqrt(1.0 / inv_var)
                else:
                    sigma = float(np.max(sigmas))
            fused[key] = {
                "value_mm":  round(fused_val, 2),
                "n_views":   len(candidates),
                "spread_mm": round(spread, 2),
                "quality":   quality,
                "view_quality_mean": round(q_mean, 3),
            }
            if sigma is not None:
                if "deg" in key:
                    fused[key]["uncertainty_deg"] = round(float(sigma), 2)
                    fused[key]["ci95_deg"] = round(float(1.96 * sigma), 2)
                else:
                    fused[key]["uncertainty_mm"] = round(float(sigma), 2)
                    fused[key]["ci95_mm"] = round(float(1.96 * sigma), 2)

        results[foot_side] = fused

    return results


# ═══════════════════════════════════════════════════════════
# RESULT
# ═══════════════════════════════════════════════════════════

@dataclass
class PipelineResult:
    patient_id:      str
    measurements:    dict
    view_details:    dict
    overall_quality: str

    def summary(self) -> str:
        lines = [
            f"\n{'='*56}",
            f"  Patient : {self.patient_id}",
            f"  Quality : {self.overall_quality}",
            "="*56,
        ]
        for foot_side in ("left", "right"):
            lines.append(f"\n  {foot_side.upper()} FOOT")
            foot = self.measurements.get(foot_side, {})
            if not foot:
                lines.append("    No measurements available.")
                continue
            for name, data in foot.items():
                unit = "°" if "deg" in name else "mm"
                flag = "✓" if data["quality"] == "trusted" else "⚠"
                ci_key = "ci95_deg" if "deg" in name else "ci95_mm"
                ci_val = data.get(ci_key)
                ci_txt = f", ci95={ci_val:.1f}" if ci_val is not None else ""
                lines.append(
                    f"    {flag} {name:<30} {data['value_mm']:>7.1f} {unit}"
                    f"  (views={data['n_views']}, spread={data['spread_mm']}{ci_txt})"
                )

        lines.append(f"\n  VIEW DETAILS")
        for (s, v), d in self.view_details.items():
            px = f"{d['px_per_mm']:.2f}" if d.get("px_per_mm") else "no scale"
            src = d.get("scale_source", "unknown")
            lines.append(
                f"    {s:<6} {v:<5}  "
                f"mask_conf={d.get('mask_conf', 0):.2f}  "
                f"px/mm={px}  src={src}"
            )
        lines.append("="*56)
        return "\n".join(lines)

    def _to_serializable(self, obj):
        if isinstance(obj, (np.floating, np.integer)):
            return obj.item()
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, dict):
            return {str(k): self._to_serializable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self._to_serializable(v) for v in obj]
        return obj

    def _view_details_serializable(self) -> dict:
        out = {}
        for (s, v), d in self.view_details.items():
            key = f"{s}/{v}"
            out[key] = self._to_serializable(d)
        return out

    # Map internal rejection codes to clinician-facing text + an actionable
    # "fix" hint. Keys are the codes that may appear in mask_qc.reason,
    # fuse_dropped, scale_source, or be derived from landmark counts. Values
    # are { "msg": short human description, "fix": one-line recommendation }.
    # Both fields are i18n keys on the SPA side — defaults are English here
    # for runs read directly without UI rendering.
    _ISSUE_CATALOG = {
        "empty_mask":              {"msg": "Foot not detected in photo",
                                    "fix": "Retake — make sure the whole foot is in frame and well lit."},
        "empty_rows":              {"msg": "Foot not detected in photo",
                                    "fix": "Retake — make sure the whole foot is in frame and well lit."},
        "tiny_after_qc":           {"msg": "Foot region too small after cleanup",
                                    "fix": "Retake — move closer so the foot fills more of the photo."},
        "top_spill":               {"msg": "Mask spilled into background",
                                    "fix": "Retake — use a plain background that contrasts with the skin."},
        "leg_segment_unresolved":  {"msg": "Leg captured along with foot — could not separate",
                                    "fix": "Retake — frame should end just above the ankle, not include the calf."},
        "lateral_spill":           {"msg": "Mask leaked sideways into other objects",
                                    "fix": "Retake — remove the other foot, hands, or objects from the frame."},
        "low_mask_conf":           {"msg": "Foot outline unclear",
                                    "fix": "Retake in brighter, even light. Avoid shadows on the foot."},
        "over_crop":               {"msg": "Too much of the photo had to be cropped",
                                    "fix": "Retake — frame the foot, not the leg or surroundings."},
        "large_mask":              {"msg": "Mask covers more than just the foot",
                                    "fix": "Retake with the foot alone in frame — no other foot, hand, or objects."},
        "squat_mask":              {"msg": "Foot shape detected was not foot-like",
                                    "fix": "Retake — ensure the foot is fully visible and oriented as instructed."},
        "low_solidity":            {"msg": "Foot outline broken into multiple pieces",
                                    "fix": "Retake with even lighting — shadows can split the foot mask."},
        "scale_outlier":           {"msg": "Reference card placed on a different surface than the foot",
                                    "fix": "Retake — place the marker FLAT on the same surface as the foot, not held up."},
        "dorsal_foot_length_disagreement": {"msg": "Top-view length disagreed with sole-view length",
                                            "fix": "Top-view rejected for length. Use plantar/medial values, or retake top photo."},
        "card_wrong_depth":        {"msg": "Scale card was held in air instead of placed flat on same surface as foot",
                                    "fix": "Retake — lay the marker flat on the SAME surface the foot is resting on. Do not hold it up."},
        "scale_missing":           {"msg": "Reference marker (card/coin) not found",
                                    "fix": "Retake — place the marker fully in the photo, flat, near the foot."},
        "low_marker_conf":         {"msg": "Reference marker found but low confidence",
                                    "fix": "Retake — clean the marker, place it flat, no glare. Avoid shadows on the marker."},
        "landmark_suppressed":     {"msg": "Could not locate enough foot landmarks",
                                    "fix": "Retake — make sure the toes, ball, and heel are all clearly visible."},
        "landmark_zero_confident": {"msg": "Landmarks could not be detected",
                                    "fix": "Retake — improve lighting and orientation. Foot should fill most of the frame."},
    }

    def _summarize_quality_issues(self) -> list[dict]:
        """
        Walk view_details and produce a flat list of clinician-facing issues.

        Each issue: {
            "side": "left"|"right",
            "view": "plantar"|"dorsal"|"medial",
            "code": "<rejection key>",
            "msg":  "<short description>",
            "fix":  "<actionable one-liner>",
            "severity": "rejected"|"degraded",
        }

        Rules:
          - mask_qc.reject  -> always "rejected" severity
          - fuse_dropped    -> "rejected" (view excluded from final numbers)
          - landmark_suppressed (LM-QC) -> "rejected" for that view's contributions
          - scale_source not "detected" -> "degraded" (borrowed/missing/mask_reject)
          - landmark_zero_confident on a non-rejected view -> "rejected"
        """
        issues: list[dict] = []
        for (s, v), d in self.view_details.items():
            if not isinstance(d, dict):
                continue

            mask_qc = d.get("mask_qc") or {}
            mask_reason = mask_qc.get("reason")
            if mask_qc.get("reject") and mask_reason:
                # Some reasons carry a numeric suffix in the log (e.g.
                # "squat_mask_1.05", "low_solidity_0.32") — strip to the
                # known prefix so the catalog lookup succeeds.
                base = mask_reason
                for prefix in (
                    "squat_mask", "low_mask_conf", "low_solidity",
                    "over_crop", "large_mask",
                ):
                    if mask_reason.startswith(prefix):
                        base = prefix
                        break
                cat = self._ISSUE_CATALOG.get(base)
                if cat:
                    issues.append({
                        "side": s, "view": v, "code": base,
                        "msg": cat["msg"], "fix": cat["fix"],
                        "severity": "rejected",
                    })
                continue  # don't double-flag a rejected mask

            if d.get("card_wrong_depth"):
                cat = self._ISSUE_CATALOG.get("card_wrong_depth")
                if cat:
                    issues.append({
                        "side": s, "view": v, "code": "card_wrong_depth",
                        "msg": cat["msg"], "fix": cat["fix"],
                        "severity": "rejected",
                    })

            fuse_dropped = d.get("fuse_dropped")
            if fuse_dropped:
                cat = self._ISSUE_CATALOG.get(fuse_dropped)
                if cat:
                    issues.append({
                        "side": s, "view": v, "code": fuse_dropped,
                        "msg": cat["msg"], "fix": cat["fix"],
                        "severity": "rejected",
                    })

            scale_src = d.get("scale_source")
            if scale_src in ("missing", "missing_distance_mismatch", "mask_reject"):
                code = "scale_missing" if scale_src.startswith("missing") else None
                if code:
                    cat = self._ISSUE_CATALOG.get(code)
                    if cat:
                        issues.append({
                            "side": s, "view": v, "code": code,
                            "msg": cat["msg"], "fix": cat["fix"],
                            "severity": "rejected",
                        })
            elif scale_src == "detected":
                # Detected but low-confidence — flag as degraded.
                conf = d.get("scale_conf") or 0.0
                if isinstance(conf, (int, float)) and conf < 0.40:
                    cat = self._ISSUE_CATALOG.get("low_marker_conf")
                    if cat:
                        issues.append({
                            "side": s, "view": v, "code": "low_marker_conf",
                            "msg": cat["msg"], "fix": cat["fix"],
                            "severity": "degraded",
                        })

            if d.get("landmark_suppressed"):
                cat = self._ISSUE_CATALOG.get("landmark_suppressed")
                if cat:
                    issues.append({
                        "side": s, "view": v, "code": "landmark_suppressed",
                        "msg": cat["msg"], "fix": cat["fix"],
                        "severity": "rejected",
                    })
            elif (d.get("landmark_conf_mean") or 0.0) < 0.05 and d.get("landmark_conf_min") is not None:
                # All landmarks effectively zero confidence on a passing-mask view.
                cat = self._ISSUE_CATALOG.get("landmark_zero_confident")
                if cat:
                    issues.append({
                        "side": s, "view": v, "code": "landmark_zero_confident",
                        "msg": cat["msg"], "fix": cat["fix"],
                        "severity": "rejected",
                    })
        return issues

    def to_dict(self, include_uncertainty: bool = False, include_views: bool = False) -> dict:
        out = {"patient_id": self.patient_id, "quality": self.overall_quality}
        for foot_side, meas in self.measurements.items():
            if include_uncertainty:
                out[foot_side] = self._to_serializable({k: v for k, v in meas.items()})
            else:
                out[foot_side] = self._to_serializable({k: v["value_mm"] for k, v in meas.items()})
        # Always include quality issues — clients (UI, PDF) need them to
        # explain to clinicians why measurements are missing or degraded.
        out["quality_issues"] = self._summarize_quality_issues()
        if include_views:
            out["view_details"] = self._view_details_serializable()
        return out

    def to_dict_full(self) -> dict:
        return self.to_dict(include_uncertainty=True, include_views=True)


# ═══════════════════════════════════════════════════════════
# PIPELINE
# ═══════════════════════════════════════════════════════════

class FootPipeline:
    """
    End-to-end foot measurement pipeline.
    Safe for RTX 4050 6GB VRAM — models load/unload sequentially.
    """

    def __init__(
        self,
        sam_path:         str,
        card_model_path:  str,
        coin_model_path:  str,
        landmark_configs: dict[tuple[str, str], tuple[str, str]],
        camera_calib:     Optional[str] = None,
        viz_dir:          Optional[str] = None,
        allow_borrowed_scale: bool = False,
        lenient_mode: bool = False,
        seg_model_path:   str = _DEFAULT_UNET_PATH,
    ):
        """
        Parameters
        ----------
        sam_path          : path to sam_b.pt (fallback if seg_model_path missing)
        card_model_path   : path to card_detector.pt (ISO ID-1 card)
        coin_model_path   : path to coin_detector.pt (Indian coins ₹1/₹2/₹5/₹10)
        landmark_configs  : {
                              ("left"|"right", "plantar"|"dorsal"|"medial"):
                              (config_path, checkpoint_path)
                            }
        camera_calib      : optional camera calibration JSON (camera_matrix, dist_coeffs)
        viz_dir           : optional output dir for per-view visualization images
        allow_borrowed_scale : if True, allow scale borrowing from same-foot detected views
        lenient_mode      : if True, relax QC/rejection gates to recover more measurements
        seg_model_path    : path to fine-tuned UNet-MobileNetV2 segmentation checkpoint
                            (falls back to SAM if not found)
        """
        self.sam_path         = sam_path
        self.card_model_path  = card_model_path
        self.coin_model_path  = coin_model_path
        self.landmark_configs = landmark_configs
        self.camera_calib     = camera_calib
        self.viz_dir          = viz_dir
        self.allow_borrowed_scale = allow_borrowed_scale
        self.lenient_mode     = bool(lenient_mode)
        self.seg_model_path   = seg_model_path

    def run(
        self,
        patient_id: str,
        images:     dict[tuple[str, str], str],
        progress_callback=None,
        patient_info: Optional[dict] = None,
    ) -> PipelineResult:
        """
        Run the full pipeline for one patient session.

        Parameters
        ----------
        patient_id : str
        images     : {
                       ("left"|"right", "plantar"|"dorsal"|"medial"): image_path
                     }
                     Missing entries are skipped gracefully.
        progress_callback : optional callable(dict) invoked at stage transitions.
                            dict has keys: stage (str), view (str|None), percent (int).

        Returns
        -------
        PipelineResult
        """
        def _cb(stage, view, pct):
            if progress_callback:
                try:
                    progress_callback({"stage": stage, "view": view, "percent": pct})
                except Exception:
                    pass

        _log_environment()
        log.info("Starting pipeline for patient: %s", patient_id)
        if self.lenient_mode:
            log.warning("Lenient mode enabled: relaxed QC and fallback gates.")
        run_start = time.perf_counter()
        view_details      = {}
        view_measurements = {}
        pending_views = {}
        scale_by_foot = {"left": [], "right": []}

        # ── Collect valid views ───────────────────────────────────────
        ordered_views = []
        for (foot_side, view), img_path in images.items():
            if view not in ("plantar", "dorsal", "medial"):
                log.error(f"Unknown view '{view}' — must be plantar/dorsal/medial. Skipping.")
                continue
            if not Path(img_path).exists():
                log.warning(f"Image not found: {img_path} — skipping {foot_side}/{view}")
                continue
            ordered_views.append(((foot_side, view), img_path))
        n_views = max(len(ordered_views), 1)

        _cb("preprocessing", None, 0)

        # ── Phase 1: Preprocess all images ───────────────────────────
        preprocessed = {}
        for (foot_side, view), img_path in ordered_views:
            log.info(f"\n{'─'*56}")
            log.info(f"  Preprocess: {foot_side.upper()} {view.upper()} — {Path(img_path).name}")
            log.info(f"{'─'*56}")
            t0 = time.perf_counter()
            bgr_orig, bgr_small, scale = preprocess(img_path, self.camera_calib)
            h_s, w_s = bgr_small.shape[:2]
            log.info(f"  Resized → {w_s}×{h_s}  scale={scale:.3f}")
            calib = _load_calibration(self.camera_calib)
            K_small = None
            if calib and calib.get("K") is not None:
                K_small = _scale_intrinsics(calib["K"], scale, scale)
            preprocessed[(foot_side, view)] = {
                "bgr_orig": bgr_orig,
                "bgr_small": bgr_small,
                "scale": scale,
                "K_small": K_small,
                "img_path": img_path,
            }
            log.info("  Preprocess time: %.2fs", time.perf_counter() - t0)

        _cb("preprocessing", None, 5)

        # ── Phase 2: Segmentation — UNet preferred, SAM fallback ──
        seg_results = {}
        _use_unet = (
            self.seg_model_path
            and Path(self.seg_model_path).exists()
        )

        if _use_unet:
            log.info("  [UNet] Loading once for all %d views...", n_views)
            _seg_model = _load_unet(self.seg_model_path)
        else:
            _seg_model = None
            # Fall back to SAM
            try:
                from ultralytics import SAM as _SAM
                _sam_available = Path(self.sam_path).exists()
            except Exception:
                _SAM = None
                _sam_available = False
            if _sam_available:
                log.info("  [SAM] Loading once for all %d views (fallback)...", n_views)
                _seg_model = _SAM(self.sam_path)
                _seg_model.to(DEVICE)
            else:
                log.warning("  No segmentation model available (no UNet or SAM).")

        for i, ((foot_side, view), _) in enumerate(ordered_views):
            log.info(f"\n{'─'*56}")
            log.info(f"  Segment: {foot_side.upper()} {view.upper()}")
            log.info(f"{'─'*56}")
            t0 = time.perf_counter()
            bgr_small = preprocessed[(foot_side, view)]["bgr_small"]
            bgr_orig  = preprocessed[(foot_side, view)]["bgr_orig"]
            if _use_unet:
                mask, mask_conf, seg_meta = run_segmentation_unet(
                    bgr_small, seg_model=_seg_model, return_meta=True,
                    bgr_full=bgr_orig,
                )
            else:
                mask, mask_conf, seg_meta = run_segmentation(
                    bgr_small, self.sam_path, return_meta=True, sam_model=_seg_model
                )
            # Sideways-foot rescue: detect when the image is portrait-shaped
            # but the foot inside is rotated 90° (EXIF / double-rotation edge
            # case the upstream orientation fix doesn't catch).
            # The PAT-001 right_medial failure mode is subtle: DeepLab finds
            # ONLY the ankle/heel portion of the foot, giving a compact partial
            # mask. That partial mask has decent conf and isn't visibly
            # sideways — so a pure bbox-aspect check misses it. We catch it via
            # mask AREA RATIO: a healthy medial/dorsal/plantar foot mask
            # occupies ~15-35% of the portrait image; a partial-ankle mask
            # occupies <12%.
            _h_s, _w_s = mask.shape[:2]
            _img_area = max(_h_s * _w_s, 1)
            _mask_area_ratio = float(mask.sum()) / _img_area
            _ys, _xs = np.where(mask > 0)
            _bw, _bh = 0, 0
            if len(_xs) > 50:
                _bw = int(_xs.max() - _xs.min())
                _bh = int(_ys.max() - _ys.min())
            # Rotation rescue: medial views are exempt from most conditions because
            # (a) the foot's long axis IS horizontal in a side-shot (bw > bh is normal),
            # and (b) rotating a correctly-oriented medial portrait breaks ArUco card
            # detection and landmark placement. Only rescue medial for catastrophic
            # segmentation (area < 8% or conf < 0.10).
            _is_medial = (view == "medial")
            _suspicious = (
                (_mask_area_ratio < 0.12 and not _is_medial)  # partial mask (plantar/dorsal)
                or (_mask_area_ratio < 0.08 and _is_medial)   # catastrophic partial (medial)
                or (_bw > _bh * 1.2 and mask_conf < 0.35 and not _is_medial)  # sideways bbox
                or (mask_conf < 0.25 and not _is_medial)      # very weak detection (plantar/dorsal)
                or (mask_conf < 0.10 and _is_medial)          # catastrophic medial failure only
            )
            if _suspicious:
                # Try a 90° CW rotation; keep whichever mask is stronger.
                # Strength = area × conf (rewards both coverage and crispness).
                _bgr_small_r = cv2.rotate(bgr_small, cv2.ROTATE_90_CLOCKWISE)
                _bgr_orig_r  = cv2.rotate(bgr_orig,  cv2.ROTATE_90_CLOCKWISE)
                if _use_unet:
                    _mask_r, _conf_r, _meta_r = run_segmentation_unet(
                        _bgr_small_r, seg_model=_seg_model, return_meta=True,
                        bgr_full=_bgr_orig_r,
                    )
                else:
                    _mask_r, _conf_r, _meta_r = run_segmentation(
                        _bgr_small_r, self.sam_path, return_meta=True, sam_model=_seg_model
                    )
                _score_orig = float(mask.sum()) * float(mask_conf)
                _score_rot  = float(_mask_r.sum()) * float(_conf_r)
                if _score_rot > _score_orig * 1.15:
                    log.info(
                        "  [ORIENT-RESEG] %s/%s rotated 90° CW kept (score %.0f vs orig %.0f, conf %.2f→%.2f, area %.1f%%→%.1f%%).",
                        foot_side, view, _score_rot, _score_orig,
                        mask_conf, _conf_r,
                        _mask_area_ratio * 100,
                        float(_mask_r.sum()) / max(_mask_r.shape[0] * _mask_r.shape[1], 1) * 100,
                    )
                    bgr_small = _bgr_small_r
                    bgr_orig  = _bgr_orig_r
                    preprocessed[(foot_side, view)]["bgr_small"] = bgr_small
                    preprocessed[(foot_side, view)]["bgr_orig"]  = bgr_orig
                    mask, mask_conf, seg_meta = _mask_r, _conf_r, _meta_r
                    seg_meta["orient_reseg"] = True
                else:
                    log.info(
                        "  [ORIENT-RESEG] %s/%s rotation didn't help (orig score %.0f >= rot %.0f) — kept original.",
                        foot_side, view, _score_orig, _score_rot,
                    )
            mask, mask_qc = apply_mask_qc(mask, view)
            # Trim leg pixels from dorsal/medial masks before bbox is computed.
            # See _trim_mask_to_foot for rationale (VJARAC-7-24 right_dorsal
            # case: bbox shrank from 1086×3003 to ~1086×1500, in-foot keypoints
            # 2/6 → 4/6 with the same checkpoint).
            mask, trim_meta = _trim_mask_to_foot(mask, view)
            if trim_meta.get("trimmed"):
                log.info(
                    "  [MASK-TRIM] Removed %d top rows (leg) — widest_w=%d at y=%d, narrow_y=%d",
                    trim_meta["rows_removed"], trim_meta["widest_w"],
                    trim_meta["widest_y"], trim_meta["narrow_y"],
                )
                mask_qc["trimmed"] = True
                mask_qc["trim_rows_removed"] = trim_meta["rows_removed"]
            mask_conf = _mask_confidence(mask)
            mask_long_edge_px = _estimate_mask_long_edge_px(mask)
            if mask_qc.get("cropped"):
                log.info(
                    "  [MASK-QC] Cropped %d rows (top_ratio=%.2f)",
                    int(mask_qc.get("rows_removed", 0)),
                    float(mask_qc.get("top_width_ratio", 0.0)),
                )
            # Hard QC gate
            if not mask_qc.get("reject"):
                base_min_mask_conf = float(MASK_CONF_MIN_BY_VIEW.get(view, 0.22))
                base_max_rows_ratio = float(MASK_QC_MAX_ROWS_REMOVED_RATIO.get(view, 0.50))
                if self.lenient_mode:
                    min_mask_conf = max(0.15, base_min_mask_conf - 0.05)
                    max_rows_ratio = min(0.70, base_max_rows_ratio + 0.08)
                    max_large_area = 0.58
                else:
                    min_mask_conf = base_min_mask_conf
                    max_rows_ratio = base_max_rows_ratio
                    max_large_area = 0.50
                rows_removed_ratio = float(mask_qc.get("rows_removed_ratio", 0.0))
                area_after = float(mask_qc.get("area_ratio_after", 0.0))
                bbox_w_after = float(mask_qc.get("bbox_width_ratio_after", 0.0))
                hard_reason = None
                if mask_conf < min_mask_conf:
                    borderline_soft = (
                        view in ("dorsal", "medial")
                        and mask_conf >= (min_mask_conf - 0.03)
                        and area_after < 0.38
                        and bbox_w_after < 0.92
                    )
                    if borderline_soft:
                        mask_qc["soft_warning"] = f"low_mask_conf_{mask_conf:.2f}"
                    else:
                        hard_reason = f"low_mask_conf_{mask_conf:.2f}"
                elif rows_removed_ratio > max_rows_ratio:
                    hard_reason = f"over_crop_{rows_removed_ratio:.2f}"
                elif view in ("dorsal", "medial") and area_after > max_large_area:
                    hard_reason = f"large_mask_{area_after:.2f}"
                if hard_reason:
                    mask_qc["reject"] = True
                    mask_qc["reason"] = hard_reason
            seg_results[(foot_side, view)] = {
                "mask": mask,
                "mask_conf": mask_conf,
                "seg_meta": seg_meta,
                "mask_qc": mask_qc,
                "mask_long_edge_px": mask_long_edge_px,
            }
            if mask_qc.get("reject"):
                log.warning("  [MASK-QC] Rejected mask for %s/%s (%s)", foot_side, view, mask_qc.get("reason"))
            else:
                log.info(f"  Mask confidence: {mask_conf:.3f}")
                warn_conf_th = float(MASK_CONF_MIN_BY_VIEW.get(view, 0.22))
                if self.lenient_mode:
                    warn_conf_th = max(0.15, warn_conf_th - 0.05)
                if mask_conf < warn_conf_th:
                    log.warning("  Low mask confidence: %.2f", mask_conf)
            log.info("  Segment time: %.2fs", time.perf_counter() - t0)
            _cb("segmentation", f"{foot_side}_{view}", 5 + (i + 1) * 30 // n_views)

        if _seg_model is not None:
            _seg_name = "UNet" if _use_unet else "SAM"
            del _seg_model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()
            log.info("  [%s] Unloaded.", _seg_name)

        # ── Phase 3: Reference analysis — ArUco first, then Card YOLO ──
        scale_results = {}
        views_needing_card = []
        views_needing_coin = []
        active_for_ref = [k for (k, _) in ordered_views if not seg_results[k]["mask_qc"].get("reject")]

        # 3a. ArUco detection — no model needed, runs via OpenCV
        for i, ((foot_side, view), _) in enumerate(ordered_views):
            seg = seg_results[(foot_side, view)]
            if seg["mask_qc"].get("reject"):
                scale_results[(foot_side, view)] = (float("nan"), 0.0, {"source": None, "selected": False})
                continue
            log.info(f"\n{'─'*56}")
            log.info(f"  Reference (ArUco): {foot_side.upper()} {view.upper()}")
            log.info(f"{'─'*56}")
            t0 = time.perf_counter()
            bgr_orig_ref = preprocessed[(foot_side, view)]["bgr_orig"]
            _ref_scale   = preprocessed[(foot_side, view)]["scale"]
            # Cap ArUco input size — 12MP scans were 5-15s per view (4x4 to
            # 53 adaptive-threshold windows × 12M pixels × multi-dict). At
            # 2048 the marker still spans 100-200 px (plenty for sub-pixel
            # corner refinement) but detection drops to ~1s per view.
            _ARUCO_MAX = 2048
            _oh, _ow = bgr_orig_ref.shape[:2]
            if max(_oh, _ow) > _ARUCO_MAX:
                _s = _ARUCO_MAX / max(_oh, _ow)
                _bgr_for_aruco = cv2.resize(
                    bgr_orig_ref, (int(_ow * _s), int(_oh * _s)),
                    interpolation=cv2.INTER_AREA,
                )
                _aruco_to_small = _ref_scale / _s   # combined orig→2048→small
            else:
                _bgr_for_aruco = bgr_orig_ref
                _aruco_to_small = _ref_scale
            px_per_mm, conf, ref_meta = _run_aruco_detector(_bgr_for_aruco, return_meta=True)
            if not math.isnan(px_per_mm):
                px_per_mm *= _aruco_to_small  # aruco-input-px/mm → bgr_small-px/mm
            if not math.isnan(px_per_mm) and conf >= ARUCO_CONF_MIN:
                log.info(f"  [REF] ArUco used — {px_per_mm:.2f} px/mm  conf={conf:.2f}")
                scale_results[(foot_side, view)] = (px_per_mm, conf, ref_meta)
            else:
                log.info("  [REF] ArUco not found for %s/%s — queued for card fallback.", foot_side, view)
                views_needing_card.append((foot_side, view))
            log.info("  ArUco detect time: %.2fs", time.perf_counter() - t0)
            _cb("reference", f"{foot_side}_{view}", 35 + (i + 1) * 30 // n_views)

        # 3b. Card YOLO fallback — loaded once for views that need it
        try:
            from ultralytics import YOLO as _YOLO
            _card_available = Path(self.card_model_path).exists()
        except Exception:
            _YOLO = None
            _card_available = False

        if views_needing_card and _card_available:
            log.info("  [CARD] Loading once for %d views needing card fallback...", len(views_needing_card))
            card_inst = _YOLO(self.card_model_path)
            card_inst.to(DEVICE)
            for (foot_side, view) in views_needing_card:
                log.info(f"\n{'─'*56}")
                log.info(f"  Reference (Card): {foot_side.upper()} {view.upper()}")
                log.info(f"{'─'*56}")
                t0 = time.perf_counter()
                bgr_small = preprocessed[(foot_side, view)]["bgr_small"]
                mask = seg_results[(foot_side, view)]["mask"]
                px_per_mm, conf, ref_meta = _run_card_detector(
                    bgr_small, self.card_model_path, foot_mask=mask, return_meta=True,
                    yolo_model=card_inst,
                )
                hom_conf = float(ref_meta.get("homography_conf", 0.0) or 0.0)
                if not math.isnan(px_per_mm) and (conf >= DETECTION_CONF_MIN or hom_conf >= HOMOGRAPHY_CONF_MIN):
                    conf_used = max(conf, hom_conf)
                    ref_meta["selected"] = True
                    ref_meta["scale_conf"] = conf_used
                    log.info(f"  [REF] Card used — {px_per_mm:.2f} px/mm  conf={conf_used:.2f}")
                    scale_results[(foot_side, view)] = (px_per_mm, conf_used, ref_meta)
                else:
                    log.info("  [REF] Card not found for %s/%s — queued for coin fallback.", foot_side, view)
                    scale_results[(foot_side, view)] = (float("nan"), 0.0, ref_meta)
                    views_needing_coin.append((foot_side, view))
                log.info("  Card detect time: %.2fs", time.perf_counter() - t0)
            del card_inst
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()
            log.info("  [CARD] Unloaded.")
        else:
            # Card model not available — ArUco-only views that failed go to coin
            for (foot_side, view) in views_needing_card:
                scale_results[(foot_side, view)] = (float("nan"), 0.0, {"source": None, "selected": False})
                views_needing_coin.append((foot_side, view))
            _cb("reference", None, 65)

        # Coin fallback — loaded once for all views that need it
        if views_needing_coin:
            _coin_available = Path(self.coin_model_path).exists() if _YOLO is not None else False
            if _coin_available:
                log.info("  [COIN] Loading for %d views needing fallback...", len(views_needing_coin))
                coin_inst = _YOLO(self.coin_model_path)
                coin_inst.to(DEVICE)
                for (foot_side, view) in views_needing_coin:
                    t0 = time.perf_counter()
                    bgr_small = preprocessed[(foot_side, view)]["bgr_small"]
                    mask = seg_results[(foot_side, view)]["mask"]
                    px_per_mm, conf, ref_meta = _run_coin_detector(
                        bgr_small, self.coin_model_path, return_meta=True, yolo_model=coin_inst,
                    )
                    if not math.isnan(px_per_mm) and conf >= DETECTION_CONF_MIN:
                        ref_meta["selected"] = True
                        ref_meta["scale_conf"] = conf
                        log.info(f"  [REF] Coin used for {foot_side}/{view} — {px_per_mm:.2f} px/mm  conf={conf:.2f}")
                        scale_results[(foot_side, view)] = (px_per_mm, conf, ref_meta)
                    else:
                        log.warning("  [REF] Neither card nor coin detected for %s/%s.", foot_side, view)
                        scale_results[(foot_side, view)] = (float("nan"), 0.0, ref_meta or {"source": None, "selected": False})
                    log.info("  Coin detect time: %.2fs", time.perf_counter() - t0)
                del coin_inst
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                gc.collect()
                log.info("  [COIN] Unloaded.")

        # ── Phase 4: Landmark detection — weight-swap optimised ──────
        # Group views by type (plantar/dorsal/medial).  Within each group
        # the HRNet architecture is identical (same backbone + head dim),
        # so we build the model ONCE and swap only the state_dict for the
        # second view.  This cuts init_model calls from 6 → 3 (~12-15s saved).
        #
        # flip_test settings per config (must be toggled on swap):
        #   left_sole=True  right_sole=True
        #   left_top=True   right_top=False
        #   left_side=False right_side=False

        # NOTE: left/dorsal was True historically but the May-11 left_top
        # config sets flip_test=False with no usable FLIP_PAIRS for the
        # left-foot-only dataset. Forcing flip_test=True at runtime caused
        # heatmaps to be averaged with un-mirrored predictions and silently
        # degraded the model output. Now matches the actual config.
        _FLIP_TEST_CFG = {
            ("left", "plantar"): True, ("right", "plantar"): True,
            ("left", "dorsal"): False, ("right", "dorsal"): False,
            ("left", "medial"): False, ("right", "medial"): False,
        }

        lm_results = {}

        # Separate active views (with configs, not rejected) into groups,
        # preserving ordered_views ordering for progress %.
        _lm_groups: dict[str, list[tuple[str, str]]] = {
            "plantar": [], "dorsal": [], "medial": [],
        }
        _lm_skipped = 0
        for (foot_side, view), _ in ordered_views:
            seg = seg_results[(foot_side, view)]
            lm_config = self.landmark_configs.get((foot_side, view))
            if seg["mask_qc"].get("reject") or not lm_config:
                lm_results[(foot_side, view)] = {}
                _lm_skipped += 1
                if not lm_config and not seg["mask_qc"].get("reject"):
                    log.warning(f"  No landmark model for {foot_side}/{view} — mask only")
                continue
            _lm_groups[view].append((foot_side, view))

        # Import MMPose once (avoid repeated import overhead)
        try:
            from mmpose.apis import init_model as _mmpose_init_raw
            from mmpose.utils import register_all_modules as _mmpose_reg
            _mmpose_reg()
            _mmpose_ready = True

            # Wrap init_model: mmpose internally calls torch.load without
            # weights_only=False, which fails on PyTorch ≥2.6 with numpy
            # objects in the checkpoint.
            _orig_torch_load = torch.load
            def _patched_torch_load(*args, **kwargs):
                kwargs.setdefault("weights_only", False)
                return _orig_torch_load(*args, **kwargs)

            def _mmpose_init(cfg, ckpt, **kw):
                torch.load = _patched_torch_load
                try:
                    return _mmpose_init_raw(cfg, ckpt, **kw)
                finally:
                    torch.load = _orig_torch_load

        except Exception as _mmp_err:
            log.error("  [MMPose] Import failed: %s", _mmp_err)
            _mmpose_ready = False

        _lm_done = 0
        phase4_start = time.perf_counter()

        for view_type in ("plantar", "dorsal", "medial"):
            group = _lm_groups[view_type]
            if not group:
                continue
            if not _mmpose_ready:
                for fs, v in group:
                    lm_results[(fs, v)] = {}
                    _lm_done += 1
                    _cb("landmarks", f"{fs}_{v}", 65 + (_lm_done + _lm_skipped) * 30 // n_views)
                continue

            # Build model once for this view-type group
            fs0, v0 = group[0]
            cfg0, ckpt0 = self.landmark_configs[(fs0, v0)]
            log.info(f"\n  [MMPose] Building {view_type} model (group of {len(group)})...")
            t_build = time.perf_counter()
            pose_model = _mmpose_init(cfg0, ckpt0, device=DEVICE)
            log.info("  [MMPose] Build time: %.2fs", time.perf_counter() - t_build)

            for j, (foot_side, view) in enumerate(group):
                log.info(f"\n{'─'*56}")
                log.info(f"  Landmarks: {foot_side.upper()} {view.upper()}")
                log.info(f"{'─'*56}")
                t0 = time.perf_counter()

                # Swap weights for subsequent views in the group
                if j > 0:
                    cfg_j, ckpt_j = self.landmark_configs[(foot_side, view)]
                    t_swap = time.perf_counter()
                    _ckpt_data = torch.load(ckpt_j, map_location=DEVICE, weights_only=False)
                    _sd = _ckpt_data["state_dict"] if "state_dict" in _ckpt_data else _ckpt_data
                    pose_model.load_state_dict(_sd)
                    log.info("  [MMPose] Weight swap: %.2fs", time.perf_counter() - t_swap)

                # Toggle flip_test to match this view's config
                _flip = _FLIP_TEST_CFG.get((foot_side, view), False)
                if hasattr(pose_model, "test_cfg") and isinstance(pose_model.test_cfg, dict):
                    pose_model.test_cfg["flip_test"] = _flip

                bgr_orig = preprocessed[(foot_side, view)]["bgr_orig"]
                img_scale = preprocessed[(foot_side, view)]["scale"]
                mask = seg_results[(foot_side, view)]["mask"]

                landmarks = run_landmark_detection(
                    bgr_orig, cfg0, ckpt0, view, foot_side, mask, img_scale,
                    lenient_mode=self.lenient_mode,
                    pose_model=pose_model,
                )
                n_conf = sum(1 for d in landmarks.values() if d["conf"] >= CONF_MIN)
                log.info(f"  Landmarks: {n_conf}/{len(landmarks)} confident")
                lm_results[(foot_side, view)] = landmarks
                log.info("  Landmark time: %.2fs", time.perf_counter() - t0)
                _lm_done += 1
                _cb("landmarks", f"{foot_side}_{view}", 65 + (_lm_done + _lm_skipped) * 30 // n_views)

            # Unload this group's model
            del pose_model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            log.info(f"  [MMPose] {view_type} group unloaded.")

        # Single gc pass after all landmark groups
        gc.collect()
        log.info("  [Phase 4] All landmarks done in %.2fs", time.perf_counter() - phase4_start)

        # ── Phase 5: Geometry per view ────────────────────────────────
        _cb("geometry", None, 95)
        for (foot_side, view), _ in ordered_views:
            view_start = time.perf_counter()
            seg       = seg_results[(foot_side, view)]
            mask      = seg["mask"]
            mask_conf = seg["mask_conf"]
            seg_meta  = seg["seg_meta"]
            mask_qc   = seg["mask_qc"]
            mask_long_edge_px = seg["mask_long_edge_px"]
            bgr_small = preprocessed[(foot_side, view)]["bgr_small"]
            scale     = preprocessed[(foot_side, view)]["scale"]
            K_small   = preprocessed[(foot_side, view)]["K_small"]
            px_per_mm, scale_conf, ref_meta = scale_results[(foot_side, view)]

            # Card fallback with very low confidence is unreliable — treat as
            # missing scale so the borrow path uses the median of same-foot
            # ArUco views instead. (e.g. right/medial conf=0.28 drives L-R gap.)
            _CARD_BORROW_CONF_THRESH = 0.35
            if (
                not math.isnan(px_per_mm)
                and float(scale_conf) < _CARD_BORROW_CONF_THRESH
                and (ref_meta or {}).get("source") == "card"
                and self.allow_borrowed_scale
            ):
                log.warning(
                    "  [REF] %s/%s card conf=%.2f < %.2f — rejecting, will borrow scale",
                    foot_side, view, scale_conf, _CARD_BORROW_CONF_THRESH,
                )
                px_per_mm = float("nan")

            # Mask-implied foot size sanity check.
            # If this view's px/mm implies a foot length < 100 mm (impossible for
            # any adult), the card was placed at the wrong depth — e.g. held in
            # the air for a sole/plantar shot while the foot rests on a stool.
            # Reject the scale so the borrow mechanism can use a better view.
            _scale_wrong_depth = False
            if (
                not math.isnan(px_per_mm)
                and mask_long_edge_px is not None
                and float(mask_long_edge_px) > 0
                and self.allow_borrowed_scale
            ):
                _implied_foot_mm = float(mask_long_edge_px) / float(px_per_mm)
                if _implied_foot_mm < 100.0:
                    log.warning(
                        "  [REF] %s/%s implied_foot=%.1fmm < 100mm "
                        "(mask_edge=%.0fpx, px/mm=%.2f) — card at wrong depth, "
                        "rejecting scale, will borrow from other views.",
                        foot_side, view, _implied_foot_mm,
                        float(mask_long_edge_px), px_per_mm,
                    )
                    px_per_mm = float("nan")
                    _scale_wrong_depth = True

            landmarks = lm_results.get((foot_side, view), {})
            _lm_spatial_score = _lm_mask_consistency(landmarks, mask, view)

            if mask_qc.get("reject"):
                viz_path = save_view_visualization(
                    viz_dir=self.viz_dir, patient_id=patient_id,
                    foot_side=foot_side, view=view, image_small=bgr_small,
                    mask_small=mask, landmarks={}, scale=scale,
                    measurements={}, mask_qc=mask_qc,
                )
                view_details[(foot_side, view)] = {
                    "mask_conf": mask_conf, "mask_qc": mask_qc,
                    "px_per_mm": None, "scale_conf": 0.0, "scale_source": "mask_reject",
                    "landmark_conf_mean": 0.0, "landmark_conf_min": 0.0,
                    "lm_spatial_consistency": _lm_spatial_score,
                    "seg_meta": seg_meta, "ref_meta": {"source": None, "selected": False},
                    "mask_long_edge_px": mask_long_edge_px, "viz_path": viz_path,
                }
                log.info("  View total time: %.2fs", time.perf_counter() - view_start)
                continue

            lm_confs = [float(d.get("conf", 0.0)) for d in landmarks.values()] if landmarks else []
            landmark_conf_mean = float(np.mean(lm_confs)) if lm_confs else 0.0
            landmark_conf_min  = float(np.min(lm_confs)) if lm_confs else 0.0
            primary_names = PRIMARY_LANDMARKS.get(view, ())
            n_primary_conf = sum(
                1 for name in primary_names
                if isinstance(landmarks.get(name), dict) and float(landmarks[name].get("conf", 0.0)) >= CONF_MIN
            )
            required_primary = int(MIN_PRIMARY_LANDMARKS.get(view, 2))
            if self.lenient_mode:
                required_primary = max(1, required_primary - 1)
            allow_mask_fallback = n_primary_conf >= required_primary
            if not allow_mask_fallback:
                log.warning(
                    "  [LM-QC] Low primary landmarks for %s/%s: %d/%d (required=%d) — suppressing fallback metrics.",
                    foot_side, view, n_primary_conf, len(primary_names), required_primary,
                )

            if math.isnan(px_per_mm):
                log.warning(f"  Scale unknown — pending fallback for {foot_side}/{view}")
                viz_path = save_view_visualization(
                    viz_dir=self.viz_dir, patient_id=patient_id,
                    foot_side=foot_side, view=view, image_small=bgr_small,
                    mask_small=mask, landmarks=landmarks, scale=scale,
                    measurements={}, mask_qc=mask_qc,
                )
                view_details[(foot_side, view)] = {
                    "mask_conf": mask_conf, "mask_qc": mask_qc,
                    "px_per_mm": None, "scale_conf": 0.0, "scale_source": "missing",
                    "landmark_conf_mean": landmark_conf_mean, "landmark_conf_min": landmark_conf_min,
                    "landmark_primary_conf": n_primary_conf,
                    "lm_spatial_consistency": _lm_spatial_score,
                    "seg_meta": seg_meta, "ref_meta": ref_meta,
                    "mask_long_edge_px": mask_long_edge_px, "viz_path": viz_path,
                    "card_wrong_depth": _scale_wrong_depth,
                }
                pending_views[(foot_side, view)] = {
                    "mask": mask, "scale": scale, "landmarks": landmarks,
                    "ref_meta": ref_meta, "mask_conf": mask_conf, "seg_meta": seg_meta,
                    "K_small": K_small, "bgr_small": bgr_small, "mask_qc": mask_qc,
                    "allow_mask_fallback": allow_mask_fallback,
                    "mask_long_edge_px": mask_long_edge_px,
                }
                log.info("  View total time: %.2fs", time.perf_counter() - view_start)
                continue

            meas = run_geometry(
                view, mask, scale, px_per_mm, landmarks, ref_meta,
                allow_mask_fallback=allow_mask_fallback,
            )
            log.info(f"  Measurements extracted: {list(meas.keys())}")

            refined = None
            if K_small is not None:
                landmarks_small = {
                    k: {"x": v["x"] * scale, "y": v["y"] * scale, "conf": v["conf"]}
                    for k, v in landmarks.items()
                }
                landmarks_small["__planar"] = meas.copy()
                refined = refine_geometry_with_depth(
                    image=bgr_small, mask=mask, landmarks=landmarks_small,
                    homography={
                        "H": ref_meta.get("homography"),
                        "scale_conf": ref_meta.get("homography_conf", scale_conf),
                    } if ref_meta else None,
                    px_per_mm=px_per_mm, camera_intrinsics=K_small,
                )
                for k in ("foot_length_mm", "forefoot_width_mm", "heel_width_mm", "arch_height_mm"):
                    rv = refined.get(k)
                    if isinstance(rv, dict) and "value_mm" in rv:
                        meas[k] = float(rv["value_mm"])

            viz_path = save_view_visualization(
                viz_dir=self.viz_dir, patient_id=patient_id,
                foot_side=foot_side, view=view, image_small=bgr_small,
                mask_small=mask, landmarks=landmarks, scale=scale,
                measurements=meas, mask_qc=mask_qc,
            )
            if viz_path:
                log.info("  Visualization saved: %s", viz_path)

            view_details[(foot_side, view)] = {
                "mask_conf": mask_conf, "mask_qc": mask_qc,
                "px_per_mm": px_per_mm, "scale_conf": scale_conf, "scale_source": "detected",
                "landmark_conf_mean": landmark_conf_mean, "landmark_conf_min": landmark_conf_min,
                "landmark_primary_conf": n_primary_conf,
                "landmark_primary_required": int(required_primary),
                "landmark_primary_total": len(primary_names),
                "landmark_suppressed": (not allow_mask_fallback),
                "lm_spatial_consistency": _lm_spatial_score,
                "seg_meta": seg_meta, "ref_meta": ref_meta,
                "mask_long_edge_px": mask_long_edge_px,
                "raw": meas, "refined": refined, "viz_path": viz_path,
            }
            view_measurements[(foot_side, view)] = meas
            # Diagnostic: per-view scale + foot_length summary so marker-plane
            # issues (px/mm computed at marker depth ≠ foot depth) are visible.
            _fl_mm = meas.get("foot_length_mm")
            _fl_px = (_fl_mm * px_per_mm) if (_fl_mm and np.isfinite(px_per_mm) and px_per_mm > 0) else None
            log.info(
                "  [SCALE] %s/%s  px/mm=%.3f  scale_conf=%.2f  src=%s  foot_len_px=%s  foot_len_mm=%s",
                foot_side, view, px_per_mm, scale_conf, "detected",
                f"{_fl_px:.1f}" if _fl_px is not None else "-",
                f"{_fl_mm:.1f}" if _fl_mm is not None else "-",
            )
            scale_by_foot[foot_side].append({
                "px_per_mm": float(px_per_mm),
                "mask_long_edge_px": float(mask_long_edge_px) if mask_long_edge_px is not None else None,
                "view": view,
            })
            log.info("  View total time: %.2fs", time.perf_counter() - view_start)

        # Fallback pass for missing scale
        for (foot_side, view), data in pending_views.items():
            if not self.allow_borrowed_scale:
                continue
            detected_refs = scale_by_foot[foot_side]
            if not detected_refs:
                continue
            px_vals = [
                float(d["px_per_mm"])
                for d in detected_refs
                if isinstance(d, dict) and np.isfinite(float(d.get("px_per_mm", float("nan"))))
            ]
            if not px_vals:
                continue
            target_edge = data.get("mask_long_edge_px")
            ref_edges = [
                float(d["mask_long_edge_px"])
                for d in detected_refs
                if isinstance(d, dict) and d.get("mask_long_edge_px") is not None
            ]
            if target_edge is not None and ref_edges:
                median_edge = float(np.median(ref_edges))
                edge_ratio = float(target_edge / (median_edge + 1e-6))
                edge_ratio_min = 0.62 if self.lenient_mode else 0.80
                edge_ratio_max = 1.38 if self.lenient_mode else 1.22
                if edge_ratio < edge_ratio_min or edge_ratio > edge_ratio_max:
                    log.warning(
                        "  [REF] Borrowed scale skipped for %s/%s (distance mismatch, edge_ratio=%.2f, expected %.2f..%.2f).",
                        foot_side,
                        view,
                        edge_ratio,
                        edge_ratio_min,
                        edge_ratio_max,
                    )
                    view_details[(foot_side, view)]["scale_source"] = "missing_distance_mismatch"
                    view_details[(foot_side, view)]["borrow_edge_ratio"] = edge_ratio
                    continue
                view_details[(foot_side, view)]["borrow_edge_ratio"] = edge_ratio
            px_fallback = float(np.median(px_vals))
            scale_conf_fb = 0.35
            meas = run_geometry(
                view,
                data["mask"],
                data["scale"],
                px_fallback,
                data["landmarks"],
                data["ref_meta"],
                allow_mask_fallback=bool(data.get("allow_mask_fallback", True)),
            )
            refined = None
            if data.get("K_small") is not None:
                landmarks_small = {
                    k: {"x": v["x"] * data["scale"], "y": v["y"] * data["scale"], "conf": v["conf"]}
                    for k, v in data["landmarks"].items()
                }
                landmarks_small["__planar"] = meas.copy()
                refined = refine_geometry_with_depth(
                    image=data["bgr_small"],
                    mask=data["mask"],
                    landmarks=landmarks_small,
                    homography={
                        "H": data["ref_meta"].get("homography") if data.get("ref_meta") else None,
                        "scale_conf": data["ref_meta"].get("homography_conf", scale_conf_fb) if data.get("ref_meta") else scale_conf_fb,
                    } if data.get("ref_meta") else None,
                    px_per_mm=px_fallback,
                    camera_intrinsics=data["K_small"],
                )
                for k in ("foot_length_mm", "forefoot_width_mm", "heel_width_mm", "arch_height_mm"):
                    rv = refined.get(k)
                    if isinstance(rv, dict) and "value_mm" in rv:
                        meas[k] = float(rv["value_mm"])

            viz_path = save_view_visualization(
                viz_dir=self.viz_dir,
                patient_id=patient_id,
                foot_side=foot_side,
                view=view,
                image_small=data["bgr_small"],
                mask_small=data["mask"],
                landmarks=data["landmarks"],
                scale=data["scale"],
                measurements=meas,
                mask_qc=data.get("mask_qc"),
            )
            if viz_path:
                log.info("  Visualization saved: %s", viz_path)

            _lm_spatial_borrowed = _lm_mask_consistency(data["landmarks"], data["mask"], view)
            view_details[(foot_side, view)].update({
                "px_per_mm": px_fallback,
                "scale_conf": scale_conf_fb,
                "scale_source": "borrowed",
                "lm_spatial_consistency": _lm_spatial_borrowed,
                "raw": meas,
                "refined": refined,
                "viz_path": viz_path,
            })
            view_measurements[(foot_side, view)] = meas
            # Diagnostic: borrowed-scale path — red flag for marker-plane mismatch.
            _fl_mm = meas.get("foot_length_mm")
            _fl_px = (_fl_mm * px_fallback) if (_fl_mm and np.isfinite(px_fallback) and px_fallback > 0) else None
            log.info(
                "  [SCALE] %s/%s  px/mm=%.3f  scale_conf=%.2f  src=borrowed  foot_len_px=%s  foot_len_mm=%s",
                foot_side, view, px_fallback, scale_conf_fb,
                f"{_fl_px:.1f}" if _fl_px is not None else "-",
                f"{_fl_mm:.1f}" if _fl_mm is not None else "-",
            )

        # Stage 6 — Fusion + bias + sanity gate
        fused = fuse_measurements(view_measurements, view_details=view_details)
        fused = apply_bias_correction(fused)
        fused = apply_isotonic_correction(fused)
        fused = apply_sanity_gates(fused, patient_info=patient_info)

        all_qualities = [
            d["quality"]
            for fd in fused.values()
            for d in fd.values()
        ]
        has_left = bool(fused.get("left"))
        has_right = bool(fused.get("right"))
        detected_views = sum(
            1 for d in view_details.values()
            if isinstance(d, dict) and d.get("scale_source") == "detected"
        )
        borrowed_views = sum(
            1 for d in view_details.values()
            if isinstance(d, dict) and d.get("scale_source") == "borrowed"
        )
        rejected_views = sum(
            1 for d in view_details.values()
            if isinstance(d, dict) and d.get("scale_source") in ("missing", "mask_reject")
        )
        if not has_left and not has_right:
            overall = "reject"
        elif not has_left or not has_right:
            overall = "degraded"
        elif "degraded" in all_qualities:
            overall = "degraded"
        elif detected_views < 2 or borrowed_views > 0 or rejected_views > 0:
            overall = "degraded"
        else:
            overall = "trusted"

        _cb("complete", None, 100)
        log.info("Pipeline total time: %.2fs", time.perf_counter() - run_start)
        return PipelineResult(
            patient_id      = patient_id,
            measurements    = fused,
            view_details    = view_details,
            overall_quality = overall,
        )


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

def _normalize_eval_key(key: str) -> str:
    return (
        str(key)
        .strip()
        .lower()
        .replace("-", "_")
        .replace("/", "_")
        .replace(" ", "_")
    )


def _parse_eval_images(sample: dict, root_dir: Path) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}

    def _consume_items(items) -> None:
        for raw_key, raw_val in items:
            if not isinstance(raw_key, str) or not isinstance(raw_val, str):
                continue
            k = _normalize_eval_key(raw_key)
            parts = [p for p in k.split("_") if p]
            if len(parts) < 2:
                continue
            side, view = parts[0], parts[1]
            if side not in ("left", "right") or view not in ("plantar", "dorsal", "medial"):
                continue
            path = Path(raw_val)
            if not path.is_absolute():
                path = root_dir / path
            out[(side, view)] = str(path)

    images = sample.get("images")
    if isinstance(images, dict):
        _consume_items(images.items())

    if not out:
        _consume_items(sample.items())

    return out


def _parse_eval_ground_truth_mm(sample: dict) -> dict[str, dict[str, float]]:
    out = {"left": {}, "right": {}}

    gt = sample.get("ground_truth", sample.get("gt"))
    if not isinstance(gt, dict):
        return out

    def _try_put(side: str, metric: str, value) -> None:
        if side not in ("left", "right"):
            return
        m = _normalize_eval_key(metric)
        if not m.endswith("_mm"):
            return
        try:
            v = float(value)
        except Exception:
            return
        if np.isfinite(v):
            out[side][m] = v

    used_nested = False
    for side in ("left", "right"):
        side_gt = gt.get(side)
        if isinstance(side_gt, dict):
            used_nested = True
            for mk, mv in side_gt.items():
                if isinstance(mk, str):
                    _try_put(side, mk, mv)

    if used_nested:
        return out

    for mk, mv in gt.items():
        if not isinstance(mk, str):
            continue
        key = _normalize_eval_key(mk)
        for side in ("left", "right"):
            prefix = f"{side}_"
            if key.startswith(prefix):
                _try_put(side, key[len(prefix):], mv)
                break

    return out


def _extract_predicted_mm(result: PipelineResult) -> dict[str, dict[str, float]]:
    out = {"left": {}, "right": {}}
    for side in ("left", "right"):
        side_data = result.measurements.get(side, {})
        if not isinstance(side_data, dict):
            continue
        for metric, value in side_data.items():
            if not isinstance(metric, str):
                continue
            metric_norm = _normalize_eval_key(metric)
            if not metric_norm.endswith("_mm"):
                continue
            pred = value.get("value_mm") if isinstance(value, dict) else value
            try:
                pred_f = float(pred)
            except Exception:
                continue
            if np.isfinite(pred_f):
                out[side][metric_norm] = pred_f
    return out


def _summarize_abs_errors(abs_errors: dict[str, list[float]]) -> dict[str, dict[str, float]]:
    summary = {}
    for metric, vals in sorted(abs_errors.items()):
        if not vals:
            continue
        arr = np.asarray(vals, dtype=np.float64)
        if arr.size == 0:
            continue
        summary[metric] = {
            "n": int(arr.size),
            "mae_mm": round(float(arr.mean()), 3),
            "p95_mm": round(float(np.percentile(arr, 95)), 3),
        }
    return summary


def format_evaluation_summary(report: dict) -> str:
    lines = [
        f"\n{'='*56}",
        "  HELD-OUT EVALUATION",
        "=" * 56,
        f"  Samples   : {report.get('n_samples', 0)}",
        f"  Evaluated : {report.get('n_evaluated', 0)}",
        f"  Failed    : {report.get('n_failed', 0)}",
    ]
    quality_counts = report.get("quality_counts", {})
    if isinstance(quality_counts, dict) and quality_counts:
        q_txt = ", ".join(f"{k}={v}" for k, v in sorted(quality_counts.items()))
        lines.append(f"  Quality   : {q_txt}")

    metrics = report.get("metrics_mm", {})
    if not metrics:
        lines.append("\n  No matched mm measurements found between predictions and ground truth.")
        lines.append("=" * 56)
        return "\n".join(lines)

    lines.append("\n  METRICS (MAE/P95 in mm)")
    for metric, m in sorted(metrics.items()):
        lines.append(
            f"    {metric:<28} MAE={m['mae_mm']:>7.3f}  P95={m['p95_mm']:>7.3f}  n={m['n']}"
        )
    lines.append("=" * 56)
    return "\n".join(lines)


def evaluate_heldout_set(
    pipeline: "FootPipeline",
    manifest_path: str,
    predictions_dir: Optional[str] = None,
) -> dict:
    payload = _load_json(manifest_path)

    if isinstance(payload, list):
        samples = payload
    elif isinstance(payload, dict):
        samples = payload.get("patients", payload.get("samples"))
        if samples is None and isinstance(payload.get("images"), dict):
            samples = [payload]
    else:
        raise ValueError("Manifest must be a JSON object or a JSON list.")

    if not isinstance(samples, list) or len(samples) == 0:
        raise ValueError(
            "Manifest must contain a non-empty list under 'patients' or 'samples', "
            "or be a non-empty list itself."
        )

    root_dir = Path(manifest_path).parent
    pred_dir = None
    if predictions_dir:
        pred_dir = Path(predictions_dir)
        pred_dir.mkdir(parents=True, exist_ok=True)

    errors_by_metric: dict[str, list[float]] = {}
    errors_by_side_metric: dict[str, list[float]] = {}
    patient_rows: list[dict] = []
    failures: list[dict] = []
    quality_counts: dict[str, int] = {}

    for idx, sample in enumerate(samples):
        if not isinstance(sample, dict):
            failures.append({"index": idx, "reason": "sample_not_object"})
            continue

        patient_id = str(sample.get("patient_id") or sample.get("id") or f"sample_{idx + 1:03d}")
        images = _parse_eval_images(sample, root_dir)
        if not images:
            failures.append({"patient_id": patient_id, "reason": "no_valid_images"})
            continue

        gt_mm = _parse_eval_ground_truth_mm(sample)
        try:
            result = pipeline.run(patient_id=patient_id, images=images)
        except Exception as e:
            failures.append({"patient_id": patient_id, "reason": f"pipeline_error: {e}"})
            continue

        quality_counts[result.overall_quality] = quality_counts.get(result.overall_quality, 0) + 1

        pred_mm = _extract_predicted_mm(result)
        matched = 0
        for side in ("left", "right"):
            side_gt = gt_mm.get(side, {})
            side_pred = pred_mm.get(side, {})
            for metric, gt_val in side_gt.items():
                if metric not in side_pred:
                    continue
                err = abs(float(side_pred[metric]) - float(gt_val))
                if not np.isfinite(err):
                    continue
                errors_by_metric.setdefault(metric, []).append(float(err))
                errors_by_side_metric.setdefault(f"{side}/{metric}", []).append(float(err))
                matched += 1

        row = {
            "patient_id": patient_id,
            "quality": result.overall_quality,
            "matched_measurements": matched,
        }
        if not gt_mm.get("left") and not gt_mm.get("right"):
            row["note"] = "ground_truth_missing_or_invalid"
        patient_rows.append(row)

        if pred_dir is not None:
            pred_path = pred_dir / f"{patient_id}.json"
            _dump_json(str(pred_path), result.to_dict_full())

    report = {
        "manifest": str(Path(manifest_path)),
        "n_samples": len(samples),
        "n_evaluated": len(patient_rows),
        "n_failed": len(failures),
        "quality_counts": quality_counts,
        "metrics_mm": _summarize_abs_errors(errors_by_metric),
        "metrics_mm_by_side": _summarize_abs_errors(errors_by_side_metric),
        "patients": patient_rows,
    }
    if failures:
        report["failures"] = failures
    return report


if __name__ == "__main__":
    import argparse, json

    p = argparse.ArgumentParser(
        description="Foot measurement pipeline — plantar / dorsal / medial (medial)"
    )
    p.add_argument("--patient",      default=None, help="Patient ID (single-patient mode)")
    p.add_argument("--sam",          default="checkpoints/sam_b.pt")
    p.add_argument("--card-model",   default="checkpoints/card_detector.pt")
    p.add_argument("--coin-model",   default="checkpoints/coin_detector.pt")
    p.add_argument("--calib",        default=None, help="Camera calibration JSON (optional)")

    # Images
    p.add_argument("--left-plantar",    default=None)
    p.add_argument("--left-dorsal",     default=None)
    p.add_argument("--left-medial",     default=None)
    p.add_argument("--right-plantar",   default=None)
    p.add_argument("--right-dorsal",    default=None)
    p.add_argument("--right-medial",    default=None)

    # Landmark configs — optional, omit to use mask-only mode
    view_cfg_map = {"plantar": "sole", "dorsal": "top", "medial": "side"}
    for s in ("left", "right"):
        for v in ("plantar", "dorsal", "medial"):
            v_cfg = view_cfg_map[v]
            p.add_argument(f"--{s}-{v}-config",
                default=f"configs/{s}_{v_cfg}_hrnet_w32.py")
            p.add_argument(f"--{s}-{v}-ckpt",
                default=f"checkpoints/{s}_{v_cfg}.pth")

    p.add_argument("--out", default=None, help="Save JSON to this path")
    p.add_argument("--out-full", default=None, help="Save full JSON with uncertainty + view details")
    p.add_argument("--viz-dir", default=None, help="Directory to save per-view overlay visualizations")
    p.add_argument("--allow-borrowed-scale", action="store_true",
                   help="Allow fallback scale borrowing from same-foot detected views")
    p.add_argument("--strict-reference", action="store_true",
                   help="Disable borrowed scale fallback (overrides --allow-borrowed-scale)")
    p.add_argument("--lenient-mode", action="store_true",
                   help="Relax QC/rejection gates to recover measurements from difficult views")
    p.add_argument(
        "--eval-manifest",
        default=None,
        help="Held-out set JSON path (evaluation mode).",
    )
    p.add_argument(
        "--eval-out",
        default=None,
        help="Where to save held-out evaluation report JSON.",
    )
    p.add_argument(
        "--eval-predictions-dir",
        default=None,
        help="Optional directory to save per-patient full prediction JSONs in evaluation mode.",
    )
    args = p.parse_args()

    pipeline = FootPipeline(
        sam_path  = args.sam,
        card_model_path = args.card_model,
        coin_model_path = args.coin_model,
        camera_calib = args.calib,
        viz_dir = args.viz_dir,
        allow_borrowed_scale = bool(args.allow_borrowed_scale and not args.strict_reference),
        lenient_mode = bool(args.lenient_mode),
        landmark_configs = {
            ("left",  "plantar"): (args.left_plantar_config,  args.left_plantar_ckpt),
            ("left",  "dorsal"):  (args.left_dorsal_config,   args.left_dorsal_ckpt),
            ("left",  "medial"): (args.left_medial_config,  args.left_medial_ckpt),
            ("right", "plantar"): (args.right_plantar_config, args.right_plantar_ckpt),
            ("right", "dorsal"):  (args.right_dorsal_config,  args.right_dorsal_ckpt),
            ("right", "medial"): (args.right_medial_config, args.right_medial_ckpt),
        }
    )

    if args.eval_manifest:
        report = evaluate_heldout_set(
            pipeline=pipeline,
            manifest_path=args.eval_manifest,
            predictions_dir=args.eval_predictions_dir,
        )
        print(format_evaluation_summary(report))
        if args.eval_out:
            _dump_json(args.eval_out, report)
            print(f"\nSaved: {Path(args.eval_out)}")
        raise SystemExit(0)

    required_flags = {
        "patient": "--patient",
        "left_plantar": "--left-plantar",
        "left_dorsal": "--left-dorsal",
        "left_medial": "--left-medial",
        "right_plantar": "--right-plantar",
        "right_dorsal": "--right-dorsal",
        "right_medial": "--right-medial",
    }
    missing = [flag for attr, flag in required_flags.items() if not getattr(args, attr)]
    if missing:
        p.error(
            "Missing required arguments for single-patient mode: "
            + ", ".join(missing)
            + ". Use --eval-manifest for held-out evaluation mode."
        )

    result = pipeline.run(
        patient_id = args.patient,
        images = {
            ("left",  "plantar"): args.left_plantar,
            ("left",  "dorsal"):  args.left_dorsal,
            ("left",  "medial"): args.left_medial,
            ("right", "plantar"): args.right_plantar,
            ("right", "dorsal"):  args.right_dorsal,
            ("right", "medial"): args.right_medial,
        }
    )

    print(result.summary())

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w") as f:
            json.dump(result.to_dict(), f, indent=2)
        print(f"\nSaved: {out_path}")

    if args.out_full:
        out_path = Path(args.out_full)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w") as f:
            json.dump(result.to_dict_full(), f, indent=2)
        print(f"\nSaved: {out_path}")

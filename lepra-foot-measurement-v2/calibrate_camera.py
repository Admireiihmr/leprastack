"""
Camera calibration utility for checkerboard or ChArUco targets.

Usage (checkerboard):
  python calibrate_camera.py --type checkerboard --pattern 9x6 --square-mm 25 --images "C:\\path\\calib\\*.jpg" --out camera_calibration.json

Usage (charuco):
  python calibrate_camera.py --type charuco --pattern 5x7 --square-mm 25 --marker-mm 18 --images "C:\\path\\calib\\*.jpg" --out camera_calibration.json
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np


def _parse_pattern(pat: str) -> Tuple[int, int]:
    if "x" not in pat:
        raise ValueError("pattern must be like 9x6")
    a, b = pat.lower().split("x")
    return int(a), int(b)


def _collect_images(images: str, folder: str) -> List[str]:
    paths: List[str] = []
    if images:
        paths.extend(glob.glob(images))
    if folder:
        p = Path(folder)
        for ext in ("*.jpg", "*.jpeg", "*.png", "*.bmp"):
            paths.extend([str(x) for x in p.glob(ext)])
    return sorted(set(paths))


def _calibrate_checkerboard(
    img_paths: List[str],
    pattern: Tuple[int, int],
    square_mm: float,
) -> dict:
    cols, rows = pattern
    objp = np.zeros((rows * cols, 3), np.float32)
    objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
    objp *= float(square_mm)

    objpoints = []
    imgpoints = []
    image_size = None

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)

    for path in img_paths:
        img = cv2.imread(path)
        if img is None:
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if image_size is None:
            image_size = (gray.shape[1], gray.shape[0])
        found, corners = cv2.findChessboardCorners(gray, (cols, rows))
        if not found:
            continue
        corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
        objpoints.append(objp)
        imgpoints.append(corners)

    if len(objpoints) < 5:
        raise RuntimeError("Not enough valid checkerboard detections (need >= 5).")

    ret, K, dist, rvecs, tvecs = cv2.calibrateCamera(
        objpoints, imgpoints, image_size, None, None
    )

    # Reprojection error
    total_err = 0.0
    total_pts = 0
    for i in range(len(objpoints)):
        img2, _ = cv2.projectPoints(objpoints[i], rvecs[i], tvecs[i], K, dist)
        err = cv2.norm(imgpoints[i], img2, cv2.NORM_L2)
        total_err += err * err
        total_pts += len(objpoints[i])
    reproj = float(np.sqrt(total_err / max(total_pts, 1)))

    return {
        "camera_matrix": K.tolist(),
        "dist_coeffs": dist.reshape(-1).tolist(),
        "reprojection_error": reproj,
        "image_size": list(image_size),
        "pattern": {"type": "checkerboard", "cols": cols, "rows": rows, "square_mm": square_mm},
    }


def _calibrate_charuco(
    img_paths: List[str],
    pattern: Tuple[int, int],
    square_mm: float,
    marker_mm: float,
) -> dict:
    cols, rows = pattern
    if not hasattr(cv2, "aruco"):
        raise RuntimeError("OpenCV aruco module not available.")
    aruco = cv2.aruco
    dictionary = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)

    # Build board (API differs across OpenCV versions)
    if hasattr(aruco, "CharucoBoard_create"):
        board = aruco.CharucoBoard_create(
            squaresX=cols,
            squaresY=rows,
            squareLength=float(square_mm),
            markerLength=float(marker_mm),
            dictionary=dictionary,
        )
    else:
        board = aruco.CharucoBoard(
            (cols, rows),
            float(square_mm),
            float(marker_mm),
            dictionary,
        )

    all_corners = []
    all_ids = []
    image_size = None

    for path in img_paths:
        img = cv2.imread(path)
        if img is None:
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if image_size is None:
            image_size = (gray.shape[1], gray.shape[0])
        corners, ids, _ = aruco.detectMarkers(gray, dictionary)
        if ids is None or len(ids) == 0:
            continue
        ret, charuco_corners, charuco_ids = aruco.interpolateCornersCharuco(
            corners, ids, gray, board
        )
        if ret is None or ret < 4:
            continue
        all_corners.append(charuco_corners)
        all_ids.append(charuco_ids)

    if len(all_corners) < 5:
        raise RuntimeError("Not enough valid charuco detections (need >= 5).")

    ret, K, dist, rvecs, tvecs = aruco.calibrateCameraCharuco(
        all_corners, all_ids, board, image_size, None, None
    )

    # Reprojection error
    total_err = 0.0
    total_pts = 0
    for i in range(len(all_corners)):
        img2, _ = cv2.projectPoints(
            board.chessboardCorners[all_ids[i].flatten()], rvecs[i], tvecs[i], K, dist
        )
        err = cv2.norm(all_corners[i], img2, cv2.NORM_L2)
        total_err += err * err
        total_pts += len(all_ids[i])
    reproj = float(np.sqrt(total_err / max(total_pts, 1)))

    return {
        "camera_matrix": K.tolist(),
        "dist_coeffs": dist.reshape(-1).tolist(),
        "reprojection_error": reproj,
        "image_size": list(image_size),
        "pattern": {
            "type": "charuco",
            "cols": cols,
            "rows": rows,
            "square_mm": square_mm,
            "marker_mm": marker_mm,
        },
    }


def main():
    p = argparse.ArgumentParser(description="Camera calibration for checkerboard/charuco targets")
    p.add_argument("--type", choices=["checkerboard", "charuco"], required=True)
    p.add_argument("--pattern", required=True, help="e.g., 9x6 or 5x7 (inner corners for checkerboard)")
    p.add_argument("--square-mm", type=float, required=True)
    p.add_argument("--marker-mm", type=float, default=None, help="Charuco marker size in mm")
    p.add_argument("--images", default=None, help="Glob pattern for images")
    p.add_argument("--folder", default=None, help="Folder containing calibration images")
    p.add_argument("--out", required=True, help="Output JSON path")
    args = p.parse_args()

    img_paths = _collect_images(args.images, args.folder)
    if not img_paths:
        raise RuntimeError("No calibration images found.")

    pattern = _parse_pattern(args.pattern)
    if args.type == "checkerboard":
        result = _calibrate_checkerboard(img_paths, pattern, args.square_mm)
    else:
        if args.marker_mm is None:
            raise RuntimeError("--marker-mm is required for charuco")
        result = _calibrate_charuco(img_paths, pattern, args.square_mm, args.marker_mm)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(result, f, indent=2)
    print(f"Saved calibration: {out_path}")
    print(f"Reprojection error: {result['reprojection_error']:.4f}")


if __name__ == "__main__":
    main()

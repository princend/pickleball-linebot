"""單鏡頭相機透視投影幾何模型 (solvePnP + 焦距最佳化)。"""
import math
import sys
from pathlib import Path
from typing import Any, List, Optional, Tuple

_worker_dir = Path(__file__).resolve().parent
_repo_root = _worker_dir.parent
for _p in [str(_repo_root), str(_worker_dir)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from worker.constants import COURT_CORNERS_XYZ, DEFAULT_COURT_CORNERS_NORM
except ImportError:
    from constants import COURT_CORNERS_XYZ, DEFAULT_COURT_CORNERS_NORM


def _validate_court_corners(corners: Any) -> Optional[List[Tuple[float, float]]]:
    """驗證自訂球場四角點 (近端左、近端右、遠端右、遠端左；正規化 0~1)。無效則回傳 None。"""
    try:
        pts = [(float(p[0]), float(p[1])) for p in corners]
    except Exception:
        return None
    # 允許角點略超出畫面 (鏡頭較近時遠端角點可能在畫面外)
    if len(pts) != 4 or any(not (-1.0 <= u <= 2.0 and -1.0 <= v <= 2.0) for u, v in pts):
        return None
    return pts


class CameraModel:
    """由球場四角點估計的單鏡頭相機模型 (solvePnP + 焦距搜尋)。

    - ground_to_uv / point_to_uv：球場 3D 座標 → 像素
    - uv_to_ground / uv_to_plane：像素視線與水平面 (Z = z) 的交點
    - reproj_err_px：四角點重投影平均誤差 (標定品質指標)
    """

    def __init__(
        self,
        corners_norm: List[Tuple[float, float]],
        width: int,
        height: int,
        calibrated: bool,
        source: Optional[str] = None,
    ):
        import cv2
        import numpy as np

        self.width = int(width)
        self.height = int(height)
        self.calibrated = bool(calibrated)
        # 四角點來源："user" (呼叫端自訂) / "auto" (自動偵測球場線) / "default" (原測試機位)
        self.source = source or ("user" if calibrated else "default")
        self.corners_norm = [(float(u), float(v)) for u, v in corners_norm]

        obj = np.array(COURT_CORNERS_XYZ, dtype=np.float64)
        img = np.array(corners_norm, dtype=np.float64) * np.array([width, height], dtype=np.float64)

        def solve(f: float):
            K = np.array([[f, 0.0, width / 2.0], [0.0, f, height / 2.0], [0.0, 0.0, 1.0]])
            n, rvecs, tvecs, _ = cv2.solvePnPGeneric(obj, img, K, None, flags=cv2.SOLVEPNP_IPPE)
            best = None
            for rv, tv in zip(rvecs, tvecs):
                R, _ = cv2.Rodrigues(rv)
                C = (-R.T @ tv).ravel()
                if C[2] <= 0.5:  # 相機必須在地面上方
                    continue
                proj, _ = cv2.projectPoints(obj, rv, tv, K, None)
                err = float(np.linalg.norm(proj.reshape(-1, 2) - img, axis=1).mean())
                if best is None or err < best[0]:
                    best = (err, K, R, tv.ravel(), C)
            return best

        best = None
        for f in np.linspace(0.4 * width, 3.0 * width, 131):
            cand = solve(float(f))
            if cand is not None and (best is None or cand[0] < best[0]):
                best = (cand[0], float(f)) + cand[1:]
        if best is None:
            raise ValueError("球場四角點無法解出有效的相機姿態，請確認四角點順序與位置")
        f0 = best[1]
        for f in np.linspace(f0 * 0.96, f0 * 1.04, 41):
            cand = solve(float(f))
            if cand is not None and cand[0] < best[0]:
                best = (cand[0], float(f)) + cand[1:]

        self.reproj_err_px, self.focal_px, self.K, self.R, self.t, self.C = best
        self.Kinv = np.linalg.inv(self.K)
        self._np = np

    def point_to_uv(self, X, Y, Z):
        """3D 球場座標 (可為純量或 numpy 陣列) → 像素 (u, v)。"""
        np = self._np
        P = np.vstack([np.atleast_1d(X), np.atleast_1d(Y), np.atleast_1d(Z)]).astype(float)
        pc = self.R @ P + self.t.reshape(3, 1)
        z = np.where(np.abs(pc[2]) < 1e-6, 1e-6, pc[2])
        u = self.K[0, 0] * pc[0] / z + self.K[0, 2]
        v = self.K[1, 1] * pc[1] / z + self.K[1, 2]
        return u, v

    def ground_to_uv(self, x: float, y: float) -> Tuple[int, int]:
        u, v = self.point_to_uv(x, y, 0.0)
        return int(round(float(u[0]))), int(round(float(v[0])))

    def uv_to_plane(self, u: float, v: float, z: float = 0.0) -> Tuple[float, float]:
        """像素視線與水平面 Z = z 的交點 (X, Y)。視線朝上 / 近乎水平時回傳遠方截斷點。"""
        np = self._np
        d = self.R.T @ (self.Kinv @ np.array([u, v, 1.0]))
        dz = float(d[2])
        if dz > -1e-4:  # 視線不會與該平面相交 (在地平線之上)
            n = math.hypot(float(d[0]), float(d[1])) or 1.0
            return float(self.C[0] + 300.0 * d[0] / n), float(self.C[1] + 300.0 * d[1] / n)
        t = (z - float(self.C[2])) / dz
        x = float(self.C[0] + t * d[0])
        y = float(self.C[1] + t * d[1])
        return (max(-300.0, min(300.0, x)), max(-300.0, min(300.0, y)))

    def uv_to_ground(self, u: float, v: float) -> Tuple[float, float]:
        return self.uv_to_plane(u, v, 0.0)

    def horizon_v(self) -> float:
        """地平線在影像中的 v 座標 (球場平面無限遠處)。"""
        _, v = self.point_to_uv(float(self.C[0]), float(self.C[1]) + 1.0e5, 0.0)
        return float(v[0])


def _camera_plausibility_issue(cam: CameraModel) -> Optional[str]:
    """四角點若來自錯誤的線段組合，通常無法對應到「主點在畫面中央的針孔相機」，以此做最後把關。"""
    if cam.reproj_err_px > 2.5:  # 精確相機標定重投影誤差應在 2.5px 以內
        return f"四角點與針孔相機模型不一致 (重投影誤差 {cam.reproj_err_px:.1f}px)"
    # 匹克球場側拍或頂拍機位正常高度約在 18ft ~ 70ft；若低於 18ft 通常為誤將內側廚房線當成外側底線
    if not (18.0 <= float(cam.C[2]) <= 70.0):
        return f"推算出的相機高度 {float(cam.C[2]):.1f} ft 不合理 (尺度縮小，可能將廚房線誤判為外側底線)"
    return None


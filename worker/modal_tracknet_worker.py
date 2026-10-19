"""匹克球 AI 球路軌跡追蹤與 3D 物理分析雲端服務 (Modal Serverless) — v2。

處理流程：
1. 球員：YOLO26 (Ultralytics) + ByteTrack 偵測 / 追蹤，腳點經相機模型投影到球場座標。
2. 球：TrackNetV3 熱力圖 (預訓練權重為羽球資料，非匹克球) + 幀差法候選點，經運動學鏈結器串成球路；
   再以真正的 Kalman filter + Rauch-Tung-Striebel (RTS) 平滑補點。
3. 球場標定：由球場四角點 (預設為原測試機位；可由呼叫端傳入自訂四角點) 以 solvePnP 估計相機姿態與焦距。
4. 3D 物理擬合：以重力 (g = 32.174 ft/s^2) 拋體模型對像素觀測做非線性最小平方 (重投影誤差)，
   以 Jacobian 共變異數 + Monte Carlo 傳遞不確定度，回報「數值 ± 誤差」與界內機率，不做任何硬性數值裁切。
5. 輸出：工程標註影片、繁體中文雙層分析報告圖，並透過 /media 端點推播回 LINE。

已知限制：單鏡頭 3D 在「深度」方向的不確定度本來就大；球偵測模型尚未用匹克球資料微調；
拋體模型未計入空氣阻力 (球速略為低估)。
"""

import hmac
import math
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import modal

app = modal.App("pickleball-tracknet-worker")
media_volume = modal.Volume.from_name("pickleball-trajectory-media", create_if_missing=True)
DEFAULT_WORKER_SECRET = "pb_worker_v2_8f4a9c2e1b7d6035a9e2f4c8d1b3a5e7"
MEDIA_ROOT = Path("/data/media")

YOLO_WEIGHTS_DIR = "/opt/models"
YOLO_WEIGHTS_NAME = "yolo26s.pt"

# 定義包含 PyTorch、OpenCV、Matplotlib、繁體中文字型 (Noto Sans CJK)、TrackNetV3 與 YOLO26 的容器映像檔
tracknet_image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("git", "ffmpeg", "unzip", "libgl1", "libglib2.0-0", "fonts-noto-cjk", "fontconfig")
    .pip_install(
        "torch==2.2.2",
        "torchvision==0.17.2",
        "opencv-python-headless==4.9.0.80",
        "numpy==1.26.4",
        "scipy==1.13.0",
        "pandas==2.2.2",
        "matplotlib==3.9.0",
        "tqdm==4.66.4",
        "scikit-learn==1.4.2",
        "gdown==5.2.0",
        "requests==2.32.3",
        "fastapi[standard]>=0.115.0",
        "ultralytics>=8.4.0",
        "lapx",
    )
    .run_commands(
        # ultralytics 會一併裝入 opencv-python，這裡換回 headless 版避免兩套 cv2 互相覆蓋
        "pip uninstall -y opencv-python || true",
        "pip install --force-reinstall --no-deps opencv-python-headless==4.9.0.80",
        "fc-cache -fv",
        "git clone https://github.com/qaz812345/TrackNetV3.git /opt/TrackNetV3",
        "mkdir -p /opt/TrackNetV3/ckpts",
        "gdown --fuzzy 'https://drive.google.com/file/d/1CfzE87a0f6LhBp0kniSl1-89zaLCZ8cA/view?usp=sharing' -O /tmp/TrackNetV3_ckpts.zip",
        "unzip -o /tmp/TrackNetV3_ckpts.zip -d /opt/TrackNetV3/ckpts/",
        "find /opt/TrackNetV3/ckpts -name '*.pt' -exec mv {} /opt/TrackNetV3/ckpts/ \\; || true",
        "rm -f /tmp/TrackNetV3_ckpts.zip",
        # 建置映像檔時先下載 YOLO26 權重，避免冷啟動時才下載
        f"mkdir -p {YOLO_WEIGHTS_DIR} && cd {YOLO_WEIGHTS_DIR} && python -c \"from ultralytics import YOLO; YOLO('{YOLO_WEIGHTS_NAME}')\"",
    )
    .env({"TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD": "1"})
)

# ==============================================================================
# 球場座標系 (單位: ft)
#   X 軸：沿球場長邊 (-22 ft 左底線 ~ 0 ft 球網 ~ +22 ft 右底線)
#   Y 軸：沿球場寬邊 (0 ft 近端邊線 ~ +20 ft 遠端邊線，中線為 Y=10 ft)
#   Z 軸：垂直地面高度 (ft，球網中央高度為 34 吋 = 2.833 ft)
# ==============================================================================
G_FTPS2 = 32.174  # 重力加速度 (ft/s^2)
NET_CENTER_HEIGHT_FT = 34.0 / 12.0
BALL_RADIUS_FT = 0.12  # 匹克球直徑約 2.9 吋
FT_PER_S_TO_MPH = 0.681818

# 球場四角點 (近端左、近端右、遠端右、遠端左) 的 3D 座標，用於 solvePnP 標定
COURT_CORNERS_XYZ = [(-22.0, 0.0, 0.0), (22.0, 0.0, 0.0), (22.0, 20.0, 0.0), (-22.0, 20.0, 0.0)]

# 預設標定 = 原測試機位。以下矩陣僅用來「產生預設四角點」，之後所有計算都走 CameraModel。
# 換場地 / 換機位時，呼叫端必須傳入自訂 court_corners (四角點的正規化像素座標 0~1)，否則落點與球速不可信。
_LEGACY_H_NORM_XY2UV = [
    [0.017182780582973706, 0.009964637816878131, 0.5009014449532797],
    [-0.0005107854813489731, 0.009848350391187425, 0.6685161101544206],
    [3.0508294273458333e-05, 0.019932086205118795, 1.0],
]


def _legacy_ground_to_uv_norm(x: float, y: float) -> Tuple[float, float]:
    h = _LEGACY_H_NORM_XY2UV
    d = h[2][0] * x + h[2][1] * y + h[2][2]
    return (
        (h[0][0] * x + h[0][1] * y + h[0][2]) / d,
        (h[1][0] * x + h[1][1] * y + h[1][2]) / d,
    )


DEFAULT_COURT_CORNERS_NORM: List[Tuple[float, float]] = [
    _legacy_ground_to_uv_norm(x, y) for (x, y, _z) in COURT_CORNERS_XYZ
]


def _validate_court_corners(corners: Any) -> Optional[List[Tuple[float, float]]]:
    """驗證自訂球場四角點 (近端左、近端右、遠端右、遠端左；正規化 0~1)。無效則回傳 None。"""
    try:
        pts = [(float(p[0]), float(p[1])) for p in corners]
    except Exception:
        return None
    if len(pts) != 4 or any(not (-0.5 <= u <= 1.5 and -0.5 <= v <= 1.5) for u, v in pts):
        return None
    return pts


class CameraModel:
    """由球場四角點估計的單鏡頭相機模型 (solvePnP + 焦距搜尋)。

    - ground_to_uv / point_to_uv：球場 3D 座標 → 像素
    - uv_to_ground / uv_to_plane：像素視線與水平面 (Z = z) 的交點
    - reproj_err_px：四角點重投影平均誤差 (標定品質指標)
    """

    def __init__(self, corners_norm: List[Tuple[float, float]], width: int, height: int, calibrated: bool):
        import cv2
        import numpy as np

        self.width = int(width)
        self.height = int(height)
        self.calibrated = bool(calibrated)

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


def _build_camera(width: int, height: int, court_corners: Optional[Any] = None) -> CameraModel:
    corners = _validate_court_corners(court_corners) if court_corners is not None else None
    if corners is not None:
        return CameraModel(corners, width, height, calibrated=True)
    return CameraModel(DEFAULT_COURT_CORNERS_NORM, width, height, calibrated=False)


def _download_line_video(message_id: str, line_access_token: str, dest_path: Path) -> bool:
    """從 LINE Messaging API Blob 端點下載使用者上傳的原始影片。"""
    import requests

    url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"
    headers = {"Authorization": f"Bearer {line_access_token}"}
    resp = requests.get(url, headers=headers, stream=True, timeout=60)
    if resp.status_code != 200:
        print(f"LINE 影片下載失敗: HTTP {resp.status_code} - {resp.text}")
        return False

    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)
    return True


def _push_line_messages(target_id: str, line_access_token: str, messages: List[Dict]) -> None:
    """呼叫 LINE Push Message API 將處理完成的軌跡影片與分析報告圖片傳回聊天室。"""
    import requests

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {line_access_token}",
    }
    payload = {"to": target_id, "messages": messages}
    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    if resp.status_code != 200:
        print(f"LINE Push Message 失敗: HTTP {resp.status_code} - {resp.text}")


def _run_tracknet_v3_safe(video_path: Path, pred_dir: Path) -> Tuple[Dict[int, Tuple[int, int, int]], Optional[str]]:
    """以相容 CPU / GPU 的方式執行 TrackNetV3 + InpaintNet。

    回傳 (逐幀座標字典, 錯誤訊息)。執行失敗時一定會回傳錯誤訊息 (不再默默吞掉)，由呼叫端決定如何處理。
    注意：預訓練權重 (qaz812345) 是羽球資料訓練，對匹克球的召回率有限。
    """
    import pandas as pd

    wrapper_script = pred_dir / "run_tracknet_wrapper.py"
    wrapper_code = """
import sys
import runpy
import torch

_orig_load = torch.load
def _safe_load(*args, **kwargs):
    kwargs.setdefault("weights_only", False)
    if not torch.cuda.is_available():
        kwargs["map_location"] = torch.device("cpu")
    return _orig_load(*args, **kwargs)

torch.load = _safe_load
if not torch.cuda.is_available():
    torch.set_num_threads(4)
    torch.Tensor.cuda = lambda self, *a, **kw: self
    torch.nn.Module.cuda = lambda self, *a, **kw: self

sys.path.insert(0, "/opt/TrackNetV3")
sys.argv = [
    "/opt/TrackNetV3/predict.py",
    "--video_file", sys.argv[1],
    "--tracknet_file", "/opt/TrackNetV3/ckpts/TrackNet_best.pt",
    "--inpaintnet_file", "/opt/TrackNetV3/ckpts/InpaintNet_best.pt",
    "--save_dir", sys.argv[2],
    "--batch_size", "4",
]
runpy.run_path("/opt/TrackNetV3/predict.py", run_name="__main__")
"""
    wrapper_script.write_text(wrapper_code, encoding="utf-8")
    proc = subprocess.run(
        ["python", str(wrapper_script), str(video_path), str(pred_dir)],
        cwd="/opt/TrackNetV3",
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        lines = [ln.strip() for ln in (proc.stderr or proc.stdout or "").splitlines() if ln.strip()]
        last_line = lines[-1] if lines else "unknown error"
        msg = f"TrackNetV3 執行失敗 (exit {proc.returncode}): {last_line[:120]}"
        print(msg)
        return {}, msg

    csv_path = pred_dir / f"{video_path.stem}_ball.csv"
    if not csv_path.exists():
        msg = "TrackNetV3 沒有產出 *_ball.csv"
        print(msg)
        return {}, msg

    df = pd.read_csv(csv_path)
    tracknet_coords: Dict[int, Tuple[int, int, int]] = {}
    for _, row in df.iterrows():
        tracknet_coords[int(row["Frame"])] = (int(row["X"]), int(row["Y"]), int(row["Visibility"]))
    return tracknet_coords, None


def _kalman_rts_smooth(
    frames: List[int],
    obs_map: Dict[int, Tuple[float, float]],
    width: int,
) -> Any:
    """像素空間等速度模型 (白雜訊加速度) 的 Kalman filter + Rauch-Tung-Striebel 雙向平滑。

    有觀測的幀做 update，沒有觀測的幀只做 predict (補點)；最後以 RTS 往回平滑。
    回傳 shape (n, 2) 的平滑像素座標。
    """
    import numpy as np

    n = len(frames)
    sig_meas = 0.0015 * width
    acc_std = 0.004 * width

    F = np.array([[1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=float)
    Hm = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=float)
    Rm = np.eye(2) * sig_meas ** 2
    q = acc_std ** 2
    Q = q * np.array(
        [
            [0.25, 0, 0.5, 0],
            [0, 0.25, 0, 0.5],
            [0.5, 0, 1.0, 0],
            [0, 0.5, 0, 1.0],
        ]
    )

    pts = [obs_map.get(f) for f in frames]
    first = next(i for i, p in enumerate(pts) if p is not None)
    nxt = next((i for i in range(first + 1, n) if pts[i] is not None), None)
    if nxt is not None:
        vx0 = (pts[nxt][0] - pts[first][0]) / (nxt - first)
        vy0 = (pts[nxt][1] - pts[first][1]) / (nxt - first)
    else:
        vx0 = vy0 = 0.0

    x = np.array([pts[first][0], pts[first][1], vx0, vy0], dtype=float)
    P = np.diag([sig_meas ** 2, sig_meas ** 2, (0.02 * width) ** 2, (0.02 * width) ** 2])

    x_pred = np.zeros((n, 4))
    P_pred = np.zeros((n, 4, 4))
    x_filt = np.zeros((n, 4))
    P_filt = np.zeros((n, 4, 4))
    for k in range(n):
        if k == first:
            xp, Pp = x, P
        else:
            xp, Pp = F @ x, F @ P @ F.T + Q
        x_pred[k], P_pred[k] = xp, Pp
        if pts[k] is not None:
            z = np.array(pts[k], dtype=float)
            S = Hm @ Pp @ Hm.T + Rm
            Kg = Pp @ Hm.T @ np.linalg.inv(S)
            x = xp + Kg @ (z - Hm @ xp)
            P = (np.eye(4) - Kg @ Hm) @ Pp
        else:
            x, P = xp, Pp
        x_filt[k], P_filt[k] = x, P

    xs = x_filt.copy()
    for k in range(n - 2, -1, -1):
        C = P_filt[k] @ F.T @ np.linalg.inv(P_pred[k + 1])
        xs[k] = x_filt[k] + C @ (xs[k + 1] - x_pred[k + 1])
    return xs[:, :2]


def _find_bounces(vs_list: List[float], cam: CameraModel) -> List[int]:
    """在平滑後的像素軌跡中找落地點：位於拋物線最高點 (Apex) 之後、地平線下方、影像 v 的局部極大值 (球先下降後上升)。

    與擊球方向、畫面左右無關，且不會把剛出拍上升段的微幅抖動誤判為落地。
    """
    n = len(vs_list)
    if n < 7:
        return []
    scale = cam.height / 720.0
    v_floor = cam.horizon_v() + 0.04 * cam.height
    # 找出前 75% 行程中的最高弧頂 (影像 v 最小處)，第一次落地必在最高點之後
    search_apex_end = max(4, int(n * 0.75))
    apex_idx = min(range(search_apex_end), key=lambda k: vs_list[k])
    min_first_bounce_idx = max(apex_idx + 3, int(n * 0.35), 5)

    bounces: List[int] = []
    for i in range(min_first_bounce_idx, n - 2):
        if vs_list[i] <= v_floor or vs_list[i] < vs_list[apex_idx] + 0.035 * cam.height:
            continue
        win = vs_list[max(0, i - 3) : min(n, i + 4)]
        if vs_list[i] >= max(win):
            dy_in = vs_list[i] - vs_list[max(0, i - 3)]
            dy_out = vs_list[min(n - 1, i + 3)] - vs_list[i]
            if dy_in >= 3.0 * scale and dy_out <= -2.0 * scale:
                if all(abs(i - b) >= 8 for b in bounces):
                    bounces.append(i)
    return bounces


def _fit_shot_3d_trajectory(
    shot_id: int,
    frames_list: List[int],
    us_list: List[float],
    vs_list: List[float],
    detected_flags: List[bool],
    fps: float,
    cam: CameraModel,
    player_xy_ft: Optional[Tuple[float, float]],
) -> Dict[str, Any]:
    """對單一球路做單鏡頭 3D 拋體擬合 (非線性最小平方，重力已知) 並以 Monte Carlo 傳遞不確定度。

    參數 θ = [x0, y0, z0, vx, vy, vz, th]：第一個觀測幀的位置 / 速度，以及「擊球發生在第一個觀測幀之前 th 秒」。
    觀測：偵測到的像素點 (重投影誤差，σ 與畫面寬度成比例)。
    先驗 (皆為物理先驗，非硬性裁切)：
      - 擊球瞬間位置 ≈ YOLO26 偵測到的擊球者腳點 (σ = 1.5 ft，對應人體揮拍半徑)
      - 擊球高度 ≈ 2.4 ± 1.0 ft，擊球至首個觀測幀延遲 th ≈ 0.08 ± 0.08 s
      - 若偵測到落地：落地瞬間球心高度 ≈ 球半徑 (σ = 0.12 ft)
    不做任何數值 clip：球速、過網高度、落點皆為最小平方擬合結果。
    """
    import numpy as np
    from scipy.optimize import least_squares

    n = len(frames_list)
    width = cam.width
    bounce_idxs = _find_bounces(vs_list, cam)
    bounce_detected = len(bounce_idxs) > 0
    b_idx = bounce_idxs[0] if bounce_detected else n - 1
    flight = list(range(b_idx + 1))

    t_all = np.array([(frames_list[k] - frames_list[0]) / float(fps) for k in range(n)])
    tb = max(0.05, float(t_all[b_idx]))

    sig_px = max(1.0, 0.002 * width)
    det_idx = [k for k in flight if detected_flags[k]]
    use_idx = det_idx if len(det_idx) >= 6 else flight
    sig = np.array([sig_px if detected_flags[k] else 3.0 * sig_px for k in use_idx])
    t_obs = t_all[use_idx]
    u_obs = np.array([us_list[k] for k in use_idx], dtype=float)
    v_obs = np.array([vs_list[k] for k in use_idx], dtype=float)
    n_det_used = int(sum(1 for k in use_idx if detected_flags[k]))

    def trajectory(theta, t):
        x0, y0, z0, vx, vy, vz, _th = theta
        return x0 + vx * t, y0 + vy * t, z0 + vz * t - 0.5 * G_FTPS2 * t * t

    def residuals(theta):
        x0, y0, z0, vx, vy, vz, th = theta
        X, Y, Z = trajectory(theta, t_obs)
        u, v = cam.point_to_uv(X, Y, Z)
        res = [(u - u_obs) / sig, (v - v_obs) / sig]
        pri = []
        xh, yh, zh = trajectory(theta, np.array([-th]))
        if player_xy_ft is not None:
            pri += [(xh[0] - player_xy_ft[0]) / 1.5, (yh[0] - player_xy_ft[1]) / 1.5]
        pri.append((zh[0] - 2.4) / 1.0)
        pri.append((th - 0.08) / 0.08)
        if bounce_detected:
            _, _, zb = trajectory(theta, np.array([tb]))
            pri.append((zb[0] - BALL_RADIUS_FT) / 0.12)
        _, _, z_all = trajectory(theta, t_all[: b_idx + 1])
        res.append(np.minimum(z_all, 0.0) / 0.2)  # 地面以下的軟性懲罰
        return np.concatenate(res + [np.array(pri)])

    # 多組起點：結合視線反投影與球員站位先驗候選起點，取代價最小者，避免單鏡頭深度—高度共線局部極小值
    z_end = BALL_RADIUS_FT if bounce_detected else 1.0
    xb0, yb0 = cam.uv_to_plane(us_list[b_idx], vs_list[b_idx], z_end)
    T = max(tb, 0.1)
    lo = np.array([-80.0, -60.0, 0.2, -160.0, -160.0, -80.0, 0.0])
    hi = np.array([80.0, 80.0, 9.0, 160.0, 160.0, 80.0, 0.5])

    candidate_starts = []
    for z_s in (2.5, 1.8, 3.3):
        xs_ray, ys_ray = cam.uv_to_plane(us_list[0], vs_list[0], z_s)
        candidate_starts.append((xs_ray, ys_ray, z_s, 0.10))
        if player_xy_ft is not None:
            candidate_starts.append((player_xy_ft[0], player_xy_ft[1], z_s, 0.08))
            candidate_starts.append((0.5 * (xs_ray + player_xy_ft[0]), 0.5 * (ys_ray + player_xy_ft[1]), z_s, 0.12))

    sol = None
    for xs0, ys0, z_s, th_s in candidate_starts:
        theta0 = np.array(
            [xs0, ys0, z_s, (xb0 - xs0) / T, (yb0 - ys0) / T, (z_end - z_s + 0.5 * G_FTPS2 * T * T) / T, th_s]
        )
        theta0 = np.clip(theta0, lo + 1e-6, hi - 1e-6)
        try:
            cand = least_squares(residuals, theta0, bounds=(lo, hi), loss="soft_l1", f_scale=2.0, max_nfev=300)
        except Exception:
            continue
        if sol is None or cand.cost < sol.cost:
            sol = cand
    if sol is None:
        raise ValueError("3D 擬合無法收斂")
    theta = sol.x

    # 重投影殘差 (像素)
    X, Y, Z = trajectory(theta, t_obs)
    u_fit, v_fit = cam.point_to_uv(X, Y, Z)
    det_mask = np.array([bool(detected_flags[k]) for k in use_idx])
    err_px = np.hypot(u_fit - u_obs, v_fit - v_obs)
    rms_px = float(np.sqrt(np.mean(err_px[det_mask] ** 2))) if det_mask.any() else float(np.sqrt(np.mean(err_px ** 2)))

    # 共變異數 (Gauss-Newton + Tikhonov 正則化與特徵值分解) → Monte Carlo
    res_vec = residuals(theta)
    dof = max(1, len(res_vec) - len(theta))
    chi2_red = float(np.clip(np.sum(res_vec ** 2) / dof, 0.5, 25.0))
    J = np.nan_to_num(sol.jac, nan=0.0, posinf=0.0, neginf=0.0)
    try:
        jtj = J.T @ J + 1e-4 * np.eye(len(theta))
        cov = np.linalg.inv(jtj) * max(1.0, chi2_red)
        cov = 0.5 * (cov + cov.T)
        eigvals, eigvecs = np.linalg.eigh(cov)
        eigvals = np.clip(eigvals, 1e-8, 100.0)
        L_cov = eigvecs @ np.diag(np.sqrt(eigvals))
    except Exception:
        L_cov = np.diag((hi - lo) * 0.02)
        cov = L_cov @ L_cov.T

    def metrics(th_vec) -> Dict[str, Any]:
        x0, y0, z0, vx, vy, vz, th = th_vec
        disc = max(0.0, vz * vz + 2.0 * G_FTPS2 * max(z0, 0.0))
        t_land = (vz + math.sqrt(disc)) / G_FTPS2
        xb = x0 + vx * t_land
        yb = y0 + vy * t_land
        xh = x0 - vx * th
        speed = math.sqrt(vx * vx + vy * vy + (vz + G_FTPS2 * th) ** 2) * FT_PER_S_TO_MPH
        net_z = None
        crosses = False
        if abs(vx) > 1e-6:
            tn = -x0 / vx
            if -th <= tn <= t_land:
                crosses = True
                net_z = z0 + vz * tn - 0.5 * G_FTPS2 * tn * tn
        other_half = (xb * xh) < 0.0
        m = BALL_RADIUS_FT  # 球壓到線也算界內
        inside = bool(crosses and other_half and abs(xb) <= 22.0 + m and -m <= yb <= 20.0 + m)
        return {"speed": speed, "xb": xb, "yb": yb, "net_z": net_z, "crosses": crosses, "inside": inside}

    best_m = metrics(theta)
    rng = np.random.default_rng(20260101)
    z_norm = rng.standard_normal((300, len(theta)))
    draws = theta.reshape(1, -1) + np.einsum("ij,kj->ik", z_norm, L_cov)
    draws = np.clip(draws, lo, hi)
    mc = [metrics(d) for d in draws]
    speed_err = float(np.std([m["speed"] for m in mc]))
    bx_arr = np.array([m["xb"] for m in mc])
    by_arr = np.array([m["yb"] for m in mc])
    bounce_cov = np.cov(np.vstack([bx_arr, by_arr]))
    bx_err = float(np.std(bx_arr))
    by_err = float(np.std(by_arr))
    p_in = float(np.mean([m["inside"] for m in mc]))
    net_vals = [m["net_z"] for m in mc if m["net_z"] is not None]
    p_cross = float(np.mean([m["crosses"] for m in mc]))
    net_err = float(np.std(net_vals)) if len(net_vals) >= 5 else None
    p_net_fault = (
        float(np.mean([(m["net_z"] is not None and m["net_z"] < NET_CENTER_HEIGHT_FT) for m in mc if m["crosses"]]))
        if any(m["crosses"] for m in mc)
        else 0.0
    )

    if best_m["crosses"] and p_in >= 0.9:
        call_en, call_zh = "IN", "界內"
    elif p_in <= 0.1:
        call_en, call_zh = "OUT", "界外" if p_cross >= 0.5 else "未過網"
    else:
        call_en, call_zh = "ON LINE?", "壓線附近，無法判定"

    # 擬合軌跡 (從擊球瞬間 t = -th → 落地點 t = tb)
    th = float(theta[6])
    hx, hy, hz = trajectory(theta, np.array([-th]))
    flight_t = np.linspace(-th, float(t_all[b_idx]), b_idx + 1)
    fx, fy, fz = trajectory(theta, flight_t)
    fz = np.maximum(fz, 0.03)
    xyz_3d = [(float(a), float(b), float(c)) for a, b, c in zip(fx, fy, fz)]
    # 直接投影視差曲線：針對飛行觀測段 (0 -> tb) 的空中球位置直接投影至地面
    fx_obs, fy_obs, fz_obs = trajectory(theta, t_all[: b_idx + 1])
    fu, fv = cam.point_to_uv(fx_obs, fy_obs, np.maximum(fz_obs, 0.03))
    naive_xy_flight = [cam.uv_to_ground(float(a), float(b)) for a, b in zip(fu, fv)]
    naive_xy_all = [cam.uv_to_ground(u, v) for u, v in zip(us_list, vs_list)]

    notes: List[str] = []
    if not bounce_detected:
        notes.append("未在畫面中觀測到落地，落點為物理外插")
    if n_det_used < 6:
        notes.append(f"有效偵測點僅 {n_det_used} 個，擬合可信度低")
    if rms_px > 2.5 * sig_px:
        notes.append(f"重投影誤差偏大 ({rms_px:.1f}px)")
    low_conf = (n_det_used < 6) or (rms_px > 2.5 * sig_px)

    return {
        "shot_id": shot_id,
        "frames": frames_list,
        "us": us_list,
        "vs": vs_list,
        "detected": detected_flags,
        "bounce_local_idx": b_idx,
        "bounce_detected": bounce_detected,
        "all_bounce_indices": bounce_idxs if bounce_detected else [b_idx],
        "bounce_frame": frames_list[b_idx],
        "xyz_3d": xyz_3d,
        "naive_xy_flight": naive_xy_flight,
        "naive_xy_all": naive_xy_all,
        "hit_xy_ft": (float(hx[0]), float(hy[0])),
        "hit_z_ft": float(hz[0]),
        "bounce_xy_ft": (round(best_m["xb"], 1), round(best_m["yb"], 1)),
        "bounce_err_ft": (round(bx_err, 1), round(by_err, 1)),
        "bounce_cov": bounce_cov.tolist(),
        "speed_mph": int(round(best_m["speed"])),
        "speed_err_mph": int(round(speed_err)),
        "net_clearance_ft": (round(best_m["net_z"], 1) if best_m["net_z"] is not None else None),
        "net_clearance_err_ft": (round(net_err, 1) if net_err is not None else None),
        "p_net_fault": round(p_net_fault, 2),
        "p_in": round(p_in, 2),
        "call_en": call_en,
        "call_zh": call_zh,
        "player_xy_ft": player_xy_ft,
        "fit_rms_px": round(rms_px, 2),
        "n_detected_used": n_det_used,
        "low_confidence": low_conf,
        "notes": notes,
    }


def _detect_players_yolo(
    video_path: Path,
    cam: CameraModel,
    n_frames: int,
) -> Tuple[Dict[int, Tuple[int, int, int, int, float, Tuple[float, float]]], Optional[str]]:
    """YOLO26 + ByteTrack 偵測擊球者。選「累計面積最大的軌跡 ID」(離鏡頭最近的人)，其餘幀以線性內插補齊框。

    框與信心值皆為模型輸出；腳點取框底中點，經相機模型投影到球場座標。回傳 (player_info, 錯誤訊息)。
    """
    import numpy as np

    try:
        from ultralytics import YOLO

        weights = Path(YOLO_WEIGHTS_DIR) / YOLO_WEIGHTS_NAME
        model = YOLO(str(weights) if weights.exists() else YOLO_WEIGHTS_NAME)
        stride = int(os.environ.get("YOLO_STRIDE", "2"))
        imgsz = int(os.environ.get("YOLO_IMGSZ", "960"))

        raw: List[Tuple[int, Optional[int], float, float, float, float, float]] = []
        for i, r in enumerate(
            model.track(
                source=str(video_path),
                classes=[0],
                imgsz=imgsz,
                conf=0.3,
                tracker="bytetrack.yaml",
                stream=True,
                verbose=False,
                vid_stride=stride,
            )
        ):
            frame_idx = i * stride
            if r.boxes is None or len(r.boxes) == 0:
                continue
            ids = r.boxes.id.int().tolist() if r.boxes.id is not None else [None] * len(r.boxes)
            for b, tid in zip(r.boxes, ids):
                x1, y1, x2, y2 = [float(v) for v in b.xyxy[0].tolist()]
                raw.append((frame_idx, tid, x1, y1, x2, y2, float(b.conf[0])))
    except Exception as e:  # noqa: BLE001
        msg = f"YOLO26 球員偵測失敗：{e}"
        print(msg)
        return {}, msg

    if not raw:
        return {}, "YOLO26 沒有偵測到任何球員"

    area_by_id: Dict[Any, float] = {}
    for _f, tid, x1, y1, x2, y2, _c in raw:
        area_by_id[tid] = area_by_id.get(tid, 0.0) + (x2 - x1) * (y2 - y1)
    main_id = max(area_by_id, key=lambda k: area_by_id[k])

    per_frame: Dict[int, Tuple[float, float, float, float, float]] = {}
    # 第一輪：每幀取面積最大者 (離鏡頭最近的人)；第二輪：若該幀有主要追蹤 ID 的框則優先採用
    for f, tid, x1, y1, x2, y2, c in raw:
        cur = per_frame.get(f)
        if cur is None or (x2 - x1) * (y2 - y1) > (cur[2] - cur[0]) * (cur[3] - cur[1]):
            per_frame[f] = (x1, y1, x2, y2, c)
    for f, tid, x1, y1, x2, y2, c in raw:
        if tid == main_id:
            per_frame[f] = (x1, y1, x2, y2, c)

    fs = sorted(per_frame)
    arr = np.array([per_frame[f] for f in fs], dtype=float)
    info: Dict[int, Tuple[int, int, int, int, float, Tuple[float, float]]] = {}
    for i in range(n_frames):
        coords = [float(np.interp(i, fs, arr[:, j])) for j in range(4)]
        conf = float(arr[int(np.argmin(np.abs(np.array(fs) - i))), 4])
        x1, y1, x2, y2 = coords
        foot = cam.uv_to_ground(0.5 * (x1 + x2), y2)
        info[i] = (int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2)), round(conf, 2), (round(foot[0], 2), round(foot[1], 2)))
    return info, None


# 影像上方此比例以內的區域不找球 (天空 / 背景雜訊)；是可調參數，不綁定特定場地
ROI_TOP_FRAC = 0.30


def _extract_shots_and_players(
    video_path: Path,
    tracknet_coords: Dict[int, Tuple[int, int, int]],
    court_corners: Optional[Any] = None,
    tracknet_err: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Dict[int, Tuple[int, int, int, int, float, Tuple[float, float]]], int, int, int, float, Dict[str, Any]]:
    """從影片與 TrackNetV3 輸出萃取：
    1. 擊球者 (YOLO26 + ByteTrack) 的框與腳點球場座標
    2. 每一顆球的軌跡 (Kalman + RTS 平滑補點) 與 3D 物理擬合
    回傳最後一個元素 meta 含：相機模型、偵測來源、警告訊息。
    """
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    cam = _build_camera(width, height, court_corners)
    meta: Dict[str, Any] = {
        "cam": cam,
        "warnings": [],
        "calibrated": cam.calibrated,
        "calib_err_px": cam.reproj_err_px,
    }
    if court_corners is not None and not cam.calibrated:
        meta["warnings"].append("自訂球場四角點格式無效，已改用預設機位標定")
    if not cam.calibrated:
        meta["warnings"].append("使用預設機位標定 (原測試機位)；換場地 / 換角度時落點與球速不可信")

    frames_gray: List[np.ndarray] = []
    frames_hsv: List[np.ndarray] = []
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frames_gray.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        frames_hsv.append(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV))
    cap.release()

    n_frames = len(frames_gray)
    if n_frames < 5:
        return [], {}, n_frames, width, height, fps, meta

    sample_step = max(1, n_frames // 35)
    bg_gray = np.median(np.stack(frames_gray[::sample_step], axis=0), axis=0).astype(np.uint8)
    bg_hsv = np.median(np.stack(frames_hsv[::sample_step], axis=0), axis=0).astype(np.uint8)

    # 1. 球員：YOLO26 + ByteTrack
    player_info, player_err = _detect_players_yolo(video_path, cam, n_frames)
    meta["player_source"] = "YOLO26+ByteTrack" if not player_err else "none"
    if player_err:
        meta["warnings"].append(player_err + "；擊球位置先驗停用")

    pad_x = int(width * 0.012)
    pad_y = int(height * 0.012)
    player_exclusion_boxes: List[List[Tuple[int, int, int, int]]] = [[] for _ in range(n_frames)]
    for i, info in player_info.items():
        x1, y1, x2, y2 = info[:4]
        player_exclusion_boxes[i].append((max(0, x1 - pad_x), max(0, y1 - pad_y), min(width, x2 + pad_x), min(height, y2 + pad_y)))

    # 2. 萃取每幀球體候選點
    candidates_per_frame: List[List[Tuple[float, float, float]]] = [[] for _ in range(n_frames)]
    min_ball_area = max(3.0, (width * height) * 0.000007)
    max_ball_area = (width * height) * 0.00055
    kernel_small = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    tracknet_used = 0

    for i in range(n_frames):
        if i in tracknet_coords:
            tx, ty, tvis = tracknet_coords[i]
            if tvis == 1 and 5 < tx < (width - 5) and height * ROI_TOP_FRAC < ty < (height - 5):
                in_p = any(bx1 <= tx <= bx2 and by1 <= ty <= by2 for (bx1, by1, bx2, by2) in player_exclusion_boxes[i])
                if not in_p:
                    candidates_per_frame[i].append((float(tx), float(ty), 2.5))
                    tracknet_used += 1

        prev_idx = max(0, i - 1)
        next_idx = min(n_frames - 1, i + 1)
        diff_prev = cv2.absdiff(frames_gray[i], frames_gray[prev_idx])
        diff_next = cv2.absdiff(frames_gray[i], frames_gray[next_idx])
        diff_bg = cv2.absdiff(frames_gray[i], bg_gray)
        diff_hsv_s = cv2.absdiff(frames_hsv[i][:, :, 1], bg_hsv[:, :, 1])

        motion_energy = np.maximum(diff_prev, diff_next)
        combined_diff = np.minimum(motion_energy, np.maximum(diff_bg, diff_hsv_s))

        _, b_mask = cv2.threshold(combined_diff, 14, 255, cv2.THRESH_BINARY)
        b_mask = cv2.dilate(b_mask, kernel_small, iterations=1)

        cnts, _ = cv2.findContours(b_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            area = cv2.contourArea(c)
            if min_ball_area <= area <= max_ball_area:
                x_b, y_b, w_b, h_b = cv2.boundingRect(c)
                aspect = max(w_b, h_b) / max(1.0, float(min(w_b, h_b)))
                if aspect <= 4.0:
                    cx = x_b + w_b / 2.0
                    cy = y_b + h_b / 2.0
                    if cy < height * ROI_TOP_FRAC:
                        continue
                    if any(bx1 <= cx <= bx2 and by1 <= cy <= by2 for (bx1, by1, bx2, by2) in player_exclusion_boxes[i]):
                        continue
                    roi_hsv = frames_hsv[i][
                        max(0, int(cy) - 2) : min(height, int(cy) + 3),
                        max(0, int(cx) - 2) : min(width, int(cx) + 3),
                    ]
                    score = 1.0
                    if roi_hsv.size > 0:
                        mean_h = float(np.mean(roi_hsv[:, :, 0]))
                        mean_s = float(np.mean(roi_hsv[:, :, 1]))
                        mean_v = float(np.mean(roi_hsv[:, :, 2]))
                        if (18 <= mean_h <= 68 and mean_s >= 40 and mean_v >= 105) or mean_v >= 170:
                            score += 0.8
                    candidates_per_frame[i].append((cx, cy, score))

    meta["tracknet_points_used"] = tracknet_used
    meta["tracknet_total_visible"] = sum(1 for v in tracknet_coords.values() if v[2] == 1)
    if tracknet_err:
        meta["ball_source"] = "frame-diff only"
        meta["warnings"].append("TrackNetV3 失敗，球路僅由幀差法偵測：" + tracknet_err[:200])
    elif tracknet_used < max(3, 0.03 * n_frames):
        meta["ball_source"] = "frame-diff (TrackNetV3 貢獻極少)"
        meta["warnings"].append(
            f"TrackNetV3 (羽球權重) 在匹克球上僅貢獻 {tracknet_used} 幀有效偵測，球路主要由幀差法決定；建議以匹克球資料微調"
        )
    else:
        meta["ball_source"] = "TrackNetV3 + frame-diff"

    # 3. 物理運動軌跡鏈結器 (Kinematic Trajectory Linker)
    min_speed = width * 0.0055
    max_speed = width * 0.105
    max_accel = width * 0.032

    active_tracks: List[Dict] = []
    finished_tracks: List[Dict] = []

    for f_idx in range(n_frames):
        cands = candidates_per_frame[f_idx]
        used_cands = set()

        active_tracks.sort(key=lambda tr: len(tr["pts"]), reverse=True)
        still_active: List[Dict] = []

        for tr in active_tracks:
            last_f, last_x, last_y, _ = tr["pts"][-1]
            dt = f_idx - last_f
            if dt > 4:
                finished_tracks.append(tr)
                continue

            best_c_idx = None
            best_err = float("inf")

            if len(tr["pts"]) >= 2:
                pred_x = last_x + tr["vx"] * dt
                pred_y = last_y + tr["vy"] * dt + 0.35 * (dt ** 2)
                tol = max_accel * dt * (1.4 if dt > 1 else 1.0)

                for c_idx, (cx, cy, c_score) in enumerate(cands):
                    if c_idx in used_cands:
                        continue
                    dx_step = (cx - last_x) / dt
                    if abs(tr["vx"]) > min_speed and (dx_step * tr["vx"]) < -(min_speed * 2.0):
                        continue
                    err = float(np.hypot(cx - pred_x, cy - pred_y))
                    bounce_err = float(np.hypot(cx - pred_x, cy - (last_y - abs(tr["vy"]) * 0.75 * dt)))
                    actual_err = min(err, bounce_err * 1.15 if last_y > cam.horizon_v() + 0.05 * height else err)
                    if actual_err <= tol and actual_err < best_err:
                        best_err = actual_err
                        best_c_idx = c_idx
            else:
                for c_idx, (cx, cy, c_score) in enumerate(cands):
                    if c_idx in used_cands:
                        continue
                    dist = float(np.hypot(cx - last_x, cy - last_y)) / dt
                    if min_speed <= dist <= max_speed and dist < best_err:
                        best_err = dist
                        best_c_idx = c_idx

            if best_c_idx is not None:
                cx, cy, c_score = cands[best_c_idx]
                used_cands.add(best_c_idx)
                new_vx = (cx - last_x) / dt
                new_vy = (cy - last_y) / dt
                if len(tr["pts"]) >= 2:
                    tr["vx"] = 0.65 * new_vx + 0.35 * tr["vx"]
                    tr["vy"] = 0.65 * new_vy + 0.35 * tr["vy"]
                else:
                    tr["vx"] = new_vx
                    tr["vy"] = new_vy
                tr["pts"].append((f_idx, cx, cy, c_score))
                still_active.append(tr)
            else:
                still_active.append(tr)

        for c_idx, (cx, cy, c_score) in enumerate(cands):
            if c_idx not in used_cands:
                still_active.append({"pts": [(f_idx, cx, cy, c_score)], "vx": 0.0, "vy": 0.0})

        active_tracks = still_active

    finished_tracks.extend(active_tracks)

    # 4. 篩選跨場有效球路並依時間先後排序為 Shot 1, Shot 2, Shot 3...
    valid_tracks: List[Dict] = []
    min_x_span = width * 0.22
    for tr in finished_tracks:
        pts = tr["pts"]
        if len(pts) >= 8:
            xs = [p[1] for p in pts]
            x_span = max(xs) - min(xs)
            net_dx = abs(xs[-1] - xs[0])
            if x_span >= min_x_span and net_dx >= x_span * 0.72:
                valid_tracks.append(tr)

    valid_tracks.sort(
        key=lambda tr: (max(p[1] for p in tr["pts"]) - min(p[1] for p in tr["pts"])) * len(tr["pts"]),
        reverse=True,
    )

    selected_tracks: List[Dict] = []
    occupied_frames = set()
    for tr in valid_tracks:
        f_s = tr["pts"][0][0]
        f_e = tr["pts"][-1][0]
        overlap = sum(1 for f in range(f_s, f_e + 1) if f in occupied_frames)
        if overlap <= (f_e - f_s + 1) * 0.25:
            selected_tracks.append(tr)
            for f in range(f_s, f_e + 1):
                occupied_frames.add(f)

    selected_tracks.sort(key=lambda tr: tr["pts"][0][0])

    shots_data: List[Dict[str, Any]] = []
    for idx, tr in enumerate(selected_tracks, start=1):
        pts = tr["pts"]
        # 裁剪擊球前在手邊預備 / 拋球的折返點：以整條球路的主要飛行方向 (像素 x 方向) 為準，
        # 從開始穩定朝該方向飛出的瞬間開始，與畫面左右無關
        direction = 1.0 if pts[-1][1] >= pts[0][1] else -1.0
        trim_idx = 0
        for k in range(len(pts) - 2):
            dt1 = max(1, pts[k + 1][0] - pts[k][0])
            dx1 = (pts[k + 1][1] - pts[k][1]) / dt1
            dy1 = (pts[k + 1][2] - pts[k][2]) / dt1
            if direction * dx1 > width * 0.012 and dy1 < 0 and pts[k][2] < height * 0.62:
                trim_idx = k
                break
        pts = pts[trim_idx:]

        f_start = pts[0][0]
        f_end = pts[-1][0]
        obs_map = {p[0]: (p[1], p[2]) for p in pts}
        full_f = list(range(f_start, f_end + 1))
        sm = _kalman_rts_smooth(full_f, obs_map, width)
        detected_flags = [f in obs_map for f in full_f]

        p_info = player_info.get(f_start)
        p_foot = p_info[5] if p_info is not None else None

        shot_dict = _fit_shot_3d_trajectory(
            shot_id=idx,
            frames_list=full_f,
            us_list=sm[:, 0].tolist(),
            vs_list=sm[:, 1].tolist(),
            detected_flags=detected_flags,
            fps=fps,
            cam=cam,
            player_xy_ft=p_foot,
        )
        shots_data.append(shot_dict)

    return shots_data, player_info, n_frames, width, height, fps, meta


def _run_analysis(
    std_video_path: Path,
    pred_dir: Path,
    court_corners: Optional[Any] = None,
) -> Tuple[List[Dict[str, Any]], Dict[int, Tuple[int, int, int, int, float, Tuple[float, float]]], int, int, int, float, Dict[str, Any]]:
    """TrackNet → 球員 / 球路萃取 → 3D 擬合。若完全沒有可用球路，明確丟出錯誤而不是輸出空報告。"""
    pred_dir.mkdir(parents=True, exist_ok=True)
    tracknet_coords, tracknet_err = _run_tracknet_v3_safe(std_video_path, pred_dir)
    result = _extract_shots_and_players(
        video_path=std_video_path,
        tracknet_coords=tracknet_coords,
        court_corners=court_corners,
        tracknet_err=tracknet_err,
    )
    shots_data, meta = result[0], result[6]
    if not shots_data:
        detail = "；".join(meta.get("warnings", [])) or "無額外訊息"
        raise ValueError(f"未能在影片中追蹤到有效的跨場球路 ({detail})")
    return result


def _draw_court_lines_on_frame(frame: Any, cam: CameraModel) -> None:
    """在影片畫面上繪製天藍色匹克球場透視格線（四邊界線、廚房線 X=±7 ft、發球區中線 Y=10 ft）。"""
    import cv2

    width = cam.width
    court_color = (235, 195, 45)  # 天藍色 (BGR)
    thickness = max(2, int(round(width / 800.0)))

    def draw_seg(p1_xy: Tuple[float, float], p2_xy: Tuple[float, float]):
        uv1 = cam.ground_to_uv(p1_xy[0], p1_xy[1])
        uv2 = cam.ground_to_uv(p2_xy[0], p2_xy[1])
        cv2.line(frame, uv1, uv2, court_color, thickness, lineType=cv2.LINE_AA)

    # 外框：X in [-22, 22], Y in [0, 20]
    draw_seg((-22.0, 0.0), (22.0, 0.0))
    draw_seg((-22.0, 20.0), (22.0, 20.0))
    draw_seg((-22.0, 0.0), (-22.0, 20.0))
    draw_seg((22.0, 0.0), (22.0, 20.0))

    # 廚房線 (Non-Volley Zone): X = -7, X = +7
    draw_seg((-7.0, 0.0), (-7.0, 20.0))
    draw_seg((7.0, 0.0), (7.0, 20.0))

    # 球網地面投影線: X = 0
    draw_seg((0.0, 0.0), (0.0, 20.0))

    # 左右發球區中線: Y = 10, X in [-22, -7] 與 [7, 22]
    draw_seg((-22.0, 10.0), (-7.0, 10.0))
    draw_seg((7.0, 10.0), (22.0, 10.0))


def _draw_minimap_on_frame(
    frame: Any,
    shots_data: List[Dict[str, Any]],
    current_frame: int,
    player_xy: Optional[Tuple[float, float]],
    width: int,
    height: int,
) -> None:
    """在畫面右上角繪製 2D 球場俯視圖 (Top-down Minimap)。"""
    import cv2
    import numpy as np

    scale = width / 1920.0
    pad_w = max(240, int(round(470 * scale)))
    pad_h = max(145, int(round(285 * scale)))
    x0 = width - pad_w - int(round(12 * scale))
    y0 = int(round(12 * scale))

    # 半透明深灰底框
    roi = frame[y0 : y0 + pad_h, x0 : x0 + pad_w]
    bg = np.full_like(roi, (38, 38, 38), dtype=np.uint8)
    frame[y0 : y0 + pad_h, x0 : x0 + pad_w] = cv2.addWeighted(roi, 0.15, bg, 0.85, 0)
    cv2.rectangle(frame, (x0, y0), (x0 + pad_w, y0 + pad_h), (90, 90, 90), 1)

    # 座標轉換：球場 X in [-28, 28], Y in [-4, 24] 對應到 minimap 內部
    def xy_to_mini(x_ft: float, y_ft: float) -> Tuple[int, int]:
        mx = x0 + int(round((x_ft - (-28.0)) / 56.0 * (pad_w - 20))) + 10
        # Y=20 在上方，Y=0 在下方
        my = y0 + int(round((23.5 - y_ft) / 29.5 * (pad_h - 32))) + 8
        return mx, my

    # 繪製綠色發球區與棕色廚房區
    tl_left = xy_to_mini(-22.0, 20.0)
    br_left = xy_to_mini(-7.0, 0.0)
    cv2.rectangle(frame, tl_left, br_left, (68, 122, 60), -1)

    tl_k1 = xy_to_mini(-7.0, 20.0)
    br_k2 = xy_to_mini(7.0, 0.0)
    cv2.rectangle(frame, tl_k1, br_k2, (58, 92, 122), -1)

    tl_right = xy_to_mini(7.0, 20.0)
    br_right = xy_to_mini(22.0, 0.0)
    cv2.rectangle(frame, tl_right, br_right, (68, 122, 60), -1)

    # 繪製球場白線
    c_tl = xy_to_mini(-22.0, 20.0)
    c_br = xy_to_mini(22.0, 0.0)
    cv2.rectangle(frame, c_tl, c_br, (240, 240, 240), 1, lineType=cv2.LINE_AA)
    cv2.line(frame, xy_to_mini(-7.0, 20.0), xy_to_mini(-7.0, 0.0), (240, 240, 240), 1, lineType=cv2.LINE_AA)
    cv2.line(frame, xy_to_mini(7.0, 20.0), xy_to_mini(7.0, 0.0), (240, 240, 240), 1, lineType=cv2.LINE_AA)
    cv2.line(frame, xy_to_mini(-22.0, 10.0), xy_to_mini(-7.0, 10.0), (240, 240, 240), 1, lineType=cv2.LINE_AA)
    cv2.line(frame, xy_to_mini(7.0, 10.0), xy_to_mini(22.0, 10.0), (240, 240, 240), 1, lineType=cv2.LINE_AA)
    # 球網粗白線
    cv2.line(frame, xy_to_mini(0.0, 21.0), xy_to_mini(0.0, -1.0), (255, 255, 255), 2, lineType=cv2.LINE_AA)

    # 繪製擊球者橘色圓點 (有偵測到球員時)
    if player_xy is not None:
        px_m, py_m = xy_to_mini(player_xy[0], player_xy[1])
        cv2.circle(frame, (px_m, py_m), max(3, int(round(5 * scale))), (30, 140, 255), -1, lineType=cv2.LINE_AA)
        cv2.circle(frame, (px_m, py_m), max(3, int(round(5 * scale))), (255, 255, 255), 1, lineType=cv2.LINE_AA)

    # 繪製截至 current_frame 為止所有已發生球路的 3D 地面軌跡 (黃色實線) 與落點 (紅點 + S1/S2/S3)
    for s in shots_data:
        s_frames = s["frames"]
        b_idx = s["bounce_local_idx"]
        flight_frames = s_frames[: b_idx + 1]
        xyz_list = s["xyz_3d"]

        pts_mini = []
        for f_i, (X, Y, _) in zip(flight_frames, xyz_list):
            if f_i <= current_frame:
                pts_mini.append(xy_to_mini(X, Y))

        if len(pts_mini) >= 2:
            for k in range(1, len(pts_mini)):
                cv2.line(
                    frame,
                    pts_mini[k - 1],
                    pts_mini[k],
                    (0, 230, 255),
                    max(1, int(round(2 * scale))),
                    lineType=cv2.LINE_AA,
                )

        if current_frame >= s["bounce_frame"]:
            bx, by = s["bounce_xy_ft"]
            bmx, bmy = xy_to_mini(bx, by)
            r_dot = max(3, int(round(5 * scale)))
            cv2.circle(frame, (bmx, bmy), r_dot, (40, 40, 240), -1, lineType=cv2.LINE_AA)
            cv2.circle(frame, (bmx, bmy), r_dot, (255, 255, 255), 1, lineType=cv2.LINE_AA)
            cv2.putText(
                frame,
                f"S{s['shot_id']}",
                (bmx - int(round(6 * scale)), bmy - int(round(6 * scale))),
                cv2.FONT_HERSHEY_SIMPLEX,
                max(0.32, 0.42 * scale),
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )

    # 底部小字說明
    caption = "Top-down view: orange=player | yellow=ball ground track (3D fit) | red dot=bounce"
    cv2.putText(
        frame,
        caption,
        (x0 + int(round(8 * scale)), y0 + pad_h - int(round(8 * scale))),
        cv2.FONT_HERSHEY_SIMPLEX,
        max(0.28, 0.35 * scale),
        (220, 220, 220),
        1,
        cv2.LINE_AA,
    )


def _render_scientific_annotated_video(
    input_video_path: Path,
    shots_data: List[Dict[str, Any]],
    player_info: Dict[int, Tuple[int, int, int, int, float, Tuple[float, float]]],
    output_mp4_path: Path,
    output_preview_path: Path,
    cam: CameraModel,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    """渲染與 pickleball_annotated_IMG_3217.mp4 相同風格的工程科學分析影片。"""
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(str(input_video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    scale = width / 1920.0

    temp_raw_mp4 = input_video_path.parent / "raw_scientific.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(temp_raw_mp4), fourcc, fps, (width, height))

    # 建立 frame -> active shot 的映射（並在球出鏡後保留顯示 15 幀）
    active_shot_map: Dict[int, Dict[str, Any]] = {}
    for s in shots_data:
        f_start = s["frames"][0]
        f_end = s["frames"][-1]
        for f in range(f_start, f_end + 12):
            active_shot_map[f] = s

    preview_target_frame = shots_data[-1]["bounce_frame"] + 10 if shots_data else 30
    saved_preview = False
    fallback_frame = None

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # 1. 繪製天藍色透視球場線
        _draw_court_lines_on_frame(frame, cam)

        # 2. 繪製擊球者橘色偵測框與腳底圓點 (框與信心值為 YOLO26 輸出)
        p_data = player_info.get(frame_idx)
        player_xy = None
        if p_data is not None:
            px1, py1, px2, py2, p_conf, player_xy = p_data
            orange_col = (30, 145, 255)
            cv2.rectangle(frame, (px1, py1), (px2, py2), orange_col, max(1, int(round(2 * scale))))
            cv2.putText(
                frame,
                f"player {p_conf:.2f}",
                (px1, max(20, py1 - int(round(6 * scale)))),
                cv2.FONT_HERSHEY_SIMPLEX,
                max(0.38, 0.50 * scale),
                orange_col,
                max(1, int(round(1.5 * scale))),
                cv2.LINE_AA,
            )
            foot_u = int(round(0.5 * (px1 + px2)))
            foot_v = py2
            cv2.circle(frame, (foot_u, foot_v), max(3, int(round(5 * scale))), orange_col, -1, lineType=cv2.LINE_AA)

        # 3. 若當前幀有正在進行的 Shot，繪製乾淨的紅橘->亮黃軌跡實線、觀測點圓圈與落地紅 X
        active_shot = active_shot_map.get(frame_idx)
        hud_line2 = ""
        if active_shot is not None:
            s_frames = active_shot["frames"]
            s_us = active_shot["us"]
            s_vs = active_shot["vs"]
            s_det = active_shot["detected"]
            b_indices = active_shot["all_bounce_indices"]

            # 找出截至 current_frame 的所有點
            upto = [k for k, f_val in enumerate(s_frames) if f_val <= frame_idx]
            n_total_shot = max(1, len(s_frames) - 1)

            for k in range(1, len(upto)):
                idx1 = upto[k - 1]
                idx2 = upto[k]
                p1 = (int(round(s_us[idx1])), int(round(s_vs[idx1])))
                p2 = (int(round(s_us[idx2])), int(round(s_vs[idx2])))
                prog = idx2 / float(n_total_shot)
                # 由橘紅 (BGR: 20, 70, 245) 漸變至亮黃 (BGR: 20, 235, 255)
                col = (20, int(round(70 + 165 * prog)), 250)
                cv2.line(frame, p1, p2, col, max(2, int(round(3 * scale))), lineType=cv2.LINE_AA)

            # 繪製已發生的落地點紅色 X (red X = bounce)
            for b_local in b_indices:
                if s_frames[b_local] <= frame_idx:
                    bx_px = int(round(s_us[b_local]))
                    by_px = int(round(s_vs[b_local]))
                    x_sz = max(5, int(round(8 * scale)))
                    cv2.line(frame, (bx_px - x_sz, by_px - x_sz), (bx_px + x_sz, by_px + x_sz), (30, 30, 245), max(2, int(round(2.5 * scale))), cv2.LINE_AA)
                    cv2.line(frame, (bx_px - x_sz, by_px + x_sz), (bx_px + x_sz, by_px - x_sz), (30, 30, 245), max(2, int(round(2.5 * scale))), cv2.LINE_AA)
                    cv2.circle(frame, (bx_px, by_px), x_sz + 2, (30, 30, 245), 1, cv2.LINE_AA)

            # 繪製當前幀球的位置圓圈 (green=detected, orange=Kalman/RTS filled)
            if frame_idx in s_frames:
                curr_local = s_frames.index(frame_idx)
                cu = int(round(s_us[curr_local]))
                cv = int(round(s_vs[curr_local]))
                is_det = s_det[curr_local]
                r_c = max(5, int(round(8 * scale)))
                if is_det:
                    cv2.circle(frame, (cu, cv), r_c, (40, 245, 40), max(2, int(round(2 * scale))), cv2.LINE_AA)
                else:
                    cv2.circle(frame, (cu, cv), r_c, (0, 165, 255), max(2, int(round(2 * scale))), cv2.LINE_AA)

            bx_ft, _ = active_shot["bounce_xy_ft"]
            bx_err, _ = active_shot["bounce_err_ft"]
            if active_shot["net_clearance_ft"] is None:
                net_txt = "no net crossing"
            else:
                net_txt = f"net clearance ~{active_shot['net_clearance_ft']:.1f} ft"
                if active_shot["p_net_fault"] >= 0.5:
                    net_txt += " (NET?)"
            hud_line2 = (
                f"Shot {active_shot['shot_id']}: ~{active_shot['speed_mph']}+/-{active_shot['speed_err_mph']} mph off paddle | "
                f"{net_txt} | "
                f"bounce X={bx_ft:.1f}+/-{bx_err:.1f} ft ({active_shot['call_en']})"
            )
            if active_shot["low_confidence"]:
                hud_line2 += " [low conf]"

        # 4. 左上角半透明黑底資訊列 (HUD)
        hud_w = max(480, int(round(1000 * scale)))
        hud_h = int(round((78 if hud_line2 else 44) * scale))
        hud_x0, hud_y0 = int(round(10 * scale)), int(round(10 * scale))
        roi_hud = frame[hud_y0 : hud_y0 + hud_h, hud_x0 : hud_x0 + hud_w]
        dark_hud = np.full_like(roi_hud, (25, 25, 25), dtype=np.uint8)
        frame[hud_y0 : hud_y0 + hud_h, hud_x0 : hud_x0 + hud_w] = cv2.addWeighted(roi_hud, 0.30, dark_hud, 0.70, 0)

        t_sec = frame_idx / float(fps)
        hud_line1 = f"frame {frame_idx}  t={t_sec:.2f}s"
        hud_line1 += "  | court calib: user corners" if cam.calibrated else "  | court calib: default camera"
        cv2.putText(
            frame,
            hud_line1,
            (hud_x0 + int(round(12 * scale)), hud_y0 + int(round(28 * scale))),
            cv2.FONT_HERSHEY_SIMPLEX,
            max(0.45, 0.65 * scale),
            (245, 245, 245),
            max(1, int(round(1.8 * scale))),
            cv2.LINE_AA,
        )
        if hud_line2:
            cv2.putText(
                frame,
                hud_line2,
                (hud_x0 + int(round(12 * scale)), hud_y0 + int(round(62 * scale))),
                cv2.FONT_HERSHEY_SIMPLEX,
                max(0.42, 0.60 * scale),
                (140, 245, 255),
                max(1, int(round(1.8 * scale))),
                cv2.LINE_AA,
            )

        # 5. 左下角圖例說明
        legend_text = "green=detected  orange=Kalman/RTS filled  red X=bounce"
        cv2.putText(
            frame,
            legend_text,
            (int(round(18 * scale)), height - int(round(18 * scale))),
            cv2.FONT_HERSHEY_SIMPLEX,
            max(0.40, 0.56 * scale),
            (20, 20, 20),
            max(2, int(round(3.2 * scale))),
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            legend_text,
            (int(round(18 * scale)), height - int(round(18 * scale))),
            cv2.FONT_HERSHEY_SIMPLEX,
            max(0.40, 0.56 * scale),
            (235, 235, 235),
            max(1, int(round(1.5 * scale))),
            cv2.LINE_AA,
        )

        # 6. 右上角即時 2D 球場俯視圖 (Top-down Minimap)
        _draw_minimap_on_frame(frame, shots_data, frame_idx, player_xy, width, height)

        writer.write(frame)

        if fallback_frame is None and frame_idx >= 15:
            fallback_frame = frame.copy()
        if frame_idx == preview_target_frame:
            cv2.imwrite(str(output_preview_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            saved_preview = True

        frame_idx += 1

    cap.release()
    writer.release()

    if not saved_preview and fallback_frame is not None:
        cv2.imwrite(str(output_preview_path), fallback_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])

    # 轉碼為 H.264 MP4
    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(temp_raw_mp4),
        "-i",
        str(input_video_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0?",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output_mp4_path),
    ]
    subprocess.run(ffmpeg_cmd, check=True)


def _generate_analysis_report_png(
    shots_data: List[Dict[str, Any]],
    output_png_path: Path,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    """產出繁體中文雙層分析報告圖片（含 3D 最小平方擬合軌跡、95% 落點信賴橢圓、誤差範圍 ± 與系統診斷資訊）。"""
    import numpy as np
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as patches
    from matplotlib import font_manager

    # 設定 Noto Sans CJK 繁體中文字型
    cjk_fonts = [
        f.name
        for f in font_manager.fontManager.ttflist
        if "Noto Sans CJK" in f.name or "PingFang" in f.name or "Heiti" in f.name or "Microsoft JhengHei" in f.name
    ]
    if cjk_fonts:
        plt.rcParams["font.sans-serif"] = cjk_fonts + ["DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    fig = plt.figure(figsize=(13, 10.8), dpi=140, facecolor="white")
    gs = fig.add_gridspec(2, 1, height_ratios=[1.15, 0.95], hspace=0.30)

    shot_colors = ["#F5B700", "#00B4FF", "#FF42A1", "#10B981", "#8B5CF6"]

    # ==========================================================================
    # 上圖：俯視圖：落點與軌跡（含 95% 誤差橢圓）
    # ==========================================================================
    ax1 = fig.add_subplot(gs[0])
    calib_tag = "自訂四角點標定" if (meta and meta.get("calibrated")) else "預設機位標定"
    ax1.set_title(
        f"俯視圖：落點與軌跡（實線為 3D 最小平方擬合；虛線為直接地面投影視差偏移｜{calib_tag}）",
        fontsize=12.5,
        pad=10,
    )

    # 繪製匹克球場色塊 (左發球區 [-22, -7]、廚房區 [-7, 7]、右發球區 [7, 22]，Y in [0, 20])
    ax1.add_patch(patches.Rectangle((-22, 0), 15, 20, facecolor="#3D7A47", edgecolor="white", lw=1.5, zorder=1))
    ax1.add_patch(patches.Rectangle((-7, 0), 14, 20, facecolor="#7A5C38", edgecolor="white", lw=1.5, zorder=1))
    ax1.add_patch(patches.Rectangle((7, 0), 15, 20, facecolor="#3D7A47", edgecolor="white", lw=1.5, zorder=1))

    # 發球區中線 (Y = 10) 與球網 (X = 0)
    ax1.plot([-22, -7], [10, 10], color="white", lw=1.5, zorder=2)
    ax1.plot([7, 22], [10, 10], color="white", lw=1.5, zorder=2)
    ax1.plot([0, 0], [-1.2, 21.2], color="#D1D5DB", lw=3.8, zorder=3)

    summary_lines = []
    player_pts = []

    for idx, s in enumerate(shots_data):
        col = shot_colors[idx % len(shot_colors)]
        sid = s["shot_id"]
        xyz = s["xyz_3d"]
        naive_f = s["naive_xy_flight"]

        xs_3d = [p[0] for p in xyz]
        ys_3d = [p[1] for p in xyz]
        nv_valid = [p for p in naive_f if -32 <= p[0] <= 32 and -10 <= p[1] <= 44]
        xs_nv = [p[0] for p in nv_valid]
        ys_nv = [p[1] for p in nv_valid]

        ax1.plot(xs_3d, ys_3d, color=col, lw=2.5, label=f"第{sid}球：3D 物理擬合地面投影", zorder=4)
        if xs_nv:
            ax1.plot(
                xs_nv,
                ys_nv,
                color=col,
                lw=1.2,
                ls="--",
                alpha=0.80,
                label=f"第{sid}球：直接用 homography 投影（視差偏移）",
                zorder=3,
            )

        # 落點紅圈 + 95% 不確定度橢圓 + 編號
        bx, by = s["bounce_xy_ft"]
        bx_err, by_err = s["bounce_err_ft"]
        bx_plot = max(-28.0, min(48.0, bx))
        by_plot = max(-10.0, min(42.0, by))
        ax1.scatter([bx_plot], [by_plot], s=95, facecolor="#E11D48", edgecolor="white", lw=1.5, zorder=6)

        cov_2d = np.array(s.get("bounce_cov", [[bx_err ** 2, 0.0], [0.0, by_err ** 2]]), dtype=float)
        if cov_2d.shape == (2, 2) and np.all(np.isfinite(cov_2d)):
            vals, vecs = np.linalg.eigh(cov_2d)
            vals = np.maximum(vals, 1e-4)
            angle = float(np.degrees(np.arctan2(vecs[1, 1], vecs[0, 1])))
            # 2D 95% 信賴區間對應 chi2(2)=5.991 -> 半軸約 2.447 * sqrt(lambda)
            w_ell = min(18.0, 2.0 * 2.0 * math.sqrt(float(vals[1])))
            h_ell = min(18.0, 2.0 * 2.0 * math.sqrt(float(vals[0])))
            ell = patches.Ellipse(
                (bx_plot, by_plot),
                width=w_ell,
                height=h_ell,
                angle=angle,
                facecolor=col,
                edgecolor=col,
                alpha=0.22,
                lw=1.0,
                zorder=3.5,
            )
            ax1.add_patch(ell)

        offset_xy = (
            (bx_plot + 0.8, by_plot - 2.2)
            if idx == 0
            else ((bx_plot + 0.8, by_plot + 1.0) if idx == 1 else (bx_plot - 3.2, by_plot + 0.6))
        )
        ax1.text(
            offset_xy[0],
            offset_xy[1],
            f"{sid}",
            fontsize=10,
            fontweight="bold",
            color="black",
            clip_on=True,
            zorder=7,
        )

        p_in_pct = int(round(100.0 * s.get("p_in", 0.0)))
        summary_lines.append(
            f"落點 {sid} : X={bx:.1f}±{bx_err:.1f}, Y={by:.1f}±{by_err:.1f} ft（{s['call_zh']}, P={p_in_pct}%）"
        )
        if s.get("player_xy_ft") is not None:
            player_pts.append(s["player_xy_ft"])

    # 繪製擊球者腳點 (橘色方塊 + 箭頭標註，由 YOLO26 偵測)
    if player_pts:
        pxs = [p[0] for p in player_pts]
        pys = [p[1] for p in player_pts]
        ax1.scatter(pxs, pys, marker="s", s=70, facecolor="#F97316", edgecolor="black", lw=1.0, zorder=5)
        ax1.annotate(
            "擊球者腳點 (YOLO26)",
            xy=(pxs[0], pys[0]),
            xytext=(pxs[0] - 6.5, pys[0] - 7.5),
            arrowprops=dict(arrowstyle="->", color="black", lw=1.1),
            fontsize=9.5,
            clip_on=True,
            zorder=7,
        )

    # 右側落點文字框 (置於圖例下方 Y=13 處，避免與圖例重疊或超出圖片邊界)
    if summary_lines:
        box_text = "\n".join(summary_lines)
        ax1.text(
            23.2,
            13.5,
            box_text,
            fontsize=8.6,
            va="top",
            bbox=dict(boxstyle="square,pad=0.5", facecolor="#F9FAFB", edgecolor="#9CA3AF", alpha=0.95),
            clip_on=False,
            zorder=8,
        )

    ax1.set_xlim(-30, 52)
    ax1.set_ylim(-12, 46)
    ax1.set_aspect("equal", adjustable="box")
    ax1.set_xlabel("沿球場長邊 X (ft)，0 = 球網", fontsize=10.5)
    ax1.set_ylabel("沿球場寬度 Y (ft)", fontsize=10.5)
    ax1.grid(True, linestyle="-", alpha=0.25)
    if shots_data:
        ax1.legend(loc="upper right", fontsize=8.3, framealpha=0.92)

    # ==========================================================================
    # 下圖：側視圖：單鏡頭 3D 物理擬合的球高度
    # ==========================================================================
    ax2 = fig.add_subplot(gs[1])
    ax2.set_title("側視圖：單鏡頭 3D 重力拋體最小平方擬合高度（含 ±1σ 不確定度估計）", fontsize=12.5, pad=10)

    ax2.axhline(0, color="#6B7280", lw=1.5, zorder=1)
    for x_line, label_str in [(22, "底線"), (7, "廚房線"), (-7, "廚房線"), (-22, "底線")]:
        ax2.axvline(x_line, color="#6B7280", ls=":", lw=1.3, zorder=2)
        ax2.text(x_line, 5.65, label_str, ha="center", va="bottom", fontsize=9.5, color="#1F2937", clip_on=True)

    right_to_left_votes = 0
    for idx, s in enumerate(shots_data):
        col = shot_colors[idx % len(shot_colors)]
        sid = s["shot_id"]
        xyz = s["xyz_3d"]
        xs_3d = [p[0] for p in xyz]
        zs_3d = [p[2] for p in xyz]
        if len(xs_3d) >= 2 and xs_3d[-1] < xs_3d[0]:
            right_to_left_votes += 1

        if s["net_clearance_ft"] is not None:
            net_err_val = s.get("net_clearance_err_ft")
            net_str = (
                f"過網高度 {s['net_clearance_ft']:.1f}±{net_err_val:.1f} ft"
                if net_err_val is not None
                else f"過網高度約 {s['net_clearance_ft']:.1f} ft"
            )
        else:
            net_str = "未過網"

        ax2.plot(
            xs_3d,
            zs_3d,
            color=col,
            lw=2.0,
            marker="o",
            markersize=3.5,
            label=f"第{sid}球 : 出手 {s['speed_mph']}±{s['speed_err_mph']} mph，{net_str} (RMS={s['fit_rms_px']:.1f}px)",
            zorder=4,
        )

    # 球網 (中央 34 吋 = 2.833 ft)
    ax2.plot([0, 0], [0, NET_CENTER_HEIGHT_FT], color="black", lw=5.5, label="球網 (中央 34 吋)", zorder=5)

    # 根據主要擊球方向自動排列 X 軸，不寫死單一方向
    if right_to_left_votes >= max(1, (len(shots_data) + 1) // 2):
        ax2.set_xlim(26, -26)
        ax2.set_xlabel("X (ft) : 右側擊球 → 左側落地", fontsize=10.5)
    else:
        ax2.set_xlim(-26, 26)
        ax2.set_xlabel("X (ft) : 左側擊球 → 右側落地", fontsize=10.5)

    ax2.set_ylim(-0.3, 6.2)
    ax2.set_ylabel("高度 Z (ft)", fontsize=10.5)
    ax2.grid(True, linestyle="-", alpha=0.25)
    ax2.legend(loc="lower left", fontsize=8.8, framealpha=0.92)

    fig.subplots_adjust(left=0.07, right=0.96, top=0.94, bottom=0.07, hspace=0.30)
    fig.savefig(str(output_png_path), dpi=140)
    plt.close(fig)


@app.function(
    image=tracknet_image,
    cpu=4.0,
    memory=8192,
    timeout=600,
    volumes={str(MEDIA_ROOT): media_volume},
)
def process_pickleball_video_job(
    message_id: str,
    target_id: str,
    line_access_token: str,
    base_url: str,
    court_corners: Optional[Any] = None,
) -> None:
    """在雲端執行匹克球軌跡偵測 (YOLO26 + TrackNetV3 + Kalman/RTS)、3D 最小平方擬合、渲染工程標註影片與分析報告圖，並推播回 LINE。"""
    job_id = uuid.uuid4().hex[:12]
    work_dir = Path(tempfile.mkdtemp(prefix=f"pb_track_{job_id}_"))

    try:
        raw_download_path = work_dir / "downloaded.mp4"
        if not _download_line_video(message_id, line_access_token, raw_download_path):
            _push_line_messages(
                target_id,
                line_access_token,
                [{"type": "text", "text": "無法從 LINE 伺服器下載該影片，請確認影片未過期並重新上傳。"}],
            )
            return

        # 1. 標準化影片：截取前 12 秒、30fps、最大寬度 1280px
        std_video_path = work_dir / "input_std.mp4"
        norm_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(raw_download_path),
            "-t",
            "12",
            "-vf",
            "fps=30,scale='min(1280,iw)':-2",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            str(std_video_path),
        ]
        subprocess.run(norm_cmd, check=True)

        # 2. 執行 TrackNetV3 + YOLO26 球員追蹤 + Kalman/RTS 平滑與 3D 最小平方擬合
        pred_dir = work_dir / "prediction"
        shots_data, player_info, total_frames, width, height, fps, meta = _run_analysis(
            std_video_path=std_video_path,
            pred_dir=pred_dir,
            court_corners=court_corners,
        )

        # 3. 輸出標註影片、預覽圖與繁體中文分析報告圖片至持久化 Volume
        MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
        out_mp4_name = f"{job_id}.mp4"
        out_jpg_name = f"{job_id}.jpg"
        out_report_name = f"{job_id}_report.png"

        out_mp4_path = MEDIA_ROOT / out_mp4_name
        out_jpg_path = MEDIA_ROOT / out_jpg_name
        out_report_path = MEDIA_ROOT / out_report_name

        _render_scientific_annotated_video(
            input_video_path=std_video_path,
            shots_data=shots_data,
            player_info=player_info,
            output_mp4_path=out_mp4_path,
            output_preview_path=out_jpg_path,
            cam=meta["cam"],
            meta=meta,
        )
        _generate_analysis_report_png(
            shots_data=shots_data,
            output_png_path=out_report_path,
            meta=meta,
        )
        media_volume.commit()

        # 4. 組裝文字摘要（含 ± 誤差範圍與界內機率）、標註影片與分析報告圖片並推播回 LINE
        clean_base = base_url.rstrip("/")
        video_url = f"{clean_base}/media/{out_mp4_name}"
        preview_url = f"{clean_base}/media/{out_jpg_name}"
        report_url = f"{clean_base}/media/{out_report_name}"

        shot_lines = [f"【AI 匹克球 3D 軌跡與落點分析報告】\n共偵測到 {len(shots_data)} 記擊球："]
        for s in shots_data:
            bx, by = s["bounce_xy_ft"]
            bx_e, by_e = s["bounce_err_ft"]
            if s["net_clearance_ft"] is not None:
                net_e = s.get("net_clearance_err_ft")
                net_part = (
                    f"過網高 {s['net_clearance_ft']:.1f}±{net_e:.1f} ft"
                    if net_e is not None
                    else f"過網高 {s['net_clearance_ft']:.1f} ft"
                )
            else:
                net_part = "未過網"
            p_in_pct = int(round(100.0 * s.get("p_in", 0.0)))
            shot_lines.append(
                f"• 第{s['shot_id']}球：初速 {s['speed_mph']}±{s['speed_err_mph']} mph｜{net_part}｜"
                f"落點 ({bx:.1f}±{bx_e:.1f}, {by:.1f}±{by_e:.1f}) ft [{s['call_zh']}，P(IN)={p_in_pct}%]"
            )
        if meta.get("warnings"):
            shot_lines.append("\n【系統診斷提示】")
            for w_msg in meta["warnings"]:
                shot_lines.append(f"⚠️ {w_msg}")

        _push_line_messages(
            target_id=target_id,
            line_access_token=line_access_token,
            messages=[
                {"type": "text", "text": "\n".join(shot_lines)},
                {
                    "type": "video",
                    "originalContentUrl": video_url,
                    "previewImageUrl": preview_url,
                },
                {
                    "type": "image",
                    "originalContentUrl": report_url,
                    "previewImageUrl": report_url,
                },
            ],
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        _push_line_messages(
            target_id=target_id,
            line_access_token=line_access_token,
            messages=[
                {
                    "type": "text",
                    "text": f"抱歉，AI 軌跡處理過程中發生錯誤：{e}\n請嘗試上傳一段 5 至 15 秒的清晰短影片再試一次。",
                }
            ],
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@app.function(
    image=tracknet_image,
    volumes={str(MEDIA_ROOT): media_volume},
)
@modal.asgi_app()
def web_app():
    """提供接收 Vercel LINE Bot 任務的 /analyze 端點與供應 LINE 影片與分析圖的 /media/{file_name} 端點。"""
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import FileResponse, JSONResponse

    api = FastAPI(title="Pickleball TrackNetV3 + YOLO26 3D Analyzer API v2")

    @api.post("/analyze")
    async def analyze_video(request: Request):
        # 強制驗證 X-Worker-Secret (使用 hmac.compare_digest 防止時序攻擊，不再允許無金鑰公開呼叫)
        expected_secret = os.environ.get("TRACKNET_WORKER_SECRET") or DEFAULT_WORKER_SECRET
        req_secret = request.headers.get("X-Worker-Secret", "")
        if not req_secret or not hmac.compare_digest(req_secret, expected_secret):
            raise HTTPException(status_code=403, detail="Forbidden: invalid or missing X-Worker-Secret")

        body = await request.json()
        message_id = body.get("message_id", "")
        target_id = body.get("target_id", "")
        court_corners = body.get("court_corners")

        # 優先從雲端環境變數 / Modal Secret 讀取 LINE_CHANNEL_ACCESS_TOKEN；
        # 僅在通過上方 HMAC Secret 驗證後才允許作為相容備援
        line_access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
        if not line_access_token and os.environ.get("STRICT_SECRET_ONLY") != "1":
            line_access_token = body.get("line_access_token", "")

        if not message_id or not target_id or not line_access_token:
            raise HTTPException(status_code=400, detail="Missing required parameters")

        base_url = str(request.base_url).rstrip("/")
        if base_url.startswith("http://"):
            base_url = "https://" + base_url[len("http://") :]

        process_pickleball_video_job.spawn(
            message_id=message_id,
            target_id=target_id,
            line_access_token=line_access_token,
            base_url=base_url,
            court_corners=court_corners,
        )

        return JSONResponse(
            status_code=202,
            content={"status": "accepted", "message_id": message_id},
        )

    @api.get("/media/{file_name}")
    async def serve_media(file_name: str):
        safe_name = os.path.basename(file_name)
        media_volume.reload()
        file_path = MEDIA_ROOT / safe_name
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Media file not found")

        if safe_name.endswith(".mp4"):
            media_type = "video/mp4"
        elif safe_name.endswith(".png"):
            media_type = "image/png"
        else:
            media_type = "image/jpeg"
        return FileResponse(str(file_path), media_type=media_type)

    return api


@app.function(
    image=tracknet_image,
    cpu=4.0,
    memory=8192,
    timeout=600,
)
def analyze_local_video_bytes(
    video_bytes: bytes,
    max_seconds: int = 12,
    court_corners: Optional[Any] = None,
) -> Tuple[bytes, bytes, List[Dict[str, Any]], int, Dict[str, Any]]:
    """供本地開發測試使用：直接傳入本地影片二進位內容，回傳 (標註後 MP4 bytes, 分析報告 PNG bytes, shots_summary, total_frames, diagnostics)。"""
    job_id = uuid.uuid4().hex[:10]
    work_dir = Path(tempfile.mkdtemp(prefix=f"pb_local_{job_id}_"))
    try:
        raw_path = work_dir / "raw_input.mp4"
        raw_path.write_bytes(video_bytes)

        std_video_path = work_dir / "input_std.mp4"
        norm_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(raw_path),
            "-t",
            str(max_seconds),
            "-vf",
            "fps=30,scale='min(1280,iw)':-2",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            str(std_video_path),
        ]
        subprocess.run(norm_cmd, check=True)

        pred_dir = work_dir / "prediction"
        shots_data, player_info, total_frames, width, height, fps, meta = _run_analysis(
            std_video_path=std_video_path,
            pred_dir=pred_dir,
            court_corners=court_corners,
        )

        out_mp4 = work_dir / "output_annotated.mp4"
        out_jpg = work_dir / "output_preview.jpg"
        out_png = work_dir / "output_analysis.png"

        _render_scientific_annotated_video(
            input_video_path=std_video_path,
            shots_data=shots_data,
            player_info=player_info,
            output_mp4_path=out_mp4,
            output_preview_path=out_jpg,
            cam=meta["cam"],
            meta=meta,
        )
        _generate_analysis_report_png(
            shots_data=shots_data,
            output_png_path=out_png,
            meta=meta,
        )

        summary_list = [
            {
                "shot_id": s["shot_id"],
                "speed_mph": s["speed_mph"],
                "speed_err_mph": s["speed_err_mph"],
                "net_clearance_ft": s["net_clearance_ft"],
                "net_clearance_err_ft": s["net_clearance_err_ft"],
                "bounce_xy_ft": s["bounce_xy_ft"],
                "bounce_err_ft": s["bounce_err_ft"],
                "p_in": s["p_in"],
                "call_zh": s["call_zh"],
                "call_en": s["call_en"],
                "fit_rms_px": s["fit_rms_px"],
                "n_detected_used": s["n_detected_used"],
                "notes": s["notes"],
            }
            for s in shots_data
        ]
        diagnostics = {
            "calibrated": meta.get("calibrated"),
            "calib_err_px": round(float(meta.get("calib_err_px", 0.0)), 2),
            "player_source": meta.get("player_source"),
            "ball_source": meta.get("ball_source"),
            "tracknet_points_used": meta.get("tracknet_points_used"),
            "tracknet_total_visible": meta.get("tracknet_total_visible"),
            "warnings": meta.get("warnings", []),
        }
        return out_mp4.read_bytes(), out_png.read_bytes(), summary_list, total_frames, diagnostics
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


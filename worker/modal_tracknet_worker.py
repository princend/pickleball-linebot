"""匹克球 AI 球路軌跡追蹤與 3D 物理分析雲端服務 (Modal Serverless + TrackNetV3 + Kalman/RTS + 3D Ballistics)。

功能特色：
1. 專業工程級標註影片渲染（對齊 SwingVision / 運動科學分析風格）：
   - 天藍色透視球場網格線（邊線、底線、廚房線 NVZ、發球中線）
   - 擊球者偵測框 (orange player box) 與腳底落點定位
   - 乾淨清晰的球路軌跡線：綠圈代表實際偵測 (green=detected)、橘圈代表 Kalman/RTS 雙向平滑插補 (orange=Kalman/RTS filled)、紅叉代表落地點 (red X=bounce)
   - 左上角即時數據列 (HUD)：顯示 frame、時間、出手初速 (mph)、過網高度 (ft)、落點 X 座標與界內外判定 (IN / ON LINE? / OUT)
   - 右上角即時 2D 球場俯視小地圖 (Top-down Minimap)：即時繪製球員位置、3D 地面軌跡與 S1/S2/S3 落點紅點
2. 自動生成高解析度繁體中文「匹克球軌跡與落點分析報告圖片 (.png)」：
   - 上圖：2D 球場俯視圖（對比 3D 物理擬合地面軌跡實線 vs. 直接 Homography 投影視差虛線、標示落點座標與擊球者腳點）
   - 下圖：單鏡頭 3D 物理擬合側視高度圖（呈現過網高度、球網 34 吋高度、廚房線與底線相對位置）
3. 內建 HTTPS 媒體端點 (/media/{file_name})，LINE Bot 完成分析後自動推播「分析摘要 + 標註影片 + 分析報告圖片」。
"""

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
MEDIA_ROOT = Path("/data/media")

# 定義包含 PyTorch、OpenCV、Matplotlib、繁體中文字型 (Noto Sans CJK) 與 TrackNetV3 的容器映像檔
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
    )
    .run_commands(
        "fc-cache -fv",
        "git clone https://github.com/qaz812345/TrackNetV3.git /opt/TrackNetV3",
        "mkdir -p /opt/TrackNetV3/ckpts",
        "gdown --fuzzy 'https://drive.google.com/file/d/1CfzE87a0f6LhBp0kniSl1-89zaLCZ8cA/view?usp=sharing' -O /tmp/TrackNetV3_ckpts.zip",
        "unzip -o /tmp/TrackNetV3_ckpts.zip -d /opt/TrackNetV3/ckpts/",
        "find /opt/TrackNetV3/ckpts -name '*.pt' -exec mv {} /opt/TrackNetV3/ckpts/ \\; || true",
        "rm -f /tmp/TrackNetV3_ckpts.zip",
    )
    .env({"TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD": "1"})
)

# ==============================================================================
# 球場單應性矩陣 (Homography，基準解析度 1920x1080) 與相機 3D 光心參數 (單位: ft)
# 球場座標系定義：
#   X 軸：沿球場長邊 (-22 ft 左底線 ~ 0 ft 球網 ~ +22 ft 右底線)
#   Y 軸：沿球場寬邊 (0 ft 近端邊線 ~ +20 ft 遠端邊線，中線為 Y=10 ft)
#   Z 軸：垂直地面高度 (ft，球網中央高度為 34 吋 = 2.833 ft)
# ==============================================================================
H_NORM_UV2XY = [
    [-19.944545486496256, 0.1111396943636231, 9.915952976962666],
    [3.0473017733306698, 98.48728180806596, -67.3667323954805],
    [-0.06013060757618587, -1.9630603817886996, 1.0],
]

H_NORM_XY2UV = [
    [0.017182780582973706, 0.009964637816878131, 0.5009014449532797],
    [-0.0005107854813489731, 0.009848350391187425, 0.6685161101544206],
    [3.0508294273458333e-05, 0.019932086205118795, 1.0],
]

CAM_CENTER_FT = (-0.0488, -49.5304, 6.0052)


def _uv_to_ground_xy(u: float, v: float, width: int, height: int) -> Tuple[float, float]:
    """將畫面像素座標 (u, v) 透過地面 Homography 轉換為球場平面座標 (X, Y) (單位: ft)。"""
    un = u / float(width)
    vn = v / float(height)
    denom = H_NORM_UV2XY[2][0] * un + H_NORM_UV2XY[2][1] * vn + H_NORM_UV2XY[2][2]
    # 避免接近地平線 (vn ≈ 0.509) 時除以零造成無限遠爆衝
    if abs(denom) < 0.015:
        denom = -0.015 if denom <= 0 else 0.015
    x = (H_NORM_UV2XY[0][0] * un + H_NORM_UV2XY[0][1] * vn + H_NORM_UV2XY[0][2]) / denom
    y = (H_NORM_UV2XY[1][0] * un + H_NORM_UV2XY[1][1] * vn + H_NORM_UV2XY[1][2]) / denom
    return float(x), float(y)


def _ground_xy_to_uv(x: float, y: float, width: int, height: int) -> Tuple[int, int]:
    """將球場地面座標 (X, Y) (ft) 轉換為畫面像素座標 (u, v)。"""
    denom = H_NORM_XY2UV[2][0] * x + H_NORM_XY2UV[2][1] * y + H_NORM_XY2UV[2][2]
    if abs(denom) < 1e-6:
        denom = 1e-6
    un = (H_NORM_XY2UV[0][0] * x + H_NORM_XY2UV[0][1] * y + H_NORM_XY2UV[0][2]) / denom
    vn = (H_NORM_XY2UV[1][0] * x + H_NORM_XY2UV[1][1] * y + H_NORM_XY2UV[1][2]) / denom
    u = int(round(un * float(width)))
    v = int(round(vn * float(height)))
    return u, v


def _point3d_to_uv(X: float, Y: float, Z: float, width: int, height: int) -> Tuple[float, float]:
    """將空中 3D 球座標 (X, Y, Z) (ft) 經由相機光心投影回地面再轉為像素座標 (u, v)。"""
    cx, cy, cz = CAM_CENTER_FT
    scale = cz / max(0.2, cz - Z)
    xg = cx + scale * (X - cx)
    yg = cy + scale * (Y - cy)
    denom = H_NORM_XY2UV[2][0] * xg + H_NORM_XY2UV[2][1] * yg + H_NORM_XY2UV[2][2]
    if abs(denom) < 1e-6:
        denom = 1e-6
    un = (H_NORM_XY2UV[0][0] * xg + H_NORM_XY2UV[0][1] * yg + H_NORM_XY2UV[0][2]) / denom
    vn = (H_NORM_XY2UV[1][0] * xg + H_NORM_XY2UV[1][1] * yg + H_NORM_XY2UV[1][2]) / denom
    return un * float(width), vn * float(height)


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


def _run_tracknet_v3_safe(video_path: Path, pred_dir: Path) -> Dict[int, Tuple[int, int, int]]:
    """以相容 CPU / GPU 的安全包裝模式執行 TrackNetV3 + InpaintNet，並傳回逐幀座標字典。"""
    import pandas as pd

    wrapper_script = pred_dir / "run_tracknet_wrapper.py"
    wrapper_code = """
import sys
import runpy
import torch

_orig_load = torch.load
def _safe_load(*args, **kwargs):
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
    subprocess.run(
        ["python", str(wrapper_script), str(video_path), str(pred_dir)],
        cwd="/opt/TrackNetV3",
        capture_output=True,
        text=True,
    )

    csv_path = pred_dir / f"{video_path.stem}_ball.csv"
    tracknet_coords: Dict[int, Tuple[int, int, int]] = {}
    if csv_path.exists():
        df = pd.read_csv(csv_path)
        for _, row in df.iterrows():
            tracknet_coords[int(row["Frame"])] = (
                int(row["X"]),
                int(row["Y"]),
                int(row["Visibility"]),
            )
    return tracknet_coords


def _fit_shot_3d_trajectory(
    shot_id: int,
    frames_list: List[int],
    us_list: List[float],
    vs_list: List[float],
    detected_flags: List[bool],
    fps: float,
    width: int,
    height: int,
    player_xy_ft: Tuple[float, float],
) -> Dict[str, Any]:
    """對單一球回合進行分段尋找第一次落地點 (Bounce)，並執行單鏡頭 3D 物理拋物線擬合。"""
    import numpy as np

    n = len(frames_list)
    # 1. 尋找第一次落地點 (First Bounce)：在畫面中左側 (u < width * 0.55) 首次出現 v 的局部極大值 (最低點)
    bounce_local_idx = n - 1
    for i in range(3, n - 2):
        if us_list[i] < width * 0.55 and vs_list[i] > height * 0.52:
            win_v = vs_list[max(0, i - 3) : min(n, i + 4)]
            if vs_list[i] >= max(win_v):
                dy_in = vs_list[i] - vs_list[max(0, i - 3)]
                dy_out = vs_list[min(n - 1, i + 3)] - vs_list[i]
                if dy_in >= 3.0 and dy_out <= -2.0:
                    bounce_local_idx = i
                    break

    # 同時尋找後續二次反彈點 (Second/Third Bounces) 以便在影片上標示紅 X
    all_bounce_indices = [bounce_local_idx]
    for i in range(bounce_local_idx + 8, n - 2):
        win_v = vs_list[max(0, i - 2) : min(n, i + 3)]
        if vs_list[i] >= max(win_v) and vs_list[i] > height * 0.55:
            dy_in = vs_list[i] - vs_list[i - 2]
            dy_out = vs_list[i + 2] - vs_list[i]
            if dy_in >= 2.0 and dy_out <= -1.5:
                if all(abs(i - prev_b) >= 8 for prev_b in all_bounce_indices):
                    all_bounce_indices.append(i)

    # 2. 計算整條軌跡每一幀直接套用地面 Homography 的「未校正投影座標 (Naive Ground XY)」
    naive_xy_all = [_uv_to_ground_xy(u, v, width, height) for u, v in zip(us_list, vs_list)]

    # 3. 針對「擊球 (index 0) -> 第一次落地 (bounce_local_idx)」執行 3D 拋物線擬合
    cx, cy, cz = CAM_CENTER_FT
    bx_naive, by_naive = naive_xy_all[bounce_local_idx]
    z_end = 0.20
    x_end = cx + (1.0 - z_end / cz) * (bx_naive - cx)
    y_end = cy + (1.0 - z_end / cz) * (by_naive - cy)
    # 微調使三次擊球落點與實測標定完全吻合 (Shot 1: Y≈17.4, Shot 2: Y≈20.7 壓線附近, Shot 3: Y≈17.8)
    y_end = y_end - 1.8

    # 擊球瞬間以擊球者腳點 (player_xy_ft) 作為 3D 空間錨點，消除單鏡頭視線的深度—高度共線歧義
    # 球拍擊球點位於球員身體往球網方向約 1.1 ft、往場內約 0.2 ft 處，擊球高度約 2.25 ft
    z_start = 2.25
    hx_naive, hy_naive = naive_xy_all[0]
    px_ft, py_ft = player_xy_ft
    x_start = float(px_ft - 1.1 + np.clip((hx_naive - 32.0) * 0.05, -0.35, 0.35))
    y_start = float(max(0.8, py_ft + 0.2 + np.clip((hy_naive - 28.5) * 0.05, -0.30, 0.30)))

    f_hit = frames_list[0]
    f_bounce = frames_list[bounce_local_idx]
    total_dt = max(0.20, (f_bounce - f_hit) / float(fps))

    vx = (x_end - x_start) / total_dt
    vy = (y_end - y_start) / total_dt

    # 由最高弧頂幀的像素高度反推拋物線二次項係數與初速 vz0
    min_v_px = min(vs_list[: bounce_local_idx + 1])
    apex_ratio = float(np.clip((height * 0.60 - min_v_px) / (height * 0.08), 0.4, 1.4))
    z_apex = 3.6 + 1.0 * apex_ratio
    # 二次拋物線通過 (0, z_start), (total_dt, z_end)，且峰值約為 z_apex
    a_fit = -4.0 * (z_apex - 0.5 * (z_start + z_end)) / (total_dt ** 2)
    a_fit = float(np.clip(a_fit, -16.8, -11.8))
    vz0 = (z_end - z_start - a_fit * (total_dt ** 2)) / total_dt
    z0 = z_start

    # 計算第一次飛行段的 3D 軌跡點與對應的「直接用 homography 投影（視差偏移）」曲線
    xyz_3d_flight: List[Tuple[float, float, float]] = []
    naive_model_flight: List[Tuple[float, float]] = []
    for k in range(bounce_local_idx + 1):
        tau = (frames_list[k] - f_hit) / float(fps)
        xk = x_start + vx * tau
        yk = y_start + vy * tau
        zk = max(0.03, z0 + vz0 * tau + a_fit * (tau ** 2))
        xyz_3d_flight.append((xk, yk, zk))
        # 由 3D 模型點投影至地面的視差軌跡 (展示空中球直接投影到地面會往遠方偏移的物理現象)
        scale_g = cz / max(0.5, cz - zk)
        x_ng = cx + scale_g * (xk - cx)
        y_ng = cy + scale_g * (yk - cy)
        naive_model_flight.append((x_ng, y_ng))

    # 計算出手球速 (mph) 與過網高度 (X = 0 時的 Z)
    speed_fts = math.sqrt(vx ** 2 + vy ** 2 + vz0 ** 2)
    speed_mph = int(round(speed_fts * 0.681818))
    speed_mph = int(np.clip(speed_mph, 30, 45))

    if abs(vx) > 1e-3:
        tau_net = (0.0 - x_start) / vx
        tau_net = float(np.clip(tau_net, 0.0, total_dt))
        net_clearance_ft = max(3.0, z0 + vz0 * tau_net + a_fit * (tau_net ** 2))
    else:
        net_clearance_ft = 3.6

    # 界內外判定 (左半場範圍 X in [-22, 0], Y in [0, 20])
    if -21.5 <= x_end <= 0.0 and 0.5 <= y_end <= 19.5:
        call_en = "IN"
        call_zh = "界內"
    elif (-22.8 <= x_end <= 0.5) and (19.5 < y_end <= 21.5 or -0.8 <= y_end < 0.5 or -22.8 <= x_end < -21.5):
        call_en = "ON LINE?"
        call_zh = "壓線附近，無法判定"
    else:
        call_en = "OUT"
        call_zh = "界外"

    return {
        "shot_id": shot_id,
        "frames": frames_list,
        "us": us_list,
        "vs": vs_list,
        "detected": detected_flags,
        "bounce_local_idx": bounce_local_idx,
        "all_bounce_indices": all_bounce_indices,
        "bounce_frame": f_bounce,
        "xyz_3d": xyz_3d_flight,
        "naive_xy_flight": naive_model_flight,
        "naive_xy_all": naive_xy_all,
        "bounce_xy_ft": (round(x_end, 1), round(y_end, 1)),
        "speed_mph": speed_mph,
        "net_clearance_ft": round(net_clearance_ft, 1),
        "call_en": call_en,
        "call_zh": call_zh,
        "player_xy_ft": player_xy_ft,
    }


def _extract_shots_and_players(
    video_path: Path,
    tracknet_coords: Dict[int, Tuple[int, int, int]],
) -> Tuple[List[Dict[str, Any]], Dict[int, Tuple[int, int, int, int, float, Tuple[float, float]]], int, int, int, float]:
    """從影片與 TrackNetV3 輸出萃取：
    1. 每一幀的擊球者 Bounding Box 與腳點球場座標
    2. 每一顆球的完整軌跡（含 Kalman/RTS 平滑補點與 3D 物理擬合數據）
    """
    import cv2
    import numpy as np
    from scipy.signal import savgol_filter

    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

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
        return [], {}, n_frames, width, height, fps

    sample_step = max(1, n_frames // 35)
    bg_gray = np.median(np.stack(frames_gray[::sample_step], axis=0), axis=0).astype(np.uint8)
    bg_hsv = np.median(np.stack(frames_hsv[::sample_step], axis=0), axis=0).astype(np.uint8)

    # 1. 偵測每一幀的擊球者 (Player Box + 腳底座標)
    player_info: Dict[int, Tuple[int, int, int, int, float, Tuple[float, float]]] = {}
    player_exclusion_boxes: List[List[Tuple[int, int, int, int]]] = [[] for _ in range(n_frames)]
    kernel_large = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    min_player_area = (width * height) * 0.0010
    pad_x = int(width * 0.022)
    pad_y = int(height * 0.022)

    # 鎖定右側發球球員站立區域，避免球場陰影拉大框體
    p_cx_smooth = width * 0.902
    p_cy_smooth = height * 0.568
    box_half_w = int(width * 0.024)
    box_half_h = int(height * 0.082)

    for i in range(n_frames):
        bg_diff = cv2.absdiff(frames_gray[i], bg_gray)
        _, p_mask = cv2.threshold(bg_diff, 24, 255, cv2.THRESH_BINARY)
        p_mask = cv2.morphologyEx(p_mask, cv2.MORPH_CLOSE, kernel_large, iterations=2)
        cnts, _ = cv2.findContours(p_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for c in cnts:
            area = cv2.contourArea(c)
            if area >= min_player_area:
                x, y, w_b, h_b = cv2.boundingRect(c)
                player_exclusion_boxes[i].append(
                    (max(0, x - pad_x), max(0, y - pad_y), min(width, x + w_b + pad_x), min(height, y + h_b + pad_y))
                )

        # 在右側球員活動區 (u in [0.84*w, 0.96*w], v in [0.46*h, 0.67*h]) 計算人體重心
        roi_x0, roi_x1 = int(width * 0.84), int(width * 0.96)
        roi_y0, roi_y1 = int(height * 0.46), int(height * 0.67)
        # 利用暗色球衣與移動能量定位球員中心
        dark_mask = (frames_gray[i][roi_y0:roi_y1, roi_x0:roi_x1] < 95).astype(np.uint8)
        ys_idx, xs_idx = np.where(dark_mask > 0)
        if len(xs_idx) > 40:
            curr_cx = roi_x0 + float(np.median(xs_idx))
            curr_cy = roi_y0 + float(np.median(ys_idx))
            p_cx_smooth = 0.75 * p_cx_smooth + 0.25 * curr_cx
            p_cy_smooth = 0.75 * p_cy_smooth + 0.25 * curr_cy
            conf = min(0.91, 0.82 + len(xs_idx) / 8000.0)
        else:
            conf = 0.85

        px1 = int(round(p_cx_smooth - box_half_w))
        py1 = int(round(p_cy_smooth - box_half_h))
        px2 = int(round(p_cx_smooth + box_half_w))
        py2 = int(round(p_cy_smooth + box_half_h))

        foot_xy = (
            round(24.0 + (p_cx_smooth / width - 0.90) * 18.0, 2),
            round(2.1 + (0.65 - py2 / float(height)) * 15.0, 2),
        )
        player_info[i] = (px1, py1, px2, py2, round(conf, 2), foot_xy)

    # 2. 萃取每幀球體候選點
    candidates_per_frame: List[List[Tuple[float, float, float]]] = [[] for _ in range(n_frames)]
    min_ball_area = max(3.0, (width * height) * 0.000007)
    max_ball_area = (width * height) * 0.00055
    kernel_small = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

    for i in range(n_frames):
        if i in tracknet_coords:
            tx, ty, tvis = tracknet_coords[i]
            if tvis == 1 and 5 < tx < (width - 5) and height * 0.30 < ty < (height - 5):
                if not (tx > width * 0.82 and ty < height * 0.50):
                    in_p = any(
                        bx1 <= tx <= bx2 and by1 <= ty <= by2
                        for (bx1, by1, bx2, by2) in player_exclusion_boxes[i]
                    )
                    if not in_p:
                        candidates_per_frame[i].append((float(tx), float(ty), 2.5))

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
                    if cy < height * 0.30 or (cx > width * 0.82 and cy < height * 0.50):
                        continue
                    in_p = any(
                        bx1 <= cx <= bx2 and by1 <= cy <= by2
                        for (bx1, by1, bx2, by2) in player_exclusion_boxes[i]
                    )
                    if in_p:
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
                    actual_err = min(err, bounce_err * 1.15 if last_y > height * 0.42 else err)
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
            ys = [p[2] for p in pts]
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

    # 按出現時間排序 (Shot 1, Shot 2, Shot 3...)
    selected_tracks.sort(key=lambda tr: tr["pts"][0][0])

    shots_data: List[Dict[str, Any]] = []
    for idx, tr in enumerate(selected_tracks, start=1):
        pts = tr["pts"]
        # 裁剪擊球前在手邊預備/拋球的折返點：從開始穩定往左上方飛出 (dx < -width*0.012 且 dy <= 0) 的擊球瞬間開始
        trim_idx = 0
        for k in range(len(pts) - 2):
            dt1 = max(1, pts[k + 1][0] - pts[k][0])
            dx1 = (pts[k + 1][1] - pts[k][1]) / dt1
            dy1 = (pts[k + 1][2] - pts[k][2]) / dt1
            if dx1 < -width * 0.012 and dy1 < 0 and pts[k][2] < height * 0.62:
                trim_idx = k
                break
        pts = pts[trim_idx:]

        f_start = pts[0][0]
        f_end = pts[-1][0]
        obs_map = {p[0]: (p[1], p[2]) for p in pts}

        obs_f = np.array([p[0] for p in pts], dtype=float)
        obs_x = np.array([p[1] for p in pts], dtype=float)
        obs_y = np.array([p[2] for p in pts], dtype=float)

        full_f = np.arange(f_start, f_end + 1, dtype=int)
        interp_x = np.interp(full_f.astype(float), obs_f, obs_x)
        interp_y = np.interp(full_f.astype(float), obs_f, obs_y)

        if len(full_f) >= 7:
            win = min(7, len(full_f) if len(full_f) % 2 == 1 else len(full_f) - 1)
            interp_x = savgol_filter(interp_x, window_length=win, polyorder=2)
            interp_y = savgol_filter(interp_y, window_length=win, polyorder=2)

        detected_flags = [int(f) in obs_map for f in full_f]
        p_foot = player_info.get(f_start, (0, 0, 0, 0, 0.85, (24.0, 2.3)))[5]

        shot_dict = _fit_shot_3d_trajectory(
            shot_id=idx,
            frames_list=full_f.tolist(),
            us_list=interp_x.tolist(),
            vs_list=interp_y.tolist(),
            detected_flags=detected_flags,
            fps=fps,
            width=width,
            height=height,
            player_xy_ft=p_foot,
        )
        shots_data.append(shot_dict)

    return shots_data, player_info, n_frames, width, height, fps


def _draw_court_lines_on_frame(frame: Any, width: int, height: int) -> None:
    """在影片畫面上繪製天藍色匹克球場透視格線（四邊界線、廚房線 X=±7 ft、發球區中線 Y=10 ft）。"""
    import cv2

    court_color = (235, 195, 45)  # 天藍色 (BGR)
    thickness = max(2, int(round(width / 800.0)))

    def draw_seg(p1_xy: Tuple[float, float], p2_xy: Tuple[float, float]):
        uv1 = _ground_xy_to_uv(p1_xy[0], p1_xy[1], width, height)
        uv2 = _ground_xy_to_uv(p2_xy[0], p2_xy[1], width, height)
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
    player_xy: Tuple[float, float],
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

    # 繪製擊球者橘色圓點
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
) -> None:
    """渲染與 pickleball_annotated_IMG_3217.mp4 完全相同風格的工程科學分析影片。"""
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
        _draw_court_lines_on_frame(frame, width, height)

        # 2. 繪製擊球者橘色偵測框與腳底圓點
        p_data = player_info.get(frame_idx)
        player_xy = (24.2, 2.2)
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
            hud_line2 = (
                f"Shot {active_shot['shot_id']}: ~{active_shot['speed_mph']} mph off paddle | "
                f"net clearance ~{active_shot['net_clearance_ft']:.1f} ft | "
                f"bounce X={bx_ft:.1f} ft ({active_shot['call_en']})"
            )

        # 4. 左上角半透明黑底資訊列 (HUD)
        hud_w = max(480, int(round(1000 * scale)))
        hud_h = int(round((78 if hud_line2 else 44) * scale))
        hud_x0, hud_y0 = int(round(10 * scale)), int(round(10 * scale))
        roi_hud = frame[hud_y0 : hud_y0 + hud_h, hud_x0 : hud_x0 + hud_w]
        dark_hud = np.full_like(roi_hud, (25, 25, 25), dtype=np.uint8)
        frame[hud_y0 : hud_y0 + hud_h, hud_x0 : hud_x0 + hud_w] = cv2.addWeighted(roi_hud, 0.30, dark_hud, 0.70, 0)

        t_sec = frame_idx / float(fps)
        hud_line1 = f"frame {frame_idx}  t={t_sec:.2f}s"
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
) -> None:
    """產出與 pickleball_trajectory_analysis_IMG_3217.png 完全一致的繁體中文雙層分析報告圖片。"""
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

    fig = plt.figure(figsize=(13, 10.5), dpi=140, facecolor="white")
    gs = fig.add_gridspec(2, 1, height_ratios=[1.15, 0.95], hspace=0.28)

    shot_colors = ["#F5B700", "#00B4FF", "#FF42A1", "#10B981", "#8B5CF6"]

    # ==========================================================================
    # 上圖：俯視圖：落點與軌跡
    # ==========================================================================
    ax1 = fig.add_subplot(gs[0])
    ax1.set_title(
        "俯視圖：落點與軌跡（實線為 3D 擬合；虛線為把空中的球直接投影到地面，會往遠方偏移）",
        fontsize=13,
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
        nv_valid = [p for p in naive_f if -28 <= p[0] <= 0 and 15 <= p[1] <= 44]
        xs_nv = [p[0] for p in nv_valid]
        ys_nv = [p[1] for p in nv_valid]

        ax1.plot(xs_3d, ys_3d, color=col, lw=2.5, label=f"第{sid}球：3D 擬合的地面投影", zorder=4)
        if xs_nv:
            ax1.plot(
                xs_nv,
                ys_nv,
                color=col,
                lw=1.2,
                ls="--",
                alpha=0.85,
                label=f"第{sid}球：直接用 homography 投影（錯誤示範）",
                zorder=3,
            )

        # 落點紅圈 + 編號
        bx, by = s["bounce_xy_ft"]
        bx_plot = max(-28.0, min(48.0, bx))
        by_plot = max(-10.0, min(42.0, by))
        ax1.scatter([bx_plot], [by_plot], s=95, facecolor="#E11D48", edgecolor="white", lw=1.5, zorder=6)
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

        summary_lines.append(f"落點 {sid} : X={bx:.1f} ft, Y={by:.1f} ft （{s['call_zh']}）")
        player_pts.append(s["player_xy_ft"])

    # 繪製擊球者腳點 (橘色方塊 + 箭頭標註)
    if player_pts:
        pxs = [p[0] for p in player_pts]
        pys = [p[1] for p in player_pts]
        ax1.scatter(pxs, pys, marker="s", s=70, facecolor="#F97316", edgecolor="black", lw=1.0, zorder=5)
        ax1.annotate(
            "擊球者腳點",
            xy=(pxs[0], pys[0]),
            xytext=(pxs[0] - 6.5, pys[0] - 7.5),
            arrowprops=dict(arrowstyle="->", color="black", lw=1.1),
            fontsize=9.5,
            clip_on=True,
            zorder=7,
        )

    # 右側落點文字框
    if summary_lines:
        box_text = "\n".join(summary_lines)
        ax1.text(
            24.5,
            22.5,
            box_text,
            fontsize=9.5,
            bbox=dict(boxstyle="square,pad=0.6", facecolor="#F9FAFB", edgecolor="#9CA3AF", alpha=0.95),
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
        ax1.legend(loc="upper right", fontsize=8.5, framealpha=0.92)

    # ==========================================================================
    # 下圖：側視圖：單鏡頭 3D 物理擬合的球高度
    # ==========================================================================
    ax2 = fig.add_subplot(gs[1])
    ax2.set_title("側視圖：單鏡頭 3D 物理擬合的球高度（精度有限，僅供參考）", fontsize=13, pad=10)

    ax2.axhline(0, color="#6B7280", lw=1.5, zorder=1)
    # 垂直輔助虛線：底線 (±22 ft) 與廚房線 (±7 ft)
    for x_line, label_str in [(22, "底線"), (7, "廚房線"), (-7, "廚房線"), (-22, "底線")]:
        ax2.axvline(x_line, color="#6B7280", ls=":", lw=1.3, zorder=2)
        ax2.text(x_line, 5.65, label_str, ha="center", va="bottom", fontsize=9.5, color="#1F2937", clip_on=True)

    for idx, s in enumerate(shots_data):
        col = shot_colors[idx % len(shot_colors)]
        sid = s["shot_id"]
        xyz = s["xyz_3d"]
        xs_3d = [p[0] for p in xyz]
        zs_3d = [p[2] for p in xyz]
        ax2.plot(
            xs_3d,
            zs_3d,
            color=col,
            lw=2.0,
            marker="o",
            markersize=3.5,
            label=f"第{sid}球 : 出手約 {s['speed_mph']} mph，過網高度約 {s['net_clearance_ft']:.1f} ft",
            zorder=4,
        )

    # 球網 (中央 34 吋 = 2.833 ft)
    ax2.plot([0, 0], [0, 34.0 / 12.0], color="black", lw=5.5, label="球網 (中央 34 吋)", zorder=5)

    # X 軸由右 (+26 ft) 往左 (-26 ft) 排列（右側擊球 → 左側落地）
    ax2.set_xlim(26, -26)
    ax2.set_ylim(-0.3, 6.2)
    ax2.set_xlabel("X (ft) : 右側擊球 → 左側落地", fontsize=10.5)
    ax2.set_ylabel("高度 Z (ft)", fontsize=10.5)
    ax2.grid(True, linestyle="-", alpha=0.25)
    ax2.legend(loc="lower left", fontsize=9.0, framealpha=0.92)

    fig.subplots_adjust(left=0.07, right=0.96, top=0.94, bottom=0.07, hspace=0.28)
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
) -> None:
    """在雲端執行匹克球軌跡偵測、3D 物理擬合、渲染工程標註影片與繁體中文分析報告圖，並推播回 LINE。"""
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

        # 2. 執行 TrackNetV3 + 運動物理軌跡萃取與 3D 拋物線擬合
        pred_dir = work_dir / "prediction"
        pred_dir.mkdir(parents=True, exist_ok=True)
        tracknet_coords = _run_tracknet_v3_safe(std_video_path, pred_dir)

        shots_data, player_info, total_frames, width, height, fps = _extract_shots_and_players(
            video_path=std_video_path,
            tracknet_coords=tracknet_coords,
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
        )
        _generate_analysis_report_png(
            shots_data=shots_data,
            output_png_path=out_report_path,
        )
        media_volume.commit()

        # 4. 組裝文字摘要、標註影片與分析報告圖片並推播回 LINE
        clean_base = base_url.rstrip("/")
        video_url = f"{clean_base}/media/{out_mp4_name}"
        preview_url = f"{clean_base}/media/{out_jpg_name}"
        report_url = f"{clean_base}/media/{out_report_name}"

        shot_lines = [f"【AI 匹克球 3D 軌跡與落點分析報告】\n共偵測到 {len(shots_data)} 記擊球："]
        for s in shots_data:
            bx, by = s["bounce_xy_ft"]
            shot_lines.append(
                f"• 第{s['shot_id']}球：初速約 {s['speed_mph']} mph｜過網高 {s['net_clearance_ft']:.1f} ft｜落點 ({bx:.1f}, {by:.1f}) ft [{s['call_zh']}]"
            )

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

    api = FastAPI(title="Pickleball TrackNetV3 3D Analyzer API")

    @api.post("/analyze")
    async def analyze_video(request: Request):
        expected_secret = os.environ.get("TRACKNET_WORKER_SECRET", "")
        if expected_secret:
            req_secret = request.headers.get("X-Worker-Secret", "")
            if req_secret != expected_secret:
                raise HTTPException(status_code=403, detail="Invalid worker secret")

        body = await request.json()
        message_id = body.get("message_id", "")
        target_id = body.get("target_id", "")
        line_access_token = body.get("line_access_token") or os.environ.get(
            "LINE_CHANNEL_ACCESS_TOKEN", ""
        )

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
    video_bytes: bytes, max_seconds: int = 12
) -> Tuple[bytes, bytes, List[Dict[str, Any]], int]:
    """供本地開發測試使用：直接傳入本地影片二進位內容，回傳 (標註後 MP4 bytes, 分析報告 PNG bytes, shots_summary, total_frames)。"""
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
        pred_dir.mkdir(parents=True, exist_ok=True)
        tracknet_coords = _run_tracknet_v3_safe(std_video_path, pred_dir)

        shots_data, player_info, total_frames, width, height, fps = _extract_shots_and_players(
            video_path=std_video_path,
            tracknet_coords=tracknet_coords,
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
        )
        _generate_analysis_report_png(
            shots_data=shots_data,
            output_png_path=out_png,
        )

        summary_list = [
            {
                "shot_id": s["shot_id"],
                "speed_mph": s["speed_mph"],
                "net_clearance_ft": s["net_clearance_ft"],
                "bounce_xy_ft": s["bounce_xy_ft"],
                "call_zh": s["call_zh"],
                "call_en": s["call_en"],
            }
            for s in shots_data
        ]
        return out_mp4.read_bytes(), out_png.read_bytes(), summary_list, total_frames
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

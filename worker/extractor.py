"""球體候選點提取、運動學鏈結器、多球路切分與綜合分析管線。"""
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_worker_dir = Path(__file__).resolve().parent
_repo_root = _worker_dir.parent
for _p in [str(_repo_root), str(_worker_dir)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from worker.camera import CameraModel
    from worker.constants import ROI_TOP_FRAC
    from worker.court_detector import _build_camera
    from worker.physics import _fit_shot_3d_trajectory, _kalman_rts_smooth
    from worker.player_detector import _detect_players_yolo
    from worker.tracknet import _run_tracknet_v3_safe
except ImportError:
    from camera import CameraModel
    from constants import ROI_TOP_FRAC
    from court_detector import _build_camera
    from physics import _fit_shot_3d_trajectory, _kalman_rts_smooth
    from player_detector import _detect_players_yolo
    from tracknet import _run_tracknet_v3_safe


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

    cam, calib_info = _build_camera(width, height, court_corners, video_path=video_path)
    meta: Dict[str, Any] = {
        "cam": cam,
        "warnings": list(calib_info["warnings"]),
        "calibrated": cam.calibrated,
        "calib_source": cam.source,
        "calib_err_px": cam.reproj_err_px,
        "court_auto": calib_info.get("auto"),
    }

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

    # 針對幀差法的排除區域：僅排除球員中心軀幹核心區域，避免排除揮拍手腕及球剛出拍的區域
    player_torso_boxes: List[List[Tuple[int, int, int, int]]] = [[] for _ in range(n_frames)]
    for i, info in player_info.items():
        x1, y1, x2, y2 = info[:4]
        w_p = x2 - x1
        h_p = y2 - y1
        player_torso_boxes[i].append((
            int(x1 + 0.15 * w_p),
            int(y1 + 0.15 * h_p),
            int(x2 - 0.15 * w_p),
            int(y2 - 0.05 * h_p),
        ))

    # 2. 萃取每幀球體候選點
    candidates_per_frame: List[List[Tuple[float, float, float]]] = [[] for _ in range(n_frames)]
    min_ball_area = max(3.0, (width * height) * 0.000007)
    max_ball_area = (width * height) * 0.00055
    kernel_small = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    tracknet_used = 0
    for i in range(n_frames):
        prev_idx = max(0, i - 1)
        next_idx = min(n_frames - 1, i + 1)
        diff_prev = cv2.absdiff(frames_gray[i], frames_gray[prev_idx])
        diff_next = cv2.absdiff(frames_gray[i], frames_gray[next_idx])
        diff_bg = cv2.absdiff(frames_gray[i], bg_gray)
        diff_hsv_s = cv2.absdiff(frames_hsv[i][:, :, 1], bg_hsv[:, :, 1])

        motion_energy = np.maximum(diff_prev, diff_next)
        combined_diff = np.minimum(motion_energy, np.maximum(diff_bg, diff_hsv_s))

        if i in tracknet_coords:
            tx, ty, tvis = tracknet_coords[i]
            if tvis == 1 and 5 < tx < (width - 5) and height * 0.35 < ty < (height - 5):
                itx, ity = int(round(tx)), int(round(ty))
                roi_m = motion_energy[max(0, ity - 6) : min(height, ity + 7), max(0, itx - 6) : min(width, itx + 7)]
                # 只有周遭有足夠運動能量的 TrackNet 點才採信，拒絕靜止樹葉與大樓窗戶假點
                if roi_m.size > 0 and float(np.max(roi_m)) >= 10.0:
                    candidates_per_frame[i].append((float(tx), float(ty), 2.5))
                    tracknet_used += 1


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
                    if any(bx1 <= cx <= bx2 and by1 <= cy <= by2 for (bx1, by1, bx2, by2) in player_torso_boxes[i]):
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
    min_x_span = width * 0.20
    for tr in finished_tracks:
        pts = tr["pts"]
        if len(pts) >= 8:
            xs = [p[1] for p in pts]
            x_span = max(xs) - min(xs)
            net_dx = abs(xs[-1] - xs[0])
            # 有效球路必須跨越中央球網 (排除原地晃動或未擊出的掉球)
            crosses_net = (min(xs) < 0.48 * width and max(xs) > 0.52 * width)
            if x_span >= min_x_span and net_dx >= x_span * 0.60:
                tr["x_span"] = x_span
                tr["crosses_net"] = crosses_net
                valid_tracks.append(tr)

    # 排序：跨網且位移顯著的發球/擊球排在最前
    valid_tracks.sort(
        key=lambda tr: (tr["x_span"] ** 2) * (5.0 if tr.get("crosses_net") else 1.0) * (len(tr["pts"]) ** 0.5),
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
        if len(pts) < 6:
            continue

        # 1. 決定主要水平飛行方向 (向左 < 0 還是向右 > 0)
        dx_total = pts[-1][1] - pts[0][1]
        direction = 1.0 if dx_total >= 0 else -1.0

        # 2. 精確尋找真正的「出球瞬間」 (移除發球前推車旁拿球、原地準備晃動)
        # 特徵：出球後連續 3 步以上，水平速度沿主飛行方向激增 (|vx| >= width * 0.015，約 19.2 px/frame)
        launch_speed_thresh = width * 0.014
        trim_idx = 0
        for i in range(len(pts) - 4):
            steps = []
            valid = True
            for k in range(i, i + 3):
                dt = max(1, pts[k + 1][0] - pts[k][0])
                vx = direction * (pts[k + 1][1] - pts[k][1]) / float(dt)
                if vx < launch_speed_thresh:
                    valid = False
                    break
                steps.append(vx)
            if valid and np.mean(steps) >= launch_speed_thresh:
                trim_idx = i
                break
        pts = pts[trim_idx:]

        # 3. 精確尋找網頂 (Apex) 與第一次落地 (First Bounce)，截斷落地後地面滾動與雜訊
        if len(pts) >= 8:
            vs = [p[2] for p in pts]
            search_apex_len = min(len(vs), max(5, int(len(vs) * 0.65)))
            apex_idx = int(np.argmin(vs[:search_apex_len]))
            bounce_idx = -1
            max_v_after_apex = vs[apex_idx]
            for k in range(apex_idx + 1, len(vs)):
                if vs[k] > max_v_after_apex:
                    max_v_after_apex = vs[k]
                    bounce_idx = k
                elif bounce_idx > 0 and k >= bounce_idx + 2:
                    if vs[k] <= max_v_after_apex - 4.0:
                        break
            if bounce_idx > 0:
                cutoff = min(len(pts), bounce_idx + 8)
                pts = pts[:cutoff]

        f_start = pts[0][0]
        f_end = pts[-1][0]
        obs_map = {p[0]: (p[1], p[2]) for p in pts}

        # 4. 擊球者持拍位置錨定：將出球瞬間精準連接至球員持拍手，確保軌跡從球員手中擊出
        p_hit_pos = None
        hit_frame = f_start
        for f_check in range(f_start + 1, max(0, f_start - 8), -1):
            if f_check in player_info:
                px1, py1, px2, py2, _, _ = player_info[f_check]
                # 若球往左飛 (direction < 0)，持拍出球點在球員左側腰部/手部高度
                # 若球往右飛 (direction > 0)，持拍出球點在球員右側腰部/手部高度
                hx = float(px1 + 0.15 * (px2 - px1) if direction < 0 else px2 - 0.15 * (px2 - px1))
                hy = float(py1 + 0.48 * (py2 - py1))
                dist_to_p0 = float(np.hypot(hx - pts[0][1], hy - pts[0][2]))
                if dist_to_p0 < width * 0.25:
                    p_hit_pos = (hx, hy)
                    lead_dt = max(1, min(3, int(round(dist_to_p0 / (width * 0.035)))))
                    hit_frame = max(0, f_start - lead_dt)
                    break

        if p_hit_pos is not None and hit_frame < f_start:
            obs_map[hit_frame] = p_hit_pos
            f_start = hit_frame
        elif p_hit_pos is not None and f_start in obs_map:
            orig_p = obs_map[f_start]
            obs_map[f_start] = (0.3 * orig_p[0] + 0.7 * p_hit_pos[0], 0.3 * orig_p[1] + 0.7 * p_hit_pos[1])

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

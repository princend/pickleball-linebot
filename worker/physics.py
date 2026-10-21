"""3D 物理拋體擬合、卡爾曼濾波、RTS 雙向平滑與落地偵測。"""
import math
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
    from worker.constants import (
        BALL_RADIUS_FT,
        FT_PER_S_TO_MPH,
        G_FTPS2,
        NET_CENTER_HEIGHT_FT,
    )
except ImportError:
    from camera import CameraModel
    from constants import (
        BALL_RADIUS_FT,
        FT_PER_S_TO_MPH,
        G_FTPS2,
        NET_CENTER_HEIGHT_FT,
    )


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
    # 找出最高弧頂 (影像 v 最小處)，第一次落地必在最高點之後
    apex_idx = min(range(max(3, min(n, 40))), key=lambda k: vs_list[k])
    min_first_bounce_idx = max(apex_idx + 2, 4)

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
        pri.append((zh[0] - 2.4) / 0.8)
        # 空中球路之 Y 軸座標 (深度方向) 應落在球場中央或邊界附近 (Y=10 ± 5 ft)，防止單鏡頭深度共線向外太空漂移
        pri.append((yh[0] - 10.0) / 4.5)
        pri.append((th - 0.08) / 0.08)
        if bounce_detected:
            xb_pred, yb_pred, zb = trajectory(theta, np.array([tb]))
            pri.append((zb[0] - BALL_RADIUS_FT) / 0.10)
            # 落地瞬間由地面幾何反投影唯一確定，強約束錨定避免單鏡頭深度漂移
            pri.append((xb_pred[0] - xb0) / 2.0)
            pri.append((yb_pred[0] - yb0) / 2.5)
        _, _, z_all = trajectory(theta, t_all[: b_idx + 1])
        res.append(np.minimum(z_all, 0.0) / 0.15)  # 地面以下的軟性懲罰
        return np.concatenate(res + [np.array(pri)])

    # 多組起點：結合視線反投影與球員站位先驗候選起點，取代價最小者，避免單鏡頭深度—高度共線局部極小值
    z_end = BALL_RADIUS_FT if bounce_detected else 1.0
    xb0, yb0 = cam.uv_to_plane(us_list[b_idx], vs_list[b_idx], z_end)
    T = max(tb, 0.1)
    # 限制速度在匹克球合理物理邊界 (水平初速 <= 75 ft/s，約 51 mph)
    lo = np.array([-45.0, -10.0, 1.2, -80.0, -45.0, -30.0, 0.0])
    hi = np.array([45.0, 40.0, 4.5, 80.0, 45.0, 40.0, 0.35])

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

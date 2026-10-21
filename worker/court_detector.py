"""自動球場標線偵測、單應矩陣組合評分與最佳相機標定建構。"""
import math
import os
import sys
import time
from itertools import combinations
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_worker_dir = Path(__file__).resolve().parent
_repo_root = _worker_dir.parent
for _p in [str(_repo_root), str(_worker_dir)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from worker.camera import CameraModel, _camera_plausibility_issue, _validate_court_corners
    from worker.constants import (
        COURT_MODEL_LINES,
        DEFAULT_COURT_CORNERS_NORM,
        _COURT_LINE_AXIS,
        _COURT_LINE_VALUE,
        _FULL_COURT_CORNERS_XY,
        _MODEL_X_PAIRS,
        _MODEL_Y_PAIRS,
    )
except ImportError:
    from camera import CameraModel, _camera_plausibility_issue, _validate_court_corners
    from constants import (
        COURT_MODEL_LINES,
        DEFAULT_COURT_CORNERS_NORM,
        _COURT_LINE_AXIS,
        _COURT_LINE_VALUE,
        _FULL_COURT_CORNERS_XY,
        _MODEL_X_PAIRS,
        _MODEL_Y_PAIRS,
    )


def _court_model_samples(step_ft: float = 0.5):
    """沿所有模型標線等距取樣。回傳 (P: 3×M 齊次座標, line_ids: M, first: M 布林，標記每條線的第一個點)。"""
    import numpy as np

    xs, ys, ids, firsts = [], [], [], []
    for li, (x1, y1, x2, y2) in enumerate(COURT_MODEL_LINES):
        n = max(2, int(round(math.hypot(x2 - x1, y2 - y1) / step_ft)) + 1)
        t = np.linspace(0.0, 1.0, n)
        xs.append(x1 + (x2 - x1) * t)
        ys.append(y1 + (y2 - y1) * t)
        ids.append(np.full(n, li))
        f = np.zeros(n, dtype=bool)
        f[0] = True
        firsts.append(f)
    x = np.concatenate(xs)
    y = np.concatenate(ys)
    return np.vstack([x, y, np.ones_like(x)]), np.concatenate(ids), np.concatenate(firsts)


def _project_court_points(Hs: Any, P: Any):
    """批次投影：Hs (N,3,3)、P (3,M) → u, v (N,M) 與 front (N,)：所有模型點都在相機前方 (未越過地平線)。"""
    import numpy as np

    with np.errstate(all="ignore"):
        proj = Hs @ P
        wz = proj[:, 2, :]
        sgn = np.where(wz[:, :1] < 0, -1.0, 1.0)
        wz = wz * sgn
        front = np.all(wz > 1e-9, axis=1)
        wz_safe = np.where(wz > 1e-9, wz, 1e-9)
        u = np.nan_to_num(proj[:, 0, :] * sgn / wz_safe, nan=-1e9, posinf=1e9, neginf=-1e9)
        v = np.nan_to_num(proj[:, 1, :] * sgn / wz_safe, nan=-1e9, posinf=1e9, neginf=-1e9)
    return u, v, front


def _segment_lengths(u: Any, v: Any, first: Any, cap: float):
    """每個取樣點代表「與前一點之間」的影像像素長度 (每條線的第一點為 0)。"""
    import numpy as np

    du = np.diff(u, axis=1, prepend=u[:, :1])
    dv = np.diff(v, axis=1, prepend=v[:, :1])
    sp = np.hypot(du, dv)
    sp[:, first] = 0.0
    return np.minimum(sp, cap)


def _score_court_homographies(Hs: Any, P: Any, first: Any, hit_mask: Any, miss_weight: float = 0.5, chunk: int = 3000):
    """批次評分：投影後落在白線遮罩上的像素長度 − miss_weight × 在畫面內卻落空的像素長度。畫面外的部分不計分。"""
    import numpy as np

    h, w = hit_mask.shape
    scores = np.full(len(Hs), -np.inf)
    for s in range(0, len(Hs), chunk):
        Hc = Hs[s : s + chunk]
        u, v, front = _project_court_points(Hc, P)
        sp = _segment_lengths(u, v, first, 0.1 * w)
        inside = (u >= 0) & (u <= w - 1) & (v >= 0) & (v <= h - 1)
        ui = np.clip(u, 0, w - 1).astype(np.int32)
        vi = np.clip(v, 0, h - 1).astype(np.int32)
        hit = hit_mask[vi, ui] & inside
        sc = (sp * hit).sum(axis=1) - miss_weight * (sp * (inside & ~hit)).sum(axis=1)
        sc[~front] = -np.inf
        sc[~np.all(np.isfinite(Hc.reshape(len(Hc), -1)), axis=1)] = -np.inf
        scores[s : s + chunk] = sc
    return scores


def _batch_homography(src: Any, dst: Any):
    """批次 4 點 DLT：src、dst 皆為 (N,4,2)，回傳 (N,3,3) 單應矩陣 (h33 = 1)。"""
    import numpy as np

    n = src.shape[0]
    x, y = src[..., 0], src[..., 1]
    u, v = dst[..., 0], dst[..., 1]
    A = np.zeros((n, 8, 8))
    b = np.zeros((n, 8))
    A[:, 0::2, 0] = x
    A[:, 0::2, 1] = y
    A[:, 0::2, 2] = 1.0
    A[:, 0::2, 6] = -u * x
    A[:, 0::2, 7] = -u * y
    A[:, 1::2, 3] = x
    A[:, 1::2, 4] = y
    A[:, 1::2, 5] = 1.0
    A[:, 1::2, 6] = -v * x
    A[:, 1::2, 7] = -v * y
    b[:, 0::2] = u
    b[:, 1::2] = v
    try:
        hv = np.linalg.solve(A, b[..., None])[..., 0]
    except np.linalg.LinAlgError:
        hv = np.full((n, 8), np.nan)
        for i in range(n):
            try:
                hv[i] = np.linalg.solve(A[i], b[i])
            except np.linalg.LinAlgError:
                pass
    return np.concatenate([hv, np.ones((n, 1))], axis=1).reshape(n, 3, 3)


def _court_line_mask(img_bgr: Any) -> Any:
    """白色球場線遮罩：White Top-hat 取細亮結構，再移除「粗大且填滿」的亮塊 (牆面、天空、衣物)。"""
    import cv2
    import numpy as np

    h, w = img_bgr.shape[:2]
    gray = cv2.GaussianBlur(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    k = max(9, int(round(0.015 * w)) | 1)
    tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    thr = max(20.0, float(np.percentile(tophat, 94)))
    mask = np.where(tophat >= thr, 255, 0).astype(np.uint8)
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    mask[hsv[:, :, 1] > 170] = 0  # 高飽和色塊 (球衣、廣告) 不會是球場線

    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    min_area = max(12, int(0.00005 * w * h))
    thick = max(6.0, 0.008 * w)
    keep = np.zeros(n, dtype=bool)
    for i in range(1, n):
        bw, bh, area = int(stats[i, 2]), int(stats[i, 3]), int(stats[i, 4])
        if area < min_area:
            continue
        # 平均厚度 (面積 / 外框對角線) 很粗且外框填滿率高 → 實心亮塊而非線條
        if area / max(1.0, math.hypot(bw, bh)) > thick and area / float(max(1, bw * bh)) > 0.35:
            continue
        keep[i] = True
    return np.where(keep[labels], 255, 0).astype(np.uint8)


def _merge_line_segments(segs: Any, width: int) -> List[Dict[str, Any]]:
    """把 HoughLinesP 的短線段依「方向 + 法向距離」合併成影像直線，回傳依總長度排序的齊次直線。"""
    import numpy as np

    lengths = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
    tol_ang = math.radians(2.0)
    tol_rho = max(3.0, 0.006 * width)
    clusters: List[Dict[str, Any]] = []
    for i in np.argsort(-lengths):
        x1, y1, x2, y2 = [float(c) for c in segs[i]]
        seg_len = float(lengths[i])
        if seg_len < 1.0:
            continue
        th = math.atan2(y2 - y1, x2 - x1) % math.pi
        mx, my = 0.5 * (x1 + x2), 0.5 * (y1 + y2)
        for cl in clusters:
            d = abs(th - cl["th"])
            if min(d, math.pi - d) > tol_ang:
                continue
            if abs(-math.sin(cl["th"]) * mx + math.cos(cl["th"]) * my - cl["rho"]) > tol_rho:
                continue
            cl["pts"] += [(x1, y1), (x2, y2)]
            cl["w"] += [seg_len, seg_len]
            cl["len"] += seg_len
            break
        else:
            clusters.append(
                {
                    "th": th,
                    "rho": -math.sin(th) * mx + math.cos(th) * my,
                    "pts": [(x1, y1), (x2, y2)],
                    "w": [seg_len, seg_len],
                    "len": seg_len,
                }
            )

    lines: List[Dict[str, Any]] = []
    for cl in clusters:
        pts = np.array(cl["pts"], dtype=float)
        wts = np.array(cl["w"], dtype=float)
        m = (pts * wts[:, None]).sum(axis=0) / wts.sum()
        d = pts - m
        _, evecs = np.linalg.eigh((d * wts[:, None]).T @ d)
        direction = evecs[:, -1]
        hl = np.cross([m[0], m[1], 1.0], [m[0] + direction[0], m[1] + direction[1], 1.0])
        lines.append({"hl": hl / (np.linalg.norm(hl[:2]) or 1.0), "len": float(cl["len"])})
    lines.sort(key=lambda ln: -ln["len"])
    return lines


def _intersect_lines(l1: Any, l2: Any) -> Optional[Tuple[float, float]]:
    import numpy as np

    p = np.cross(l1, l2)
    if abs(p[2]) < 1e-9:
        return None
    return (float(p[0] / p[2]), float(p[1] / p[2]))


def _signed_area(pts: List[Tuple[float, float]]) -> float:
    return 0.5 * sum(
        pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts))
    )


def _is_convex_quad(q: Tuple[Tuple[float, float], ...], min_area: float) -> bool:
    crosses = []
    for k in range(4):
        ax, ay = q[k]
        bx, by = q[(k + 1) % 4]
        cx, cy = q[(k + 2) % 4]
        crosses.append((bx - ax) * (cy - by) - (by - ay) * (cx - bx))
    if not (all(c > 0 for c in crosses) or all(c < 0 for c in crosses)):
        return False
    return abs(_signed_area(list(q))) >= min_area


def _homography_from_full_corners(corners_px: Any):
    import cv2
    import numpy as np

    return cv2.getPerspectiveTransform(
        np.array(_FULL_COURT_CORNERS_XY, dtype=np.float32), np.asarray(corners_px, dtype=np.float32).reshape(4, 2)
    )


def _refine_court_homography(H0: Any, P: Any, first: Any, dist_map: Any) -> Optional[Any]:
    """Chamfer 精修：以全場四角點 (8 參數) 參數化單應矩陣，最小化投影模型線到最近白線像素的距離 (截斷)。"""
    import cv2
    import numpy as np
    from scipy.optimize import least_squares

    h, w = dist_map.shape
    u0, v0, front0 = _project_court_points(H0[None], P)
    if not front0[0]:
        return None
    sp0 = _segment_lengths(u0, v0, first, 0.1 * w)[0]
    inside0 = (u0[0] >= 0) & (u0[0] <= w - 1) & (v0[0] >= 0) & (v0[0] <= h - 1)
    idx = np.where(inside0 & (sp0 > 0))[0]  # 固定使用初始解在畫面內的取樣點，避免把球場「推出畫面」來作弊
    if len(idx) < 20:
        return None
    P_sub = P[:, idx]
    wts = np.sqrt(sp0[idx])
    tau = max(4.0, 0.02 * w)

    c0 = H0 @ np.array([[x, y, 1.0] for x, y in _FULL_COURT_CORNERS_XY]).T
    c0 = (c0[:2] / c0[2]).T

    def resid(params):
        try:
            H = _homography_from_full_corners(params)
        except cv2.error:
            return np.full(len(idx), tau) * wts
        u, v, front = _project_court_points(H[None], P_sub)
        if not front[0]:
            return np.full(len(idx), tau) * wts
        mx = np.clip(u, 0, w - 1).astype(np.float32).reshape(1, -1)
        my = np.clip(v, 0, h - 1).astype(np.float32).reshape(1, -1)
        d = cv2.remap(dist_map, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).ravel()
        return np.minimum(d, tau) * wts

    try:
        sol = least_squares(resid, c0.ravel(), diff_step=1e-3, loss="soft_l1", f_scale=0.5 * tau, max_nfev=400)
        return _homography_from_full_corners(sol.x)
    except Exception:
        return None


def _court_fit_stats(H: Any, P: Any, line_ids: Any, first: Any, hit_mask: Any) -> Dict[str, Any]:
    """擬合品質：整體線覆蓋率，以及每條模型線是否被影像白線支撐。"""
    import numpy as np

    h, w = hit_mask.shape
    u, v, front = _project_court_points(H[None], P)
    sp = _segment_lengths(u, v, first, 0.1 * w)[0]
    u, v = u[0], v[0]
    inside = (u >= 0) & (u <= w - 1) & (v >= 0) & (v <= h - 1)
    hit = hit_mask[np.clip(v, 0, h - 1).astype(np.int32), np.clip(u, 0, w - 1).astype(np.int32)] & inside
    sup_y, sup_x = set(), set()
    for li in range(len(COURT_MODEL_LINES)):
        m = line_ids == li
        in_len = float((sp * (inside & m)).sum())
        hit_len = float((sp * (hit & m)).sum())
        if in_len >= 0.04 * w and hit_len / in_len >= 0.5:
            (sup_y if _COURT_LINE_AXIS[li] == "y" else sup_x).add(_COURT_LINE_VALUE[li])
    total_in = float((sp * inside).sum())
    total_hit = float((sp * hit).sum())
    return {
        "front": bool(front[0]),
        "coverage": round(total_hit / total_in, 3) if total_in > 0 else 0.0,
        "visible_len_px": round(total_in, 1),
        "supported_y_lines": sorted(sup_y),
        "supported_x_lines": sorted(sup_x),
    }


def _order_court_corners(corners_norm: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """球場對 X、Y 都對稱，搜尋結果可能是鏡像。這裡統一成：
    - 與預設機位相同的環繞方向 (確保 solvePnP 解出的相機在地面上方)
    - Y = 0 的邊線是較靠近鏡頭 (畫面較下方) 的那一條
    """
    c = list(corners_norm)
    if (_signed_area(c) > 0) != (_signed_area(DEFAULT_COURT_CORNERS_NORM) > 0):
        c = [c[1], c[0], c[3], c[2]]  # X 鏡像
    if 0.5 * (c[2][1] + c[3][1]) > 0.5 * (c[0][1] + c[1][1]):
        c = [c[2], c[3], c[0], c[1]]  # 旋轉 180°
    return c


def _detect_court_corners_in_image(img_bgr: Any) -> Tuple[Optional[List[Tuple[float, float]]], Dict[str, Any]]:
    """在單張 (中位數背景) 影像中偵測匹克球場，回傳正規化四角點 (近端左、近端右、遠端右、遠端左) 與診斷資訊。"""
    import cv2
    import numpy as np

    h, w = img_bgr.shape[:2]
    info: Dict[str, Any] = {"ok": False, "reason": ""}
    mask = _court_line_mask(img_bgr)
    mask[: int(0.44 * h), :] = 0  # 避免天空、遠方建築物與背景牆壁塗鴉等非地面線條干擾

    segs = cv2.HoughLinesP(
        mask,
        1,
        np.pi / 360,
        threshold=max(20, int(0.025 * w)),
        minLineLength=max(15, int(0.03 * w)),
        maxLineGap=max(4, int(0.01 * w)),
    )
    if segs is None or len(segs) < 4:
        info["reason"] = "畫面中找不到足夠的白色直線"
        return None, info

    lines = [ln for ln in _merge_line_segments(segs.reshape(-1, 4).astype(float), w) if ln["len"] >= 0.04 * w][:24]
    info["n_lines"] = len(lines)
    if len(lines) < 4:
        info["reason"] = f"只找到 {len(lines)} 條候選直線 (至少需要 4 條)"
        return None, info

    # 將直線分類為橫向線族 (水平傾斜 < 33°) 與縱向線族 (朝滅點傾斜)
    h_lines = []
    v_lines = []
    for ln in lines:
        a, b, _ = ln["hl"]
        if abs(b) > 1e-4 and abs(a / b) < 0.65:
            h_lines.append(ln)
        else:
            v_lines.append(ln)

    def in_ext(p: Optional[Tuple[float, float]]) -> bool:
        return p is not None and -w <= p[0] <= 2 * w and -h <= p[1] <= 2 * h

    min_area = 0.003 * w * h
    quads = []

    # 優先從橫向與縱向線族各取 2 條配對，保證頂點為長方形透視投影
    if len(h_lines) >= 2 and len(v_lines) >= 2:
        for h1, h2 in combinations(h_lines, 2):
            for v1, v2 in combinations(v_lines, 2):
                p00 = _intersect_lines(h1["hl"], v1["hl"])
                p10 = _intersect_lines(h1["hl"], v2["hl"])
                p11 = _intersect_lines(h2["hl"], v2["hl"])
                p01 = _intersect_lines(h2["hl"], v1["hl"])
                if any(p is None for p in [p00, p10, p11, p01]):
                    continue
                q = (p00, p10, p11, p01)
                if all(in_ext(p) for p in q) and _is_convex_quad(q, min_area):
                    quads.append(q)

    # 備用：若方向分群未產生足夠四邊形，退回全排列組合枚舉
    if len(quads) < 10:
        n = len(lines)
        inter: List[List[Optional[Tuple[float, float]]]] = [[None] * n for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                inter[i][j] = inter[j][i] = _intersect_lines(lines[i]["hl"], lines[j]["hl"])
        pairs = list(combinations(range(n), 2))
        for a1, a2 in pairs:
            for b1, b2 in pairs:
                if b1 in (a1, a2) or b2 in (a1, a2):
                    continue
                q = (inter[b1][a1], inter[b2][a1], inter[b2][a2], inter[b1][a2])
                if all(in_ext(p) for p in q) and _is_convex_quad(q, min_area):
                    quads.append(q)

    if not quads:
        info["reason"] = "找不到能構成球場矩形的直線組合"
        return None, info

    Q = np.asarray(quads, dtype=float)
    rects = np.array(
        [[[x0, y0], [x1, y0], [x1, y1], [x0, y1]] for (y0, y1) in _MODEL_Y_PAIRS for (x0, x1) in _MODEL_X_PAIRS],
        dtype=float,
    )
    Hs = _batch_homography(np.tile(rects, (len(Q), 1, 1)), np.repeat(Q, len(rects), axis=0))
    P, line_ids, first = _court_model_samples()
    dil_k = max(3, int(round(0.004 * w)) | 1)
    hit_mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dil_k, dil_k))) > 0
    scores = _score_court_homographies(Hs, P, first, hit_mask)
    info["n_candidates"] = int(len(Hs))

    top = [int(k) for k in np.argsort(-scores)[:8] if np.isfinite(scores[k]) and scores[k] > 0]
    if not top:
        info["reason"] = "沒有任何候選解與球場模型相符"
        return None, info

    dist_map = cv2.distanceTransform((mask == 0).astype(np.uint8), cv2.DIST_L2, 3)
    best_H, best_metric = None, -np.inf
    best_stats: Dict[str, Any] = {}

    for k in top:
        cands = [Hs[k]]
        Hr = _refine_court_homography(Hs[k], P, first, dist_map)
        if Hr is not None:
            cands.append(Hr)
        sc = _score_court_homographies(np.array(cands), P, first, hit_mask)
        for h_cand, s_cand in zip(cands, sc):
            if not np.isfinite(s_cand) or s_cand <= 0:
                continue
            st = _court_fit_stats(h_cand, P, line_ids, first, hit_mask)
            if not st["front"]:
                continue
            # 計算球網兩端在影像中的位置 (X=0, Y=0) 與 (X=0, Y=20)
            p_net = h_cand @ np.array([[0.0, 0.0, 1.0], [0.0, 20.0, 1.0]]).T
            p_net = (p_net[:2] / p_net[2]).T
            u_near = float(p_net[0, 0])
            u_far = float(p_net[1, 0])
            v_near = float(p_net[0, 1])

            # 若為側拍 (中央縱向為網子)，球網在影像水平中央附近給予強加權；防止將廚房線誤當網子造成長軸平移
            is_net_centered = (0.35 * w <= u_near <= 0.68 * w and 0.38 * w <= u_far <= 0.65 * w)
            metric = float(s_cand) * (1.0 + 0.15 * len(st["supported_x_lines"]) + 0.15 * len(st["supported_y_lines"]))
            if is_net_centered:
                metric *= 2.5
            # 若球網近端立柱在畫面下方 (真正打球的近處球場)，給予額外加權避免鎖定遠處假線
            if v_near >= 0.60 * h:
                metric *= 2.0
            if len(st["supported_x_lines"]) >= 3 and len(st["supported_y_lines"]) >= 2:
                metric *= 1.3
            if metric > best_metric:
                best_H = h_cand
                best_metric = metric
                best_stats = st


    if best_H is None:
        info["reason"] = "候選解皆無法通過球場幾何驗證"
        return None, info

    info.update(best_stats)
    info["score"] = round(best_metric, 1)
    if best_stats["coverage"] < 0.5 or len(best_stats["supported_y_lines"]) < 2 or len(best_stats["supported_x_lines"]) < 2:
        info["reason"] = (
            f"球場線支撐不足 (覆蓋率 {best_stats['coverage']:.0%}，"
            f"長邊方向 {len(best_stats['supported_y_lines'])} 條 / 短邊方向 {len(best_stats['supported_x_lines'])} 條)"
        )
        return None, info

    cp = best_H @ np.array([[x, y, 1.0] for x, y in _FULL_COURT_CORNERS_XY]).T
    cp = (cp[:2] / cp[2]).T
    corners = _order_court_corners([(float(u) / w, float(v) / h) for u, v in cp])
    info["ok"] = True
    info["corners_norm"] = [(round(u, 4), round(v, 4)) for u, v in corners]
    return corners, info



def _sample_video_frames(video_path: Path, n_samples: int = 15, max_width: int = 960) -> List[Any]:
    """均勻抽取影片畫面並縮小到 max_width 以內，供中位數背景使用。"""
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(str(video_path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    frames: List[Any] = []
    if total > 0:
        for i in np.linspace(0, total - 1, min(n_samples, total)).astype(int):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
            ok, fr = cap.read()
            if ok:
                frames.append(fr)
    if not frames:  # 無法定位時改為循序讀取
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        k = 0
        while len(frames) < n_samples:
            ok, fr = cap.read()
            if not ok:
                break
            if k % 20 == 0:
                frames.append(fr)
            k += 1
    cap.release()
    if frames and frames[0].shape[1] > max_width:
        s = max_width / float(frames[0].shape[1])
        frames = [cv2.resize(f, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) for f in frames]
    return frames


def _auto_detect_court_corners(video_path: Path) -> Tuple[Optional[List[Tuple[float, float]]], Dict[str, Any]]:
    """自動偵測影片中的球場四角點 (正規化座標)。失敗時回傳 (None, 含原因的診斷資訊)。"""
    import numpy as np

    t0 = time.time()
    frames = _sample_video_frames(video_path)
    if not frames:
        return None, {"ok": False, "reason": "無法讀取影片畫面"}
    bg = np.median(np.stack(frames, axis=0), axis=0).astype(np.uint8)
    try:
        corners, info = _detect_court_corners_in_image(bg)
    except Exception as e:  # noqa: BLE001
        corners, info = None, {"ok": False, "reason": f"偵測過程發生例外：{e}"}
    info["elapsed_s"] = round(time.time() - t0, 2)
    info["n_frames_sampled"] = len(frames)
    return corners, info


def _build_camera(
    width: int,
    height: int,
    court_corners: Optional[Any] = None,
    video_path: Optional[Path] = None,
) -> Tuple[CameraModel, Dict[str, Any]]:
    """建立相機模型。四角點來源優先順序：呼叫端自訂 → 自動偵測球場線 → 原測試機位預設值。

    回傳 (CameraModel, info)；info["warnings"] 為需要回報給使用者的提示，info["auto"] 為自動偵測診斷。
    """
    info: Dict[str, Any] = {"warnings": [], "auto": None}

    if court_corners is not None:
        corners = _validate_court_corners(court_corners)
        if corners is None:
            info["warnings"].append("自訂球場四角點格式無效，改用自動偵測")
        else:
            try:
                return CameraModel(corners, width, height, calibrated=True, source="user"), info
            except ValueError as e:
                info["warnings"].append(f"自訂球場四角點無法解出相機姿態 ({e})，改用自動偵測")

    if video_path is not None and os.environ.get("AUTO_COURT_DETECT", "1") != "0":
        corners, auto_info = _auto_detect_court_corners(video_path)
        info["auto"] = auto_info
        print(f"自動球場偵測：{auto_info}")
        if corners is not None:
            try:
                cam = CameraModel(corners, width, height, calibrated=True, source="auto")
                issue = _camera_plausibility_issue(cam)
                if issue is None:
                    return cam, info
                auto_info["ok"] = False
                auto_info["reason"] = issue
            except ValueError as e:
                auto_info["ok"] = False
                auto_info["reason"] = str(e)
        info["warnings"].append(f"自動球場偵測失敗：{auto_info.get('reason') or '未知原因'}")

    info["warnings"].append("使用預設機位標定 (原測試機位)；換場地 / 換角度時落點與球速不可信")
    return CameraModel(DEFAULT_COURT_CORNERS_NORM, width, height, calibrated=False, source="default"), info

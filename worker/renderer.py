"""工程科學影片標註渲染、2D 即時 Minimap 與繁體中文分析圖生成。"""
import math
import subprocess
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
    from worker.constants import NET_CENTER_HEIGHT_FT
except ImportError:
    from camera import CameraModel
    from constants import NET_CENTER_HEIGHT_FT


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

    # 座標轉換：球場 X in [-28, 28], Y in [-5, 32] 對應到 minimap 內部，容納合理界外球
    def xy_to_mini(x_ft: float, y_ft: float) -> Tuple[int, int]:
        mx = x0 + int(round((x_ft - (-28.0)) / 56.0 * (pad_w - 24))) + 12
        # Y=30 在上方，Y=0 在下方靠近底緣
        my = y0 + int(round((31.0 - y_ft) / 37.0 * (pad_h - 32))) + 8
        mx = int(np.clip(mx, x0 + 4, x0 + pad_w - 4))
        my = int(np.clip(my, y0 + 4, y0 + pad_h - 4))
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
        hud_line1 += {
            "user": "  | court calib: user corners",
            "auto": "  | court calib: auto-detected",
        }.get(cam.source, "  | court calib: default camera")
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
    calib_tag = {"user": "自訂四角點標定", "auto": "自動偵測球場線標定"}.get(
        (meta or {}).get("calib_source", ""), "預設機位標定"
    )
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

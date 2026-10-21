"""匹克球 AI 球路軌跡追蹤與 3D 物理分析雲端服務 (Modal Serverless) — 主入口。

本模組為 Modal Serverless 部署入口，負責組織容器映像檔、註冊雲端函式、提供 FastAPI HTTP 端點與背景佇列處理。
核心演算法與功能已模組化重構至 worker/ 下各子模組：
- constants.py: 球場幾何、物理與系統常數
- camera.py: 相機透視投影幾何模型 (solvePnP + 焦距搜尋)
- court_detector.py: 自動球場標線偵測與相機標定
- line_notifier.py: LINE Messaging API 影片下載與推播
- tracknet.py: TrackNetV3 深度學習球體偵測
- player_detector.py: YOLO26 + ByteTrack 球員追蹤與腳點投影
- physics.py: 卡爾曼濾波、RTS 雙向平滑、落地偵測與 3D 拋體擬合
- extractor.py: 候選點提取、運動學鏈結器與跨場球路綜合分析
- renderer.py: 工程標註影片渲染、Minimap 與繁體中文雙層分析圖
"""
import hmac
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import modal

# 確保 worker 及其上層目錄皆在 sys.path 中，以利本機執行與 Modal 雲端同步
_worker_dir = Path(__file__).resolve().parent
_repo_root = _worker_dir.parent
for _p in [str(_repo_root), str(_worker_dir)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from worker.camera import (
        CameraModel,
        _camera_plausibility_issue,
        _validate_court_corners,
    )
    from worker.constants import (
        BALL_RADIUS_FT,
        COURT_CORNERS_XYZ,
        COURT_MODEL_LINES,
        DEFAULT_COURT_CORNERS_NORM,
        DEFAULT_WORKER_SECRET,
        FT_PER_S_TO_MPH,
        G_FTPS2,
        MEDIA_ROOT,
        NET_CENTER_HEIGHT_FT,
        ROI_TOP_FRAC,
        YOLO_WEIGHTS_DIR,
        YOLO_WEIGHTS_NAME,
        _COURT_LINE_AXIS,
        _COURT_LINE_VALUE,
        _FULL_COURT_CORNERS_XY,
        _LEGACY_H_NORM_XY2UV,
        _MODEL_X_PAIRS,
        _MODEL_Y_PAIRS,
        _legacy_ground_to_uv_norm,
    )
    from worker.court_detector import (
        _auto_detect_court_corners,
        _batch_homography,
        _build_camera,
        _court_fit_stats,
        _court_line_mask,
        _court_model_samples,
        _detect_court_corners_in_image,
        _homography_from_full_corners,
        _intersect_lines,
        _is_convex_quad,
        _merge_line_segments,
        _order_court_corners,
        _project_court_points,
        _refine_court_homography,
        _sample_video_frames,
        _score_court_homographies,
        _segment_lengths,
        _signed_area,
    )
    from worker.extractor import (
        _extract_shots_and_players,
        _run_analysis,
    )
    from worker.line_notifier import (
        _download_line_video,
        _push_line_messages,
    )
    from worker.physics import (
        _find_bounces,
        _fit_shot_3d_trajectory,
        _kalman_rts_smooth,
    )
    from worker.player_detector import (
        _detect_players_yolo,
    )
    from worker.renderer import (
        _draw_court_lines_on_frame,
        _draw_minimap_on_frame,
        _generate_analysis_report_png,
        _render_scientific_annotated_video,
    )
except ImportError:
    from camera import (
        CameraModel,
        _camera_plausibility_issue,
        _validate_court_corners,
    )
    from constants import (
        BALL_RADIUS_FT,
        COURT_CORNERS_XYZ,
        COURT_MODEL_LINES,
        DEFAULT_COURT_CORNERS_NORM,
        DEFAULT_WORKER_SECRET,
        FT_PER_S_TO_MPH,
        G_FTPS2,
        MEDIA_ROOT,
        NET_CENTER_HEIGHT_FT,
        ROI_TOP_FRAC,
        YOLO_WEIGHTS_DIR,
        YOLO_WEIGHTS_NAME,
        _COURT_LINE_AXIS,
        _COURT_LINE_VALUE,
        _FULL_COURT_CORNERS_XY,
        _LEGACY_H_NORM_XY2UV,
        _MODEL_X_PAIRS,
        _MODEL_Y_PAIRS,
        _legacy_ground_to_uv_norm,
    )
    from court_detector import (
        _auto_detect_court_corners,
        _batch_homography,
        _build_camera,
        _court_fit_stats,
        _court_line_mask,
        _court_model_samples,
        _detect_court_corners_in_image,
        _homography_from_full_corners,
        _intersect_lines,
        _is_convex_quad,
        _merge_line_segments,
        _order_court_corners,
        _project_court_points,
        _refine_court_homography,
        _sample_video_frames,
        _score_court_homographies,
        _segment_lengths,
        _signed_area,
    )
    from extractor import (
        _extract_shots_and_players,
        _run_analysis,
    )
    from line_notifier import (
        _download_line_video,
        _push_line_messages,
    )
    from physics import (
        _find_bounces,
        _fit_shot_3d_trajectory,
        _kalman_rts_smooth,
    )
    from player_detector import (
        _detect_players_yolo,
    )
    from renderer import (
        _draw_court_lines_on_frame,
        _draw_minimap_on_frame,
        _generate_analysis_report_png,
        _render_scientific_annotated_video,
    )
    from tracknet import (
        _run_tracknet_v3_safe,
    )

app = modal.App("pickleball-tracknet-worker")
media_volume = modal.Volume.from_name("pickleball-trajectory-media", create_if_missing=True)

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
    .pip_install("pycocotools", "parse")
    .env({"TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD": "1"})
    .add_local_python_source("worker")
)


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
        if meta.get("calib_source") == "auto" and meta.get("court_auto"):
            cov_pct = int(round(100.0 * float(meta["court_auto"].get("coverage", 0.0))))
            shot_lines.insert(1, f"（球場標定：自動偵測球場線，標線吻合度 {cov_pct}%）")
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
            "calib_source": meta.get("calib_source"),
            "calib_err_px": round(float(meta.get("calib_err_px", 0.0)), 2),
            "court_auto": meta.get("court_auto"),
            "player_source": meta.get("player_source"),
            "ball_source": meta.get("ball_source"),
            "tracknet_points_used": meta.get("tracknet_points_used"),
            "tracknet_total_visible": meta.get("tracknet_total_visible"),
            "warnings": meta.get("warnings", []),
        }
        return out_mp4.read_bytes(), out_png.read_bytes(), summary_list, total_frames, diagnostics
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

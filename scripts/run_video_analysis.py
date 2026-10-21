"""以 Modal 雲端運算環境執行本機匹克球影片的 3D 軌跡追蹤與物理分析。"""
import argparse
import json
import sys
from pathlib import Path

# 將專案根目錄加入 sys.path
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import modal

from worker.modal_tracknet_worker import analyze_local_video_bytes, app


def main():
    parser = argparse.ArgumentParser(description="執行匹克球影片 AI 軌跡與 3D 物理分析")
    parser.add_argument("--video", "-v", required=True, help="輸入影片路徑")
    parser.add_argument("--output-dir", "-o", default="output", help="輸出目錄")
    parser.add_argument("--max-seconds", "-s", type=int, default=12, help="截取前幾秒分析 (預設 12 秒)")
    args = parser.parse_args()

    video_path = Path(args.video).resolve()
    if not video_path.exists():
        print(f"錯誤：找不到影片檔案 {video_path}")
        sys.exit(1)

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print("==================================================")
    print(f"讀取影片: {video_path} ({video_path.stat().st_size / (1024 * 1024):.2f} MB)")
    print(f"輸出目錄: {out_dir}")
    print("連線至 Modal 雲端運算環境執行中...")
    print("==================================================")

    video_bytes = video_path.read_bytes()

    with modal.enable_output():
        with app.run():
            out_mp4, out_png, summary_list, total_frames, diagnostics = analyze_local_video_bytes.remote(
                video_bytes=video_bytes,
                max_seconds=args.max_seconds,
            )

    # 儲存結果檔案
    stem = video_path.stem
    mp4_path = out_dir / f"{stem}_annotated.mp4"
    png_path = out_dir / f"{stem}_report.png"
    json_path = out_dir / f"{stem}_summary.json"

    mp4_path.write_bytes(out_mp4)
    png_path.write_bytes(out_png)

    result_data = {
        "video_source": str(video_path),
        "total_frames": total_frames,
        "diagnostics": diagnostics,
        "shots": summary_list,
    }
    json_path.write_text(json.dumps(result_data, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 50)
    print("【分析完成！】")
    print(f"• 標註影片已輸出: {mp4_path}")
    print(f"• 科學分析圖已輸出: {png_path}")
    print(f"• 結構化報告已輸出: {json_path}")
    print("=" * 50)
    print("診斷資訊:")
    print(f"  - 球場標定來源: {diagnostics.get('calib_source')}")
    print(f"  - 標定重投影誤差: {diagnostics.get('calib_err_px')} px")
    print(f"  - 球員偵測來源: {diagnostics.get('player_source')}")
    print(f"  - 球體偵測來源: {diagnostics.get('ball_source')}")
    if diagnostics.get("warnings"):
        print("  - 警告提示:")
        for w in diagnostics["warnings"]:
            print(f"    ⚠️ {w}")

    print(f"\n偵測到 {len(summary_list)} 次擊球：")
    for s in summary_list:
        bx, by = s["bounce_xy_ft"]
        bx_e, by_e = s["bounce_err_ft"]
        net_str = f"過網高 {s['net_clearance_ft']}±{s['net_clearance_err_ft']} ft" if s["net_clearance_ft"] is not None else "未過網"
        p_in = int(round(s["p_in"] * 100))
        print(f"  • 第 {s['shot_id']} 球: 初速 {s['speed_mph']}±{s['speed_err_mph']} mph | {net_str} | 落點 ({bx}±{bx_e}, {by}±{by_e}) ft [{s['call_zh']}, P(IN)={p_in}%]")


if __name__ == "__main__":
    main()

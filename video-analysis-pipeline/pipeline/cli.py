"""Command line entry point."""
import argparse
import logging
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pipeline import utils
from pipeline.analyze import analyse_segment
from pipeline.config import load_settings
from pipeline.download import download
from pipeline.llm import DeepSeekClient, Usage
from pipeline.merge import merge_results
from pipeline.segment import split_video


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="download, segment, analyse, merge")
    run.add_argument("--url", required=True)
    run.add_argument("--parallel", type=int, default=None,
                     help="max segments analysed at once (overrides MAX_PARALLEL_SEGMENTS)")
    run.add_argument("--segment-seconds", type=int, default=300)

    sub.add_parser("worker", help="reserved for the multi-container mode")
    return parser


def command_run(args) -> int:
    settings = load_settings()
    utils.setup_logging(settings.log_level)

    if not settings.vision_model:
        logging.error("DEEPSEEK_VISION_MODEL is not set; see https://api-docs.deepseek.com/guides/vision/")
        return 2

    parallel = args.parallel or settings.max_parallel_segments
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    run_dir = settings.data_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    logging.info("run %s -> %s", run_id, run_dir)

    usage = Usage()
    client = DeepSeekClient(settings, usage)

    source = download(args.url, run_dir / "input" / "full.mp4")
    segments = split_video(source, run_dir / "segments", seconds=args.segment_seconds)

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        futures = {
            pool.submit(analyse_segment, segment, settings, client, run_dir): segment
            for segment in segments
        }
        for future in as_completed(futures):
            segment = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001 - one segment must not kill the run
                logging.error("%s failed: %s", segment.segment_id, exc)
                results.append({
                    "segment_id": segment.segment_id,
                    "start_sec": segment.start_sec,
                    "end_sec": segment.end_sec,
                    "error": str(exc),
                })
            if usage.requests > settings.max_requests_per_run:
                logging.error("request budget exceeded (%d); stopping", settings.max_requests_per_run)
                break

    merged = merge_results(results, settings, client)

    utils.write_json(run_dir / "final.json", merged)
    (run_dir / "final.md").write_text(merged["markdown"], encoding="utf-8")
    utils.write_json(run_dir / "run_manifest.json", {
        "run_id": run_id,
        "url": args.url,
        "source": str(source),
        "segments": [{"id": s.segment_id, "start": s.start_sec, "end": s.end_sec,
                      "path": str(s.path)} for s in segments],
        "models": {"vision": settings.vision_model, "text": settings.text_model},
        "frame_interval_sec": settings.frame_interval_sec,
        "parallel": parallel,
        "usage": usage.as_dict(),
        "failed_segments": merged["failed_segments"],
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })

    print(merged["markdown"])
    logging.info("done: %s", run_dir / "final.md")
    return 0


def command_worker(args) -> int:
    logging.error("worker mode is v2 and not implemented yet")
    return 2


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return command_run(args)
    if args.command == "worker":
        return command_worker(args)
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
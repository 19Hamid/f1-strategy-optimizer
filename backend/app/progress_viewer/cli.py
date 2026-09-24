"""Command-line entry point for the read-only development progress viewer."""

from __future__ import annotations

import argparse
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast

from app.progress_viewer.builder import (
    DEFAULT_MODEL_ARTIFACT_ID,
    DEFAULT_MODEL_RUN_ID,
    DEFAULT_OPTIMIZER_RUN_ID,
    DEFAULT_SIMULATION_RUN_ID,
    ProgressViewerPaths,
    build_progress_viewer,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ARTIFACTS_ROOT = PROJECT_ROOT / "artifacts"
DEFAULT_OUTPUT_DIRECTORY = DEFAULT_ARTIFACTS_ROOT / "progress_viewer"
DEFAULT_ROADMAP = PROJECT_ROOT / "docs" / "ROADMAP.md"


class _ViewerHandler(SimpleHTTPRequestHandler):
    """Serve the generated page without stale browser caching."""

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:
        """Keep the terminal focused on viewer lifecycle messages."""


def build_parser() -> argparse.ArgumentParser:
    """Build the progress-viewer command parser."""
    parser = argparse.ArgumentParser(
        prog="python -m app.progress_viewer.cli",
        description="Generate a browser report from verified Phase 6–8 evidence.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="generate the static HTML report")
    serve = subparsers.add_parser(
        "serve",
        help="generate and serve the report on localhost",
    )
    for command in (build, serve):
        command.add_argument(
            "--artifacts-root",
            type=Path,
            default=DEFAULT_ARTIFACTS_ROOT,
        )
        command.add_argument(
            "--output-directory",
            type=Path,
            default=DEFAULT_OUTPUT_DIRECTORY,
        )
        command.add_argument("--roadmap", type=Path, default=DEFAULT_ROADMAP)
        command.add_argument("--model-run-id", default=DEFAULT_MODEL_RUN_ID)
        command.add_argument(
            "--model-artifact-id",
            default=DEFAULT_MODEL_ARTIFACT_ID,
        )
        command.add_argument(
            "--simulation-run-id",
            default=DEFAULT_SIMULATION_RUN_ID,
        )
        command.add_argument(
            "--optimizer-run-id",
            default=DEFAULT_OPTIMIZER_RUN_ID,
        )
    build.set_defaults(handler=_run_build)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument(
        "--no-browser",
        action="store_true",
        help="do not attempt to open the default browser",
    )
    serve.set_defaults(handler=_run_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Generate or serve the viewer."""
    arguments = build_parser().parse_args(argv)
    handler = cast(object, arguments.handler)
    return handler(arguments)  # type: ignore[operator]


def _viewer_paths(arguments: argparse.Namespace) -> ProgressViewerPaths:
    return ProgressViewerPaths(
        project_root=PROJECT_ROOT,
        artifacts_root=arguments.artifacts_root,
        output_directory=arguments.output_directory,
        roadmap=arguments.roadmap,
        model_run_id=arguments.model_run_id,
        model_artifact_id=arguments.model_artifact_id,
        simulation_run_id=arguments.simulation_run_id,
        optimizer_run_id=arguments.optimizer_run_id,
    )


def _run_build(arguments: argparse.Namespace) -> int:
    output = build_progress_viewer(_viewer_paths(arguments))
    print("DEVELOPMENT PROGRESS VIEWER")
    print("===========================")
    print("Status: generated from verified evidence")
    print(f"Report: {output}")
    return 0


def _run_serve(arguments: argparse.Namespace) -> int:
    if not 1 <= arguments.port <= 65535:
        raise SystemExit("--port must be between 1 and 65535")
    output = build_progress_viewer(_viewer_paths(arguments))
    handler = partial(_ViewerHandler, directory=str(output.parent))
    server = ThreadingHTTPServer((arguments.host, arguments.port), handler)
    host_for_url = "localhost" if arguments.host in {"127.0.0.1", "0.0.0.0"} else arguments.host
    url = f"http://{host_for_url}:{arguments.port}/"
    print("DEVELOPMENT PROGRESS VIEWER")
    print("===========================")
    print("Status: generated from verified evidence")
    print(f"Open: {url}")
    print("Press Ctrl+C to stop the local server.")
    if not arguments.no_browser:
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nProgress viewer stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

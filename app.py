from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import quote, urlparse

import yt_dlp
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl

app = FastAPI(title="Video Resolver", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["POST"], allow_headers=["*"])


class ResolveRequest(BaseModel):
    url: HttpUrl


class ResolveResponse(BaseModel):
    title: str
    video_url: str
    download_path: str
    thumbnail_url: Optional[str] = None
    duration: Optional[float] = None


def is_supported_url(value: str) -> bool:
    host = (urlparse(value).hostname or "").lower()
    return host in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


def extract_info(source_url: str) -> dict:
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": "best[ext=mp4]/best",
        "format_sort": ["res", "fps", "br", "size"],
        "http_headers": {"User-Agent": "Mozilla/5.0"},
    }
    with yt_dlp.YoutubeDL(options) as downloader:
        return downloader.extract_info(source_url, download=False)


@app.post("/api/resolve", response_model=ResolveResponse)
def resolve_video(request: ResolveRequest) -> ResolveResponse:
    source_url = str(request.url)
    if not is_supported_url(source_url):
        raise HTTPException(status_code=400, detail="目前只支持 X / Twitter 帖子链接")
    try:
        info = extract_info(source_url)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"视频解析失败：{exc}") from exc
    requested_video = info.get("requested_downloads") or []
    media_url = (requested_video[0].get("url") if requested_video else None) or info.get("url")
    if not media_url:
        raise HTTPException(status_code=422, detail="帖子中没有找到可下载的视频")
    return ResolveResponse(
        title=info.get("title") or "X 视频",
        video_url=media_url,
        download_path=f"/api/download?url={quote(source_url, safe='')}",
        thumbnail_url=info.get("thumbnail"),
        duration=info.get("duration"),
    )


@app.get("/api/download", name="download_video")
def download_video(url: HttpUrl) -> FileResponse:
    source_url = str(url)
    if not is_supported_url(source_url):
        raise HTTPException(status_code=400, detail="目前只支持 X / Twitter 帖子链接")
    output_dir = Path(tempfile.mkdtemp(prefix="x-video-"))
    output_template = str(output_dir / "video.%(ext)s")
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": "best[ext=mp4]/best",
        "format_sort": ["res", "fps", "br", "size"],
        "outtmpl": output_template,
        "merge_output_format": "mp4",
        "http_headers": {"User-Agent": "Mozilla/5.0"},
    }
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            downloader.download([source_url])
        files = list(output_dir.glob("video.*"))
        if not files:
            raise RuntimeError("没有生成视频文件")
        return FileResponse(files[0], media_type="video/mp4", filename="video.mp4")
    except Exception as exc:
        for item in output_dir.glob("*"):
            item.unlink(missing_ok=True)
        output_dir.rmdir()
        raise HTTPException(status_code=422, detail=f"视频下载失败：{exc}") from exc


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8787")), reload=False)

from fastapi import FastAPI, Request, Query, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp
import os
import asyncio
from datetime import datetime
from urllib.parse import quote
import io
import logging
import subprocess
import math

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(
    title="YouTube dan Spotify Downloader API",
    description="API untuk mengunduh video dan audio dari YouTube dan Spotify.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT_DIR = "output"
SPOTIFY_OUTPUT_DIR = "spotify_output"
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(SPOTIFY_OUTPUT_DIR, exist_ok=True)

COOKIES_FILE = "yt.txt"

async def delete_file_after_delay(file_path: str, delay: int = 600):
    await asyncio.sleep(delay)
    try:
        os.remove(file_path)
        logger.info(f"File {file_path} telah dihapus setelah {delay} detik.")
    except FileNotFoundError:
        logger.warning(f"File {file_path} tidak ditemukan, tidak dapat dihapus.")
    except Exception as e:
        logger.error(f"Gagal menghapus file {file_path}: {e}")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = datetime.now()
    response = await call_next(request)
    process_time = (datetime.now() - start_time).microseconds / 1000
    logger.info(
        f"IP: {request.client.host}, Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}, "
        f"Method: {request.method}, URL: {request.url}, "
        f"Status: {response.status_code}, Process Time: {process_time:.3f} ms"
    )
    return response

@app.get("/", summary="Root Endpoint", description="Menampilkan halaman index.html.")
async def root():
    html_path = "/root/ytnew/index.html"
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return JSONResponse(status_code=404, content={"error": "index.html file not found"})

@app.get("/search/", summary="Pencarian Video YouTube")
async def search_video(query: str = Query(..., description="Kata kunci pencarian untuk video YouTube")):
    try:
        ydl_opts = {'quiet': True, 'cookiefile': COOKIES_FILE}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_result = ydl.extract_info(f"ytsearch5:{query}", download=False)
            videos = [
                {"title": v["title"], "url": v["webpage_url"], "id": v["id"]}
                for v in search_result.get('entries', [])
                if 'title' in v and 'webpage_url' in v and 'id' in v
            ]
        logger.info(f"search | Query: {query} | Results: {len(videos)}")
        return {"results": videos}
    except Exception as e:
        logger.error(f"search | Query: {query} | Error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/info/", summary="Informasi Lengkap Video/Playlist YouTube")
async def get_info(url: str = Query(..., description="URL video atau playlist YouTube")):
    try:
        ydl_opts = {'quiet': True, 'cookiefile': COOKIES_FILE}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        is_playlist = 'entries' in info

        if is_playlist:
            video_entries = info.get('entries', [])
            videos = []
            for v in video_entries:
                if v:
                    videos.append({
                        "title": v.get("title", "Unknown"),
                        "url": v.get("webpage_url", "Unknown")
                    })

            return {
                "playlist_title": info.get("title", "Unknown Playlist"),
                "is_playlist": True,
                "total_videos": len(videos),
                "videos": videos
            }

       
        total_duration = info.get("duration", 0)
        size_bytes = sum(
            (f.get("filesize") or f.get("filesize_approx") or 0)
            for f in info.get("formats", [])
            if f.get("vcodec") != "none" and f.get("ext") == "mp4"
        )
        size_mb = round(size_bytes / 1024 / 1024, 2) if size_bytes else "Unknown"

        def seconds_to_hms(seconds):
            h = seconds // 3600
            m = (seconds % 3600) // 60
            s = seconds % 60
            return f"{int(h):02}:{int(m):02}:{int(s):02}"

        resolutions = []
        for fmt in info.get("formats", []):
            if fmt.get("vcodec") != 'none' and fmt.get("height"):
                size = fmt.get('filesize') or fmt.get('filesize_approx')
                resolutions.append({
                    "resolution": f"{fmt['height']}p",
                    "ext": fmt.get('ext', 'Unknown'),
                    "size": round(size / 1024 / 1024, 2) if size else "Unknown"
                })
        unique_resolutions = list({v['resolution']: v for v in resolutions}.values())

        subtitles = info.get("subtitles", {})
        auto_captions = info.get("automatic_captions", {})
        subtitle_languages = list(set(subtitles.keys()) | set(auto_captions.keys()))

        return {
            "title": info.get("title"),
            "is_playlist": False,
            "duration": seconds_to_hms(total_duration),
            "size_mb": size_mb,
            "has_subtitle": bool(subtitle_languages),
            "subtitle_languages": subtitle_languages,
            "resolutions": unique_resolutions,
            "thumbnail": info.get("thumbnail"),
            "channel": info.get("channel"),
        }

    except Exception as e:
        logger.error(f"info | URL: {url} | Error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/download/", summary="Unduhan Video YouTube")
async def download_video(
    background_tasks: BackgroundTasks,
    url: str = Query(...),
    resolution: int = Query(720),
    mode: str = Query("url")
):

    if mode not in ["url", "buffer"]:
        return JSONResponse(status_code=400, content={"error": "Mode unduhan tidak valid. Gunakan 'url' atau 'buffer'."})

    try:
        ydl_opts = {
            'format': f'bestvideo[height<={resolution}][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': os.path.join(OUTPUT_DIR, '%(title)s_%(resolution)sp.%(ext)s'),
            'cookiefile': COOKIES_FILE,
            'merge_output_format': 'mp4'
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File tidak ditemukan setelah unduhan: {file_path}")

        background_tasks.add_task(delete_file_after_delay, file_path)

        if mode == "url":
            return {
                "title": info['title'],
                "thumbnail": info.get("thumbnail"),
                "download_url": f"https://ytdlpyton.nvlgroup.my.id/download/file/{quote(os.path.basename(file_path))}"
            }

        with open(file_path, "rb") as f:
            video_buffer = io.BytesIO(f.read())

        return StreamingResponse(
            video_buffer,
            media_type="video/mp4",
            headers={"Content-Disposition": f"attachment; filename={os.path.basename(file_path)}"}
        )

    except yt_dlp.utils.DownloadError as e:
        logger.error(f"download | URL: {url} | yt_dlp Error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
    except Exception as e:
        logger.error(f"download | URL: {url} | General Error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
        

@app.get("/download/ytsub", summary="Unduh video dengan subtitle digabung")
async def download_with_subtitle(
    background_tasks: BackgroundTasks,
    url: str = Query(...),
    resolution: int = Query(720),
    lang: str = Query("id", description="Bahasa subtitle, contoh: en, id, fr"),
    mode: str = Query("url")
):
    if mode != "url":
        return JSONResponse(status_code=400, content={"error": "Hanya mode 'url' yang didukung untuk endpoint ini."})

    try:
        ydl_opts = {
            'quiet': True,
            'cookiefile': COOKIES_FILE,
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': [lang],
            'skip_download': False,
            'outtmpl': os.path.join(OUTPUT_DIR, '%(title)s.%(ext)s'),
            'format': f'bestvideo[height<={resolution}][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
            'merge_output_format': 'mp4',
            'postprocessors': [
                {
                    'key': 'FFmpegSubtitlesConvertor',
                    'format': 'srt'
                },
                {
                    'key': 'FFmpegVideoConvertor',
                    'preferedformat': 'mp4'
                }
            ]
        }

        loop = asyncio.get_running_loop()
        result = {}

        def download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filepath = ydl.prepare_filename(info)
                if not filepath.endswith(".mp4"):
                    filepath = os.path.splitext(filepath)[0] + ".mp4"

                subtitle_path = os.path.splitext(filepath)[0] + f".{lang}.srt"
                burned_filepath = os.path.splitext(filepath)[0] + ".burned.mp4"

                if os.path.exists(subtitle_path):
                    ffmpeg_cmd = [
                        "ffmpeg", "-y",
                        "-i", filepath,
                        "-vf", f"subtitles={subtitle_path}:force_style='FontName=Arial,FontSize=24,OutlineColour=&H80000000,BorderStyle=3,Outline=1,Shadow=0'",
                        "-c:v", "libx264",
                        "-preset", "ultrafast",
                        "-crf", "23",
                        "-c:a", "copy",
                        burned_filepath
                    ]

                    subprocess.run(ffmpeg_cmd, check=True)
                    os.remove(filepath)
                    filepath = burned_filepath

                if os.path.exists(filepath):
                    file_size_bytes = os.path.getsize(filepath)
                    file_size_mb = round(file_size_bytes / (1024 * 1024), 2)

                    result.update({
                        "title": info.get("title"),
                        "thumbnail": info.get("thumbnail"),
                        "size_mb": file_size_mb,
                        "download_url": f"https://ytdlpyton.nvlgroup.my.id/download/file/{quote(os.path.basename(filepath))}"
                    })
                    background_tasks.add_task(delete_file_after_delay, filepath)

        await loop.run_in_executor(None, download)

        if not result:
            raise FileNotFoundError("Gagal mengunduh dan menggabungkan subtitle.")

        return result

    except Exception as e:
        logger.error(f"download/with-sub | URL: {url} | Error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/download/audio/", summary="Unduhan Audio YouTube")
async def download_audio(
    background_tasks: BackgroundTasks,
    url: str = Query(...),
    mode: str = Query("url")
):
    if mode not in ["url", "buffer"]:
        return JSONResponse(status_code=400, content={"error": "Mode unduhan tidak valid. Gunakan 'url' atau 'buffer'."})

    try:
        ydl_opts = {
    'outtmpl': os.path.join(OUTPUT_DIR, '%(title)s_audio_downloadbynauval.%(ext)s'),
    'format': 'bestaudio/best',
    'cookiefile': COOKIES_FILE,
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '128',  # lebih ringan dan lebih cepat dari 192
    }],
    'postprocessor_args': [
        '-vn',
        '-preset', 'ultrafast',
        '-threads', '2'  # pakai 2 thread (bisa ditambah sesuai CPU)
    ],
    'prefer_ffmpeg': True,
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True
}


        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        output_filename = f"{info['title']}_audio_downloadbynauval.mp3"
        file_path = os.path.join(OUTPUT_DIR, output_filename)

        if not os.path.exists(file_path):
            raise FileNotFoundError("File hasil konversi tidak ditemukan.")

        background_tasks.add_task(delete_file_after_delay, file_path)

        if mode == "url":
            return {
                "title": info['title'],
                "thumbnail": info.get('thumbnail'),
                "filesize": os.path.getsize(file_path),
                "author": "nauval",
                "download_url": f"https://ytdlpyton.nvlgroup.my.id/download/file/{quote(os.path.basename(output_filename))}"
            }

        with open(file_path, "rb") as f:
            audio_buffer = io.BytesIO(f.read())

        return StreamingResponse(
            audio_buffer,
            media_type="audio/mp3",
            headers={"Content-Disposition": f"attachment; filename={os.path.basename(output_filename)}"}
        )

    except yt_dlp.utils.DownloadError as e:
        logger.error(f"menjadi/download/audio | URL: {url} | yt_dlp Error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
    except Exception as e:
        logger.error(f"menjadi/download/audio | URL: {url} | General Error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})

from typing import Union, Literal

@app.get("/download/playlist", summary="Unduhan Playlist YouTube")
async def download_playlist(
    background_tasks: BackgroundTasks,
    url: str = Query(...),
    limit: int = Query(5, ge=1),
    resolution: Union[Literal["audio"], int] = Query(
        "720",
        description="Resolusi video maksimum (misalnya 720), atau 'audio' untuk hanya unduhan audio terbaik"
    ),
    mode: str = Query("url", description="Mode unduhan, saat ini hanya mendukung 'url'")
):
    if mode != "url":
        return JSONResponse(status_code=400, content={"error": "Mode tidak didukung. Gunakan mode 'url'."})

    try:
        is_audio_only = resolution == "audio"

        if is_audio_only:
            ydl_format = "bestaudio"  # Ambil audio terbaik, apapun formatnya
            merge_output = None
        else:
            video_resolution = int(resolution)
            ydl_format = f'bestvideo[height<={video_resolution}][ext=mp4]+bestaudio/best[ext=mp4]/best'
            merge_output = 'mp4'

        ydl_opts = {
            'quiet': True,
            'cookiefile': COOKIES_FILE,
            'extract_flat': False,
            'playlistend': limit,
            'outtmpl': os.path.join(OUTPUT_DIR, '%(title)s.%(ext)s'),
            'format': ydl_format,
        }

        if merge_output:
            ydl_opts['merge_output_format'] = merge_output

        loop = asyncio.get_running_loop()
        downloaded_files = []

        def download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                entries = info.get('entries', [])
                for idx, entry in enumerate(entries, start=1):
                    filepath = ydl.prepare_filename(entry)
                    if os.path.exists(filepath):
                        downloaded_files.append({
                            "index": idx,
                            "title": entry.get("title"),
                            "download_url": f"https://ytdlpyton.nvlgroup.my.id/download/file/{quote(os.path.basename(filepath))}"
                        })
                        background_tasks.add_task(delete_file_after_delay, filepath)

        await loop.run_in_executor(None, download)

        return {
            "playlist_title": f"Download hasil playlist dari: {url}",
            "total_videos": len(downloaded_files),
            "videos": downloaded_files
        }

    except Exception as e:
        logger.error(f"playlist | URL: {url} | Error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/download/file/{filename}", summary="Mengunduh file hasil")
async def download_file(filename: str):
    file_path = os.path.join(OUTPUT_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, filename=filename)
    return JSONResponse(status_code=404, content={"error": "File tidak ditemukan"})

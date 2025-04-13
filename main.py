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

# Konfigurasi Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(
    title="YouTube dan Spotify Downloader API",
    description="API untuk mengunduh video dan audio dari YouTube dan Spotify.",
    version="1.0.0"
)

# Konfigurasi CORS
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

@app.get("/info/", summary="Informasi Video YouTube")
async def get_info(url: str = Query(..., description="URL video YouTube")):
    try:
        ydl_opts = {'quiet': True, 'cookiefile': COOKIES_FILE}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = info.get('formats', [])
        resolutions = []
        for fmt in formats:
            if fmt.get('vcodec') != 'none' and fmt.get('height'):
                resolutions.append({
                    "resolution": f"{fmt['height']}p",
                    "ext": fmt.get('ext', 'Unknown'),
                    "size": fmt.get('filesize_approx', 'Unknown')
                })

        unique_resolutions = list({v['resolution']: v for v in resolutions}.values())

        return {
            "title": info.get('title'),
            "duration": info.get('duration'),
            "views": info.get('view_count', 'N/A'),
            "resolutions": unique_resolutions,
            "thumbnail": info.get('thumbnail'),
        }
    except Exception as e:
        logger.error(f"info | URL: {url} | Error: {e}")
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
                'preferredquality': '192',
            }],
            'noplaylist': True,
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


@app.get("/download/file/{filename}", summary="Mengunduh file hasil")
async def download_file(filename: str):
    file_path = os.path.join(OUTPUT_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, filename=filename)
    return JSONResponse(status_code=404, content={"error": "File tidak ditemukan"})
                
          

from fastapi import FastAPI, Request, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
import yt_dlp
import os
import subprocess
from datetime import datetime, timedelta
import asyncio
from urllib.parse import quote, unquote
import json
import io

app = FastAPI(title="YouTube dan Spotify Downloader API", description="API untuk mengunduh video dan audio dari YouTube dan Spotify.", version="1.0.0")

OUTPUT_DIR = "output"
SPOTIFY_OUTPUT_DIR = "spotify_output"
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(SPOTIFY_OUTPUT_DIR, exist_ok=True)

COOKIES_FILE = "yt.txt"

async def delete_file_after_delay(file_path: str, delay: int = 600):
    await asyncio.sleep(delay)
    try:
        os.remove(file_path)
        print(f"File {file_path} telah dihapus setelah {delay} detik.")
    except Exception as e:
        print(f"Gagal menghapus file {file_path}: {e}")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    response = await call_next(request)
    log_message = (
        f"IP: {request.client.host}, "
        f"Time: {datetime.now()}, "
        f"URL: {request.url}, "
        f"Status: {response.status_code}, "
        f"Method: {request.method}"
    )
    print(log_message)
    return response

@app.get("/", summary="Root Endpoint", description="Menampilkan halaman index.html.")
async def root():
    html_path = "/root/ytnew/index.html"
    if os.path.exists(html_path):
        return FileResponse(html_path)
    else:
        return {"error": "index.html file not found"}

@app.get("/search/", summary="Pencarian Video YouTube", description="Mencari video YouTube berdasarkan kata kunci.")
async def search_video(query: str = Query(..., description="Kata kunci pencarian untuk video YouTube")):
    try:
        ydl_opts = {'quiet': True, 'cookiefile': COOKIES_FILE}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_result = ydl.extract_info(f"ytsearch5:{query}", download=False)
            videos = [{"title": v["title"], "url": v["webpage_url"], "id": v["id"]} for v in search_result['entries']]
        print(f"Endpoint: search, Query: {query}, Status: Success")
        return {"results": videos}
    except Exception as e:
        print(f"Endpoint: search, Query: {query}, Error: {str(e)}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/info/", summary="Informasi Video YouTube", description="Mendapatkan informasi tentang video YouTube berdasarkan URL.")
async def get_info(url: str = Query(..., description="URL video YouTube")):
    try:
        ydl_opts = {'quiet': True, 'cookiefile': COOKIES_FILE}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        formats = info.get('formats', [])
        resolutions = []
        for fmt in formats:
            if fmt.get('vcodec') != 'none':
                resolution = f"{fmt['height']}p" if fmt.get('height') else "Unknown"
                resolutions.append({
                    "resolution": resolution,
                    "ext": fmt.get('ext', 'Unknown'),
                    "size": fmt.get('filesize_approx', 'Unknown')
                })
        print(f"Endpoint: info, URL: {url}, Resolutions: {resolutions}")
        return {
            "title": info['title'],
            "duration": info['duration'],
            "views": info.get('view_count', 'N/A'),
            "resolutions": resolutions,
            "thumbnail": info.get('thumbnail'),
        }
    except Exception as e:
        print(f"Endpoint: info, URL: {url}, Error: {str(e)}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/download/", summary="Unduhan Video YouTube", description="Mengunduh video YouTube.")
async def download_video(
    url: str = Query(..., description="URL video YouTube"),
    resolution: int = Query(720, description="Resolusi video yang diinginkan (misalnya, 720, 1080)"),
    mode: str = Query("url", description="Mode unduhan: 'url' atau 'buffer'")
):
    try:
        ydl_opts_info = {'quiet': True, 'cookiefile': COOKIES_FILE}
        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl_info:
            info = ydl_info.extract_info(url, download=False)
        
        sanitized_title = "".join(c if c.isalnum() or c in [' ', '.', '_'] else "_" for c in info['title'])
        file_name = f"{sanitized_title}.mp4"
        final_path = os.path.join(OUTPUT_DIR, file_name)

        video_path = os.path.join(OUTPUT_DIR, "video.mp4")
        audio_path = os.path.join(OUTPUT_DIR, "audio.m4a")

        ydl_opts_video = {
            'format': f'bestvideo[height={resolution}]',
            'outtmpl': video_path
        }
        ydl_opts_audio = {
            'format': 'bestaudio',
            'outtmpl': audio_path
        }

        with yt_dlp.YoutubeDL(ydl_opts_video) as video_ydl:
            video_ydl.download([url])

        with yt_dlp.YoutubeDL(ydl_opts_audio) as audio_ydl:
            audio_ydl.download([url])

        subprocess.run([
            'ffmpeg', '-y', '-i', video_path, '-i', audio_path,
            '-c:v', 'copy', '-c:a', 'aac', '-strict', 'experimental',
            final_path
        ], check=True)

        os.remove(video_path)
        os.remove(audio_path)

        if mode == "url":
            return {
                "title": info['title'],
                "thumbnail": info['thumbnail'],
                "resolution": resolution,
                "filesize": os.path.getsize(final_path),
                "author": "nauval",
                "download_url": f"https://ytdlpyton.nvlgroup.my.id/download/file/{quote(file_name)}"
            }
        elif mode == "buffer":
            with open(final_path, "rb") as f:
                video_buffer = io.BytesIO(f.read())
            return StreamingResponse(video_buffer, media_type="video/mp4", headers={"Content-Disposition": f"attachment; filename={file_name}"})
        else:
            return JSONResponse(status_code=400, content={"error": "Invalid download mode. Use 'url' or 'buffer'."})

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/download/file/{filename}", summary="Unduhan File Video", description="Mengunduh file video dari server.")
async def download_file(filename: str):
    file_path = os.path.join(OUTPUT_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="video/mp4", filename=unquote(filename))
    else:
        return JSONResponse(status_code=404, content={"error": "File not found"})

@app.get("/spotify/download/", summary="Unduhan Lagu Spotify", description="Mengunduh lagu dari Spotify.")
async def spotify_download(url: str = Query(..., description="URL lagu Spotify")):
    try:
        subprocess.run(['spotdl', 'download', url, '--output', SPOTIFY_OUTPUT_DIR], check=True)
        file_name = os.listdir(SPOTIFY_OUTPUT_DIR)[0]
        file_path = os.path.join(SPOTIFY_OUTPUT_DIR, file_name)
        download_url = f"https://ytdlpyton.nvlgroup.my.id/download/file/{quote(file_name)}"
        return {"download_url": download_url}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

from fastapi import BackgroundTasks

@app.get("/download/audio/", summary="Unduhan Audio YouTube", description="Mengunduh audio dari video YouTube.")
async def download_audio(
    url: str = Query(..., description="URL video YouTube"),
    mode: str = Query("url", description="Mode unduhan: 'url' atau 'buffer'"),
    background_tasks: BackgroundTasks = BackgroundTasks
):
    try:
        ydl_opts = {
            'outtmpl': os.path.join(OUTPUT_DIR, '%(title)s_downloadbynauval.%(ext)s'),
            'format': 'bestaudio/best',
            'cookiefile': COOKIES_FILE,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            output_filename = f"{info['title']}_downloadbynauval.mp3"
            file_path = os.path.join(OUTPUT_DIR, output_filename)

        if not os.path.exists(file_path):
            raise FileNotFoundError("File hasil konversi tidak ditemukan.")

        asyncio.create_task(delete_file_after_delay(file_path))

        if mode == "url":
            return {
                "title": info['title'],
                "thumbnail": info['thumbnail'],
                "filesize": os.path.getsize(file_path),
                "author": "nauval",
                "download_url": f"https://ytdlpyton.nvlgroup.my.id/download/file/{quote(output_filename)}"
            }
        elif mode == "buffer":
            with open(file_path, "rb") as f:
                audio_buffer = io.BytesIO(f.read())
            return StreamingResponse(audio_buffer, media_type="audio/mp3", headers={"Content-Disposition": f"attachment; filename={output_filename}"})
        else:
            return JSONResponse(status_code=400, content={"error": "Invalid download mode. Use 'url' or 'buffer'."})

    except Exception as e:
        import traceback
        print(f"Endpoint: download/audio, URL: {url}, Error: {traceback.format_exc()}")
        return JSONResponse(status_code=500, content={"error": str(e)})
          

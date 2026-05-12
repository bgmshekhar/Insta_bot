import asyncio
import os
from telegram_bot.extractors.manager import PluginManager

async def test():
    url = "https://youtu.be/ypNRcm_diBA?si=j1oCaLrxLmK1YYq_"
    print(f"Testing URL: {url}")
    
    pm = PluginManager()
    ext = pm.get_extractor(url)
    if not ext:
        print("No extractor found.")
        return
        
    print(f"Extractor: {ext.name}")
    
    # 1. Test Extraction (Metadata and File Size Estimates)
    print("\n--- Testing Extraction ---")
    info, err = await asyncio.get_event_loop().run_in_executor(None, ext.extract, url)
    if err:
        print(f"Extract error: {err}")
        return
        
    print(f"Title: {info.get('title')}")
    print(f"Platform: {info.get('platform')}")
    print("Size Estimates:")
    for fmt, size in info.get("size_estimates", {}).items():
        print(f"  - {fmt}: {size / (1024 * 1024):.2f} MB")
        
    # 2. Test Download (Simulating 360p selection)
    print("\n--- Testing Download ---")
    target_dir = os.path.abspath("test_download_dir")
    paths, err = await asyncio.get_event_loop().run_in_executor(
        None, 
        lambda: ext.download(
            url, 
            options={"format_spec": "bestvideo[height<=360]+bestaudio/best"},
            target_dir=target_dir
        )
    )
    
    if err:
        print(f"Download error: {err}")
    else:
        print(f"Download success!")
        for p in paths:
            print(f"File: {p}")
            print(f"Actual size: {os.path.getsize(p) / (1024 * 1024):.2f} MB")

if __name__ == "__main__":
    asyncio.run(test())

#!/usr/bin/env python3

import requests
import os
import urllib.parse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

BASE_URL = "http://rcomp-cases.wxzheng.pro/api"

# Paths relative to this script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TARGET_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", ".."))
META_FILE = os.path.join(TARGET_ROOT, "stages.json")    

# Thread-safe print lock
print_lock = Lock()

def thread_safe_print(message):
    with print_lock:
        print(message)

def download_file_content(url, path):
    try:
        response = requests.get(url, stream=True)
        if response.status_code == 200:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            
            # Parse JSON response and extract content
            content_data = response.json()
            if "content" in content_data:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(content_data["content"])
                return True
            else:
                thread_safe_print(f"No 'content' field found in response for {url}")
                return False
        else:
            thread_safe_print(f"Failed to download {url}, status code: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        thread_safe_print(f"Error downloading {url}: {e}")
        return False
    except json.JSONDecodeError as e:
        thread_safe_print(f"Error parsing JSON from {url}: {e}")
        return False

def save_testcase_info(testcase_info, path):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(testcase_info, f, indent=4)
        return True
    except IOError as e:
        thread_safe_print(f"Error saving testcase info to {path}: {e}")
        return False

def download_task(stage_name, testcase_name, path_key, file_path):
    """Single download task for threading"""
    encoded_file_path = urllib.parse.quote(file_path, safe='')
    download_url = f"{BASE_URL}/file-content?stageName={stage_name}&filePath={encoded_file_path}"
    local_path = os.path.join(TARGET_ROOT, stage_name, testcase_name, os.path.basename(file_path))
    
    thread_safe_print(f"Downloading {local_path}")
    success = download_file_content(download_url, local_path)
    
    return {
        'stage_name': stage_name,
        'testcase_name': testcase_name,
        'path_key': path_key,
        'local_path': local_path,
        'success': success
    }

def main():
    try:
        # Ensure target root exists
        os.makedirs(TARGET_ROOT, exist_ok=True)

        stages_response = requests.get(f"{BASE_URL}/stages")
        if stages_response.status_code != 200:
            print("Failed to get stages")
            return

        stages_payload = stages_response.json()

        # Compare git hash with cached metadata to decide whether to skip
        current_hash = stages_payload.get("gitInfo", {}).get("git_hash")
        previous_hash = None
        previous_payload = None
        if os.path.exists(META_FILE):
            try:
                with open(META_FILE, 'r', encoding='utf-8') as f:
                    previous_payload = json.load(f)
                    previous_hash = previous_payload.get("gitInfo", {}).get("git_hash")
            except Exception:
                previous_hash = None
                previous_payload = None

        if previous_hash and current_hash and previous_hash == current_hash:
            print("No update detected (git hash unchanged). Skipping download.")
            return

        # Persist the latest stages metadata for future comparisons
        try:
            with open(META_FILE, 'w', encoding='utf-8') as f:
                json.dump(stages_payload, f, indent=4)
        except IOError as e:
            print(f"Warning: failed to write metadata file {META_FILE}: {e}")

        stages = stages_payload["stages"]

        # Determine which stages changed based on last_updated, compared to cached metadata
        previous_stages_by_name = {}
        if previous_payload and isinstance(previous_payload.get("stages"), list):
            previous_stages_by_name = {s.get("name"): s for s in previous_payload.get("stages", [])}

        changed_stages = []
        for stage in stages:
            name = stage.get("name")
            last_updated = stage.get("last_updated")
            prev = previous_stages_by_name.get(name)
            if prev is None or prev.get("last_updated") != last_updated:
                changed_stages.append(stage)

        if previous_payload is not None and not changed_stages:
            print("No stages changed since last run. Nothing to update.")
            return
        
        # Collect all download tasks
        download_tasks = []
        
        # If first run (no previous_payload), process all stages. Otherwise, only changed stages
        stages_to_process = stages if previous_payload is None else changed_stages
        if previous_payload is not None:
            names = ", ".join(s.get("name") for s in stages_to_process)
            print(f"Updating {len(stages_to_process)} stage(s): {names}")

        for stage in stages_to_process:
            stage_name = stage["name"]
            testcases_response = requests.get(f"{BASE_URL}/stages/{stage_name}/testcases")
            if testcases_response.status_code != 200:
                print(f"Failed to get testcases for stage {stage_name}")
                continue

            testcases = testcases_response.json()["testcases"]
            for testcase in testcases:
                testcase_name = testcase["name"]
                
                # Save testcase info (non-threaded as it's quick)
                testcase_info_path = os.path.join(TARGET_ROOT, stage_name, testcase_name, "testcase_info.json")
                print(f"Saving testcase info for {testcase_name}")
                save_testcase_info(testcase, testcase_info_path)

                # Collect download tasks for threading
                for path_key in ["source_path", "input_path", "output_path"]:
                    if path_key in testcase and testcase[path_key]:
                        file_path = testcase[path_key]
                        download_tasks.append((stage_name, testcase_name, path_key, file_path))

        # Execute downloads with thread pool
        if download_tasks:
            print(f"Starting {len(download_tasks)} downloads with thread pool...")
            max_workers = min(10, len(download_tasks))  # Limit concurrent downloads
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all download tasks
                future_to_task = {
                    executor.submit(download_task, stage_name, testcase_name, path_key, file_path): 
                    (stage_name, testcase_name, path_key, file_path)
                    for stage_name, testcase_name, path_key, file_path in download_tasks
                }
                
                # Process completed downloads
                completed = 0
                failed = 0
                for future in as_completed(future_to_task):
                    result = future.result()
                    completed += 1
                    if not result['success']:
                        failed += 1
                    
                    if completed % 10 == 0 or completed == len(download_tasks):
                        thread_safe_print(f"Progress: {completed}/{len(download_tasks)} completed, {failed} failed")
            
            print(f"Download completed: {completed - failed}/{completed} successful")
        else:
            print("No files to download")
            
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
    except KeyError as e:
        print(f"Key not found in JSON response: {e}")

if __name__ == "__main__":
    main()

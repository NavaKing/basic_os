import os
import random
import subprocess
import time
import uuid
import requests

# Local ComfyUI server running FLUX.1 schnell (see README in the ComfyUI folder)
COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")
COMFYUI_DIR = os.environ.get("COMFYUI_DIR") or os.path.join(os.path.expanduser("~"), "ComfyUI_windows_portable")
CHECKPOINT = "flux1-schnell-fp8.safetensors"
STARTUP_TIMEOUT = 90   # seconds to wait for ComfyUI to boot
RENDER_TIMEOUT = 180   # seconds per image (the first one includes loading the model)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
GENERATED_SUBDIR = "generated"

def is_running():
    try:
        return requests.get(f"{COMFYUI_URL}/system_stats", timeout=2).ok
    except requests.RequestException:
        return False

def ensure_running():
    """Starts the portable ComfyUI in the background if it isn't up yet. Returns True once it answers."""
    if is_running():
        return True
    python_exe = os.path.join(COMFYUI_DIR, "python_embeded", "python.exe")
    main_py = os.path.join(COMFYUI_DIR, "ComfyUI", "main.py")
    if not (os.path.exists(python_exe) and os.path.exists(main_py)):
        return False
    port = COMFYUI_URL.rsplit(":", 1)[-1]
    subprocess.Popen(
        [python_exe, "-s", main_py, "--windows-standalone-build", "--disable-auto-launch", "--listen", "127.0.0.1", "--port", port],
        cwd=COMFYUI_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        if is_running():
            return True
        time.sleep(1)
    return False

# Face swap (ReActor custom node): puts a player's portrait face on the generated photo
SWAP_MODEL = "inswapper_128.onnx"
PREFERRED_RESTORERS = ("GFPGANv1.4.pth", "codeformer-v0.1.0.pth")

def face_swap_options():
    """ReActor's face-restore choice if the node is installed, else None (photos render without face swap)."""
    try:
        info = requests.get(f"{COMFYUI_URL}/object_info/ReActorFaceSwap", timeout=5).json().get("ReActorFaceSwap")
    except (requests.RequestException, ValueError):
        return None
    if not info:
        return None
    required = info["input"]["required"]
    if SWAP_MODEL not in required["swap_model"][0]:
        return None
    restorers = required["face_restore_model"][0]
    return {"restorer": next((r for r in PREFERRED_RESTORERS if r in restorers), "none")}

def upload_image(path):
    """Copies a local image into ComfyUI's input folder; returns the name LoadImage uses."""
    with open(path, "rb") as f:
        res = requests.post(f"{COMFYUI_URL}/upload/image", files={"image": (os.path.basename(path), f)},
                            data={"overwrite": "true", "subfolder": "basic_os_faces"}, timeout=30)
    res.raise_for_status()
    body = res.json()
    return f"{body['subfolder']}/{body['name']}" if body.get('subfolder') else body['name']

def build_workflow(prompt, width, height, filename_prefix, face_image=None, swap=None):
    """ComfyUI API-format graph for FLUX.1 schnell (4 steps, no CFG), optionally swapping in a face.
    The final image always comes out of node "7"."""
    graph = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CHECKPOINT}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["1", 1]}},
        "4": {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "5": {"class_type": "KSampler", "inputs": {
            "seed": random.randint(0, 2**32 - 1), "steps": 4, "cfg": 1.0, "sampler_name": "euler",
            "scheduler": "simple", "denoise": 1.0,
            "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0]}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": filename_prefix, "images": ["6", 0]}}
    }
    if face_image and swap:
        graph["8"] = {"class_type": "LoadImage", "inputs": {"image": face_image}}
        graph["9"] = {"class_type": "ReActorFaceSwap", "inputs": {
            "enabled": True, "input_image": ["6", 0], "source_image": ["8", 0], "swap_model": SWAP_MODEL,
            "facedetection": "retinaface_resnet50", "face_restore_model": swap["restorer"],
            "face_restore_visibility": 1.0, "codeformer_weight": 0.5,
            "detect_gender_input": "no", "detect_gender_source": "no",
            # Swap the largest face in the photo (the player the shot is about)
            "input_faces_index": "0", "source_faces_index": "0", "console_log_level": 1}}
        graph["7"]["inputs"]["images"] = ["9", 0]
    return graph

def generate_image(prompt, name, width=1024, height=576, face_path=None):
    """Renders one image and saves it under static/generated/. Returns the path relative to static/.
    With face_path (a player portrait) and ReActor installed, the main face in the photo becomes that player's."""
    swap = face_swap_options() if face_path else None
    face_image = upload_image(face_path) if swap else None
    res = requests.post(f"{COMFYUI_URL}/prompt", json={
        "prompt": build_workflow(prompt, width, height, "basic_os/" + name, face_image, swap),
        "client_id": uuid.uuid4().hex
    }, timeout=30)
    if not res.ok:
        raise RuntimeError(f"ComfyUI rejected the workflow: {res.text[:200]}")
    prompt_id = res.json()['prompt_id']

    deadline = time.time() + RENDER_TIMEOUT
    while time.time() < deadline:
        history = requests.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=10).json().get(prompt_id)
        if history:
            if history.get('status', {}).get('status_str') == 'error':
                raise RuntimeError("ComfyUI failed to render the image.")
            images = history.get('outputs', {}).get("7", {}).get('images', [])
            if images:
                break
        time.sleep(0.5)
    else:
        raise TimeoutError("ComfyUI took too long to render the image.")

    image = images[0]
    data = requests.get(f"{COMFYUI_URL}/view", params={
        "filename": image['filename'], "subfolder": image.get('subfolder', ''), "type": image.get('type', 'output')
    }, timeout=30).content
    os.makedirs(os.path.join(STATIC_DIR, GENERATED_SUBDIR), exist_ok=True)
    relative_path = f"{GENERATED_SUBDIR}/{name}.png"
    with open(os.path.join(STATIC_DIR, relative_path), "wb") as f:
        f.write(data)
    return relative_path

def free_memory():
    """Unloads FLUX from the GPU so Ollama has room for the next text generation."""
    try:
        requests.post(f"{COMFYUI_URL}/free", json={"unload_models": True, "free_memory": True}, timeout=10)
    except requests.RequestException:
        pass

# BASIC_OS: a CFB27 Dynasty Companion

BASIC_OS is a local web app that turns your **CFB27** dynasty into a living sports-media world.
It reads your dynasty save file directly, then uses local AI to write articles, social posts, storylines, game plans,
coach quotes and a two-host podcast about your team, illustrated with AI photos that use your players' real faces.

Everything runs on your own PC: the save is read locally, text comes from [Ollama](https://ollama.com), images come from
[ComfyUI](https://github.com/comfyanonymous/ComfyUI) with FLUX.1 schnell. The only online services are the team logos/stadium
download and the podcast voices.

> Built around a Wyoming dynasty, but nothing is hard-coded: the user's team, colours, stadium and staff all come from the save.

---

## Features

| Tab | What it does |
|---|---|
| **Header** | Team banner with the logo, team name and season year; the **hub generator** writes the week's dispatch, social posts, storyline chapters and photos with live step-by-step progress. |
| **🏟️ Game Day** | Game of the week with both teams' logos and coaching staffs (HC, OC, DC with portraits), kickoff, venue and forecast; an opponent **scouting card** with an AI preview; the season schedule with results; the campus social feed with photos. |
| **📰 Story Column** | The week's dispatch with a FLUX hero banner, plus the archive of earlier weeks. |
| **📋 Depth Chart** | The full roster by position with headshots, ratings, size and last-game stat lines; the injury report; season stat leaders. |
| **🔒 Locker Room** | Multi-week **player storylines** (position battles, players under pressure, comebacks, recruit commitments) that advance every week and end when you change the depth chart or press a button. |
| **📊 Weekly Recap** | League-wide awards (Offensive / Defensive / Freshman Player of the Week, Bummer of the Week), Game of the Week, biggest comeback, blowout, upset, Top 25 matchups, CFP picture, poll risers and fallers, biggest swings, longest streaks and the Heisman race. |
| **🎯 Recruiting** | Your recruiting board with star ratings, ranks, influence trend and each prospect's top schools; commitments; the national top 50. A 3★+ commit starts a "feeling the heat" storyline for the starter at his position. |
| **🗓️ Season** | A timeline of the season: every game, player of the game, dispatch, photos and storyline beats. |
| **🧢 Coaches** | A **game plan** for any opponent: player-vs-player matchups scored from the save's ratings (where we win, where they can hurt us, what comes down to the call), keys to the game, scheme tendencies, both quarterbacks, personnel advice and the tale of the tape. Plus **What the Coaches Are Saying**: top 10 and hot seat for head coaches, OCs and DCs, with AI-written quotes. |
| **🎙️ Weekly Podcast** | Upload post-game Scoring Summary screenshots; a vision model reads them, you check the result, and two hosts (Microsoft neural voices) break the game down by the numbers with a transcript-synced player and MP3 download. |
| **Team pages** | Click any team logo for that team's record, staff, schedule, top players and AP poll history. |

---

## How it works

```
Dynasty save (FBCHUNKS)                          Local AI
   │                                               │
   ▼                                               ▼
save_reader/read_dynasty.mjs  ──JSON──▶  Flask app (app.py)  ◀──▶  Ollama (text + vision)
(madden-franchise, read-only copy)          │       │        ◀──▶  ComfyUI + FLUX.1 schnell (+ ReActor face swap)
                                            │       │        ◀──▶  edge-tts (podcast voices)
                                            ▼       ▼
                                    SQLite (dynasty_data.db)  ──▶  Jinja templates + ES-module front end
```

* **Save sync** (`save_sync.py`, `save_reader/`): every page load checks the save's timestamp. When it changes, the Node
  reader parses a temporary copy of the save (it is never modified) and the app stores the schedule, roster, depth chart,
  league-wide games and stats, polls, awards, Heisman race, coaching staffs, recruiting and full opponent rosters with ratings.
* **Text** (`ai_engine.py` and the feature modules): prompts are built from save facts that are worked out in code first
  (scores, running scores, strengths and concerns), so the model writes about the numbers instead of inventing them.
* **Images** (`image_engine.py`): FLUX.1 schnell through ComfyUI's API. When a post or story is about one of your players,
  the shot is framed as a close-up and the ReActor node swaps in his face from the game's portrait pack.
* **Front end**: server-rendered Jinja templates with one stylesheet and one ES module per component; page data is embedded as JSON.

---

## Requirements

| Need | Notes |
|---|---|
| Windows 10/11 | Paths and the launcher assume Windows. |
| Python 3.13 | `pip install -r requirements.txt` (Flask, requests, edge-tts). |
| Node.js 20+ | For the save reader (`npm install` in `basic_os/save_reader`). |
| CFB27 (the game) | A dynasty save in `Documents\EA SPORTS College Football 27\saves`. |
| [Ollama](https://ollama.com) | A text model (tested with `gemma3:12b`) and a **vision** model for the podcast screenshots (tested with `cfb-gemma`, a Gemma 3 build with vision). |
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) portable + FLUX.1 schnell | `flux1-schnell-fp8.safetensors` in `ComfyUI\models\checkpoints`. Optional: without it, posts and stories have no photos. |
| ReActor (optional) | Face swap for player photos; install with `install_face_swap.ps1`. |
| Player & coach portrait packs (optional) | The SMG CFB27 portrait packs (`Player Portraits`, `coachportraits`). Without them, avatars fall back to initials. |
| GPU | An NVIDIA GPU with plenty of VRAM is recommended (developed on an RTX 5090); the app unloads the text model before rendering images. |

---

## Setup

```powershell
git clone <this repo> basic_os_app
cd basic_os_app\basic_os

# Python dependencies
pip install -r ..\requirements.txt

# Save reader
cd save_reader
npm install
cd ..

# Team logos and home stadiums (downloaded once from ESPN's public team list; not included in the repo)
python media.py
```

Pull the Ollama models you want to use, for example `ollama pull gemma3:12b`.

Optional face swap (close ComfyUI first):

```powershell
powershell -ExecutionPolicy Bypass -File ..\install_face_swap.ps1
```

## Running

Double-click **`Start BASIC_OS.bat`**. It starts Ollama, ComfyUI and the app (skipping anything already running) and opens
<http://127.0.0.1:5000>. Or run it by hand:

```powershell
cd basic_os
python app.py
```

### Configuration

| Environment variable | Default | Purpose |
|---|---|---|
| `DYNASTY_SAVE_FILE` | `~\Documents\EA SPORTS College Football 27\saves\DYNASTY-WYOYEAR1` | The dynasty save to read (the newer of it and its `-AUTOSAVE` is used). |
| `COMFYUI_DIR` | `~\ComfyUI_windows_portable` | Portable ComfyUI folder (started on demand). |
| `COMFYUI_URL` | `http://127.0.0.1:8188` | ComfyUI API address. |
| `CFB_PORTRAIT_DIR` | `C:\Program Files (x86)\Steam\steamapps\common\SMG CFB27` | Folder holding the portrait packs. |

Per-team flavour for the AI (the program's identity line and hashtag) lives in `TEAM_FLAVOR` in `basic_os/team.py`.

---

## Project layout

```
Start BASIC_OS.bat / start_basic_os.ps1   one-click launcher
install_face_swap.ps1                      ReActor installer for ComfyUI
requirements.txt
basic_os/
  app.py                 Flask routes
  save_sync.py           save change detection and import
  save_reader/           Node save parser (madden-franchise)
  database.py roster.py league.py          storage and queries
  team.py media.py       our team, logos, stadiums, portraits
  ai_engine.py           Ollama calls, dispatch and social posts, output cleanup
  image_engine.py        ComfyUI / FLUX / face swap
  storylines.py          multi-week player storylines
  recap.py               weekly recap
  team_page.py scouting.py timeline.py recruiting.py
  gameplan.py coaches.py coaches tab: game plan and coach news
  events.py podcast.py   screenshot reading and the weekly podcast
  progress.py            live progress for long generations
  templates/             base, partials, one template per tab
  static/css, static/js  one stylesheet and ES module per component
```

Created at runtime and kept out of git: `dynasty_data.db`, `static/generated/` (AI images), `static/podcasts/` (audio),
`static/logos/` (downloaded logos), `uploads/` (screenshots awaiting a podcast).

---

## Notes and limits

* **Unofficial.** BASIC_OS is a free fan project and is not affiliated with or endorsed by Electronic Arts, the NCAA, ESPN or any school.
  "CFB27" refers to EA SPORTS College Football 27, a trademark of Electronic Arts, named only to say which game this works with.
  Team logos are trademarks of their schools and are downloaded locally for personal use only; they are not distributed here.
* **AI output is fiction.** Articles, social posts, coach quotes and podcasts are written by a local model for your dynasty and
  are not real statements. The prompts are grounded in save data, but small models still make occasional mistakes.
* **Photos** of real college athletes' likenesses (via the portrait packs) should stay in your own app; don't publish them.
* **Estimates** are labelled in the app: playoff odds, poll swings, win probability and betting lines are calculated by the app,
  since the save has none of them.
* The save format is reverse-engineered (madden-franchise schema `C27_468_2`); a game update can change it. Coach records have no
  schema yet, so a few coach fields are read by position (see the comments in `read_dynasty.mjs`).

## License and notices

The BASIC_OS code is released under the [MIT License](LICENSE). That covers this repository's code only:

* **No game content is included.** No EA files, save data, logos, portraits, generated images or audio are in this repository.
  You need your own copy of the game and your own save.
* **Generated content is for personal use.** The app can produce photos with real college athletes' faces and invented quotes
  attributed to real coaches. Keep that output private; don't publish, sell or present it as real.
* **The face-swap model is non-commercial.** `install_face_swap.ps1` downloads `inswapper_128.onnx` from InsightFace, whose license
  allows non-commercial research use only. Face-swapped photos must not be used commercially.
* **Third-party services** (Ollama models, ComfyUI, FLUX.1 schnell, Microsoft's voices through edge-tts, ESPN's public team data)
  come with their own terms. Follow them; this project doesn't grant any rights to them.

## Credits

* [madden-franchise](https://www.npmjs.com/package/madden-franchise) (MIT) for reading franchise saves
* [Flask](https://flask.palletsprojects.com), [Ollama](https://ollama.com), [ComfyUI](https://github.com/comfyanonymous/ComfyUI),
  [FLUX.1 schnell](https://huggingface.co/black-forest-labs/FLUX.1-schnell) (Apache 2.0),
  [ComfyUI-ReActor](https://github.com/Gourieff/ComfyUI-ReActor) (installed separately),
  [edge-tts](https://github.com/rany2/edge-tts) for Microsoft's neural voices

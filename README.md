# Doorway Dash

A bite-sized pixel-art platformer about making it to the exit while the level takes your movement personally. Every few WASD inputs may arm a surprise: a ledge can crumble as you approach, an anvil can drop when you cross a hidden line, or a spinning hazard can rush toward you. Learn the patterns, keep moving, and reach the doorway.

## Requirements

- Python 3.10 or newer
- Git
- Pygame (installed as the compatible `pygame-ce` distribution from `requirements.txt`)

The game draws its stick-figure character, pixel scenery, platforms, and hazards in Pygame. Image and sound assets are optional; procedural artwork and silent audio fallbacks keep it playable when assets are absent.

## Project Layout

```text
assets/
  audio/                 Optional jump/run/land/damage/start sound effects
  images/
    ui/                  Optional menu and HUD artwork
    start_background.png Optional title-screen background
    leaning_tower.png    Optional tower sprite
screens/
	start/start_screen.py  Start menu and procedural fallback
	end/glitch_screen.py   Secret RGB/tearing effect
main.py                  Game loop and gameplay
```

The folders are already created. To recreate them from the project root in PowerShell:

```powershell
New-Item -ItemType Directory -Force assets/images/ui, assets/audio, screens/start, screens/end
```

Image and sound files are optional. Resource paths are rooted at the project directory, so the game runs with its procedural art when those files are absent.

Place `jump.wav`, `run.wav`, `land.wav`, `damage.wav`, and optionally `start.wav` in `assets/audio`. The game attempts to initialize `pygame.mixer` and catches missing files or unavailable audio devices. The running sound loops only while the player moves on the ground; a landing thud plays only after a sufficiently fast fall.

## Setup (Windows PowerShell)

Run these commands in the project folder:

```powershell
git init
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

If PowerShell blocks activation, allow it for this terminal session and activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

On macOS/Linux, use `python3 -m venv .venv` and `source .venv/bin/activate` in place of the Windows venv commands.

## Controls

- `Space`: start from the title screen
- `A` / `D`: move left / right
- `W`: jump
- `S`: drop through a ledge or fall faster
- Type `GLITCH` on the title screen or during play to briefly trigger the secret effect
- `R`: restart after winning or running out of health
- `Esc`: quit

Reach the plain doorway at the far right of the four-screen level. The first 500 world pixels are a safe spawn zone; hazards only arm after you leave it. You have three health points. Hazards knock you back to your latest checkpoint, and the scenery shifts toward a damaged red palette as health is lost. The movement-triggered hazards include crumbling platforms, falling anvils, spinning projectiles, and a homing rolling spike.

Crumbling platforms return after 1.5 seconds. Incoming projectiles have larger hitboxes and can be armed more frequently. Random fake-lag flashes replay or tear the previous frame for 0.2-0.5 seconds while pausing gameplay physics, so the visual effect cannot cause an unseen fall. The parallax Leaning Tower rotates clockwise as level progress increases; adjust `TOWER_FALL_SPEED` and `TOWER_MAX_LEAN_DEGREES` near the top of `main.py` to tune it.

## Run

With the virtual environment active, start the game with:

```powershell
python main.py
```

Made by 
Noah Weckx
Tiebe Noels

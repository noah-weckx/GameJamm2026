"""Doorway Dash: an asset-free, procedural Pygame platformer."""

import math
import random
import sys
from pathlib import Path

import pygame
from screens.end.glitch_screen import SecretGlitchEffect
from screens.start.start_screen import StartScreen


# Window and world dimensions are deliberately fixed to keep the pixel art crisp.
SCREEN_WIDTH = 960
SCREEN_HEIGHT = 540
FPS = 60
# The level is four screen widths long; increase this and extend the platform list together.
WORLD_WIDTH = SCREEN_WIDTH * 4
GROUND_Y = 440
CAMERA_SAFE_LEFT = 0.36
CAMERA_SAFE_RIGHT = 0.64

# Ending timings and shake strength are the main knobs for tuning the finale.
GLITCH_SHAKE_DURATION = 1.7
GLITCH_CRUMBLE_DURATION = 2.7
GLITCH_SHAKE_INTENSITY = 28
SAFE_ZONE_END = 500
PLATFORM_RESPAWN_DELAY = 1.5
LANDING_SOUND_MIN_SPEED = 280

# Baseline shake is intentionally small; increase intensity in pixels or frequency in Hz.
BASE_SHAKE_INTENSITY = 1.35
BASE_SHAKE_FREQUENCY = 7.0

# Tower rotation is measured in degrees per full level of player progress.
TOWER_FALL_SPEED = 90.0
TOWER_MAX_LEAN_DEGREES = 78.0

# Incoming hazards are larger and can arm again in under a second.
OBSTACLE_SIZE_MULTIPLIER = 1.7
TRAP_ARM_PROBABILITY = 0.66
TRAP_SPAWN_COOLDOWN = 0.85

# Fake lag is a deliberate visual pause, never a dropped-frame performance problem.
FAKE_LAG_INTERVAL_MIN = 5.0
FAKE_LAG_INTERVAL_MAX = 9.0
FAKE_LAG_DURATION_MIN = 0.2
FAKE_LAG_DURATION_MAX = 0.5

PROJECT_ROOT = Path(__file__).resolve().parent
ASSET_ROOT = PROJECT_ROOT / "assets"
IMAGE_ASSETS = ASSET_ROOT / "images"
UI_IMAGE_ASSETS = IMAGE_ASSETS / "ui"
AUDIO_ASSETS = ASSET_ROOT / "audio"

WHITE = (245, 240, 220)
INK = (19, 24, 32)


def clamp(value, low, high):
    """Limit a numeric value to an inclusive range."""
    return max(low, min(high, value))


def mix_color(first, second, amount):
    """Blend two RGB colors, used to make damage visibly alter the world."""
    amount = clamp(amount, 0.0, 1.0)
    return tuple(round(a + (b - a) * amount) for a, b in zip(first, second))


def load_optional_sound(path):
    """Load an optional file from assets/audio, or silently keep procedural audio-free play."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return pygame.mixer.Sound(str(path))
    except (pygame.error, OSError):
        return None


class AudioManager:
    """Loads optional effects and owns the looping grounded-footstep channel."""

    SOUND_FILES = {
        "jump": "jump.wav",
        "run": "run.wav",
        "land": "land.wav",
        "damage": "damage.wav",
        "start": "start.wav",
    }

    def __init__(self):
        self.sounds = {
            name: load_optional_sound(AUDIO_ASSETS / filename)
            for name, filename in self.SOUND_FILES.items()
        }
        self.run_channel = None

    def play(self, name):
        sound = self.sounds.get(name)
        if sound is not None:
            sound.play()

    def set_running(self, should_run):
        """Loop footsteps only while moving on the ground; stop on jump, fall, or pause."""
        run_sound = self.sounds.get("run")
        if run_sound is None:
            return
        if should_run:
            if self.run_channel is None or not self.run_channel.get_busy():
                self.run_channel = run_sound.play(loops=-1)
        elif self.run_channel is not None:
            self.run_channel.stop()
            self.run_channel = None

    def stop_all(self):
        self.set_running(False)


class Platform:
    """A one-way platform which can be marked to crumble after a warning."""

    def __init__(self, x, y, width, height=18):
        self.rect = pygame.Rect(x, y, width, height)
        self.alive = True
        self.break_timer = None
        self.respawn_timer = None

    def update(self, dt):
        if self.break_timer is not None:
            self.break_timer -= dt
            if self.break_timer <= 0:
                self.alive = False
                self.break_timer = None
                self.respawn_timer = PLATFORM_RESPAWN_DELAY
        elif not self.alive and self.respawn_timer is not None:
            self.respawn_timer -= dt
            if self.respawn_timer <= 0:
                self.alive = True
                self.respawn_timer = None

    def draw(self, surface, camera_x, damage, offset_y=0):
        if not self.alive:
            return

        draw_rect = self.rect.move(-round(camera_x), round(offset_y))
        base = mix_color((67, 112, 109), (115, 47, 55), damage)
        top = mix_color((116, 190, 158), (238, 102, 80), damage)
        pygame.draw.rect(surface, base, draw_rect)
        pygame.draw.rect(surface, top, (draw_rect.x, draw_rect.y, draw_rect.width, 5))

        # Small, regular marks sell the blocky pixel-art look.
        for tile_x in range(draw_rect.x + 8, draw_rect.right, 24):
            pygame.draw.rect(surface, mix_color(base, (28, 46, 52), 0.38),
                             (tile_x, draw_rect.y + 8, 12, 3))

        if self.break_timer is not None:
            # Flashing yellow cracks warn that this ledge is about to vanish.
            flash = int(pygame.time.get_ticks() / 75) % 2 == 0
            if flash:
                pygame.draw.line(surface, (255, 226, 90),
                                 (draw_rect.left + 8, draw_rect.top + 2),
                                 (draw_rect.centerx, draw_rect.bottom - 2), 3)
                pygame.draw.line(surface, (255, 226, 90),
                                 (draw_rect.centerx, draw_rect.bottom - 2),
                                 (draw_rect.right - 10, draw_rect.top + 3), 2)


class Player:
    """Player physics plus a procedural animated stick-figure renderer."""

    WIDTH = 26
    HEIGHT = 58

    def __init__(self, x, y, audio=None):
        self.rect = pygame.Rect(x, y, self.WIDTH, self.HEIGHT)
        self.audio = audio
        self.velocity_x = 0.0
        self.velocity_y = 0.0
        self.grounded = False
        self.coyote_time = 0.0
        self.facing = 1
        self.animation_time = 0.0
        self.drop_timer = 0.0

    def jump(self):
        if self.grounded or self.coyote_time > 0:
            self.velocity_y = -585
            self.grounded = False
            self.coyote_time = 0.0
            if self.audio is not None:
                self.audio.play("jump")
                self.audio.set_running(False)
            return True
        return False

    def update(self, dt, keys, platforms):
        previous_grounded = self.grounded
        incoming_fall_speed = max(0.0, self.velocity_y)
        self.grounded = False
        self.drop_timer = max(0.0, self.drop_timer - dt)
        self.animation_time += dt

        horizontal = int(keys[pygame.K_d]) - int(keys[pygame.K_a])
        self.velocity_x = horizontal * 265
        if horizontal:
            self.facing = horizontal

        # S is both a drop-through command and a faster-fall modifier.
        gravity = 1550 if not keys[pygame.K_s] else 2200
        self.velocity_y = min(self.velocity_y + gravity * dt, 900)

        self.rect.x += round(self.velocity_x * dt)
        self.rect.x = clamp(self.rect.x, 0, WORLD_WIDTH - self.rect.width)

        old_bottom = self.rect.bottom
        self.rect.y += round(self.velocity_y * dt)

        # One-way collision only considers downward top crossings. There is deliberately
        # no underside/ceiling collision, so rising players pass straight through ledges.
        if self.velocity_y >= 0 and self.drop_timer <= 0:
            for platform in platforms:
                if not platform.alive or platform.break_timer is not None:
                    continue
                overlaps_x = self.rect.right > platform.rect.left and self.rect.left < platform.rect.right
                crossed_top_downward = old_bottom <= platform.rect.top < self.rect.bottom
                if overlaps_x and crossed_top_downward:
                    self.rect.bottom = platform.rect.top
                    self.velocity_y = 0
                    self.grounded = True
                    break

        landed_hard = self.grounded and not previous_grounded
        if (landed_hard and incoming_fall_speed >= LANDING_SOUND_MIN_SPEED
                and self.audio is not None):
            self.audio.play("land")
        if self.audio is not None:
            self.audio.set_running(self.grounded and horizontal != 0)

        if self.grounded:
            self.coyote_time = 0.11
        else:
            self.coyote_time = max(0.0, self.coyote_time - dt)

        return previous_grounded

    def draw(self, surface, camera_x, invulnerable, offset_y=0):
        # Sinusoidal limb motion gives the stick figure distinct idle and walk loops.
        walking = abs(self.velocity_x) > 1 and self.grounded
        phase = self.animation_time * (13 if walking else 2.4)
        stride = math.sin(phase) * (10 if walking else 1.5)
        bob = abs(math.sin(phase * 2)) * (2 if walking else 1)
        center_x = self.rect.centerx - round(camera_x)
        top_y = self.rect.top + offset_y + bob
        ink = (235, 242, 232)
        if invulnerable and int(pygame.time.get_ticks() / 80) % 2:
            ink = (255, 111, 103)

        head = (round(center_x), round(top_y + 10))
        neck = (round(center_x), round(top_y + 20))
        shoulder_left = (round(center_x - 6), round(top_y + 24))
        shoulder_right = (round(center_x + 6), round(top_y + 24))
        hip_left = (round(center_x - 4), round(top_y + 41))
        hip_right = (round(center_x + 4), round(top_y + 41))

        pygame.draw.circle(surface, ink, head, 7, 3)
        pygame.draw.line(surface, ink, neck, (round(center_x), round(top_y + 40)), 3)
        pygame.draw.line(surface, ink, shoulder_left, shoulder_right, 3)

        arm_swing = stride * 0.72 if walking else math.sin(phase) * 2
        for shoulder, direction in ((shoulder_left, -1), (shoulder_right, 1)):
            elbow = (round(shoulder[0] + direction * 7 - arm_swing), round(top_y + 33))
            hand = (round(elbow[0] + direction * 3 - arm_swing * 0.25), round(top_y + 40))
            pygame.draw.line(surface, ink, shoulder, elbow, 3)
            pygame.draw.line(surface, ink, elbow, hand, 3)

        for hip, direction in ((hip_left, -1), (hip_right, 1)):
            foot_x = hip[0] + round(stride * direction)
            knee = (hip[0] + round(stride * direction * 0.45), round(top_y + 49))
            foot = (foot_x + self.facing * 4, round(top_y + 56))
            pygame.draw.line(surface, ink, hip, knee, 3)
            pygame.draw.line(surface, ink, knee, foot, 3)


class Anvil:
    """A heavy ceiling hazard that accelerates as it falls."""

    def __init__(self, x):
        self.rect = pygame.Rect(x - 17, -48, 34, 30)
        self.velocity_y = 80
        self.alive = True

    def update(self, dt):
        self.velocity_y = min(self.velocity_y + 1050 * dt, 850)
        self.rect.y += round(self.velocity_y * dt)
        if self.rect.top > SCREEN_HEIGHT + 40:
            self.alive = False

    def draw(self, surface, camera_x, offset_y=0):
        rect = self.rect.move(-round(camera_x), round(offset_y))
        pygame.draw.rect(surface, (57, 63, 69), rect)
        pygame.draw.rect(surface, (161, 174, 175), (rect.x + 5, rect.y, rect.width - 10, 8))
        pygame.draw.rect(surface, (39, 43, 49), (rect.x + 10, rect.y + 8, 14, 17))
        pygame.draw.rect(surface, (79, 87, 91), (rect.x + 3, rect.bottom - 6, rect.width - 6, 6))


class Spinner:
    """A fast rotating projectile aimed toward the player when it appears."""

    BASE_DRAW_RADIUS = 17
    DRAW_RADIUS = round(BASE_DRAW_RADIUS * OBSTACLE_SIZE_MULTIPLIER)
    HITBOX_RADIUS = round(14 * OBSTACLE_SIZE_MULTIPLIER)

    def __init__(self, x, y, target):
        self.x = float(x)
        self.y = float(y)
        self.angle = 0.0
        self.alive = True
        dx = target.centerx - self.x
        dy = target.centery - self.y
        distance = max(1.0, math.hypot(dx, dy))
        self.velocity_x = dx / distance * 380
        self.velocity_y = dy / distance * 380

    def update(self, dt):
        self.x += self.velocity_x * dt
        self.y += self.velocity_y * dt
        self.angle += dt * 18
        if self.x < -80 or self.x > WORLD_WIDTH + 80 or self.y < -100 or self.y > SCREEN_HEIGHT + 100:
            self.alive = False

    def rect(self):
        diameter = self.HITBOX_RADIUS * 2
        return pygame.Rect(round(self.x - self.HITBOX_RADIUS),
                           round(self.y - self.HITBOX_RADIUS), diameter, diameter)

    def draw(self, surface, camera_x, offset_y=0):
        center = (round(self.x - camera_x), round(self.y + offset_y))
        points = []
        for index in range(8):
            radius = self.DRAW_RADIUS if index % 2 == 0 else round(6 * OBSTACLE_SIZE_MULTIPLIER)
            angle = self.angle + index * math.tau / 8
            points.append((round(center[0] + math.cos(angle) * radius),
                           round(center[1] + math.sin(angle) * radius)))
        pygame.draw.polygon(surface, (244, 83, 77), points)
        pygame.draw.circle(surface, (255, 224, 131), center, 4)


class HomingRollingSpike:
    """A ground-hugging spiked wheel that accelerates toward the player's X position."""

    BASE_RADIUS = 19
    RADIUS = round(BASE_RADIUS * OBSTACLE_SIZE_MULTIPLIER)
    SPIKE_EXTENSION = round(8 * OBSTACLE_SIZE_MULTIPLIER)

    def __init__(self, x, target_x):
        self.x = float(x)
        self.y = GROUND_Y - self.RADIUS
        self.velocity_x = 0.0
        self.acceleration = 1120.0
        self.max_speed = 590.0
        self.angle = 0.0
        self.alive = True
        self.update_target = target_x

    def update(self, dt, target_x=None):
        if target_x is not None:
            self.update_target = target_x
        direction = 1 if self.update_target > self.x else -1
        self.velocity_x += direction * self.acceleration * dt
        self.velocity_x = clamp(self.velocity_x, -self.max_speed, self.max_speed)
        self.x += self.velocity_x * dt
        self.angle += self.velocity_x * dt / self.RADIUS
        if self.x < -self.RADIUS or self.x > WORLD_WIDTH + self.RADIUS:
            self.alive = False

    def rect(self):
        diameter = self.RADIUS * 2
        return pygame.Rect(round(self.x - self.RADIUS), round(self.y - self.RADIUS),
                           diameter, diameter)

    def draw(self, surface, camera_x, offset_y=0):
        center = (round(self.x - camera_x), round(self.y + offset_y))
        points = []
        for index in range(16):
            radius = (self.RADIUS + self.SPIKE_EXTENSION if index % 2 == 0
                      else self.RADIUS - round(4 * OBSTACLE_SIZE_MULTIPLIER))
            angle = self.angle + index * math.tau / 16
            points.append((round(center[0] + math.cos(angle) * radius),
                           round(center[1] + math.sin(angle) * radius)))
        pygame.draw.polygon(surface, (194, 59, 69), points)
        pygame.draw.circle(surface, (239, 186, 128), center, self.RADIUS - 5)
        pygame.draw.circle(surface, (54, 43, 48), center, 5)


class FallingPixel:
    """A small world fragment used to crumble platforms, the door, and scenery."""

    def __init__(self, x, y, size, color):
        self.x = float(x)
        self.y = float(y)
        self.size = size
        self.color = color
        self.velocity_x = random.uniform(-135, 135)
        self.velocity_y = random.uniform(-250, -45)
        self.spin = random.uniform(-8, 8)
        self.alive = True

    def update(self, dt):
        self.velocity_y = min(self.velocity_y + 690 * dt, 850)
        self.x += self.velocity_x * dt
        self.y += self.velocity_y * dt
        self.spin *= max(0.0, 1.0 - dt * 0.4)
        if self.y > SCREEN_HEIGHT + 50:
            self.alive = False

    def draw(self, surface, camera_x):
        screen_x = round(self.x - camera_x)
        if -self.size <= screen_x <= SCREEN_WIDTH:
            pygame.draw.rect(surface, self.color,
                             (screen_x, round(self.y), self.size, self.size))


class LeaningTower:
    """Parallax Tower of Pisa sprite, procedurally drawn if no PNG is provided."""

    SIZE = (132, 300)

    def __init__(self, image_path):
        self.image = None
        image_path = Path(image_path)
        if image_path.is_file():
            try:
                loaded = pygame.image.load(str(image_path)).convert_alpha()
                self.image = pygame.transform.smoothscale(loaded, self.SIZE)
            except (pygame.error, OSError):
                self.image = None
        if self.image is None:
            self.image = self._make_procedural_tower()

    @classmethod
    def _make_procedural_tower(cls):
        width, height = cls.SIZE
        tower = pygame.Surface((width, height), pygame.SRCALPHA)
        stone = (211, 194, 151)
        shade = (117, 104, 83)
        outline = (59, 65, 63)

        body = [(38, height - 20), (48, 22), (84, 22), (96, height - 20)]
        pygame.draw.polygon(tower, stone, body)
        pygame.draw.polygon(tower, outline, body, 3)
        pygame.draw.ellipse(tower, shade, (34, height - 31, 66, 20))
        pygame.draw.ellipse(tower, stone, (34, height - 37, 66, 17))

        # Repeated arcades make the silhouette read as a tiered Romanesque tower.
        for floor_y in range(46, height - 43, 37):
            pygame.draw.rect(tower, shade, (43, floor_y + 23, 49, 5))
            for column_x in (49, 61, 73, 85):
                pygame.draw.rect(tower, outline, (column_x, floor_y + 4, 3, 19))
                pygame.draw.arc(tower, outline,
                                (column_x - 2, floor_y - 1, 8, 13), 0, math.pi, 2)
            pygame.draw.line(tower, (241, 225, 188),
                             (49, floor_y + 2), (85, floor_y + 2), 3)

        pygame.draw.rect(tower, shade, (51, 15, 30, 8))
        pygame.draw.ellipse(tower, stone, (49, 8, 34, 14))
        return tower

    @staticmethod
    def angle_for_progress(player_progress):
        """Map level progress [0..1] to a clockwise fall angle in degrees."""
        progress = clamp(player_progress, 0.0, 1.0)
        return min(TOWER_MAX_LEAN_DEGREES, progress * TOWER_FALL_SPEED)

    def draw(self, surface, camera_x, player_progress, ground_y):
        # As progress grows, the tower rotates clockwise (negative Pygame angle) toward a fall.
        angle = self.angle_for_progress(player_progress)
        rotated = pygame.transform.rotate(self.image, -angle)

        # Slow parallax keeps the tower in view across most of the long level.
        base_x = round(SCREEN_WIDTH * 0.84 - camera_x * 0.30)
        destination = rotated.get_rect(midbottom=(base_x, ground_y))
        surface.blit(rotated, destination)


class Game:
    """Owns the level, input-driven trap system, camera, HUD, and main loop."""

    def __init__(self):
        pygame.init()
        # Mixer support is optional on headless systems; missing audio devices stay nonfatal.
        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init()
        except pygame.error:
            pass
        pygame.display.set_caption("Doorway Dash")
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.audio = AudioManager()
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 25)
        self.large_font = pygame.font.Font(None, 64)
        self.crash_font = pygame.font.SysFont("consolas", 22)
        self.crash_small_font = pygame.font.SysFont("consolas", 16)
        self.start_screen = StartScreen(IMAGE_ASSETS / "start_background.png")
        self.tower = LeaningTower(IMAGE_ASSETS / "leaning_tower.png")
        self.secret_effect = SecretGlitchEffect()
        self.running = True
        self.reset()

    def reset(self):
        self.audio.stop_all()
        self.player = Player(56, GROUND_Y - Player.HEIGHT, self.audio)
        self.health = 3
        self.camera_x = 0.0
        self.checkpoint_x = 56
        self.invulnerable_timer = 0.0
        self.game_state = "start"
        self.ending_timer = 0.0
        self.world_time = 0.0
        self.crumble_pixels = []
        self.secret_buffer = ""
        self.secret_return_state = "playing"
        self.secret_effect.active = False
        self.pending_trap = None
        self.trap_spawn_cooldown = 0.0
        self.input_count = 0
        self.fake_lag_timer = 0.0
        self.fake_lag_cooldown = random.uniform(FAKE_LAG_INTERVAL_MIN,
                               FAKE_LAG_INTERVAL_MAX)
        self.fake_lag_mode = "freeze"
        self.last_frame_surface = None
        self.trap_message = "Reach the doorway. The level reacts to every move."
        self.message_timer = 4.0
        self.traps = []
        self.platforms = [
            Platform(0, 440, 370, 100),
            Platform(440, 440, 220, 100),
            Platform(735, 440, 245, 100),
            Platform(1065, 440, 215, 100),
            Platform(1360, 440, 250, 100),
            Platform(1690, 440, 235, 100),
            Platform(1990, 440, 250, 100),
            Platform(2290, 440, 350, 100),
            Platform(2700, 440, 210, 100),
            Platform(2960, 440, 240, 100),
            Platform(3270, 440, 220, 100),
            Platform(3560, 440, 280, 100),
            Platform(290, 350, 108),
            Platform(575, 315, 105),
            Platform(850, 355, 112),
            Platform(1180, 320, 112),
            Platform(1510, 360, 115),
            Platform(1810, 310, 110),
            Platform(2140, 350, 112),
            Platform(2460, 320, 108),
            Platform(2780, 350, 112),
            Platform(3070, 305, 110),
            Platform(3370, 350, 112),
            Platform(3610, 320, 100),
        ]
        self.door = pygame.Rect(WORLD_WIDTH - 122, GROUND_Y - 88, 42, 88)
        self.held_keys = set()
        self.sky_details = self._make_sky_details()

    def _make_sky_details(self):
        """Generate deterministic pixel blocks so the scenery is stable each run."""
        rng = random.Random(41)
        buildings = []
        for x in range(0, WORLD_WIDTH + 180, 90):
            width = rng.randint(48, 82)
            height = rng.randint(55, 145)
            buildings.append((x, GROUND_Y - height, width, height))
        pixels = [(rng.randrange(WORLD_WIDTH), rng.randrange(50, 395), rng.choice((3, 4, 6)))
                  for _ in range(95)]
        return buildings, pixels

    def _arm_trap_from_input(self):
        """Randomly arm one trap on movement input; movement later crosses its trigger."""
        if (self.game_state != "playing" or self.pending_trap is not None
            or self.player.rect.centerx < SAFE_ZONE_END
            or self.trap_spawn_cooldown > 0):
            return

        self.input_count += 1
        # Slightly better than even odds over a handful of presses, but never on its own.
        if random.random() > TRAP_ARM_PROBABILITY:
            return
        self.trap_spawn_cooldown = TRAP_SPAWN_COOLDOWN

        candidates = [platform for platform in self.platforms
                      if platform.alive and platform.break_timer is None
                      and platform.rect.centerx > self.player.rect.right + 65
                      and platform.rect.centerx < self.player.rect.right + 620]
        kinds = ["anvil", "spinner", "rolling_spike"]
        if candidates:
            kinds.append("crumble")
        kind = random.choice(kinds)

        if kind == "crumble":
            platform = min(candidates, key=lambda item: item.rect.left)
            self.pending_trap = {"kind": kind, "platform": platform}
            self._set_message("AHEAD: one of these ledges is ready to crumble.", 2.2)
        else:
            trigger_x = self.player.rect.centerx + random.randint(155, 350)
            self.pending_trap = {"kind": kind, "x": trigger_x}
            if kind == "anvil":
                self._set_message("AHEAD: something is waiting above the path.", 2.2)
            elif kind == "spinner":
                self._set_message("AHEAD: a fast-moving surprise is armed.", 2.2)
            else:
                self._set_message("AHEAD: a rolling spike is tracking your route.", 2.2)

    def _set_message(self, message, duration):
        self.trap_message = message
        self.message_timer = duration

    def _listen_for_secret(self, event):
        """Recognize GLITCH in the menu or normal play without blocking movement keys."""
        if self.game_state not in ("start", "playing"):
            return False
        letter = event.unicode.lower()
        if len(letter) != 1 or not letter.isalpha():
            return False

        self.secret_buffer = (self.secret_buffer + letter)[-len("glitch"):]
        if self.secret_buffer == "glitch":
            self.secret_return_state = self.game_state
            self.game_state = "secret_glitch"
            self.secret_buffer = ""
            self.secret_effect.start()
            return True
        return False

    def handle_event(self, event):
        if event.type == pygame.QUIT:
            self.running = False
            return
        if event.type == pygame.KEYUP:
            self.held_keys.discard(event.key)
            return
        if event.type != pygame.KEYDOWN:
            return

        if event.key == pygame.K_ESCAPE:
            self.running = False
            return
        if self.fake_lag_timer > 0:
            # Keep movement input from accumulating while the visual frame is frozen.
            return
        if self._listen_for_secret(event):
            return

        if self.game_state == "start":
            if event.key == pygame.K_SPACE:
                self.game_state = "playing"
                self.audio.play("start")
            return
        if self.game_state == "secret_glitch":
            return
        if self.game_state != "playing":
            if event.key == pygame.K_r:
                self.reset()
            return

        if event.key in (pygame.K_a, pygame.K_d, pygame.K_w, pygame.K_s):
            if event.key not in self.held_keys:
                self.held_keys.add(event.key)
                self._arm_trap_from_input()
            if event.key == pygame.K_w:
                self.player.jump()
            elif event.key == pygame.K_s:
                # Pressing down briefly disables ledge collision for a drop-through.
                self.player.drop_timer = 0.20
                self.player.rect.y += 3

    def _process_pending_trap(self):
        # Enforce the spawn buffer even if the player walks back into it with a pending trap.
        if self.player.rect.centerx < SAFE_ZONE_END:
            self.pending_trap = None
            self.traps.clear()
            return
        if self.pending_trap is None:
            return

        trap = self.pending_trap
        if trap["kind"] == "crumble":
            platform = trap["platform"]
            near_platform = (self.player.rect.right > platform.rect.left - 8
                             and self.player.rect.left < platform.rect.right + 8)
            approaching_top = (self.player.velocity_y >= 0
                               and self.player.rect.bottom <= platform.rect.top + 76)
            if near_platform and approaching_top:
                platform.break_timer = 0.18
                self.pending_trap = None
                self._set_message("CRUMBLE! Keep moving!", 1.6)
            elif self.player.rect.left > platform.rect.right + 80:
                self.pending_trap = None
        elif self.player.rect.centerx >= trap["x"]:
            if trap["kind"] == "anvil":
                self.traps.append(Anvil(trap["x"]))
                self._set_message("ANVIL DROP!", 1.5)
            elif trap["kind"] == "spinner":
                spawn_y = self.player.rect.centery + random.randint(-72, 72)
                self.traps.append(Spinner(trap["x"], spawn_y, self.player.rect))
                self._set_message("SPINNER INCOMING!", 1.5)
            else:
                # The trigger is crossed as the player passes; the wheel spawns farther ahead.
                self.traps.append(HomingRollingSpike(trap["x"] + 110,
                                                     self.player.rect.centerx))
                self._set_message("ROLLING SPIKE! Jump or evade!", 1.7)
            self.pending_trap = None

    def _begin_glitch_ending(self):
        """Freeze gameplay and start the deliberately alarming door fake-out."""
        self.game_state = "glitch_shake"
        self.ending_timer = 0.0
        self.pending_trap = None
        self.player.velocity_x = 0
        self.player.velocity_y = 0

    def _seed_crumble_pixels(self):
        """Replace visible world geometry with colored falling pixel fragments."""
        rng = random.Random(404)
        damage = (3 - self.health) / 2
        platform_colors = (
            mix_color((67, 112, 109), (115, 47, 55), damage),
            mix_color((116, 190, 158), (238, 102, 80), damage),
            (37, 49, 55),
        )

        # Divide each platform into small cells, then give every cell its own fall arc.
        for platform in self.platforms:
            if not platform.alive:
                continue
            for y in range(platform.rect.top, platform.rect.bottom, 12):
                for x in range(platform.rect.left, platform.rect.right, 12):
                    self.crumble_pixels.append(FallingPixel(
                        x, y, rng.randint(6, 11), rng.choice(platform_colors)))
            platform.alive = False

        # Break the doorway into a frame and darker inner-door pixels.
        for y in range(self.door.top, self.door.bottom, 8):
            for x in range(self.door.left, self.door.right, 8):
                on_frame = (x < self.door.left + 8 or x >= self.door.right - 8
                            or y < self.door.top + 8)
                color = (231, 220, 184) if on_frame else (27, 28, 33)
                self.crumble_pixels.append(FallingPixel(x, y, 7, color))

        # Only nearby parallax scenery needs fragments: the camera is fixed during the finale.
        camera_x = clamp(self.player.rect.centerx - SCREEN_WIDTH * 0.5,
                         0, WORLD_WIDTH - SCREEN_WIDTH)
        buildings, sky_pixels = self.sky_details
        for x, y, width, height in buildings:
            screen_x = x - camera_x * 0.38
            if screen_x > SCREEN_WIDTH or screen_x + width < 0:
                continue
            world_x = x + camera_x * 0.62
            for pixel_y in range(y, y + height, 14):
                for pixel_x in range(x, x + width, 14):
                    if rng.random() < 0.84:
                        self.crumble_pixels.append(FallingPixel(
                            world_x + pixel_x - x, pixel_y, 10,
                            mix_color((41, 88, 99), (79, 43, 57), damage)))

        for x, y, size in sky_pixels:
            if -size <= x - camera_x * 0.22 <= SCREEN_WIDTH:
                self.crumble_pixels.append(FallingPixel(
                    x + camera_x * 0.78, y, size,
                    mix_color((129, 195, 174), (247, 102, 79), damage)))

    def _advance_ending(self, dt):
        """Advance shake -> crumble -> fake crash; durations are tuning constants above."""
        self.ending_timer += dt
        if self.game_state == "glitch_shake":
            if self.ending_timer >= GLITCH_SHAKE_DURATION:
                self.game_state = "glitch_crumble"
                self.ending_timer = 0.0
                self._seed_crumble_pixels()
        elif self.game_state == "glitch_crumble":
            for pixel in self.crumble_pixels:
                pixel.update(dt)
            self.crumble_pixels = [pixel for pixel in self.crumble_pixels if pixel.alive]
            if self.ending_timer >= GLITCH_CRUMBLE_DURATION:
                self.game_state = "glitch_crash"
                self.ending_timer = 0.0

    def _shake_offset(self):
        """Return intense finale shake or the adjustable subtle normal-play shake."""
        if self.game_state == "glitch_shake":
            progress = clamp(self.ending_timer / GLITCH_SHAKE_DURATION, 0, 1)
            strength = GLITCH_SHAKE_INTENSITY * (1.0 - progress * 0.45)
            time_value = self.ending_timer
            x = math.sin(time_value * 61) * strength + random.uniform(-strength * 0.55, strength * 0.55)
            y = math.cos(time_value * 53) * strength + random.uniform(-strength * 0.55, strength * 0.55)
            return round(x), round(y)

        if self.game_state in ("playing", "secret_glitch"):
            # Two close frequencies keep the baseline shake subtle but never perfectly static.
            phase = self.world_time * math.tau * BASE_SHAKE_FREQUENCY
            x = math.sin(phase) * BASE_SHAKE_INTENSITY
            y = math.cos(phase * 0.83) * BASE_SHAKE_INTENSITY * 0.7
            return round(x), round(y)
        return 0, 0

    def _damage_player(self, reason):
        if self.invulnerable_timer > 0 or self.game_state != "playing":
            return

        self.health -= 1
        self.audio.play("damage")
        self.audio.set_running(False)
        self.invulnerable_timer = 1.35
        self.player.rect.x = self.checkpoint_x
        self.player.rect.bottom = GROUND_Y - Player.HEIGHT + Player.HEIGHT
        self.player.velocity_x = 0
        self.player.velocity_y = 0
        self.player.grounded = True
        self.pending_trap = None
        self._set_message(reason, 2.0)
        if self.health <= 0:
            self.health = 0
            self.game_state = "lost"

    def _advance_fake_lag(self, dt):
        """Pause the whole simulation during a short freeze/tearing visual event."""
        if self.fake_lag_timer > 0:
            self.fake_lag_timer = max(0.0, self.fake_lag_timer - dt)
            if self.fake_lag_timer == 0:
                self.fake_lag_cooldown = random.uniform(FAKE_LAG_INTERVAL_MIN,
                                                        FAKE_LAG_INTERVAL_MAX)
            return True

        self.fake_lag_cooldown -= dt
        if self.fake_lag_cooldown <= 0 and self.last_frame_surface is not None:
            self.fake_lag_timer = random.uniform(FAKE_LAG_DURATION_MIN,
                                                 FAKE_LAG_DURATION_MAX)
            self.fake_lag_mode = random.choice(("freeze", "tear"))
            self.audio.set_running(False)
            return True
        return False

    def update(self, dt):
        if self.game_state == "start":
            self.world_time += dt
            self.start_screen.update(dt)
            return

        if self.game_state == "secret_glitch":
            self.world_time += dt
            if not self.secret_effect.update(dt):
                self.game_state = self.secret_return_state
            return

        if self.game_state.startswith("glitch_"):
            self._advance_ending(dt)
            return

        if self.game_state != "playing":
            self.message_timer = max(0.0, self.message_timer - dt)
            return

        # Fake lag intentionally pauses physics, timers, and audio for its full visual duration.
        if self._advance_fake_lag(dt):
            return

        self.world_time += dt
        self.trap_spawn_cooldown = max(0.0, self.trap_spawn_cooldown - dt)
        self.invulnerable_timer = max(0.0, self.invulnerable_timer - dt)
        self.message_timer = max(0.0, self.message_timer - dt)

        for platform in self.platforms:
            platform.update(dt)

        self._process_pending_trap()
        self.player.update(dt, pygame.key.get_pressed(), self.platforms)
        if self.player.rect.centerx < SAFE_ZONE_END:
            self.pending_trap = None
            self.traps.clear()

        # Record a simple checkpoint every few hundred pixels while safely grounded.
        if self.player.grounded and self.player.rect.x - self.checkpoint_x > 520:
            self.checkpoint_x = self.player.rect.x
            self._set_message("Checkpoint reached.", 1.6)

        for hazard in self.traps:
            if isinstance(hazard, HomingRollingSpike):
                hazard.update(dt, self.player.rect.centerx)
            else:
                hazard.update(dt)
            hazard_rect = hazard.rect() if callable(getattr(hazard, "rect", None)) else hazard.rect
            if hazard.alive and self.player.rect.colliderect(hazard_rect):
                hazard.alive = False
                self._damage_player("A hazard got you. Back to the checkpoint.")
        self.traps = [hazard for hazard in self.traps if hazard.alive]

        if self.player.rect.top > SCREEN_HEIGHT + 60:
            self._damage_player("Mind the gaps. Back to the checkpoint.")

        if self.player.rect.colliderect(self.door):
            self._begin_glitch_ending()

        # Keep the player inside a horizontal dead zone; center them when they cross it.
        player_screen_x = self.player.rect.centerx - self.camera_x
        target_camera = self.camera_x
        if player_screen_x < SCREEN_WIDTH * CAMERA_SAFE_LEFT or player_screen_x > SCREEN_WIDTH * CAMERA_SAFE_RIGHT:
            target_camera = self.player.rect.centerx - SCREEN_WIDTH * 0.5
        target_camera = clamp(target_camera, 0, WORLD_WIDTH - SCREEN_WIDTH)
        self.camera_x += (target_camera - self.camera_x) * min(1.0, dt * 5)

    def draw_background(self, camera_x=None, offset_y=0):
        if camera_x is None:
            camera_x = self.camera_x
        damage = (3 - self.health) / 2
        sky = mix_color((37, 69, 91), (72, 28, 43), damage)
        self.screen.fill(sky)

        buildings, pixels = self.sky_details
        for x, y, size in pixels:
            screen_x = round(x - camera_x * 0.22)
            if -size <= screen_x <= SCREEN_WIDTH:
                color = mix_color((129, 195, 174), (247, 102, 79), damage)
                pygame.draw.rect(self.screen, color,
                                 (screen_x, y + round(offset_y), size, size))

        for x, y, width, height in buildings:
            screen_x = round(x - camera_x * 0.38)
            if screen_x > SCREEN_WIDTH or screen_x + width < 0:
                continue
            building_color = mix_color((41, 88, 99), (79, 43, 57), damage)
            window_color = mix_color((224, 193, 112), (238, 92, 71), damage)
            pygame.draw.rect(self.screen, building_color,
                             (screen_x, y + round(offset_y), width, height))
            for window_y in range(y + 12, GROUND_Y - 10, 22):
                for window_x in range(screen_x + 8, screen_x + width - 5, 18):
                    if (window_x // 18 + window_y // 22) % 3:
                        pygame.draw.rect(self.screen, window_color,
                                         (window_x, window_y + round(offset_y), 5, 7))

                progress = clamp(self.player.rect.centerx / WORLD_WIDTH, 0.0, 1.0)
                self.tower.draw(self.screen, camera_x, progress,
                        GROUND_Y + 18 + round(offset_y))

        # A dark ground band fills the gaps visually without acting as a platform.
        ground = mix_color((26, 43, 48), (41, 27, 35), damage)
        pygame.draw.rect(self.screen, ground,
                         (0, GROUND_Y + 18 + round(offset_y), SCREEN_WIDTH, SCREEN_HEIGHT))

    def draw_door(self, camera_x=None, offset_y=0):
        if camera_x is None:
            camera_x = self.camera_x
        rect = self.door.move(-round(camera_x), round(offset_y))
        pygame.draw.rect(self.screen, (27, 28, 33), rect)
        pygame.draw.rect(self.screen, (231, 220, 184), rect, 3)
        pygame.draw.circle(self.screen, (244, 188, 83), (rect.right - 9, rect.centery + 8), 2)

    def draw_hud(self):
        # Compact health marks and level progress stay readable during scrolling.
        label = self.font.render("HEALTH", True, WHITE)
        self.screen.blit(label, (18, 15))
        for index in range(3):
            color = (242, 91, 83) if index < self.health else (79, 67, 73)
            pygame.draw.rect(self.screen, color, (97 + index * 24, 17, 16, 14))

        progress = clamp(self.player.rect.centerx / WORLD_WIDTH, 0, 1)
        pygame.draw.rect(self.screen, (29, 35, 40), (SCREEN_WIDTH - 222, 19, 202, 10))
        pygame.draw.rect(self.screen, (126, 220, 170),
                         (SCREEN_WIDTH - 220, 21, round(198 * progress), 6))
        controls = self.font.render("A/D move   W jump   S drop", True, (215, 222, 216))
        self.screen.blit(controls, (18, SCREEN_HEIGHT - 31))

        if self.message_timer > 0 and self.trap_message:
            message = self.font.render(self.trap_message, True, (255, 230, 156))
            message_rect = message.get_rect(center=(SCREEN_WIDTH // 2, 32))
            self.screen.blit(message, message_rect)

    def draw_overlay(self, title, subtitle):
        shade = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        shade.fill((8, 12, 18, 190))
        self.screen.blit(shade, (0, 0))
        title_image = self.large_font.render(title, True, (250, 226, 165))
        subtitle_image = self.font.render(subtitle, True, WHITE)
        self.screen.blit(title_image, title_image.get_rect(center=(SCREEN_WIDTH // 2, 235)))
        self.screen.blit(subtitle_image, subtitle_image.get_rect(center=(SCREEN_WIDTH // 2, 292)))

    def draw_crash_screen(self):
        """Paint a fake blue-screen crash with fresh static and tearing every frame."""
        self.screen.fill((5, 17, 62))

        # Random pixel noise and horizontal tears make this unmistakably a fake glitch.
        for _ in range(520):
            x = random.randrange(SCREEN_WIDTH)
            y = random.randrange(SCREEN_HEIGHT)
            color = random.choice(((20, 55, 145), (68, 108, 190),
                                   (165, 197, 238), (3, 10, 39)))
            pygame.draw.rect(self.screen, color,
                             (x, y, random.randint(1, 5), random.randint(1, 3)))
        for _ in range(9):
            tear_y = random.randrange(SCREEN_HEIGHT)
            tear_x = random.randrange(-100, SCREEN_WIDTH)
            pygame.draw.rect(self.screen, random.choice(((94, 144, 215), (10, 28, 91))),
                             (tear_x, tear_y, random.randint(80, 420), random.randint(2, 8)))
        for scan_y in range(0, SCREEN_HEIGHT, 5):
            pygame.draw.line(self.screen, (8, 22, 69), (0, scan_y),
                             (SCREEN_WIDTH, scan_y), 1)

        white = (238, 244, 255)
        center_x = SCREEN_WIDTH // 2
        lines = (
            (":(  SYSTEM FAILURE", 150, self.crash_font),
            ("YOUR LEVEL RAN INTO A PROBLEM", 208, self.crash_font),
            ("FATAL EXCEPTION: LEVEL_DEVIL_OVERFLOW", 260, self.crash_font),
            ("If you see this screen, the doorway was a trap.", 316, self.crash_small_font),
            ("Press ESC to close this totally normal game.", 346, self.crash_small_font),
        )
        for text, y, font in lines:
            image = font.render(text, True, white)
            self.screen.blit(image, image.get_rect(center=(center_x, y)))

    def draw_fake_lag(self):
        """Replay the last complete frame, optionally shifting copied horizontal bands."""
        if self.last_frame_surface is None:
            self.screen.fill((7, 10, 18))
            return

        self.screen.blit(self.last_frame_surface, (0, 0))
        if self.fake_lag_mode != "tear":
            return

        for _ in range(14):
            band_y = random.randrange(SCREEN_HEIGHT)
            band_height = random.randint(3, 17)
            band_rect = pygame.Rect(0, band_y, SCREEN_WIDTH,
                                    min(band_height, SCREEN_HEIGHT - band_y))
            band = self.last_frame_surface.subsurface(band_rect).copy()
            self.screen.blit(band, (random.randint(-58, 58), band_y))
            pygame.draw.line(self.screen, (220, 244, 255),
                             (0, band_y), (SCREEN_WIDTH, band_y), 1)

    def draw(self):
        if self.game_state == "glitch_crash":
            self.draw_crash_screen()
            pygame.display.flip()
            return

        if self.game_state == "glitch_crumble":
            self.screen.fill((15, 21, 29))
            for pixel in self.crumble_pixels:
                pixel.draw(self.screen, self.camera_x)
            pygame.display.flip()
            return

        if self.fake_lag_timer > 0:
            self.draw_fake_lag()
            pygame.display.flip()
            return

        if self.game_state == "start" or (
                self.game_state == "secret_glitch" and self.secret_return_state == "start"):
            self.start_screen.draw(self.screen, self.large_font, self.font,
                                   self.crash_small_font)
            if self.game_state == "secret_glitch":
                self.secret_effect.apply(self.screen)
            pygame.display.flip()
            return

        damage = (3 - self.health) / 2
        shake_x, shake_y = self._shake_offset()
        render_camera_x = self.camera_x + shake_x
        self.draw_background(render_camera_x, shake_y)

        for platform in self.platforms:
            platform.draw(self.screen, render_camera_x, damage, shake_y)

        self.draw_door(render_camera_x, shake_y)
        for hazard in self.traps:
            hazard.draw(self.screen, render_camera_x, shake_y)

        character_layer = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        self.player.draw(character_layer, render_camera_x,
                         self.invulnerable_timer > 0, shake_y)
        self.screen.blit(character_layer, (0, 0))
        self.draw_hud()

        if self.game_state == "lost":
            self.draw_overlay("OUT OF HEALTH", "Press R to try again")
        elif self.game_state == "secret_glitch":
            self.secret_effect.apply(self.screen, character_layer)

        if self.game_state == "playing":
            self.last_frame_surface = self.screen.copy()
        pygame.display.flip()

    def run(self):
        while self.running:
            dt = min(self.clock.tick(FPS) / 1000.0, 0.035)
            for event in pygame.event.get():
                self.handle_event(event)
            self.update(dt)
            self.draw()

        pygame.quit()
        sys.exit(0)


if __name__ == "__main__":
    Game().run()

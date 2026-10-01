"""Procedural title screen with an optional background image asset."""

import math
import random
from pathlib import Path

import pygame


class StartScreen:
    """Draws the start menu and falls back to procedural art when no image exists."""

    def __init__(self, background_path):
        self.background = None
        self.elapsed = 0.0
        self.pixel_blocks = []
        rng = random.Random(82)
        for _ in range(70):
            self.pixel_blocks.append((rng.randrange(960), rng.randrange(90, 500),
                                      rng.choice((3, 5, 7)), rng.choice((0, 1, 2))))

        # Art is optional: this project remains playable with an empty assets/images folder.
        background_path = Path(background_path)
        if background_path.is_file():
            try:
                self.background = pygame.image.load(str(background_path)).convert()
            except (pygame.error, OSError):
                self.background = None

    def update(self, dt):
        self.elapsed += dt

    def draw(self, surface, title_font, prompt_font, small_font):
        width, height = surface.get_size()
        if self.background is not None:
            surface.blit(pygame.transform.scale(self.background, (width, height)), (0, 0))
        else:
            surface.fill((15, 28, 43))
            pygame.draw.rect(surface, (24, 44, 57), (0, height // 2, width, height // 2))
            for index, (x, y, size, color_index) in enumerate(self.pixel_blocks):
                color = ((36, 81, 90), (50, 110, 104), (86, 62, 79))[color_index]
                drift_x = round(math.sin(self.elapsed * 0.3 + index) * 3)
                pygame.draw.rect(surface, color, (x + drift_x, y, size, size))

            # A spare, block-built doorway anchors the menu artwork without external assets.
            door = pygame.Rect(width - 170, height - 210, 72, 150)
            pygame.draw.rect(surface, (8, 15, 24), door)
            pygame.draw.rect(surface, (204, 211, 183), door, 4)
            pygame.draw.circle(surface, (246, 186, 78), (door.right - 14, door.centery + 16), 4)

        for y in range(0, height, 5):
            pygame.draw.line(surface, (19, 34, 48), (0, y), (width, y), 1)

        title = title_font.render("Totally Stable", True, (244, 239, 217))
        title_rect = title.get_rect(center=(width // 2, height // 2 - 62))
        shadow = title_font.render("Totally Stable", True, (35, 20, 35))
        surface.blit(shadow, title_rect.move(4, 5))
        surface.blit(title, title_rect)

        pulse = 0.5 + 0.5 * math.sin(self.elapsed * 4.0)
        prompt_color = (round(120 + pulse * 115), round(195 + pulse * 50), 190)
        prompt = prompt_font.render("Press SPACE to Start", True, prompt_color)
        surface.blit(prompt, prompt.get_rect(center=(width // 2, height // 2 + 20)))
        controls = small_font.render("A / D move     W jump     S drop", True, (194, 206, 207))
        surface.blit(controls, controls.get_rect(center=(width // 2, height // 2 + 65)))

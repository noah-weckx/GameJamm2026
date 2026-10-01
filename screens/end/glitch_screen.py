"""A short, original neon dimensional-glitch effect for the secret key sequence."""

import random

import pygame


class SecretGlitchEffect:
    """Apply RGB splitting, horizontal tearing, and character-local neon flashes."""

    def __init__(self, duration=3.6):
        self.duration = duration
        self.elapsed = 0.0
        self.active = False
        self.rng = random.Random()

    def start(self):
        self.elapsed = 0.0
        self.active = True

    def update(self, dt):
        if not self.active:
            return False
        self.elapsed += dt
        if self.elapsed >= self.duration:
            self.active = False
        return self.active

    @staticmethod
    def _invert_visible_pixels(surface):
        """Invert only nontransparent character pixels, not the full-screen scene."""
        bounds = surface.get_bounding_rect()
        if bounds.width == 0 or bounds.height == 0:
            return

        pixels = pygame.PixelArray(surface)
        for x in range(bounds.left, bounds.right):
            for y in range(bounds.top, bounds.bottom):
                color = surface.unmap_rgb(pixels[x, y])
                pixels[x, y] = surface.map_rgb(
                    (255 - color.r, 255 - color.g, 255 - color.b, color.a))
        del pixels

    def apply(self, surface, character_layer=None):
        if not self.active:
            return

        width, height = surface.get_size()
        source = surface.copy()

        # RGB channel offsets create chromatic aberration; raise split_px for a stronger tear.
        split_px = 5 + round(4 * abs(self.rng.uniform(-1.0, 1.0)))
        for tint, offset, alpha in (
            ((255, 36, 120), (-split_px, 0), 100),
            ((40, 238, 255), (split_px, 0), 115),
        ):
            channel = source.copy()
            channel.fill(tint, special_flags=pygame.BLEND_RGB_MULT)
            channel.set_alpha(alpha)
            surface.blit(channel, offset)

        # Jagged horizontal slices are copied from the original frame and shifted sideways.
        torn_source = surface.copy()
        band_count = 13
        for _ in range(band_count):
            band_y = self.rng.randrange(height)
            band_height = self.rng.randint(2, 15)
            band_rect = pygame.Rect(0, band_y, width, min(band_height, height - band_y))
            band = torn_source.subsurface(band_rect).copy()
            surface.blit(band, (self.rng.randint(-42, 42), band_y))

        # Keep the fastest neon/inverted flashes isolated to the transparent player layer.
        if character_layer is not None and round(self.elapsed * 18) % 2 == 0:
            neon = character_layer.copy()
            tint = self.rng.choice(((255, 35, 205), (30, 250, 255), (255, 235, 40)))
            neon.fill((*tint, 255), special_flags=pygame.BLEND_RGBA_MULT)
            if self.rng.random() < 0.35:
                self._invert_visible_pixels(neon)
            neon.set_alpha(225)
            surface.blit(neon, (self.rng.randint(-3, 3), self.rng.randint(-2, 2)))

        # Brief whole-frame polarity flashes punctuate the effect without staying inverted.
        if self.rng.random() < 0.12:
            inverted = source.copy()
            inverted.fill((255, 255, 255), special_flags=pygame.BLEND_RGB_SUB)
            inverted.set_alpha(105)
            surface.blit(inverted, (0, 0))

"""Asset-optional Xingbao animation state machine."""

import math
import random

import pygame

IDLE = "idle"
THINKING = "thinking"
HAPPY = "happy"
ENCOURAGE = "encourage"
CELEBRATE = "celebrate"
STATES = (IDLE, THINKING, HAPPY, ENCOURAGE, CELEBRATE)


class XingbaoAnimator:
    def __init__(self):
        self.state = IDLE
        self.time = 0.0
        self.state_time = 0.0
        self.random = random.Random(2026)

    def set_state(self, state):
        state = state if state in STATES else IDLE
        if state != self.state:
            self.state = state
            self.state_time = 0.0

    def update(self, dt):
        dt = max(0.0, float(dt))
        self.time += dt
        self.state_time += dt

    def render(self, image):
        if image is None:
            return None
        scale = 1.02 + math.sin(self.time * 2.1) * 0.02
        angle = 0.0
        jump = 0
        if self.state == THINKING:
            angle = math.sin(self.time * 2.0) * 3.0
        elif self.state == HAPPY:
            scale += max(0.0, math.sin(self.state_time * 7.0)) * 0.06
            jump = int(max(0.0, math.sin(self.state_time * 7.0)) * 8)
        elif self.state == ENCOURAGE:
            angle = math.sin(self.time * 4.0) * 2.5
        elif self.state == CELEBRATE:
            scale += max(0.0, math.sin(self.state_time * 8.0)) * 0.10
            jump = int(max(0.0, math.sin(self.state_time * 8.0)) * 12)
        rendered = pygame.transform.rotozoom(image, angle, scale)
        canvas = pygame.Surface((rendered.get_width() + 28, rendered.get_height() + 36), pygame.SRCALPHA)
        canvas.blit(rendered, rendered.get_rect(center=(canvas.get_width() // 2, canvas.get_height() // 2 - jump)))
        color = (255, 220, 90, 210) if self.state in (HAPPY, CELEBRATE) else (80, 225, 255, 150)
        count = 8 if self.state == CELEBRATE else 4
        for index in range(count):
            phase = self.time * (0.7 + index * 0.08) + index
            x = int(canvas.get_width() / 2 + math.cos(phase) * canvas.get_width() * 0.38)
            y = int(canvas.get_height() / 2 + math.sin(phase * 1.3) * canvas.get_height() * 0.36)
            pygame.draw.circle(canvas, color, (x, y), 2 + index % 2)
        if int(self.time * 2.0) % 13 == 0:
            blink = pygame.Surface(canvas.get_size(), pygame.SRCALPHA)
            pygame.draw.ellipse(blink, (10, 20, 45, 55), blink.get_rect().inflate(-30, -18))
            canvas.blit(blink, (0, 0))
        return canvas

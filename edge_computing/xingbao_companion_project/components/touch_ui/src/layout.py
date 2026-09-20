import pygame

from . import theme


class Layout:
    def __init__(self, size):
        self.width, self.height = (max(640, int(size[0])), max(400, int(size[1])))
        self.scale = min(self.width / theme.BASE_WIDTH, self.height / theme.BASE_HEIGHT)
        self.margin = max(18, round(theme.PAGE_MARGIN * self.scale))
        self.gap = max(8, round(theme.GAP * self.scale))

        self.safe_area = pygame.Rect(
            self.margin,
            self.margin,
            self.width - self.margin * 2,
            self.height - self.margin * 2,
        )
        title_height = max(54, round(theme.TITLE_HEIGHT * self.scale))
        footer_height = max(64, round(theme.FOOTER_HEIGHT * self.scale))
        content_height = self.safe_area.height - title_height - footer_height - self.gap * 2
        self.title_area = pygame.Rect(self.safe_area.x, self.safe_area.y, self.safe_area.width, title_height)
        self.content_area = pygame.Rect(
            self.safe_area.x,
            self.title_area.bottom + self.gap,
            self.safe_area.width,
            content_height,
        )
        self.footer_area = pygame.Rect(
            self.safe_area.x,
            self.content_area.bottom + self.gap,
            self.safe_area.width,
            footer_height,
        )

    def font(self, base_size):
        return max(18, round(base_size * max(0.72, self.scale)))

    def home_character_area(self):
        width = max(150, int(self.content_area.width * 0.22))
        return pygame.Rect(self.content_area.x, self.content_area.y, width, self.content_area.height)

    def home_cards_area(self):
        character = self.home_character_area()
        return pygame.Rect(
            character.right + self.gap,
            self.content_area.y,
            self.content_area.right - character.right - self.gap,
            self.content_area.height,
        )

    def home_game_cards(self, count):
        area = self.home_cards_area()
        return self.grid_rects(area, count=count, columns=3 if count > 3 else count)

    def game_regions(self):
        upper_height = max(90, int(self.content_area.height * 0.38))
        character_width = max(140, int(self.content_area.width * 0.22))
        character = pygame.Rect(self.content_area.x, self.content_area.y, character_width, upper_height)
        task = pygame.Rect(
            character.right + self.gap,
            self.content_area.y,
            self.content_area.right - character.right - self.gap,
            upper_height,
        )
        options = pygame.Rect(
            self.content_area.x,
            self.content_area.y + upper_height + self.gap,
            self.content_area.width,
            self.content_area.bottom - self.content_area.y - upper_height - self.gap,
        )
        return character, task, options

    def feedback_area(self):
        _, task, _ = self.game_regions()
        inset = max(6, self.gap // 2)
        return task.inflate(-inset * 2, -inset * 2)

    def grid_rects(self, area, count, columns=None):
        count = max(0, int(count))
        if not count:
            return []
        columns = max(1, min(int(columns or count), count))
        rows = (count + columns - 1) // columns
        cell_width = (area.width - self.gap * (columns - 1)) // columns
        cell_height = (area.height - self.gap * (rows - 1)) // rows
        rects = []
        for index in range(count):
            row, column = divmod(index, columns)
            rects.append(pygame.Rect(
                area.x + column * (cell_width + self.gap),
                area.y + row * (cell_height + self.gap),
                cell_width,
                cell_height,
            ))
        return rects

    def footer_buttons(self, count, align="center"):
        count = max(1, int(count))
        button_height = max(48, self.footer_area.height - self.gap)
        total_width = min(self.footer_area.width, count * max(150, int(220 * self.scale)) + (count - 1) * self.gap)
        button_width = (total_width - (count - 1) * self.gap) // count
        if align == "right":
            start_x = self.footer_area.right - total_width
        else:
            start_x = self.footer_area.centerx - total_width // 2
        y = self.footer_area.centery - button_height // 2
        return [
            pygame.Rect(start_x + index * (button_width + self.gap), y, button_width, button_height)
            for index in range(count)
        ]

    def corner_button(self):
        size = max(48, round(58 * max(0.8, self.scale)))
        return pygame.Rect(self.width - self.margin - size, self.margin, size, size)

"""Original approved-menu frame pixels, with separately rendered labels."""
import pygame
from xssgkpz.fonts import ui_font
from xssgkpz.resource_paths import RESOURCE_ROOT

class MenuButtons:
    def __init__(self):
        self.cache = {}
        self.fonts = {}
        self.sources = {}

    def font(self, size, value):
        size = max(8, round(size))
        key = (size, 'kaiti')
        if key not in self.fonts:
            self.fonts[key] = ui_font('kaiti', size)
        font = self.fonts[key]
        if any(metric is None for metric in font.metrics(value)):
            key = (size, 'microsoftyahei')
            if key not in self.fonts:
                self.fonts[key] = ui_font('microsoftyahei', size)
            font = self.fonts[key]
        return font

    def draw(self, surface, rect, *, primary=False, selected=False, enabled=True, hover=False, strong_hover=False):
        rect = pygame.Rect(rect)
        key = (rect.size, primary, selected, enabled, hover, strong_hover)
        if key not in self.cache:
            name = 'selected' if primary or selected else 'normal'
            if name not in self.sources:
                filename = '按键框-选中.png' if name == 'selected' else '按键框.png'
                path = RESOURCE_ROOT / 'assets/references' / filename
                self.sources[name] = pygame.image.load(path).convert_alpha()
            source = self.sources[name]
            sw, sh = source.get_size()
            # Both supplied sources have different native heights. Match corner
            # proportions using each asset's own height before stretching the middle.
            left = right = round(sh * 24 / 69)
            scale = rect.h / sh
            dl, dr = min(round(left*scale), rect.w//3), min(round(right*scale), rect.w//3)
            art = pygame.Surface(rect.size, pygame.SRCALPHA)
            # Stretch the quiet middle; scale the original corner artwork uniformly.
            for sx, width, dx, dw in ((0,left,0,dl),(left,sw-left-right,dl,rect.w-dl-dr),(sw-right,right,rect.w-dr,dr)):
                if dw > 0:
                    part = source.subsurface((sx,0,width,sh))
                    art.blit(pygame.transform.smoothscale(part,(dw,rect.h)),(dx,0))
            if not enabled:
                art.fill((155,155,155,255), special_flags=pygame.BLEND_RGBA_MULT)
            elif hover:
                art.fill((32,26,13,0) if strong_hover else (7,6,3,0), special_flags=pygame.BLEND_RGBA_ADD)
            self.cache[key] = art
            if len(self.cache) > 384:
                self.cache.pop(next(iter(self.cache)))
        surface.blit(self.cache[key], rect)

    def label(self, surface, rect, text, size, color):
        rect = pygame.Rect(rect)
        if text in ('−', '-', '＋', '+'):
            cx, cy = rect.center
            radius = max(3, min(rect.h//5, rect.w//5))
            width = max(1, round(rect.h/24))
            pygame.draw.line(surface, color, (cx-radius,cy), (cx+radius,cy), width)
            if text in ('＋','+'):
                pygame.draw.line(surface, color, (cx,cy-radius), (cx,cy+radius), width)
            return
        if text in ('‹', '›', '←', '→'):
            direction = -1 if text in ('‹', '←') else 1
            radius = max(3, min(rect.h // 5, rect.w // 6))
            cx, cy = rect.center
            points = [(cx + direction * radius, cy), (cx - direction * radius // 2, cy-radius), (cx-direction * radius // 2, cy+radius)]
            pygame.draw.polygon(surface, color, points)
            return
        lines = str(text).split('\n')
        size = min(size, max(8, rect.h / max(1,len(lines)) * .65))
        font = self.font(size, text)
        while size > 9 and max(font.size(line)[0] for line in lines) > rect.w - 20:
            size -= 1
            font = self.font(size, text)
        # Centre visible ink, excluding the font's asymmetric ascender margins.
        rendered = [font.render(line, True, color) for line in lines]
        rendered = [line.subsurface(line.get_bounding_rect()).copy() for line in rendered if line.get_bounding_rect().w]
        gap = max(2, round(size * .18))
        total = sum(line.get_height() for line in rendered) + max(0,len(rendered)-1)*gap
        y = rect.centery - total // 2
        for line in rendered:
            surface.blit(line, (rect.centerx-line.get_width()//2, y))
            y += line.get_height()+gap

    @staticmethod
    def hover_overlay(surface, rect):
        rect = pygame.Rect(rect)
        overlay = pygame.Surface(rect.size, pygame.SRCALPHA)
        w,h = rect.size
        cut = max(3, round(h*.15))
        points = [(cut,2),(w-cut,2),(w-2,cut),(w-2,h-cut),(w-cut,h-2),(cut,h-2),(2,h-cut),(2,cut)]
        pygame.draw.polygon(overlay, (238,190,91,18), points)
        surface.blit(overlay, rect)

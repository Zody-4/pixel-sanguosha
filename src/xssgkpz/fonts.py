"""Keep approved Windows fonts, with licensed bundled Chinese fallbacks."""
import pygame
from xssgkpz.resource_paths import RESOURCE_ROOT


def ui_font(name: str, size: int, bold: bool = False) -> pygame.font.Font:
    system = pygame.font.match_font(name, bold=bold)
    if system:
        return pygame.font.SysFont(name, size, bold=bold)
    else:
        filename = "LXGWWenKai-Regular.ttf" if name == "kaiti" else "NotoSansCJKsc-Regular.otf"
        font = pygame.font.Font(str(RESOURCE_ROOT / "assets/runtime/fonts" / filename), size)
    if bold:
        font.set_bold(True)
    return font

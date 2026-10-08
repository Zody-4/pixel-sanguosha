"""Mode-specific inspector placement using a dimmed, draggable table preview."""
from dataclasses import replace
import pygame
from xssgkpz.fonts import ui_font
from xssgkpz.data.settings import Settings
from xssgkpz.data.modes import MODE_BY_ID
from xssgkpz.data.cards import CARD_DEFINITIONS, CARD_KIND_BY_NAME
from xssgkpz.persistence import save_settings
from xssgkpz.battle_ui import STAGE, DUEL, UPPER_LEFT, UPPER_RIGHT, LEFT, RIGHT


class DetailEditor:
    def __init__(self, app):
        self.a = app
        self.mode = 'duel'
        self.return_page = 'settings'
        self.preview = pygame.Rect(410, 230, 820, round(820 * STAGE[1] / STAGE[0]))
        self.drag = None

    def open(self):
        a = self.a
        self.return_page = a.page
        self.mode = a.engine.state.mode_id if a.page == 'game' and a.engine else a.selected_mode
        a.pause_open = False
        self.drag = None
        a.page = 'detail_editor'

    def close(self):
        if self.drag is not None:
            self.drag = None
            self.save()
        self.a.page = self.return_page
        if self.return_page == 'game':
            self.a.pause_open = True

    def save(self):
        try:
            save_settings(self.a.settings)
            self.a.settings_message = '提示框设置已保存'
        except OSError:
            self.a.settings_message = '本次有效，保存失败'

    def update(self, size, x, y, persist=True):
        size = max(.5, min(2.5, size))
        x = max(0, min(x, 1 - 605 * size / STAGE[0]))
        y = max(0, min(y, 1 - 336 * size / STAGE[1]))
        layouts = {key: (s, px, py) for key, s, px, py in self.a.settings.card_details_layouts}
        layouts[self.mode] = (size, x, y)
        self.a.settings = replace(self.a.settings, card_details_layouts=tuple((key, *value) for key, value in layouts.items()))
        if persist:
            self.save()

    def activate(self, action):
        name, *args = action
        if name == 'detail_close':
            self.close()
        elif name == 'detail_mode':
            self.mode = args[0]
            self.drag = None
        elif name == 'detail_toggle':
            self.a.settings = replace(self.a.settings, card_details_enabled=not self.a.settings.card_details_enabled)
            self.save()
        elif name == 'detail_change':
            values = list(self.a.settings.detail_layout(self.mode))
            values[args[0]] += args[1]
            self.update(*values)
        elif name == 'detail_reset':
            defaults = Settings()
            self.update(*defaults.detail_layout(self.mode))
        elif name == 'detail_sync':
            _, x, y = self.a.settings.detail_layout(self.mode)
            current = self.mode
            for key in MODE_BY_ID:
                if key != current:
                    self.mode = key
                    size, _, _ = self.a.settings.detail_layout(key)
                    self.update(size, x, y, persist=False)
            self.mode = current
            self.save()

    def inspector_box(self):
        size, x, y = self.a.settings.detail_layout(self.mode)
        scale = self.preview.w / STAGE[0]
        return pygame.Rect(self.preview.x + min(x * STAGE[0], STAGE[0] - 605 * size) * scale,
                           self.preview.y + min(y * STAGE[1], STAGE[1] - 336 * size) * scale,
                           605 * size * scale, 336 * size * scale)

    def start_drag(self, position):
        if self.a.page != 'detail_editor' or not self.a.settings.card_details_enabled:
            return False
        box = self.inspector_box()
        if box.collidepoint(position) and self.preview.collidepoint(position):
            self.drag = (position[0] - box.x, position[1] - box.y)
            return True
        return False

    def move(self, position):
        if self.drag is None:
            return
        size, _, _ = self.a.settings.detail_layout(self.mode)
        self.update(size, (position[0] - self.drag[0] - self.preview.x) / self.preview.w,
                    (position[1] - self.drag[1] - self.preview.y) / self.preview.h, persist=False)

    def draw(self):
        a, shell = self.a, self.a.shell_layout
        shell.header('提示框设置', '', ('detail_close',))
        for i, (key, mode) in enumerate(MODE_BY_ID.items()):
            shell.button(mode.name, ('detail_mode', key), 50 + i * 405, 155, 370, 46, selected=key == self.mode)
        shell.panel(50, 230, 330, 375)
        shell.button('牌面详情：' + ('开启' if a.settings.card_details_enabled else '关闭'), ('detail_toggle',), 70, 250, 290, 42)
        values = a.settings.detail_layout(self.mode)
        for i, title in enumerate(('大小', '横向位置', '纵向位置')):
            y = 318 + i * 65
            shell.text(f'{title}  {values[i] * 100:.0f}%', 70, y + 7, a.small_font)
            for direction, x in ((-1, 252), (1, 308)):
                shell.button('−' if direction < 0 else '＋', ('detail_change', i, direction * (.05 if i == 0 else .01)), x, y, 44, 36)
        shell.button('恢复当前模式默认', ('detail_reset',), 70, 524, 290, 42)
        shell.button('位置同步给另外两种模式', ('detail_sync',), 50, 627, 330, 42)
        shell.text('拖动预览中的牌面与说明；仅悬停牌面时显示', 410, 209, a.tiny_font)
        board = a.battle_ui._background().copy()
        seats = (DUEL,) if self.mode == 'duel' else (UPPER_LEFT, UPPER_RIGHT) if self.mode == 'two_heroes' else (LEFT, UPPER_LEFT, UPPER_RIGHT, RIGHT)
        for seat in seats:
            pygame.draw.rect(board, (44, 67, 51), seat.frame)
            pygame.draw.rect(board, (139, 120, 76), seat.frame, 2)
        pygame.draw.rect(board, (44, 67, 51), (36, 653, 390, 173))
        shade = pygame.Surface(STAGE, pygame.SRCALPHA)
        shade.fill((0, 0, 0, 125))
        board.blit(shade, (0, 0))
        if a.settings.card_details_enabled:
            size, x, y = values
            x = round(min(x * STAGE[0], STAGE[0] - 605 * size))
            y = round(min(y * STAGE[1], STAGE[1] - 336 * size))
            card = CARD_DEFINITIONS[0]
            board.blit(a.card_art.surface(card, (round(240 * size), round(336 * size))), (x, y))
            rect = pygame.Rect(x + 260 * size, y + 44 * size, 330 * size, 248 * size)
            pygame.draw.rect(board, (22, 37, 29), rect)
            pygame.draw.rect(board, (221, 186, 123), rect, 2)
            font = ui_font('microsoftyahei', round(25 * size))
            board.blit(font.render(CARD_KIND_BY_NAME[card.name].name, True, (238, 220, 183)), (rect.x + 18 * size, rect.y + 18 * size))
            board.blit(font.render('拖动此处调整位置', True, (221, 186, 123)), (rect.x + 18 * size, rect.y + 75 * size))
        a.screen.blit(pygame.transform.smoothscale(board, a._shell_rect(self.preview).size), a._shell_rect(self.preview))
        shell.text(a.settings_message or '三个模式分别保存大小与位置，开关全局生效', 50, 692, a.tiny_font)

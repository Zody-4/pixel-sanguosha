"""Approved shell layouts; data and actions remain owned by Stage1App."""
from xssgkpz.resource_paths import RESOURCE_ROOT
import pygame
import math
from xssgkpz.data.assets import ASSET_BY_KEY
from xssgkpz.data.cards import CARD_DEFINITIONS, CARD_BY_ID, CARD_KIND_BY_NAME, CardCategory
from xssgkpz.data.heroes import HEROES, HERO_BY_ID
from xssgkpz.data.modes import MODE_BY_ID
from xssgkpz.data.tutorials import TUTORIALS
from xssgkpz.persistence import load_record_summaries
from xssgkpz import APP_VERSION, RULES_VERSION

ROOT = RESOURCE_ROOT
INK = (238, 220, 183)
GOLD = (221, 186, 123)
MUTED = (180, 169, 143)

class ShellLayouts:
    def __init__(self, app):
        self.a = app
        self.images = {}
        self.regions = []
        self.setup_stage = 'config'
        self.identity_revealed = False
        self.identity_flip_started = None
        self.hero_index_scroll = 0
        self.setup_skill_scroll = 0
        self.card_rule_scroll = 0

    def reset(self):
        self.setup_stage = 'config'
        self.identity_revealed = False
        self.identity_flip_started = None
        self.setup_skill_scroll = 0

    def draw(self, page):
        self.regions.clear()
        getattr(self, page)()

    def text(self, value, x, y, font=None, color=INK):
        self.a._text(str(value), (x, y), font or self.a.small_font, color)

    def panel(self, x, y, w, h):
        self.a._panel(pygame.Rect(x, y, w, h))

    def button(self, label, action, x, y, w=180, h=44, **kw):
        self.a._button(pygame.Rect(x, y, w, h), label, action, **kw)

    def header(self, title, subtitle, back=('back',), *, back_enabled=True):
        self.button('返回', back, 50, 35, 132, 42, enabled=back_enabled)
        self.text(title, 210, 32, self.a.title_font)
        # Keep the page heading clean; the content supplies its own instructions.

    def art(self, key, box, *, width_factor=1.0, lift=0.0, glow=0.0):
        if key not in self.images:
            self.images[key] = pygame.image.load(ROOT / ASSET_BY_KEY[key].relative_path).convert_alpha()
        rect = self.a._shell_rect(pygame.Rect(box))
        image = self.images[key]
        scale = min(rect.w / image.get_width(), rect.h / image.get_height())
        size = (max(1, round(image.get_width() * scale * width_factor)), round(image.get_height() * scale))
        rect.y -= round(lift * self.a.ui_render_scale)
        if glow > 0:
            halo = pygame.Surface(self.a.screen.get_size(), pygame.SRCALPHA)
            outline = pygame.Rect(0,0,size[0]+8,size[1]+8)
            outline.center = rect.center
            pygame.draw.rect(halo, (226,176,79,round(80*glow)), outline, max(1,round(3*self.a.ui_render_scale)), border_radius=3)
            self.a.screen.blit(halo,(0,0))
        self.a.screen.blit(pygame.transform.smoothscale(image, size),
                           (rect.centerx - size[0] // 2, rect.centery - size[1] // 2))

    def reading(self, lines, box, owner, attr):
        normalized = []
        for item in lines:
            line, color = item if isinstance(item, tuple) else (item, INK)
            if normalized and line and line[0] in '。，；：、！？':
                previous, previous_color = normalized[-1]
                normalized[-1] = (previous + line[0], previous_color)
                line = line[1:]
            if line or not str(item):
                normalized.append((line, color))
        lines = normalized
        rect = pygame.Rect(box)
        count = max(1, (rect.h - 22) // 27)
        maximum = max(0, len(lines) - count)
        offset = max(0, min(maximum, getattr(owner, attr)))
        setattr(owner, attr, offset)
        self.regions.append((rect, owner, attr, maximum))
        clip = self.a.screen.get_clip()
        self.a.screen.set_clip(self.a._shell_rect(rect))
        for i, item in enumerate(lines[offset:offset + count]):
            line, color = item if isinstance(item, tuple) else (item, INK)
            self.text(line, rect.x + 16, rect.y + 12 + i * 27, color=color)
        self.a.screen.set_clip(clip)
        if maximum:
            self.text(f'{offset + 1}–{min(offset + count, len(lines))} / {len(lines)} · 滚轮阅读',
                      rect.x + 16, rect.bottom - 8, self.a.tiny_font, MUTED)

    def scroll(self, amount, position):
        for rect, owner, attr, maximum in self.regions:
            if rect.collidepoint(position):
                setattr(owner, attr, max(0, min(maximum, getattr(owner, attr) + amount)))
                return True
        return False

    def menu(self):
        self.art('shell.approved_menu', (0, 0, 1280, 720))
        boxes = ((493, 515, 355, 81, 'open_setup'), (882, 515, 296, 81, 'open_tutorials'),
                 (245, 742, 210, 66, 'open_hero_album'), (489, 742, 207, 66, 'open_card_album'),
                 (733, 742, 208, 66, 'open_records'), (978, 742, 207, 66, 'open_settings'),
                 (1222, 742, 208, 66, 'quit'))
        for x, y, w, h, action in boxes:
            rect = pygame.Rect(round(x * 1280 / 1672), round(y * 720 / 941),
                               round(w * 1280 / 1672), round(h * 720 / 941))
            self.a._register_battle_hit(rect, (action,))
            if self.a.mouse_canvas_position and rect.collidepoint(self.a.mouse_canvas_position):
                self.a.shell_theme.buttons.hover_overlay(self.a.screen, self.a._shell_rect(rect))

    def setup(self):
        if self.setup_stage == 'hero':
            self.hero()
            return
        readonly = self.setup_stage == 'readonly'
        self.header('本局配置' if readonly else '新对局设置', '模式、难度与选将方式',
                    ('roster_back',) if readonly else ('confirm', 'abandon_setup'))
        a = self.a
        for i, (key, mode) in enumerate(MODE_BY_ID.items()):
            x = 50 + i * 405
            self.panel(x, 155, 370, 135)
            title, _, suffix = mode.name.partition('：')
            self.button(title, ('mode', key), x + 16, 170, 338, 52,
                        selected=a.selected_mode == key, enabled=not readonly)
            self.text(suffix, x + 24, 243, color=GOLD)
        self.panel(50, 315, 1180, 290)
        self.text('AI难度', 80, 346, a.font, GOLD)
        from xssgkpz.app import DIFFICULTY_LABELS
        for i, (tier, label) in enumerate(DIFFICULTY_LABELS.items()):
            self.button(label, ('difficulty', tier.value), 350 + i * 265, 340, 240, 46,
                        selected=a.selected_difficulty == tier, enabled=not readonly)
        self.text('武将选择', 80, 431, a.font, GOLD)
        for i, (key, label) in enumerate((('free_choice', '自由选择'), ('random_three_choose_one', '随机三选一'), ('full_random', '完全随机'))):
            self.button(label, ('hero_method', key), 350 + i * 265, 425, 240, 46,
                        selected=a.hero_method == key, enabled=not readonly)


        if not readonly:
            self.button('下一步 · 选择武将', ('setup_next',), 950, 645, 280, 48, primary=True)

    def hero(self):
        a = self.a
        self.header('选择武将', '查看完整技能后确认；确认时锁定本局阵容。', ('setup_config',))
        self.panel(50, 155, 280, 460)
        a._draw_hero_portrait(a.selected_hero, pygame.Rect(65, 170, 250, 345))
        hero = HERO_BY_ID[a.selected_hero]
        self.text(hero.name, 80, 531, a.big_font, GOLD)
        self.text(f'{hero.faction.value} · {hero.base_hp}体力', 80, 579, color=MUTED)
        identity_mode = a.selected_mode == 'five_player_identity'
        height = 325 if identity_mode else 390
        self.panel(350, 155, 880, height)
        self.reading(a._hero_album_lines(hero, MODE_BY_ID[a.selected_mode], 47), (360, 163, 858, height - 30), self, 'setup_skill_scroll')
        if identity_mode:
            self.text('身份', 350, 505, color=GOLD)
            for i, (key, label) in enumerate(((None, '随机'), ('lord', '主公'), ('loyalist', '忠臣'), ('rebel', '反贼'), ('turncoat', '内奸'))):
                self.button(label, ('identity', key), 420 + i * 162, 493, 148, 40, selected=a.identity_choice == key)
        a.hero_scroll = min(a.hero_scroll, max(0, len(a.candidates) - 5))
        self.button('‹', ('hero_strip', -1), 350, 566, 42, 48, enabled=a.hero_scroll > 0)
        for i, hero_id in enumerate(a.candidates[a.hero_scroll:a.hero_scroll + 5]):
            self.button(HERO_BY_ID[hero_id].name, ('hero', hero_id), 407 + i * 149, 566, 136, 48,
                        selected=a.selected_hero == hero_id, enabled=a.hero_method != 'full_random')
        self.button('›', ('hero_strip', 1), 1188, 566, 42, 48, enabled=a.hero_scroll + 5 < len(a.candidates))
        self.regions.append((pygame.Rect(350, 555, 880, 70), a, 'hero_scroll', max(0, len(a.candidates) - 5)))
        self.button('确认武将 · 锁定阵容', ('lock_roster',), 950, 645, 280, 48, primary=True)

    def roster(self):
        a = self.a
        if not a.pending_match_state or not a.roster:
            return
        self.header('本局阵容已锁定', '这里只展示允许公开的信息；返回不会重新抽取阵容。', ('confirm', 'abandon_setup'))
        players = sorted(a.pending_match_state.players, key=lambda p: p.seat_index)
        own = next(p for p in players if p.player_id == 'P1')
        self.panel(50, 155, 300, 440)
        a._draw_hero_portrait(own.hero_id, pygame.Rect(65, 167, 270, 310))
        self.text(HERO_BY_ID[own.hero_id].name, 80, 495, a.big_font, GOLD)
        self.text(f'你方 · {own.hp}/{own.max_hp}体力', 80, 548)
        self.panel(380, 155, 850, 440)
        others = [p for p in players if p.player_id != 'P1']
        for i, p in enumerate(others):
            y = 174 + i * 101
            a._draw_hero_portrait(p.hero_id, pygame.Rect(397, y, 74, 90))
            self.text(f'座位 {p.seat_index + 1} · {HERO_BY_ID[p.hero_id].name}', 490, y + 8, a.font, GOLD)
            self.text(f'{p.hp}/{p.max_hp}体力', 490, y + 46)
            identity = a._identity_label(p.identity) if a.roster.mode_id != 'five_player_identity' else '身份保密'
            self.text(identity, 860, y + 46, color=MUTED)
        self.button('查看本局配置', ('roster_config',), 50, 645, 230, 48)
        identity = a.roster.mode_id == 'five_player_identity'
        self.button('查看我的身份' if identity else '进入对局', ('reveal_identity',) if identity else ('start_match',), 950, 645, 280, 48, primary=True)

    @property
    def identity_flipping(self):
        return self.identity_flip_started is not None

    def begin_identity_flip(self):
        if not self.identity_revealed and not self.identity_flipping:
            self.identity_flip_started = pygame.time.get_ticks()

    def identity_progress(self):
        if self.identity_flip_started is None:
            return 1.0 if self.identity_revealed else 0.0
        progress = min(1.0, max(0.0, (pygame.time.get_ticks()-self.identity_flip_started)/650))
        if progress >= 1:
            self.identity_revealed = True
            self.identity_flip_started = None
        return progress

    def identity(self):
        self.identity_page(False)

    def objective(self):
        self.identity_page(True)

    def identity_page(self, objective):
        a = self.a
        role = dict(a.roster.identities).get('P1') if a.roster else None
        progress = self.identity_progress() if not objective else 1.0
        flipping = self.identity_flipping and not objective
        shown = self.identity_revealed or objective or (flipping and progress >= .5)
        self.header('胜利目标' if objective else '查看我的身份', '身份仅生成一次，查看和返回不会重新分配。', ('show_identity',) if objective else ('roster_back',), back_enabled=not flipping)
        self.panel(50, 155, 355, 440)
        eased = progress*progress*(3-2*progress)
        width = max(.018, abs(math.cos(math.pi*eased))) if flipping else 1.0
        self.art('identity.' + role if shown and role else 'card.back', (78, 171, 299, 396),
                 width_factor=width, lift=8*math.sin(math.pi*progress) if flipping else 0,
                 glow=max(0, math.sin(math.pi*(progress-.5)*2))*.6 if flipping and shown else 0)
        if not shown and not flipping:
            a._register_battle_hit(pygame.Rect(78,171,299,396), ('show_own_identity',))
        self.panel(435, 155, 795, 440)
        self.text(a._identity_label(role) if shown else '你的身份尚未翻开', 475, 195, a.big_font, GOLD)
        targets = {'lord': '主公与忠臣：消灭所有反贼与内奸。', 'loyalist': '忠臣：保护主公存活，并协助主公阵营获胜。', 'rebel': '反贼：击败主公。', 'turncoat': '内奸：主公阵亡且自己成为唯一幸存者时获胜。'}
        message = targets.get(role, '击败对方阵营。') if objective else ('记下自己的身份，再查看胜利目标。' if shown else '点击翻开，仅向你展示自己的身份。')
        a._draw_wrapped(message, (475, 278), 32, a.font)
        self.text('其他未公开身份继续保密。', 475, 491, color=MUTED)
        action = ('start_match',) if objective else (('confirm_identity',) if shown else ('show_own_identity',))
        self.button('翻牌中…' if flipping else ('进入对局' if objective else ('查看胜利目标' if shown else '翻开身份卡')), action, 950, 645, 280, 48, primary=True, enabled=not flipping)

    def hero_album(self):
        a = self.a
        self.header('武将录', '25名武将 · 立绘与完整技能说明')
        for i, (key, label) in enumerate((('all', '全部模式'), *((key, mode.name) for key, mode in MODE_BY_ID.items()))):
            self.button(label, ('hero_album_mode', key), 50 + i * 225, 125, 210, 32, selected=a.hero_album_mode == key)
        self.panel(50, 180, 210, 425)
        self.hero_index_scroll = min(self.hero_index_scroll, len(HEROES) - 10)
        for i, hero in enumerate(HEROES[self.hero_index_scroll:self.hero_index_scroll + 10]):
            self.button(hero.name, ('hero_album_select', hero.hero_id), 63, 190 + i * 37, 184, 32, selected=a.hero_album_selection == hero.hero_id)
        self.text('滚轮浏览武将', 73, 576, a.tiny_font, MUTED)
        self.regions.append((pygame.Rect(50, 180, 210, 425), self, 'hero_index_scroll', max(0, len(HEROES) - 10)))
        self.panel(280, 180, 280, 425)
        hero = HERO_BY_ID[a.hero_album_selection]
        a._draw_hero_portrait(hero.hero_id, pygame.Rect(290, 190, 260, 330))
        self.text(hero.name, 307, 536, a.big_font, GOLD)
        self.text(f'{hero.faction.value} · {hero.base_hp}体力', 307, 579)
        self.panel(580, 180, 650, 425)
        self.reading(a._hero_album_lines(hero, MODE_BY_ID.get(a.hero_album_mode), 33), (590, 190, 630, 390), a, 'hero_album_scroll')

    def card_album(self):
        a = self.a
        self.header('卡牌录', '108张实体牌 · 卡面短提示与完整规则')
        for i, (category, label) in enumerate(((None, '全部'), (CardCategory.BASIC, '基本'), (CardCategory.TRICK, '锦囊'), (CardCategory.EQUIPMENT, '装备'))):
            self.button(label, ('card_category', category.value if category else 'all'), 50 + i * 148, 125, 132, 32, selected=a.card_album_category is category)
        entries = [c for c in CARD_DEFINITIONS if a.card_album_category is None or c.category is a.card_album_category]
        self.panel(50, 180, 320, 425)
        start = a.card_album_index * 12
        suit_names = {'spades': '黑桃', 'hearts': '红桃', 'clubs': '梅花', 'diamonds': '方块'}
        for i, card in enumerate(entries[start:start + 12]):
            label = f'{card.name} · {suit_names[card.suit.value]}{card.rank}' + (' · EX' if card.edition.value == 'EX' else '')
            self.button(label, ('card_select', card.definition_id), 63, 191 + i * 30, 294, 28, selected=a.selected_card_id == card.definition_id)
        self.button('‹', ('card_page', -1), 63, 563, 48, 30, enabled=a.card_album_index > 0)
        self.text(f'{a.card_album_index + 1}/{max(1, (len(entries) + 11) // 12)}页 · {len(entries)}张', 125, 569, a.tiny_font, MUTED)
        self.button('›', ('card_page', 1), 309, 563, 48, 30, enabled=start + 12 < len(entries))
        card = CARD_BY_ID[a.selected_card_id]
        kind = CARD_KIND_BY_NAME[card.name]
        box = a._shell_rect(pygame.Rect(398, 207, 230, 322))
        a.screen.blit(a.card_art.surface(card, box.size), box)
        self.panel(650, 180, 580, 425)
        lines = [(card.name + ' · ' + suit_names[card.suit.value] + str(card.rank), GOLD), ('卡面提示', GOLD)]
        lines += [(line, INK) for line in a._wrap_lines(kind.display_summary, 29)]
        lines += [('', MUTED), ('完整规则', GOLD)]
        lines += [(line, INK) for line in a._wrap_lines(kind.description, 29)]
        self.reading(lines, (660, 190, 558, 390), self, 'card_rule_scroll')
        self.button('规则帮助', ('open_rules_help',), 1010, 645, 220, 48)

    def rules_help(self):
        a = self.a
        self.header('规则帮助', '按模式阅读；牌与技能细则可进入图鉴。')
        self.panel(50, 160, 260, 445)
        for i, (key, mode) in enumerate(MODE_BY_ID.items()):
            self.button(mode.name, ('help_mode', key), 65, 180 + i * 68, 230, 48, selected=a.help_mode == key)
        self.button('武将录', ('open_hero_album',), 65, 444, 230, 44)
        self.button('卡牌录', ('open_card_album',), 65, 506, 230, 44)
        self.panel(335, 160, 895, 445)
        mode = MODE_BY_ID[a.help_mode]
        self.text(mode.name, 365, 189, a.big_font, GOLD)
        self.text(f'{mode.player_count}名玩家 · {mode.ai_count}名电脑角色', 365, 245)
        objectives = {'duel': '目标：击败唯一对手。身份牌不参与此模式。', 'two_heroes': '目标：玩家与两名对手进行1对2对局。', 'five_player_identity': '目标按主公、忠臣、反贼和内奸身份确定；存活身份保密。'}
        a._draw_wrapped(objectives[a.help_mode], (365, 292), 40, a.font)
        self.text('准备 → 判定 → 摸牌 → 出牌 → 弃牌 → 结束', 365, 386, a.font, GOLD)
        a._draw_wrapped('牌的具体时机与目标合法性以卡牌和武将说明为准。普通主动操作先选择并检查合法性，确认后进入结算。打开帮助不会清除当前选择。', (365, 447), 45, a.small_font)

    def settings(self):
        a = self.a
        self.header('设置', '选择后自动保存到本机。')
        from xssgkpz.data.settings import WindowMode, AiDisplaySpeed, SkillAnimation
        values = [('窗口模式', '无边框全屏' if a.settings.window_mode is WindowMode.BORDERLESS_FULLSCREEN else '窗口', 'cycle_window_mode'),
                  ('分辨率', f'{a.settings.resolution_width} × {a.settings.resolution_height}', 'cycle_resolution'),
                  ('UI缩放', f'{a.settings.ui_scale:.2f}×', 'cycle_ui_scale'),
                  ('AI展示速度', {AiDisplaySpeed.NORMAL: '正常', AiDisplaySpeed.FAST: '快速', AiDisplaySpeed.INSTANT: '即时'}[a.settings.ai_display_speed], 'cycle_ai_speed'),
                  ('技能演出', {SkillAnimation.NORMAL: '正常', SkillAnimation.FAST: '快速', SkillAnimation.OFF: '关闭'}[a.settings.skill_animation], 'cycle_skill_animation')]
        for group, title in enumerate(('显示', '对局呈现')):
            x = 50 + group * 605
            self.panel(x, 160, 575, 238)
            self.text(title, x + 26, 175, a.font, GOLD)
            for i, (label, value, action) in enumerate(values[:3] if group == 0 else values[3:]):
                y = 215 + i * 55
                self.text(label, x + 26, y + 10)
                self.button(value, (action,), x + 255, y, 290, 40)
        self.panel(50, 420, 1180, 185)
        self.text('声音', 76, 438, a.font, GOLD)
        feedback = '问题反馈：项目 GitHub Issues'
        self.text(feedback, 1204 - a.tiny_font.size(feedback)[0], 444, a.tiny_font, MUTED)
        for i, (field, label) in enumerate((('music_volume','音乐'),('voice_volume','报牌'),('effects_volume','音效'))):
            x = 80 + i*395
            volume = getattr(a.settings, field)
            self.text(label, x, 487, a.font)
            self.text('静音' if volume == 0 else f'{round(volume*100)}%', x + 245, 490, color=GOLD)
            self.button('−', ('volume_change',field,-.1), x, 530, 46, 42, enabled=volume > 0)
            self.button('＋', ('volume_change',field,.1), x + 284, 530, 46, 42, enabled=volume < 1)
            bar = pygame.Rect(x+64,546,202,10)
            pygame.draw.rect(a.screen, (39,51,39), a._shell_rect(bar), border_radius=3)
            filled = bar.copy(); filled.w = round(bar.w*volume)
            if filled.w:
                pygame.draw.rect(a.screen, GOLD, a._shell_rect(filled), border_radius=3)
            thumb = a._shell_rect(pygame.Rect(bar.x+round(bar.w*volume)-3,540,6,22))
            pygame.draw.rect(a.screen, INK, thumb, border_radius=2)
            # Clicking anywhere along the bar sets 5% increments, in addition to +/-.
            for step in range(21):
                a._register_battle_hit(pygame.Rect(bar.x+round(step*bar.w/21),530,
                                                  max(1,round(bar.w/21)+1),42),
                                      ('volume_set',field,step/20))
        self.text(a.settings_message, 50, 649, a.tiny_font, MUTED)
        self.text('提示框', 681, 335)
        self.button('大小与位置', ('open_detail_editor',), 910, 325, 290, 40)

    def volume_at(self, position, field=None):
        if self.a.page != 'settings':
            return None
        for i, key in enumerate(('music_volume','voice_volume','effects_volume')):
            bar = pygame.Rect(144+i*395,530,202,42)
            if (field == key) or (field is None and bar.collidepoint(position)):
                return key, round(max(0,min(1,(position[0]-bar.x)/bar.w)),2)
        return None

    def tutorial_index(self):
        a = self.a
        self.header('演武教学', '在真实牌桌中练习操作；各章独立进入，不计战绩。')
        self.panel(50, 160, 260, 445)
        for i, lesson in enumerate(TUTORIALS):
            self.button(lesson.title, ('select_tutorial', lesson.lesson_id), 65, 190 + i * 90, 230, 60, selected=a.tutorial_id == lesson.lesson_id)
        self.panel(335, 160, 895, 445)
        lesson = next(item for item in TUTORIALS if item.lesson_id == a.tutorial_id)
        self.text(lesson.title, 372, 198, a.big_font, GOLD)
        descriptions = {'basic': ('基础操作 · 12步', '选牌、目标、取消、杀与闪、桃恢复与救援、结束阶段与弃牌。'),
                        'advanced': ('进阶规则 · 7步', '距离、装备、锦囊、鬼才改判、濒死救援与苦肉。'),
                        'modes': ('三种模式 · 9步', '斗将、力敌双雄、身份保密、奖励、误杀惩罚与胜利条件。')}
        title, text = descriptions[a.tutorial_id]
        self.text(title, 372, 270, a.font, GOLD)
        a._draw_wrapped(text, (372, 330), 38, a.font)
        a._draw_wrapped('进入预设局面，跟随提示亲自选牌、选择目标并确认。可重看提示、重练当前场景或退出。', (372, 452), 45, a.small_font)
        self.button('开始练习', ('start_tutorial', a.tutorial_id), 950, 645, 280, 48, primary=True)

    def records(self):
        a = self.a
        self.header('战绩', '本地结果摘要；不保存可续玩的对局。')
        for i, (key, label) in enumerate((('all', '全部版本'), ('program', f'程序 {APP_VERSION}'), ('rules', '当前规则版'))):
            self.button(label, ('records_filter', key), 50 + i * 230, 125, 210, 32, selected=a.records_filter == key)
        records = load_record_summaries()
        if a.records_filter == 'program':
            records = tuple(r for r in records if r.program_version == APP_VERSION)
        elif a.records_filter == 'rules':
            records = tuple(r for r in records if r.rules_version == RULES_VERSION)
        a.records_scroll = min(a.records_scroll, max(0, len(records) - 8))
        self.panel(50, 180, 1180, 425)
        self.text(f'共{len(records)}局' + (' · 样本不足5局，胜率仅供参考' if len(records) < 5 else ''), 75, 193, color=MUTED)
        for label, x in (('日期 / 模式', 75), ('武将 / 身份', 350), ('结果 / 原因', 595), ('回合 / 版本', 930)):
            self.text(label, x, 231, color=GOLD)
        shown = records[max(0, len(records) - 8 - a.records_scroll):len(records) - a.records_scroll if a.records_scroll else None]
        from xssgkpz.app import DIFFICULTY_LABELS
        results = {'win': '胜利', 'loss': '失败', 'draw': '平局', 'unfinished': '未完成'}
        reasons = {'resigned': '认输', 'restart': '重新开始', 'exit_to_menu': '退出主菜单', 'normal': '正常终局', 'no_survivors': '无存活角色平局', 'C-04_insufficient_cards': '牌堆不足平局'}
        for i, r in enumerate(reversed(shown)):
            y = 270 + i * 40
            difficulty = next((label for tier, label in DIFFICULTY_LABELS.items() if tier.value == r.difficulty), r.difficulty)
            self.text(difficulty + 'AI', 350, y + 18, a.tiny_font, MUTED)
            self.text(r.recorded_at[:10] + ' · ' + (MODE_BY_ID[r.mode_id].name if r.mode_id in MODE_BY_ID else r.mode_id), 75, y, a.tiny_font)
            hero = HERO_BY_ID.get(r.player_hero_id)
            self.text((hero.name if hero else '未知武将') + ' · ' + a._identity_label(r.player_identity), 350, y, a.tiny_font)
            self.text(results.get(r.result, r.result), 595, y, a.tiny_font, GOLD)
            self.text(reasons.get(r.end_reason, r.end_reason), 667, y, a.tiny_font)
            self.text(f'{r.turn_count}回合 · {r.program_version}/{r.rules_version}', 930, y, a.tiny_font)
        if not records:
            self.text('暂无战绩', 540, 395, a.big_font, MUTED)
        self.regions.append((pygame.Rect(50, 180, 1180, 425), a, 'records_scroll', max(0, len(records) - 8)))
        self.button('清除战绩', ('confirm', 'clear_records'), 50, 645, 180, 48)
        self.text(a.records_message, 260, 661, a.tiny_font, MUTED)
        self.button('较新', ('records_scroll', -8), 950, 645, 130, 48, enabled=a.records_scroll > 0)
        self.button('较旧', ('records_scroll', 8), 1100, 645, 130, 48, enabled=a.records_scroll + 8 < len(records))

    def result(self):
        a = self.a
        self.header('本局结果', '对局结算与保存状态', ('to_menu',))
        self.panel(50, 160, 1180, 445)
        outcome = a.engine.player_outcome if a.engine else 'unfinished'
        self.text({'win': '你方胜利', 'loss': '你方失败', 'draw': '平局', 'unfinished': '未完成'}.get(outcome, '对局结束'), 435, 185, a.big_font, GOLD)
        a._draw_wrapped(a.last_result_text, (435, 244), 36, a.small_font)
        if a.engine:
            player = next((p for p in a.engine.state.players if p.player_id == 'P1'), None)
            from xssgkpz.app import DIFFICULTY_LABELS
            if player:
                a._draw_hero_portrait(player.hero_id, pygame.Rect(75, 180, 320, 370))
                self.text(HERO_BY_ID[player.hero_id].name + ' · ' + a._identity_label(player.identity), 96, 564, a.font, GOLD)
            difficulty = DIFFICULTY_LABELS[a.roster.difficulty] if a.roster else '未知'
            self.text(f'{MODE_BY_ID[a.engine.state.mode_id].name}  ·  {difficulty}  ·  {a.engine.state.turn_number}回合', 435, 298, a.small_font, MUTED)
            for i, p in enumerate(sorted(a.engine.state.players, key=lambda p: p.seat_index)):
                y = 350 + i * 43
                self.text(('你 · ' if p.player_id == 'P1' else '') + HERO_BY_ID[p.hero_id].name, 435, y, a.small_font, INK)
                self.text(a._identity_label(p.identity), 700, y, a.small_font, GOLD)
                self.text(f'存活 · {p.hp}/{p.max_hp}' if p.alive else '已阵亡', 965, y, a.small_font, INK if p.alive else MUTED)
            a._draw_wrapped(a.record_save_error or '战绩已保存', (435, 578), 40, a.tiny_font)
        self.button('查看战绩', ('open_records',), 700, 645, 220, 48)
        self.button('新建一局', ('restart_from_result',), 950, 645, 280, 48, primary=True)

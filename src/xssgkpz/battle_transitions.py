"""Short, input-blocking deal and outcome performances on the existing table."""
from xssgkpz.resource_paths import RESOURCE_ROOT
from math import cos, pi, sin
import pygame
from xssgkpz.data.cards import CARD_BY_ID

ROOT = RESOURCE_ROOT
STAGE = (1672, 941)
_back = None
_outcome_images = {}
_outcome_sizes = {}


def deal_schedule(app):
    """Visual schedule only; initial hands are already assigned by match setup."""
    players = sorted(app.engine.state.players, key=lambda p: p.seat_index)
    counts = {p.player_id: len(app.engine.state.zones[p.hand_zone_id].card_ids) for p in players}
    sequence = [(p.player_id, index) for index in range(max(counts.values(), default=0))
                for p in players if index < counts[p.player_id]]
    interval = 1900 / max(1, len(sequence)-1)
    return [(pid, index, 250 + order*interval) for order, (pid,index) in enumerate(sequence)]


def deal_arrived_count(app, player_id):
    elapsed = pygame.time.get_ticks() - app.deal_started_ms
    return sum(pid == player_id and elapsed >= start+300 for pid, _, start in deal_schedule(app))


def draw_transition(app):
    global _back
    ui = app.battle_ui
    layer = pygame.Surface(STAGE, pygame.SRCALPHA)
    now = pygame.time.get_ticks()
    if app.outcome_started_ms is not None and not app.window_focused and app.focus_lost_ms is not None:
        now = app.focus_lost_ms

    def text(value, center, size, color):
        font = ui.font(size)
        image = font.render(value, True, color)
        layer.blit(image, image.get_rect(center=center))

    if app.deal_started_ms is not None:
        elapsed = max(0, now - app.deal_started_ms)
        shade = 55 * max(0, min(1, (3000-elapsed)/350))
        layer.fill((4, 12, 9, round(shade)))
        if _back is None:
            _back = pygame.image.load(str(ROOT / 'assets/references/卡背-设计参考.png')).convert_alpha()
        card = pygame.transform.scale(_back, (100, 140))
        origin = (836, 430)
        # Small offset layers form a physical deck; no extra frame or loading bar.
        deck_alpha = round(255 * min(1, elapsed/180) * max(0, min(1, (2800-elapsed)/350)))
        deck = card.copy(); deck.set_alpha(deck_alpha)
        for offset in (8, 4, 0):
            layer.blit(deck, deck.get_rect(center=(origin[0]+offset, origin[1]+offset)))
        own = next(p for p in app.engine.state.players if p.player_id == 'P1')
        own_ids = app.engine.state.zones[own.hand_zone_id].card_ids
        for pid, index, start in deal_schedule(app):
            if elapsed < start:
                continue
            arrived = elapsed >= start+300
            if pid != 'P1' and arrived:
                continue  # The real seat badge now displays the received count.
            target = (569.5+index*150, 792.5) if pid == 'P1' else ui.seats[pid].hand_box.center
            progress = min(1, max(0, (elapsed-start)/300))
            ease = progress*progress*(3-2*progress)
            x = origin[0] + (target[0]-origin[0])*ease
            y = origin[1] + (target[1]-origin[1])*ease - sin(pi*progress)*28
            width = round(100 + (45 if pid == 'P1' else -74)*ease)
            height = round(width*1.4)
            image = _back
            if pid == 'P1' and arrived:
                flip = min(1, max(0, (elapsed-2500-index*60)/220))
                if flip >= .5:
                    definition = CARD_BY_ID[app.engine.state.cards[own_ids[index]].definition_id]
                    image = app.card_art.surface(definition, (145,203))
                width = max(1, round(width*abs(cos(pi*flip))))
            flying = pygame.transform.scale(image, (max(1,width),max(1,height)))
            layer.blit(flying, flying.get_rect(center=(round(x),round(y))))
    else:
        elapsed = max(0, now - app.outcome_started_ms)
        progress = min(1, elapsed / 750)
        ease = 1 - (1-progress)**3
        layer.fill((4, 8, 7, round(190*min(1, elapsed/400))))
        outcome = app.engine.player_outcome
        if outcome not in {'win', 'loss'}:
            text('平局' if outcome == 'draw' else '对局结束', (836, 450), 80, (235, 216, 178))
        if elapsed > 1800:
            text('即将进入结算', (836, 835), 23, (202, 187, 158))
    app.screen.blit(pygame.transform.smoothscale(layer, ui.viewport.size), ui.viewport)

    if app.outcome_started_ms is not None and app.engine.player_outcome in {'win', 'loss'}:
        outcome = app.engine.player_outcome
        if outcome not in _outcome_images:
            # User-provided atlas: victory left, defeat right. Preserve the
            # original RGBA pixels; the apparent black backdrop is alpha zero.
            atlas = pygame.image.load(str(ROOT / 'assets/references/结算.png')).convert_alpha()
            # The actual transparent gutter is x=1103..1130, not x=1073.
            split = 1116
            box = (0, 0, split, atlas.get_height()) if outcome == 'win' else (
                split, 0, atlas.get_width()-split, atlas.get_height())
            image = atlas.subsurface(box)
            bounds = image.get_bounding_rect(min_alpha=128).inflate(16,16).clip(image.get_rect())
            _outcome_images[outcome] = image.subsurface(bounds).copy()
        image = _outcome_images[outcome]
        ratio = ui.viewport.w / STAGE[0]
        width = max(1, round(920 * ratio))
        height = max(1, round(width * image.get_height() / image.get_width()))
        key = (outcome, width, height)
        if key not in _outcome_sizes:
            # Nearest-neighbor at the final viewport, never a second smooth pass.
            if len(_outcome_sizes) >= 12:
                _outcome_sizes.clear()
            _outcome_sizes[key] = pygame.transform.scale(image, (width, height))
        sprite = _outcome_sizes[key].copy()
        elapsed = max(0, now - app.outcome_started_ms)
        progress = min(1, elapsed / 650)
        ease = 1 - (1-progress)**3
        sprite.set_alpha(round(255 * min(1, elapsed/280)))
        center = (ui.viewport.centerx, ui.viewport.y + round((465 - 16*(1-ease))*ratio))
        target = sprite.get_rect(center=center)
        # Reveal from the center without stretching or deforming the emblem.
        old_clip = app.screen.get_clip()
        reveal = target.copy()
        reveal.width = max(1, round(target.width * ease))
        reveal.centerx = target.centerx
        app.screen.set_clip(old_clip.clip(reveal).clip(ui.viewport))
        app.screen.blit(sprite, target)
        app.screen.set_clip(old_clip)

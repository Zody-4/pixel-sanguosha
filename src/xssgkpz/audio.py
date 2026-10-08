"""Optional desktop audio, driven solely by committed public presentation events."""
from collections import deque
from array import array
import json
from xssgkpz.resource_paths import RESOURCE_ROOT
from weakref import WeakKeyDictionary

import pygame
from xssgkpz.data.cards import CARD_BY_ID, CARD_KIND_BY_NAME

ROOT = RESOURCE_ROOT
AUDIO_ROOT = ROOT / 'Music' / '定稿'
# Healing uses the approved recovery cue, never the old peach announcement.
EXCLUDED_VOICES = frozenset({'tao'})
VOICE_FEEDBACK = frozenset({'heal', 'victory', 'defeat'})
EFFECT_FEEDBACK = frozenset({'ui_click', 'card_draw', 'card_place', 'damage',
                             'identity_reveal', 'equip', 'judgement'})

class GameAudio:
    def __init__(self):
        self.started = False
        self.available = False
        self.errors = []
        self.track = None
        self.sounds = {}
        self.queue = deque(maxlen=6)
        self.channel = None
        self.effects_channel = None
        self.effects_channels = []
        self.music_volume = .32
        self.voice_volume = .85
        self.effects_volume = .70
        self.effect_sounds = {}
        self.context_engine = None
        self.seen = WeakKeyDictionary()
        self.boosted_sounds = {}
        self.sound_gains = {}

    def start(self, settings=None):
        if self.started:
            return
        self.started = True
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
            pygame.mixer.set_reserved(4)
            self.channel = pygame.mixer.Channel(0)
            self.effects_channel = pygame.mixer.Channel(1)
            self.effects_channels = [pygame.mixer.Channel(index) for index in (1, 2, 3)]
            self.available = True
            if settings is not None:
                self.apply_settings(settings)
        except pygame.error as error:
            self.errors.append(f'音频设备不可用：{error}')
            return
        try:
            manifest = json.loads((AUDIO_ROOT / 'voice' / 'approved_manifest.json').read_text(encoding='utf-8-sig'))
            for line in manifest['lines']:
                kind = line['kind_id']
                if kind in EXCLUDED_VOICES or line['status'] not in {'user_approved','user_accepted'}:
                    continue
                try:
                    self.sounds[kind] = pygame.mixer.Sound(str(AUDIO_ROOT / 'voice' / line['file']))
                except (pygame.error, OSError) as error:
                    self.errors.append(f'{kind}加载失败：{error}')
        except (OSError, ValueError, KeyError) as error:
            self.errors.append(f'配音清单加载失败：{error}')
        try:
            manifest = json.loads((AUDIO_ROOT / 'sfx' / 'approved_manifest.json').read_text(encoding='utf-8-sig'))
            for item in manifest['sounds']:
                key = item['name']
                if item['status'] not in {'user_approved', 'user_accepted'} or key not in VOICE_FEEDBACK | EFFECT_FEEDBACK:
                    continue
                try:
                    sound = pygame.mixer.Sound(str(AUDIO_ROOT / 'sfx' / item['file']))
                    (self.sounds if key in VOICE_FEEDBACK else self.effect_sounds)[key] = sound
                except (pygame.error, OSError) as error:
                    self.errors.append(f'{key}加载失败：{error}')
        except (OSError, ValueError, KeyError) as error:
            self.errors.append(f'反馈声音清单加载失败：{error}')

    def _music(self, track):
        if track == self.track:
            return
        self.track = track
        if track is None:
            pygame.mixer.music.stop()
            return
        try:
            pygame.mixer.music.load(str(AUDIO_ROOT / f'{track}_bgm.wav'))
            pygame.mixer.music.set_volume(self.music_volume)
            pygame.mixer.music.play(-1)
        except (pygame.error, OSError) as error:
            pygame.mixer.music.stop()
            self.errors.append(f'{track}音乐加载失败：{error}')

    def _enqueue(self, key):
        if self.voice_volume > 0 and key in self.sounds and key not in EXCLUDED_VOICES:
            self.queue.append(key)

    def apply_settings(self, settings):
        # New displayed scale preserves the user's chosen listening levels:
        # music 30 -> old 10; voice 50 -> old 76; effects 50 -> old 100.
        self.music_volume = settings.music_volume / 3
        self.voice_volume = settings.voice_volume * 1.52
        self.effects_volume = settings.effects_volume * 2
        if self.available and pygame.mixer.get_init():
            self._channel_volume(self.channel, self.voice_volume)
            for channel in self.effects_channels:
                self._channel_volume(channel, self.effects_volume)
            if self.voice_volume == 0:
                self.queue.clear()
                self.channel.stop()
            if self.effects_volume == 0:
                for channel in self.effects_channels:
                    channel.stop()
            pygame.mixer.music.set_volume(self.music_volume * (.625 if self.voice_volume > 0 and self.channel.get_busy() else 1))

    def play_effect(self, path):
        # Compatibility interface for effect paths; approved cues use play_feedback.
        if not self.available or self.effects_volume == 0:
            return
        try:
            key = str(path)
            if key not in self.effect_sounds:
                self.effect_sounds[key] = pygame.mixer.Sound(key)
            channel = next((item for item in self.effects_channels if not item.get_busy()), self.effects_channel)
            channel.play(self.effect_sounds[key])
        except (OSError, pygame.error) as error:
            self.errors.append(f'音效加载失败：{error}')

    def play_feedback(self, key):
        if not self.available:
            return
        if key in VOICE_FEEDBACK:
            self._enqueue(key)
        elif key in self.effect_sounds and self.effects_volume > 0:
            channels = self.effects_channels[:1] if key == 'ui_click' else self.effects_channels[1:]
            channel = next((item for item in channels if not item.get_busy()), channels[0])
            channel.play(self._sound_at_gain(self.effect_sounds[key], self.effects_volume))
            self._channel_volume(channel, self.effects_volume)

    def _channel_volume(self, channel, gain):
        sound = channel.get_sound()
        boost = self.sound_gains.get(id(sound), 1)
        channel.set_volume(min(1, max(0, gain/boost)))

    def _sound_at_gain(self, sound, gain):
        boost = round(max(1, gain), 2)
        if boost == 1:
            return sound
        key = (id(sound), boost)
        if key not in self.boosted_sounds:
            # Increase actual signal headroom, not just the slider label.
            # Saturate to signed PCM limits at the expanded upper settings.
            if pygame.mixer.get_init()[1] != -16:
                return sound
            samples = array('h', sound.get_raw())
            samples = array('h', (max(-32768, min(32767, round(value*boost))) for value in samples))
            boosted = pygame.mixer.Sound(buffer=samples.tobytes())
            if len(self.boosted_sounds) >= 24:
                self.boosted_sounds.clear()
                active = {id(channel.get_sound()) for channel in [self.channel, *self.effects_channels]}
                self.sound_gains = {key: value for key,value in self.sound_gains.items() if key in active}
            self.boosted_sounds[key] = boosted
            self.sound_gains[id(boosted)] = boost
        return self.boosted_sounds[key]

    def update(self, app):
        # start is deliberately called only by the interactive run loop. Static
        # rendering and engine consumers do not initialize or play any audio.
        if not self.available:
            return
        self.apply_settings(app.settings)
        engine = app.engine
        ending = app.page == 'result' or app.outcome_started_ms is not None
        battle_context = app.page == 'game' or (engine is not None and 'game' in app.page_stack)
        audio_context = battle_context or (app.page == 'result' and engine is not None)
        self._music(None if ending else ('battle' if battle_context else 'menu'))
        if not app.window_focused:
            pygame.mixer.music.pause()
            self.channel.pause()
            for channel in self.effects_channels:
                channel.pause()
            return
        pygame.mixer.music.unpause()
        self.effects_channel.unpause()
        if (audio_context and engine is not self.context_engine) or (not audio_context and self.context_engine is not None):
            self.queue.clear()
            self.channel.stop()
            for channel in self.effects_channels[1:]:
                channel.stop()
            self.context_engine = engine if audio_context else None
        if app.page not in {'game', 'result'} or app.pause_open or app.confirm_kind or app.battle_ui.details_open:
            self.channel.pause()
            for channel in self.effects_channels[1:]:
                if battle_context:
                    channel.pause()
                else:
                    channel.unpause()
            return
        self.channel.unpause()
        for channel in self.effects_channels:
            channel.unpause()
        if engine is None:
            return
        state = self.seen.setdefault(engine, {'serial': -1, 'turn': None, 'audio_serial': 0, 'result': False, 'deal': False})
        if ending:
            if not state['result']:
                state['result'] = True
                self.queue.clear()
                self.channel.stop()
                for channel in self.effects_channels:
                    channel.stop()
                outcome = engine.player_outcome
                if outcome in {'win', 'loss'}:
                    self.play_feedback('victory' if outcome == 'win' else 'defeat')
            self._play_queued()
            return
        if app.deal_started_ms is not None:
            elapsed = pygame.time.get_ticks() - app.deal_started_ms
            from xssgkpz.battle_transitions import deal_schedule
            starts = [start for _, _, start in deal_schedule(app)]
            tick = sum(elapsed >= start for start in starts)
            if tick != state.get('deal_tick'):
                state['deal_tick'] = tick
                if tick > 0:
                    self.play_feedback('card_draw')
            state['deal'] = True
            return
        if not state['deal']:
            state['deal'] = True
            self.play_feedback('card_draw')
        # Consume even when muted; do not replay old recovery/draw cues later.
        pending = set()
        for serial, key in engine.audio_events:
            if serial > state['audio_serial']:
                state['audio_serial'] = serial
                if key not in pending:
                    self.play_feedback(key)
                    pending.add(key)
        cue = engine.presentation_event
        if cue is not None and cue.serial != state['serial']:
            state['serial'] = cue.serial
            if cue.kind in {'play', 'response', 'rescue', 'negate'}:
                self.play_feedback('card_place')
            elif cue.kind in {'damage', 'equip'}:
                self.play_feedback(cue.kind)
            if cue.kind in {'play', 'response', 'negate'}:
                # effective_name is essential for converted cards (e.g. Qingguo,
                # Wusheng): never announce the discarded material's original name.
                name = cue.effective_name
                if not name and cue.card_ids:
                    instance = engine.state.cards.get(cue.card_ids[0])
                    definition = CARD_BY_ID.get(instance.definition_id) if instance else None
                    name = definition.name if definition else None
                kind = CARD_KIND_BY_NAME.get(name)
                if kind:
                    self._enqueue(kind.kind_id)
        if engine.is_human_turn:
            token = (engine.state.turn_number, engine.state.current_player_id)
            if token != state['turn']:
                state['turn'] = token
                self._enqueue('your_turn')
        self._play_queued()

    def _play_queued(self):
        if not self.channel.get_busy() and self.queue:
            self.channel.play(self._sound_at_gain(self.sounds[self.queue.popleft()], self.voice_volume))
            self._channel_volume(self.channel, self.voice_volume)
        pygame.mixer.music.set_volume(self.music_volume * (.625 if self.voice_volume > 0 and self.channel.get_busy() else 1))

    def close(self):
        if self.available and pygame.mixer.get_init():
            self.channel.stop()
            for channel in self.effects_channels:
                channel.stop()
            pygame.mixer.music.stop()
        self.queue.clear()

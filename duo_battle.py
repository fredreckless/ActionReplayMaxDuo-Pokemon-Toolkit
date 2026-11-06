"""A Gen 3 single battle on the PC, and three players for it: easy, medium and elite.

This is the thinking half of the battle partner (docs/BATTLE.md). In a real link battle the game
runs the battle; the DUO's program will pass the PC what happens and ask it for each choice. Here
the PC keeps its own model of the battle to choose with, and the same model can play whole battles
on its own, which is how the players are tested against each other.

    python duo_battle.py --demo                       a battle between two made-up teams
    python duo_battle.py --pk3 A.pk3 B.pk3 ... --vs C.pk3 ... --level elite --opponent medium

The numbers are pret/pokeemerald's (battle_data.py, made by tools/make_battle_data.py). The damage
follows pokemon.c CalculateBaseDamage and battle_script_commands.c (critcalc, damagecalc, typecalc,
adjustnormaldamage) step by step, rounding where the game rounds. The move effects, abilities and
held items that change battles most are modelled; the rarest are treated as doing nothing, which
only matters for choosing, never for the real game (which runs the battle itself).

Fair play: a player sees the other side as a person would (species, level, HP bar, status, what
has been used and shown) and fills the rest with likely guesses; `sees_all=True` lets it see
everything instead."""
import argparse, math, random, struct, sys

from battle_data import DATA

# ------------------------------------------------------------------------------------------- data
SPECIES = DATA["species"]                 # [hp, atk, def, spe, spa, spd, type1, type2, ability1, ability2]
MOVES = DATA["moves"]                     # [effect, power, type, accuracy, pp, chance, target, priority, flags]
EFFECT = {int(k): v for k, v in DATA["effects"].items()}
ABILITY = {int(k): v for k, v in DATA["abilities"].items()}
HOLD = {int(k): v for k, v in DATA["hold_effects"].items()}
HELD = {int(k): (HOLD.get(v[0], "NONE"), v[1]) for k, v in DATA["held"].items()}
TYPES = {int(k): v for k, v in DATA["types"].items()}
TYPE_ID = {v: k for k, v in TYPES.items()}
TARGET = DATA["targets"]
FLAGS = DATA["flags"]
CONTACT, PROTECTABLE = FLAGS["MAKES_CONTACT"], FLAGS["PROTECT_AFFECTED"]
MYSTERY = TYPE_ID["MYSTERY"]
CHART = {}                                # (attacking type, defending type) -> multiplier x10, as listed
_FORESIGHT_AT = None
for _i in range(0, len(DATA["type_chart"]), 3):
    _a, _d, _m = DATA["type_chart"][_i:_i + 3]
    if _a == 0xFE:
        _FORESIGHT_AT = len(CHART)        # (entries after this are skipped when Foresight is on)
        continue
    if _a == 0xFF:
        break
    CHART[(_a, _d)] = (_m, _FORESIGHT_AT is not None)

STAT_RATIOS = [(10, 40), (10, 35), (10, 30), (10, 25), (10, 20), (10, 15), (10, 10),
               (15, 10), (20, 10), (25, 10), (30, 10), (35, 10), (40, 10)]
ACC_RATIOS = [(33, 100), (36, 100), (43, 100), (50, 100), (60, 100), (75, 100), (1, 1),
              (133, 100), (166, 100), (2, 1), (233, 100), (133, 50), (3, 1)]
CRIT_CHANCE = [16, 8, 4, 3, 2]
TYPE_ITEMS = {"BUG_POWER": "BUG", "STEEL_POWER": "STEEL", "GROUND_POWER": "GROUND", "ROCK_POWER": "ROCK",
              "GRASS_POWER": "GRASS", "DARK_POWER": "DARK", "FIGHTING_POWER": "FIGHTING",
              "ELECTRIC_POWER": "ELECTRIC", "WATER_POWER": "WATER", "FLYING_POWER": "FLYING",
              "POISON_POWER": "POISON", "ICE_POWER": "ICE", "GHOST_POWER": "GHOST",
              "PSYCHIC_POWER": "PSYCHIC", "FIRE_POWER": "FIRE", "DRAGON_POWER": "DRAGON", "NORMAL_POWER": "NORMAL"}
ATK, DEF, SPE, SPA, SPD, ACC, EVA = range(7)  # stat stages (stored 0..12, 6 = normal)
STAGE_OF = {"ATTACK": ATK, "DEFENSE": DEF, "SPEED": SPE, "SPECIAL_ATTACK": SPA, "SPECIAL_DEFENSE": SPD,
            "ACCURACY": ACC, "EVASION": EVA}
SHEDINJA = 303
MOVE_STRUGGLE = 165


def tables():
    import secret_bases
    return secret_bases.tables()


def move_name(m):
    t = tables()
    return t.moves[m] if 0 < m < len(t.moves) else f"move {m}"


def species_name(s):
    t = tables()
    return t.species[s] if 0 < s < len(t.species) else f"species {s}"


def move_id(name):
    import secret_bases
    return secret_bases._lookup(name, tables().moves, "move")


def species_id(name):
    import secret_bases
    return secret_bases._lookup(name, tables().species, "Pokemon")


def item_id(name):
    import secret_bases
    return secret_bases._lookup(name, [i[0] for i in tables().items], "item") if name else 0


def effect_of(m):
    return EFFECT.get(MOVES[m][0], "HIT")


def type_mult(move_type, types, foresight=False):
    """The type chart's multiplier (x10 per type, as the game applies them), as a float."""
    mult = 1.0
    for i, t in enumerate(types):
        if i == 1 and t == types[0]:
            break
        m = CHART.get((move_type, t))
        if m and not (foresight and m[1]):
            mult *= m[0] / 10
    return mult


# ------------------------------------------------------------------------------------- Pokemon
class Mon:
    __slots__ = ("species", "level", "stats", "hp", "maxhp", "types", "ability", "item", "moves", "pp",
                 "status", "sleep", "toxic", "stages", "confused", "substitute", "seeded", "protect_count",
                 "protected", "recharge", "charging", "choice", "flinch", "focus", "trapped_by", "wrap",
                 "last_move", "truant", "flash_fire", "ivs", "nature", "name", "taken", "taken_physical",
                 "yawn", "taunt", "endure", "destiny", "invulnerable", "rampage", "known_moves", "shown_item",
                 "shown_ability", "nickname", "disabled", "encore", "biding", "uproar", "perish", "charged", "ingrained",
                 "cursed", "rampage_left")

    def __init__(self, species, level, moves, item=0, ability_slot=0, ivs=(31,) * 6, evs=(0,) * 6, nature=0,
                 hp=None, status=0, nickname=None):
        base = SPECIES[species]
        self.species, self.level, self.item = species, level, item
        self.ivs, self.nature = list(ivs), nature
        self.stats = []
        for i in range(6):
            n = (2 * base[i] + ivs[i] + evs[i] // 4) * level // 100
            if i == 0:
                self.stats.append(1 if species == SHEDINJA else n + level + 10)
                continue
            n += 5
            if nature // 5 != nature % 5:
                if nature // 5 == i - 1:
                    n = n * 110 // 100
                elif nature % 5 == i - 1:
                    n = n * 90 // 100
            self.stats.append(n)
        self.maxhp = self.stats[0]
        self.hp = self.maxhp if hp is None else hp
        self.types = [base[6], base[7]]
        self.ability = ABILITY.get(base[9] if ability_slot and base[9] else base[8], "NONE")
        self.moves = [m for m in moves if m][:4]
        self.pp = [MOVES[m][4] for m in self.moves]
        self.status, self.sleep, self.toxic = status, 0, 0
        self.name = nickname or species_name(species)
        self.nickname = self.name
        self.known_moves, self.shown_item, self.shown_ability = set(), False, False
        self.reset_volatile()

    def reset_volatile(self):
        self.stages = [6] * 7
        self.confused = self.substitute = self.protect_count = 0
        self.seeded = self.protected = self.recharge = self.flinch = self.focus = self.endure = False
        self.charging = self.choice = self.trapped_by = self.last_move = self.yawn = self.taunt = 0
        self.wrap = self.truant = self.rampage = self.disabled = self.encore = self.biding = self.uproar = 0
        self.flash_fire = self.destiny = self.invulnerable = self.charged = False
        self.perish = self.rampage_left = 0
        self.ingrained = self.cursed = False
        self.taken = self.taken_physical = 0
        if self.status != "TOX":
            self.toxic = 0

    def clone(self):
        c = Mon.__new__(Mon)
        for s in Mon.__slots__:
            v = getattr(self, s)
            setattr(c, s, list(v) if isinstance(v, list) else set(v) if isinstance(v, set) else v)
        return c

    @property
    def fainted(self):
        return self.hp <= 0

    def hold(self):
        return HELD.get(self.item, ("NONE", 0))

    def speed(self, weather):
        n, d = STAT_RATIOS[self.stages[SPE]]
        s = self.stats[3] * n // d
        if self.ability == "SWIFT_SWIM" and weather == "RAIN" or self.ability == "CHLOROPHYLL" and weather == "SUN":
            s *= 2
        if self.hold()[0] == "MACHO_BRACE":
            s //= 2
        if self.status == "PAR":
            s //= 4
        return s

    def describe(self):
        st = f" {self.status}" if self.status else ""
        return f"{self.name} {self.hp}/{self.maxhp}{st}"


def mon_from_pk3(data):
    """A Mon from a .pk3 (80 or 100 bytes), with the toolkit's own reader: its level and stats as
    the game works them out, its moves, item, ability (from the IVs word's top bit) and nature."""
    import duo_events as E
    f, problems = E.parse_pk3(data)
    if problems:
        raise ValueError("; ".join(problems))
    party = E.pk3_party_fields(f)
    level = party[4]
    ivword = struct.unpack_from("<I", f["blocks"], 36 + 4)[0]
    return Mon(f["species"], level, f["moves"], f["item"], ivword >> 31 & 1, f["ivs"], f["evs"], f["pid"] % 25,
               nickname=f["nickname"] or None)


def default_moves(species, level):
    """The moves a Pokemon of this species knows at this level from levelling up (the game's own
    default for a newly met one): the last four learnt."""
    t = tables()
    learnt = sorted(((lv, m) for m, lv in t.learn.get(species, ({}, set()))[0].items() if lv <= level),
                    key=lambda x: x[0])
    out = []
    for _, m in learnt:
        if m in out:
            out.remove(m)
        out.append(m)
    return out[-4:] or [33]


def learnable(species, level):
    """Every move this species can know at this level: its level-up moves so far, TMs, HMs and tutors."""
    lv, other = tables().learn.get(species, ({}, set()))
    return {m for m, at in lv.items() if at <= level} | set(other)


AWKWARD = {"RECHARGE", "EXPLOSION", "RAMPAGE", "FOCUS_PUNCH", "SKY_ATTACK", "RAZOR_WIND", "SKULL_BASH",
           "SEMI_INVULNERABLE", "SOLAR_BEAM", "FUTURE_SIGHT", "BIDE", "SNORE", "DREAM_EATER", "FAKE_OUT",
           "FALSE_SWIPE", "RECOIL_IF_MISS", "OHKO", "FRUSTRATION", "SPIT_UP", "ERUPTION", "FLAIL", "PRESENT",
           "SMELLINGSALT", "REVENGE", "UPROAR", "THIEF", "RAPID_SPIN", "PURSUIT", "TRAP"}


def likely_attacks(species, level):
    """Its attacks a trainer would use, strongest first: power x accuracy, x1.5 for its own type,
    x its attacking stat for the move's kind (physical or special types in Gen 3)."""
    base = SPECIES[species]
    def worth(m):
        p, t, a = MOVES[m][1], MOVES[m][2], MOVES[m][3] or 100
        if effect_of(m) in ("MULTI_HIT",):
            p *= 3
        elif effect_of(m) in ("DOUBLE_HIT", "TWINEEDLE"):
            p *= 2
        return p * a / 100 * (1.5 if t in base[6:8] else 1) * (base[1] if t < MYSTERY else base[4])
    pool = [m for m in learnable(species, level) if MOVES[m][1] > 1 and effect_of(m) not in AWKWARD
            and m != MOVE_STRUGGLE]
    return sorted(pool, key=lambda m: -worth(m))


# ---------------------------------------------------------------------------------------- sides
class Side:
    __slots__ = ("team", "active", "reflect", "light_screen", "safeguard", "mist", "spikes", "name", "wish")

    def __init__(self, team, name):
        self.team, self.active, self.name = team, 0, name
        self.reflect = self.light_screen = self.safeguard = self.mist = self.spikes = 0
        self.wish = None

    def clone(self):
        c = Side.__new__(Side)
        c.team = [m.clone() for m in self.team]
        for s in ("active", "reflect", "light_screen", "safeguard", "mist", "spikes", "name", "wish"):
            setattr(c, s, getattr(self, s))
        return c

    @property
    def mon(self):
        return self.team[self.active]

    def alive(self):
        return [i for i, m in enumerate(self.team) if not m.fainted]

    def bench(self):
        return [i for i in self.alive() if i != self.active]

    @property
    def lost(self):
        return not self.alive()


# --------------------------------------------------------------------------------------- battle
class Battle:
    """One single battle: two sides, the weather, the turn engine. `log` collects lines when set."""

    def __init__(self, team_a, team_b, seed=None, names=("A", "B"), log=False):
        self.sides = [Side(team_a, names[0]), Side(team_b, names[1])]
        self.rng = random.Random(seed)
        self.weather, self.weather_turns, self.turn = None, 0, 0
        self.log = [] if log else None
        self.winner = None
        for s in (0, 1):
            self.on_switch_in(s)

    def clone(self, seed=None):
        c = Battle.__new__(Battle)
        c.sides = [s.clone() for s in self.sides]
        c.rng = random.Random(seed)
        c.weather, c.weather_turns, c.turn, c.log, c.winner = self.weather, self.weather_turns, self.turn, None, self.winner
        return c

    def say(self, text):
        if self.log is not None:
            self.log.append(text)

    # ------------------------------------------------------------- helpers
    def weather_on(self):
        a, b = self.sides[0].mon, self.sides[1].mon
        if any(m.ability in ("CLOUD_NINE", "AIR_LOCK") and not m.fainted for m in (a, b)):
            return None
        return self.weather

    def legal_actions(self, s):
        """('move', index) for each usable move (or Struggle), ('switch', index) for each bench Pokemon."""
        side, mon = self.sides[s], self.sides[s].mon
        if mon.fainted:
            return [("switch", i) for i in side.bench()]
        if mon.recharge or mon.charging or mon.rampage or mon.biding or mon.uproar:
            return [("move", -1)]                    # (carries on: chosen for it)
        moves = []
        for i, m in enumerate(mon.moves):
            if mon.pp[i] <= 0 or (mon.choice and mon.choice != m) or mon.disabled == m:
                continue
            if mon.taunt and MOVES[m][1] == 0 and effect_of(m) not in ("COUNTER", "MIRROR_COAT", "LEVEL_DAMAGE"):
                continue
            if mon.encore and mon.encore != m:
                continue
            moves.append(("move", i))
        if not moves:
            moves = [("move", -2)]                   # Struggle
        trapped = (mon.trapped_by or mon.wrap) and mon.hold()[0] != "SHED_SHELL"
        foe = self.sides[1 - s].mon
        if not foe.fainted and (foe.ability == "SHADOW_TAG" or foe.ability == "ARENA_TRAP" and self.grounded(mon)
                                or foe.ability == "MAGNET_PULL" and TYPE_ID["STEEL"] in mon.types):
            trapped = True
        if mon.ingrained:
            trapped = True
        return moves + ([] if trapped else [("switch", i) for i in side.bench()])

    def grounded(self, mon):
        return TYPE_ID["FLYING"] not in mon.types and mon.ability != "LEVITATE"

    # ------------------------------------------------------------- damage (pokemon.c + battle_script_commands.c)
    def base_damage(self, att, de, move, side_de, crit, power=None, mtype=None):
        eff = effect_of(move)
        power = MOVES[move][1] if power is None else power
        mtype = MOVES[move][2] if mtype is None else mtype
        attack, defense, spatk, spdef = att.stats[1], de.stats[2], att.stats[4], de.stats[5]
        ah, ap = att.hold()
        dh, dp = de.hold()
        if att.ability in ("HUGE_POWER", "PURE_POWER"):
            attack *= 2
        if ah in TYPE_ITEMS and TYPE_ID[TYPE_ITEMS[ah]] == mtype:
            if mtype < MYSTERY:
                attack = attack * (ap + 100) // 100
            else:
                spatk = spatk * (ap + 100) // 100
        if ah == "CHOICE_BAND":
            attack = 150 * attack // 100
        latios = (species_id_cached("LATIOS"), species_id_cached("LATIAS"))
        if ah == "SOUL_DEW" and att.species in latios:
            spatk = 150 * spatk // 100
        if dh == "SOUL_DEW" and de.species in latios:
            spdef = 150 * spdef // 100
        if ah == "DEEP_SEA_TOOTH" and att.species == species_id_cached("CLAMPERL"):
            spatk *= 2
        if dh == "DEEP_SEA_SCALE" and de.species == species_id_cached("CLAMPERL"):
            spdef *= 2
        if ah == "LIGHT_BALL" and att.species == species_id_cached("PIKACHU"):
            spatk *= 2
        if dh == "METAL_POWDER" and de.species == species_id_cached("DITTO"):
            defense *= 2
        if ah == "THICK_CLUB" and att.species in (species_id_cached("CUBONE"), species_id_cached("MAROWAK")):
            attack *= 2
        if de.ability == "THICK_FAT" and mtype in (TYPE_ID["FIRE"], TYPE_ID["ICE"]):
            spatk //= 2
        if att.ability == "HUSTLE":
            attack = 150 * attack // 100
        if att.ability == "GUTS" and att.status:
            attack = 150 * attack // 100
        if de.ability == "MARVEL_SCALE" and de.status:
            defense = 150 * defense // 100
        third = att.hp <= att.maxhp // 3
        for ab, t in (("OVERGROW", "GRASS"), ("BLAZE", "FIRE"), ("TORRENT", "WATER"), ("SWARM", "BUG")):
            if att.ability == ab and mtype == TYPE_ID[t] and third:
                power = 150 * power // 100
        if eff == "EXPLOSION":
            defense //= 2
        damage = 0
        if mtype < MYSTERY:                                          # physical
            n, d = STAT_RATIOS[att.stages[ATK]]
            damage = attack * n // d if not (crit and att.stages[ATK] <= 6) else attack
            damage = damage * power * (2 * att.level // 5 + 2)
            n, d = STAT_RATIOS[de.stages[DEF]]
            helper = defense * n // d if not (crit and de.stages[DEF] >= 6) else defense
            damage = damage // max(1, helper) // 50
            if att.status == "BRN" and att.ability != "GUTS":
                damage //= 2
            if side_de.reflect and not crit:
                damage //= 2
            damage = max(1, damage)
        elif mtype > MYSTERY:                                        # special
            n, d = STAT_RATIOS[att.stages[SPA]]
            damage = spatk * n // d if not (crit and att.stages[SPA] <= 6) else spatk
            damage = damage * power * (2 * att.level // 5 + 2)
            n, d = STAT_RATIOS[de.stages[SPD]]
            helper = spdef * n // d if not (crit and de.stages[SPD] >= 6) else spdef
            damage = damage // max(1, helper) // 50
            if side_de.light_screen and not crit:
                damage //= 2
            w = self.weather_on()
            if w == "RAIN":
                if mtype == TYPE_ID["FIRE"]:
                    damage //= 2
                elif mtype == TYPE_ID["WATER"]:
                    damage = 15 * damage // 10
            if w in ("RAIN", "SAND", "HAIL") and eff == "SOLAR_BEAM":
                damage //= 2
            if w == "SUN":
                if mtype == TYPE_ID["FIRE"]:
                    damage = 15 * damage // 10
                elif mtype == TYPE_ID["WATER"]:
                    damage //= 2
            if att.flash_fire and mtype == TYPE_ID["FIRE"]:
                damage = 15 * damage // 10
        return damage + 2

    def move_type_power(self, att, de, move):
        """(type, power) as the move will use them: Hidden Power, Weather Ball, Flail and the like."""
        eff, power, mtype = effect_of(move), MOVES[move][1], MOVES[move][2]
        if eff == "HIDDEN_POWER":
            iv = att.ivs
            t = ((iv[0] & 1) + 2 * (iv[1] & 1) + 4 * (iv[2] & 1) + 8 * (iv[3] & 1) + 16 * (iv[4] & 1) + 32 * (iv[5] & 1)) * 15 // 63
            mtype = t + 1 if t + 1 < MYSTERY else t + 2
            power = ((iv[0] >> 1 & 1) + 2 * (iv[1] >> 1 & 1) + 4 * (iv[2] >> 1 & 1) + 8 * (iv[3] >> 1 & 1)
                     + 16 * (iv[4] >> 1 & 1) + 32 * (iv[5] >> 1 & 1)) * 40 // 63 + 30
        elif eff == "WEATHER_BALL" and self.weather_on():
            power = 100
            mtype = TYPE_ID[{"RAIN": "WATER", "SUN": "FIRE", "SAND": "ROCK", "HAIL": "ICE"}[self.weather_on()]]
        elif eff == "FLAIL":
            r = 48 * att.hp // att.maxhp
            power = 200 if r <= 1 else 150 if r <= 4 else 100 if r <= 9 else 80 if r <= 16 else 40 if r <= 32 else 20
        elif eff == "ERUPTION":
            power = max(1, 150 * att.hp // att.maxhp)
        elif eff == "RETURN":
            power = 102
        elif eff == "FRUSTRATION":
            power = 1
        elif eff == "FACADE" and att.status in ("PSN", "TOX", "BRN", "PAR"):
            power *= 2
        elif eff == "REVENGE" and att.taken:
            power *= 2
        elif eff == "SMELLINGSALT" and de.status == "PAR":
            power *= 2
        elif eff == "LOW_KICK":
            power = 60                                            # (weights aren't in the data: a middle value)
        elif eff == "MAGNITUDE":
            power = 70
        elif eff == "PRESENT":
            power = 40
        elif eff == "ROLLOUT" or eff == "FURY_CUTTER":
            power = MOVES[move][1]
        if att.charged and mtype == TYPE_ID["ELECTRIC"]:
            power *= 2
        return mtype, power

    def damage(self, att, de, move, side_de, crit=False, roll=100, mtype=None, power=None):
        """The damage one hit does: base damage, critical hit, STAB, types, the random roll (85-100)."""
        t, p = self.move_type_power(att, de, move)
        mtype = t if mtype is None else mtype
        power = p if power is None else power
        if power == 0 or mtype == MYSTERY:
            return 0, 1.0
        d = self.base_damage(att, de, move, side_de, crit, power, mtype)
        if crit:
            d *= 2
        if mtype in att.types:
            d = d * 15 // 10
        mult = 1.0
        foresight = False
        for i, t2 in enumerate(de.types):
            if i == 1 and t2 == de.types[0]:
                break
            m = CHART.get((mtype, t2))
            if m and not (foresight and m[1]):
                d = d * m[0] // 10
                if d == 0 and m[0]:
                    d = 1
                mult *= m[0] / 10
        if mult == 0:
            return 0, 0.0
        if d:
            d = max(1, d * roll // 100)
        return d, mult

    def immune(self, att, de, move):
        """Why the move can't affect the target at all (types, abilities), or ''."""
        mtype, power = self.move_type_power(att, de, move)
        eff = effect_of(move)
        if mtype == TYPE_ID["GROUND"] and de.ability == "LEVITATE" and power:
            return "Levitate"
        if mtype == TYPE_ID["ELECTRIC"] and de.ability == "VOLT_ABSORB" and move != 86 and power:
            return "Volt Absorb"
        if mtype == TYPE_ID["WATER"] and de.ability == "WATER_ABSORB" and power:
            return "Water Absorb"
        if mtype == TYPE_ID["FIRE"] and de.ability == "FLASH_FIRE":
            return "Flash Fire"
        if de.ability == "SOUNDPROOF" and move_name(move) in SOUND_MOVES:
            return "Soundproof"
        if move == MOVE_STRUGGLE:
            return ""
        if power or eff in ("LEVEL_DAMAGE", "SONICBOOM", "DRAGON_RAGE", "SUPER_FANG", "PSYWAVE", "OHKO", "ENDEAVOR"):
            if type_mult(mtype, de.types) == 0 and eff not in ("PSYWAVE",):
                return "types"
            if de.ability == "WONDER_GUARD" and power and type_mult(mtype, de.types) <= 1 and move != MOVE_STRUGGLE:
                return "Wonder Guard"
        if eff == "OHKO" and (de.ability == "STURDY" or de.level > att.level):
            return "Sturdy" if de.ability == "STURDY" else "level"
        return ""

    def accuracy(self, att, de, move):
        """The chance (0-1) the move hits, as Cmd_accuracycheck works it out."""
        eff, acc = effect_of(move), MOVES[move][3]
        if eff in ("ALWAYS_HIT", "VITAL_THROW") or acc == 0 or MOVES[move][6] == TARGET["USER"]:
            return 1.0
        if de.invulnerable:
            hits = {"ON_AIR": ("GUST", "TWISTER", "THUNDER", "SKY_UPPERCUT"), "UNDERGROUND": ("EARTHQUAKE", "MAGNITUDE"),
                    "UNDERWATER": ("SURF", "WHIRLPOOL")}.get(de.invulnerable, ())
            if move_name(move) not in hits:
                return 0.0
        if eff == "OHKO":
            return max(0, min(100, att.level - de.level + 30)) / 100
        if self.weather_on() == "RAIN" and eff == "THUNDER":
            return 1.0
        buff = max(0, min(12, att.stages[ACC] + 6 - de.stages[EVA]))
        if self.weather_on() == "SUN" and eff == "THUNDER":
            acc = 50
        n, d = ACC_RATIOS[buff]
        calc = n * acc // d
        if att.ability == "COMPOUND_EYES":
            calc = calc * 130 // 100
        if self.weather_on() == "SAND" and de.ability == "SAND_VEIL":
            calc = calc * 80 // 100
        mtype = self.move_type_power(att, de, move)[0]
        if att.ability == "HUSTLE" and mtype < MYSTERY:
            calc = calc * 80 // 100
        h, p = de.hold()
        if h == "EVASION_UP":
            calc = calc * (100 - p) // 100
        return min(100, calc) / 100

    def crit_chance(self, att, de, move):
        if de.ability in ("BATTLE_ARMOR", "SHELL_ARMOR"):
            return 0.0
        eff, h = effect_of(move), att.hold()[0]
        c = (2 * att.focus + (eff in ("HIGH_CRITICAL", "SKY_ATTACK", "BLAZE_KICK", "POISON_TAIL"))
             + (h == "SCOPE_LENS") + 2 * (h == "LUCKY_PUNCH" and att.species == species_id_cached("CHANSEY"))
             + 2 * (h == "STICK" and att.species == species_id_cached("FARFETCHD")))
        return 1 / CRIT_CHANCE[min(c, 4)]

    # ------------------------------------------------------------- the turn
    def order(self, actions):
        """Who acts first: switches, then priority, then speed (Quick Claw), ties at random."""
        keys = []
        for s in (0, 1):
            kind, i = actions[s]
            mon = self.sides[s].mon
            if kind == "switch":
                keys.append((2, 0, 0))
                continue
            m = self.chosen_move(s, i)
            prio = MOVES[m][7] if m else 0
            qc = mon.hold()[0] == "QUICK_CLAW" and self.rng.randrange(100) < mon.hold()[1]
            keys.append((1, prio, (1 if qc else 0, mon.speed(self.weather_on()))))
        if keys[0] == keys[1]:
            return [0, 1] if self.rng.random() < 0.5 else [1, 0]
        return [0, 1] if keys[0] > keys[1] else [1, 0]

    def chosen_move(self, s, i):
        mon = self.sides[s].mon
        if i == -2:
            return MOVE_STRUGGLE
        if i == -1:                                     # carrying on (charging, rampage, recharge)
            return mon.charging or mon.rampage or mon.last_move or MOVE_STRUGGLE
        return mon.moves[i]

    def play_turn(self, actions):
        """One turn: actions[s] is ('move', i) or ('switch', j)."""
        self.turn += 1
        for s in (0, 1):
            self.sides[s].mon.protected = False
            self.sides[s].mon.flinch = False
            self.sides[s].mon.endure = False
            self.sides[s].mon.taken = self.sides[s].mon.taken_physical = 0
        first = self.order(actions)
        chose = [self.sides[0].active, self.sides[1].active]
        moved = []
        for s in first:
            kind, i = actions[s]
            if kind == "switch":
                self.switch(s, i)
                continue
            if self.sides[s].mon.fainted or self.sides[s].active != chose[s]:   # (dragged out by Roar)
                continue
            self.use_move(s, i, moved_second=bool(moved))
            moved.append(s)
            if self.check_end():
                return
        self.end_of_turn()
        self.check_end()

    def check_end(self):
        for side in self.sides:                            # (recoil and the like can overshoot)
            for m in side.team:
                if m.hp < 0:
                    m.hp = 0
        for s in (0, 1):
            if self.sides[s].lost:
                self.winner = 1 - s if not self.sides[1 - s].lost else None
                if self.winner is None:
                    self.winner = -1                   # (both out at once: a draw)
                return True
        return False

    def switch(self, s, i, forced=False):
        side = self.sides[s]
        out = side.mon
        if not out.fainted and out.ability == "NATURAL_CURE":
            out.status = 0
        baton = None
        out.reset_volatile()
        foe = self.sides[1 - s].mon
        if foe.trapped_by:
            foe.trapped_by = 0
        side.active = i
        self.say(f"{side.name} sends out {side.mon.name}")
        self.on_switch_in(s, baton)

    def on_switch_in(self, s, baton=None):
        side, mon, foe = self.sides[s], self.sides[s].mon, self.sides[1 - s].mon
        if side.spikes and self.grounded(mon):
            mon.hp -= max(1, mon.maxhp // {1: 8, 2: 6, 3: 4}[side.spikes])
        a = mon.ability
        weather = {"DRIZZLE": "RAIN", "DROUGHT": "SUN", "SAND_STREAM": "SAND"}.get(a)
        if weather:
            self.weather, self.weather_turns = weather, 0       # (permanent until replaced)
            mon.shown_ability = True
        if a == "INTIMIDATE" and not foe.fainted and foe.ability not in ("CLEAR_BODY", "WHITE_SMOKE", "HYPER_CUTTER") \
                and not foe.substitute:
            foe.stages[ATK] = max(0, foe.stages[ATK] - 1)
            mon.shown_ability = True
        if a == "TRACE" and not foe.fainted and foe.ability not in ("TRACE", "NONE"):
            mon.ability = foe.ability

    def use_move(self, s, i, moved_second):
        side, foe_side = self.sides[s], self.sides[1 - s]
        att, de = side.mon, foe_side.mon
        move = self.chosen_move(s, i)
        if att.recharge:
            att.recharge = False
            self.say(f"{att.name} must recharge")
            return
        if att.ability == "TRUANT":
            att.truant ^= 1
            if not att.truant:
                return
        if att.status == "SLP":
            att.sleep -= 2 if att.ability == "EARLY_BIRD" else 1
            if att.sleep > 0:
                if effect_of(move) not in ("SNORE", "SLEEP_TALK"):
                    self.say(f"{att.name} is fast asleep")
                    att.charging = 0
                    return
            else:
                att.status, att.sleep = 0, 0
                self.say(f"{att.name} woke up")
        if att.status == "FRZ":
            if self.rng.randrange(5) == 0 or effect_of(move) in ("THAW_HIT",):
                att.status = 0
            else:
                self.say(f"{att.name} is frozen solid")
                return
        if att.flinch and moved_second:
            self.say(f"{att.name} flinched")
            att.charging = 0
            return
        if att.confused:
            att.confused -= 1
            if att.confused and self.rng.random() < 0.5:
                d = self.confusion_damage(att)
                att.hp -= d
                self.say(f"{att.name} hurt itself in its confusion ({d})")
                att.charging = 0
                return
        if att.status == "PAR" and self.rng.randrange(4) == 0:
            self.say(f"{att.name} is fully paralysed")
            att.charging = att.rampage = 0
            return
        if i >= 0 and not att.charging and not att.rampage:
            k = att.moves.index(move)
            att.pp[k] -= 2 if de.ability == "PRESSURE" and not de.fainted else 1
            att.pp[k] = max(0, att.pp[k])
        att.known_moves.add(move)
        if effect_of(move) not in ("PROTECT", "ENDURE"):
            att.protect_count = 0
        if att.hold()[0] == "CHOICE_BAND" and move != MOVE_STRUGGLE:
            att.choice = att.choice or move
        att.last_move = move
        self.say(f"{side.name}'s {att.name} uses {move_name(move)}")
        self.execute(s, move)

    def confusion_damage(self, mon):
        """A typeless 40-power physical hit on itself (no crit, no roll beyond the game's)."""
        n, d = STAT_RATIOS[mon.stages[ATK]]
        dmg = mon.stats[1] * n // d * 40 * (2 * mon.level // 5 + 2)
        n, d = STAT_RATIOS[mon.stages[DEF]]
        dmg = dmg // max(1, mon.stats[2] * n // d) // 50 + 2
        return max(1, dmg * self.rng.randrange(85, 101) // 100)

    def execute(self, s, move):
        side, foe_side = self.sides[s], self.sides[1 - s]
        att, de = side.mon, foe_side.mon
        eff = effect_of(move)
        target_self = MOVES[move][6] in (TARGET["USER"], TARGET.get("OPPONENTS_FIELD", 64)) or eff in SELF_EFFECTS
        # two-turn moves: the first turn only gets ready
        if eff in TWO_TURN and not att.charging:
            if eff == "SOLAR_BEAM" and self.weather_on() == "SUN":
                pass
            else:
                att.charging = move
                if eff == "SEMI_INVULNERABLE":
                    att.invulnerable = {"FLY": "ON_AIR", "BOUNCE": "ON_AIR", "DIG": "UNDERGROUND", "DIVE": "UNDERWATER"}.get(
                        move_name(move), "ON_AIR")
                if eff == "SKULL_BASH":
                    att.stages[DEF] = min(12, att.stages[DEF] + 1)
                self.say(f"{att.name} is getting ready")
                return
        att.charging = 0
        att.invulnerable = False
        if eff == "FOCUS_PUNCH" and att.taken:
            self.say(f"{att.name} lost its focus")
            return
        if not target_self and de.fainted:
            return
        if not target_self and de.protected and MOVES[move][8] & PROTECTABLE:
            self.say(f"{de.name} protected itself")
            att.rampage = 0
            return
        if not target_self:
            why = self.immune(att, de, move)
            if why:
                self.say(f"it doesn't affect {de.name} ({why})")
                mtype = self.move_type_power(att, de, move)[0]
                if why == "Volt Absorb" or why == "Water Absorb":
                    de.hp = min(de.maxhp, de.hp + de.maxhp // 4)
                    de.shown_ability = True
                if why == "Flash Fire":
                    de.flash_fire = True
                    de.shown_ability = True
                if eff == "RECOIL_IF_MISS":
                    att.hp -= max(1, att.maxhp // 2) if False else 0
                att.rampage = 0
                return
            if self.rng.random() >= self.accuracy(att, de, move):
                self.say(f"{att.name}'s attack missed")
                if eff == "RECOIL_IF_MISS":
                    att.hp -= max(1, min(de.maxhp // 2, de.hp) // 8)
                att.rampage = 0
                if eff == "EXPLOSION":
                    att.hp = 0
                return
        handler = EFFECTS.get(eff)
        power = self.move_type_power(att, de, move)[1]
        if power and eff not in NON_DAMAGE:
            self.hit(s, move, eff)
            if handler and eff in AFTER_HIT:
                handler(self, s, move)
        elif handler:
            handler(self, s, move)
        elif eff in ("LEVEL_DAMAGE", "SONICBOOM", "DRAGON_RAGE", "SUPER_FANG", "PSYWAVE", "OHKO", "ENDEAVOR"):
            self.fixed_damage(s, move, eff)

    def deal(self, s, amount, physical=True, from_move=True):
        """Damage to the other side's active Pokemon: Substitute, Endure, Focus Band, the record."""
        de = self.sides[1 - s].mon
        if de.substitute and from_move:
            de.substitute -= amount
            if de.substitute <= 0:
                de.substitute = 0
            return amount
        if amount >= de.hp:
            h, p = de.hold()
            if de.endure or (h == "FOCUS_BAND" and self.rng.randrange(100) < p):
                amount = de.hp - 1
        amount = min(amount, de.hp)
        de.hp -= amount
        de.taken += amount
        if physical:
            de.taken_physical += amount
        return amount

    def hit(self, s, move, eff):
        att, de, foe_side = self.sides[s].mon, self.sides[1 - s].mon, self.sides[1 - s]
        hits = 1
        if eff == "MULTI_HIT":
            hits = self.rng.choice([2, 2, 2, 3, 3, 3, 4, 5])
        elif eff in ("DOUBLE_HIT", "TWINEEDLE"):
            hits = 2
        elif eff == "TRIPLE_KICK":
            hits = 3
        total, mult = 0, 1.0
        mtype = self.move_type_power(att, de, move)[0]
        for h in range(hits):
            if de.fainted:
                break
            crit = self.rng.random() < self.crit_chance(att, de, move)
            power = None
            if eff == "TRIPLE_KICK":
                power = 10 * (h + 1)
            d, mult = self.damage(att, de, move, foe_side, crit, self.rng.randrange(85, 101), power=power)
            if eff in ("EARTHQUAKE",) and de.invulnerable == "UNDERGROUND":
                d *= 2
            if eff == "PURSUIT" and False:
                d *= 2
            if move == MOVE_STRUGGLE:
                d = self.base_damage(att, de, move, foe_side, crit) * (2 if crit else 1) * self.rng.randrange(85, 101) // 100
            total += self.deal(s, d, physical=mtype < MYSTERY)
            # contact abilities and the King's Rock
            if MOVES[move][8] & CONTACT and not de.fainted:
                self.contact(att, de)
            if att.hold()[0] == "KINGS_ROCK" and self.rng.randrange(100) < att.hold()[1] and MOVES[move][8] & FLAGS["KINGS_ROCK_AFFECTED"]:
                de.flinch = True
        self.say(f"  {de.name} takes {total} ({de.hp}/{de.maxhp})")
        if total and de.hold()[0] in ("RESTORE_HP", "CONFUSE_SPICY", "CONFUSE_DRY", "CONFUSE_SWEET", "CONFUSE_BITTER", "CONFUSE_SOUR"):
            self.berry(de)
        # drain and recoil
        if eff in ("ABSORB", "DREAM_EATER"):
            att.hp = min(att.maxhp, att.hp + max(1, total // 2))
        elif eff == "RECOIL" and att.ability != "ROCK_HEAD":
            att.hp -= max(1, total // 4)
        elif eff == "DOUBLE_EDGE" and att.ability != "ROCK_HEAD":
            att.hp -= max(1, total // 3)
        elif move == MOVE_STRUGGLE:
            att.hp -= max(1, total // 4)
        if att.hold()[0] == "SHELL_BELL" and total and att.hp < att.maxhp:
            att.hp = min(att.maxhp, att.hp + max(1, total // 8))
            att.shown_item = True
        if eff == "EXPLOSION":
            att.hp = 0
        if eff == "RECHARGE" and not de.fainted:
            att.recharge = True
        if eff == "RAMPAGE":
            if not att.rampage:
                att.rampage = move
                att.biding = 0
                att.rampage_left = self.rng.choice([1, 2])
            else:
                att.rampage_left -= 1
                if att.rampage_left <= 0:
                    att.rampage = 0
                    if att.ability != "OWN_TEMPO":
                        att.confused = self.rng.randrange(2, 6)
        # the move's chance of something more
        chance = MOVES[move][5]
        if att.ability == "SERENE_GRACE":
            chance *= 2
        if chance and not de.fainted and de.ability != "SHIELD_DUST" and not de.substitute and self.rng.randrange(100) < chance:
            self.secondary(s, move, eff)
        if eff in ("RAPID_SPIN",):
            att.seeded = att.wrap = 0
            self.sides[s].spikes = 0
        if eff == "KNOCK_OFF" and de.item and de.ability != "STICKY_HOLD":
            de.item = 0
        if eff == "THIEF" and de.item and not att.item and de.ability != "STICKY_HOLD":
            att.item, de.item = de.item, 0
        if eff == "SUPERPOWER":
            att.stages[ATK] = max(0, att.stages[ATK] - 1)
            att.stages[DEF] = max(0, att.stages[DEF] - 1)
        if eff == "OVERHEAT":
            att.stages[SPA] = max(0, att.stages[SPA] - 2)
        if eff == "BRICK_BREAK":
            foe_side.reflect = foe_side.light_screen = 0
        if eff == "TRAP" and not de.fainted and not de.wrap:
            de.wrap = self.rng.randrange(2, 6)
        if eff == "FAKE_OUT" and not de.fainted:
            pass                                          # (the flinch is its secondary effect)

    def contact(self, att, de):
        a = de.ability
        if att.fainted:
            return
        if a == "ROUGH_SKIN":
            att.hp -= max(1, att.maxhp // 16)
        elif a in ("STATIC", "FLAME_BODY", "POISON_POINT", "EFFECT_SPORE") and self.rng.randrange(3) == 0 and not att.status:
            st = {"STATIC": "PAR", "FLAME_BODY": "BRN", "POISON_POINT": "PSN"}.get(a) or self.rng.choice(["PSN", "PAR", "SLP"])
            self.give_status(att, st, by_foe=True)

    def secondary(self, s, move, eff):
        att, de = self.sides[s].mon, self.sides[1 - s].mon
        status = {"POISON_HIT": "PSN", "BURN_HIT": "BRN", "FREEZE_HIT": "FRZ", "PARALYZE_HIT": "PAR",
                  "POISON_FANG": "TOX", "BLAZE_KICK": "BRN", "POISON_TAIL": "PSN", "THUNDER": "PAR",
                  "TWINEEDLE": "PSN"}.get(eff)
        if status:
            self.give_status(de, status, side=self.sides[1 - s])
        elif eff == "TRI_ATTACK":
            self.give_status(de, self.rng.choice(["BRN", "FRZ", "PAR"]), side=self.sides[1 - s])
        elif eff in ("FLINCH_HIT", "FAKE_OUT", "TWISTER", "STOMP", "SNORE", "SKY_ATTACK"):
            if de.ability != "INNER_FOCUS":
                de.flinch = True
        elif eff == "CONFUSE_HIT":
            if de.ability != "OWN_TEMPO" and not de.confused and not self.sides[1 - s].safeguard:
                de.confused = self.rng.randrange(2, 6)
        elif eff.endswith("_DOWN_HIT"):
            stat = STAGE_OF.get(eff[:-9])
            if stat is not None and not self.sides[1 - s].mist and de.ability not in ("CLEAR_BODY", "WHITE_SMOKE"):
                de.stages[stat] = max(0, de.stages[stat] - 1)
        elif eff in ("ATTACK_UP_HIT", "DEFENSE_UP_HIT", "SPECIAL_ATTACK_UP_HIT"):
            stat = STAGE_OF[eff[:-7]]
            att.stages[stat] = min(12, att.stages[stat] + 1)
        elif eff == "ALL_STATS_UP_HIT":
            for stat in (ATK, DEF, SPE, SPA, SPD):
                att.stages[stat] = min(12, att.stages[stat] + 1)

    def give_status(self, mon, status, side=None, by_foe=False):
        """True if the status took (not already one, not immune by type, ability or Safeguard)."""
        if mon.fainted or mon.status:
            return False
        if side is not None and side.safeguard:
            return False
        a, types = mon.ability, mon.types
        if status in ("PSN", "TOX") and (TYPE_ID["POISON"] in types or TYPE_ID["STEEL"] in types or a == "IMMUNITY"):
            return False
        if status == "BRN" and (TYPE_ID["FIRE"] in types or a == "WATER_VEIL"):
            return False
        if status == "FRZ" and (TYPE_ID["ICE"] in types or a == "MAGMA_ARMOR" or self.weather_on() == "SUN"):
            return False
        if status == "PAR" and a == "LIMBER":
            return False
        if status == "SLP" and (a in ("INSOMNIA", "VITAL_SPIRIT") or any(m.uproar for m in (self.sides[0].mon, self.sides[1].mon))):
            return False
        mon.status = status
        if status == "SLP":
            mon.sleep = self.rng.randrange(2, 6)
        if status == "TOX":
            mon.toxic = 1
        if mon.hold()[0] in ("CURE_STATUS", "CURE_PAR", "CURE_SLP", "CURE_PSN", "CURE_BRN", "CURE_FRZ"):
            self.berry(mon)
        return True

    def berry(self, mon):
        h, p = mon.hold()
        used = False
        if h == "RESTORE_HP" and mon.hp <= mon.maxhp // 2 and not mon.fainted:
            mon.hp = min(mon.maxhp, mon.hp + p)
            used = True
        elif h.startswith("CONFUSE_") and mon.hp <= mon.maxhp // 2 and not mon.fainted:
            mon.hp = min(mon.maxhp, mon.hp + mon.maxhp // 8)
            used = True
        elif h == "CURE_STATUS" and (mon.status or mon.confused):
            mon.status, mon.confused, mon.sleep = 0, 0, 0
            used = True
        elif h in ("CURE_PAR", "CURE_SLP", "CURE_PSN", "CURE_BRN", "CURE_FRZ") and mon.status:
            want = {"CURE_PAR": ("PAR",), "CURE_SLP": ("SLP",), "CURE_PSN": ("PSN", "TOX"), "CURE_BRN": ("BRN",),
                    "CURE_FRZ": ("FRZ",)}[h]
            if mon.status in want:
                mon.status, mon.sleep = 0, 0
                used = True
        if used:
            mon.item = 0
            mon.shown_item = True

    def fixed_damage(self, s, move, eff):
        att, de = self.sides[s].mon, self.sides[1 - s].mon
        d = {"LEVEL_DAMAGE": att.level, "SONICBOOM": 20, "DRAGON_RAGE": 40, "SUPER_FANG": max(1, de.hp // 2),
             "PSYWAVE": max(1, att.level * self.rng.randrange(5, 16) // 10), "OHKO": de.hp,
             "ENDEAVOR": max(0, de.hp - att.hp)}[eff]
        self.deal(s, d, physical=False)
        self.say(f"  {de.name} takes {d} ({de.hp}/{de.maxhp})")

    def end_of_turn(self):
        w = self.weather_on()
        for s in (0, 1):
            m = self.sides[s].mon
            if m.fainted:
                continue
            if w == "SAND" and not any(t in m.types for t in (TYPE_ID["ROCK"], TYPE_ID["GROUND"], TYPE_ID["STEEL"])) \
                    and m.ability != "SAND_VEIL" and not m.invulnerable:
                m.hp -= max(1, m.maxhp // 16)
            if w == "HAIL" and TYPE_ID["ICE"] not in m.types and not m.invulnerable:
                m.hp -= max(1, m.maxhp // 16)
            if w == "RAIN" and m.ability == "RAIN_DISH":
                m.hp = min(m.maxhp, m.hp + max(1, m.maxhp // 16))
        if self.weather and self.weather_turns:
            self.weather_turns -= 1
            if not self.weather_turns:
                self.weather = None
        for s in (0, 1):
            side, m, foe = self.sides[s], self.sides[s].mon, self.sides[1 - s].mon
            if m.fainted:
                continue
            if side.wish is not None:
                if side.wish[0] <= 1:
                    m.hp = min(m.maxhp, m.hp + side.wish[1])
                    side.wish = None
                else:
                    side.wish = (side.wish[0] - 1, side.wish[1])
            if m.ingrained:
                m.hp = min(m.maxhp, m.hp + max(1, m.maxhp // 16))
            if m.hold()[0] == "LEFTOVERS" and m.hp < m.maxhp:
                m.hp = min(m.maxhp, m.hp + max(1, m.maxhp // 16))
                m.shown_item = True
            if m.seeded and not foe.fainted:
                d = min(m.hp, max(1, m.maxhp // 8))
                m.hp -= d
                foe.hp = min(foe.maxhp, foe.hp + d)
            if m.status == "PSN":
                m.hp -= max(1, m.maxhp // 8)
            elif m.status == "TOX":
                m.hp -= max(1, m.maxhp * m.toxic // 16)
                m.toxic = min(15, m.toxic + 1)
            elif m.status == "BRN":
                m.hp -= max(1, m.maxhp // 8)
            if m.wrap:
                m.wrap -= 1
                m.hp -= max(1, m.maxhp // 16)
            if m.yawn:
                m.yawn -= 1
                if not m.yawn:
                    self.give_status(m, "SLP", side=side)
            if m.ability == "SPEED_BOOST" and not m.fainted:
                m.stages[SPE] = min(12, m.stages[SPE] + 1)
            if m.ability == "SHED_SKIN" and m.status and self.rng.randrange(3) == 0:
                m.status, m.sleep = 0, 0
            if m.taunt:
                m.taunt -= 1
            if m.cursed:
                m.hp -= max(1, m.maxhp // 4)
            if m.perish:
                m.perish -= 1
                if not m.perish:
                    m.hp = 0
            if m.hold()[0] in ("RESTORE_HP", "CONFUSE_SPICY", "CONFUSE_DRY", "CONFUSE_SWEET", "CONFUSE_BITTER", "CONFUSE_SOUR"):
                self.berry(m)
            m.hp = max(0, m.hp)
            m.charged = False
            for attr in ("reflect", "light_screen", "safeguard", "mist"):
                v = getattr(side, attr)
                if v:
                    setattr(side, attr, v - 1)
        for s in (0, 1):
            self.sides[s].mon.hp = max(0, self.sides[s].mon.hp)

    # ------------------------------------------------------------- playing a whole battle
    def run(self, players, max_turns=200):
        """Plays to the end with two players (objects with choose(battle, side) and replace(battle, side))."""
        while self.winner is None and self.turn < max_turns:
            for s in (0, 1):
                if self.sides[s].mon.fainted and self.sides[s].bench():
                    self.switch(s, players[s].replace(self, s), forced=True)
            if self.check_end():
                break
            actions = [players[s].choose(self, s) for s in (0, 1)]
            self.play_turn(actions)
        if self.winner is None:
            hp = [sum(m.hp / m.maxhp for m in side.team) for side in self.sides]
            self.winner = 0 if hp[0] > hp[1] else 1 if hp[1] > hp[0] else -1
        return self.winner


_SPECIES_CACHE = {}


def species_id_cached(name):
    if name not in _SPECIES_CACHE:
        _SPECIES_CACHE[name] = species_id(name)
    return _SPECIES_CACHE[name]


SOUND_MOVES = {"GROWL", "ROAR", "SING", "SUPERSONIC", "SCREECH", "SNORE", "UPROAR", "METAL SOUND", "GRASSWHISTLE",
               "HYPER VOICE", "PERISH SONG", "HEAL BELL"}
TWO_TURN = {"RAZOR_WIND", "SKY_ATTACK", "SOLAR_BEAM", "SEMI_INVULNERABLE", "SKULL_BASH"}
SELF_EFFECTS = {"PROTECT", "ENDURE", "REST", "RESTORE_HP", "SOFTBOILED", "MORNING_SUN", "SYNTHESIS", "MOONLIGHT",
                "LIGHT_SCREEN", "REFLECT", "SAFEGUARD", "MIST", "RAIN_DANCE", "SUNNY_DAY", "SANDSTORM", "HAIL",
                "SUBSTITUTE", "FOCUS_ENERGY", "BELLY_DRUM", "CURSE", "BULK_UP", "CALM_MIND", "DRAGON_DANCE",
                "COSMIC_POWER", "DEFENSE_CURL", "MINIMIZE", "WISH", "INGRAIN", "REFRESH", "HEAL_BELL", "CHARGE",
                "STOCKPILE", "SPLASH", "TELEPORT", "BATON_PASS", "SPIKES", "SLEEP_TALK", "PERISH_SONG"}
SELF_EFFECTS |= {e for e in set(EFFECT.values()) if e.endswith("_UP") or e.endswith("_UP_2")}
NON_DAMAGE = {"LEVEL_DAMAGE", "SONICBOOM", "DRAGON_RAGE", "SUPER_FANG", "PSYWAVE", "OHKO", "ENDEAVOR", "COUNTER",
              "MIRROR_COAT", "BIDE", "PRESENT"}
AFTER_HIT = set()


# ---------------------------------------------------------------------------------- move effects
def _stat(target_self, stat, n):
    def f(b, s, move):
        att, de = b.sides[s].mon, b.sides[1 - s].mon
        mon = att if target_self else de
        if not target_self:
            if b.sides[1 - s].mist or de.ability in ("CLEAR_BODY", "WHITE_SMOKE") or de.substitute \
                    or (stat == ATK and de.ability == "HYPER_CUTTER") or (stat == ACC and de.ability == "KEEN_EYE"):
                return
        mon.stages[stat] = max(0, min(12, mon.stages[stat] + n))
    return f


def _status(st):
    def f(b, s, move):
        de = b.sides[1 - s].mon
        if de.substitute and st != "PAR":
            return
        if st == "PAR" and move == 86 and b.type_ok_tw(de) is False:
            return
        b.give_status(de, st, side=b.sides[1 - s])
    return f


def _heal(fraction_by_weather=False):
    def f(b, s, move):
        m = b.sides[s].mon
        amount = m.maxhp // 2
        if fraction_by_weather:
            w = b.weather_on()
            amount = m.maxhp * 2 // 3 if w == "SUN" else m.maxhp // 4 if w else m.maxhp // 2
        m.hp = min(m.maxhp, m.hp + amount)
    return f


def _weather(kind):
    def f(b, s, move):
        b.weather, b.weather_turns = kind, 5
    return f


def _screen(attr, turns=5):
    def f(b, s, move):
        side = b.sides[s]
        if not getattr(side, attr):
            setattr(side, attr, turns)
    return f


def _protect(b, s, move):
    m = b.sides[s].mon
    if b.rng.random() < 1 / 2 ** min(m.protect_count, 3):
        if effect_of(move) == "ENDURE":
            m.endure = True
        else:
            m.protected = True
        m.protect_count += 1
    else:
        m.protect_count = 0


def _rest(b, s, move):
    m = b.sides[s].mon
    if m.hp == m.maxhp or m.ability in ("INSOMNIA", "VITAL_SPIRIT"):
        return
    m.hp, m.status, m.sleep = m.maxhp, "SLP", 3


def _substitute(b, s, move):
    m = b.sides[s].mon
    if m.substitute or m.hp <= m.maxhp // 4:
        return
    m.hp -= m.maxhp // 4
    m.substitute = m.maxhp // 4


def _leech_seed(b, s, move):
    de = b.sides[1 - s].mon
    if TYPE_ID["GRASS"] not in de.types and not de.substitute:
        de.seeded = True


def _confuse(b, s, move):
    de = b.sides[1 - s].mon
    if not de.confused and de.ability != "OWN_TEMPO" and not de.substitute and not b.sides[1 - s].safeguard:
        de.confused = b.rng.randrange(2, 6)


def _swagger(b, s, move):
    de = b.sides[1 - s].mon
    if de.substitute:
        return
    stat = SPA if effect_of(move) == "FLATTER" else ATK
    de.stages[stat] = min(12, de.stages[stat] + (1 if stat == SPA else 2))
    _confuse(b, s, move)


def _toxic(b, s, move):
    de = b.sides[1 - s].mon
    if not de.substitute:
        b.give_status(de, "TOX", side=b.sides[1 - s])


def _will_o_wisp(b, s, move):
    de = b.sides[1 - s].mon
    if not de.substitute:
        b.give_status(de, "BRN", side=b.sides[1 - s])


def _belly_drum(b, s, move):
    m = b.sides[s].mon
    if m.hp > m.maxhp // 2:
        m.hp -= m.maxhp // 2
        m.stages[ATK] = 12


def _curse(b, s, move):
    m, de = b.sides[s].mon, b.sides[1 - s].mon
    if TYPE_ID["GHOST"] in m.types:
        m.hp -= m.maxhp // 2
        de.cursed = True
    else:
        m.stages[SPE] = max(0, m.stages[SPE] - 1)
        m.stages[ATK] = min(12, m.stages[ATK] + 1)
        m.stages[DEF] = min(12, m.stages[DEF] + 1)


def _multi_up(stats):
    def f(b, s, move):
        m = b.sides[s].mon
        for st in stats:
            m.stages[st] = min(12, m.stages[st] + 1)
    return f


def _haze(b, s, move):
    for side in b.sides:
        side.mon.stages = [6] * 7


def _roar(b, s, move):
    side = b.sides[1 - s]
    if side.bench() and side.mon.ability != "SUCTION_CUPS" and not side.mon.ingrained:
        b.switch(1 - s, b.rng.choice(side.bench()))


def _counter(kind):
    def f(b, s, move):
        m = b.sides[s].mon
        taken = m.taken_physical if kind == "physical" else m.taken - m.taken_physical
        if taken:
            b.deal(s, 2 * taken, physical=False)
    return f


def _pain_split(b, s, move):
    m, de = b.sides[s].mon, b.sides[1 - s].mon
    avg = (m.hp + de.hp) // 2
    m.hp, de.hp = min(m.maxhp, avg), min(de.maxhp, avg)


def _spikes(b, s, move):
    side = b.sides[1 - s]
    side.spikes = min(3, side.spikes + 1)


def _yawn(b, s, move):
    de = b.sides[1 - s].mon
    if not de.status and not de.yawn:
        de.yawn = 2


def _taunt(b, s, move):
    b.sides[1 - s].mon.taunt = 2


def _wish(b, s, move):
    side = b.sides[s]
    if side.wish is None:
        side.wish = (2, side.mon.maxhp // 2)


def _ingrain(b, s, move):
    b.sides[s].mon.ingrained = True


def _refresh(b, s, move):
    m = b.sides[s].mon
    if m.status in ("PSN", "TOX", "BRN", "PAR"):
        m.status = 0


def _heal_bell(b, s, move):
    for m in b.sides[s].team:
        m.status, m.sleep = 0, 0


def _focus(b, s, move):
    b.sides[s].mon.focus = True


def _charge(b, s, move):
    b.sides[s].mon.charged = True


def _destiny(b, s, move):
    b.sides[s].mon.destiny = True


def _memento(b, s, move):
    m, de = b.sides[s].mon, b.sides[1 - s].mon
    de.stages[ATK] = max(0, de.stages[ATK] - 2)
    de.stages[SPA] = max(0, de.stages[SPA] - 2)
    m.hp = 0


def _perish(b, s, move):
    for side in b.sides:
        if not side.mon.perish and side.mon.ability != "SOUNDPROOF":
            side.mon.perish = 4


def _sleep_talk(b, s, move):
    m = b.sides[s].mon
    if m.status != "SLP":
        return
    choices = [x for x in m.moves if effect_of(x) not in ("SLEEP_TALK", "FOCUS_PUNCH", "BIDE", "UPROAR") and effect_of(x) not in TWO_TURN]
    if choices:
        b.execute(s, b.rng.choice(choices))


def _attract(b, s, move):
    pass                                                   # (genders aren't modelled: no effect)


EFFECTS = {"SLEEP": _status("SLP"), "POISON": _status("PSN"), "PARALYZE": _status("PAR"), "TOXIC": _toxic,
           "WILL_O_WISP": _will_o_wisp, "CONFUSE": _confuse, "SWAGGER": _swagger, "FLATTER": _swagger,
           "RESTORE_HP": _heal(), "SOFTBOILED": _heal(), "MORNING_SUN": _heal(True), "SYNTHESIS": _heal(True),
           "MOONLIGHT": _heal(True), "REST": _rest, "PROTECT": _protect, "ENDURE": _protect,
           "LIGHT_SCREEN": _screen("light_screen"), "REFLECT": _screen("reflect"), "SAFEGUARD": _screen("safeguard"),
           "MIST": _screen("mist"), "RAIN_DANCE": _weather("RAIN"), "SUNNY_DAY": _weather("SUN"),
           "SANDSTORM": _weather("SAND"), "HAIL": _weather("HAIL"), "SUBSTITUTE": _substitute,
           "LEECH_SEED": _leech_seed, "BELLY_DRUM": _belly_drum, "CURSE": _curse, "HAZE": _haze, "ROAR": _roar,
           "COUNTER": _counter("physical"), "MIRROR_COAT": _counter("special"), "PAIN_SPLIT": _pain_split,
           "SPIKES": _spikes, "YAWN": _yawn, "TAUNT": _taunt, "WISH": _wish, "INGRAIN": _ingrain,
           "REFRESH": _refresh, "HEAL_BELL": _heal_bell, "FOCUS_ENERGY": _focus, "CHARGE": _charge,
           "DESTINY_BOND": _destiny, "MEMENTO": _memento, "PERISH_SONG": _perish, "SLEEP_TALK": _sleep_talk,
           "ATTRACT": _attract,
           "BULK_UP": _multi_up((ATK, DEF)), "CALM_MIND": _multi_up((SPA, SPD)), "DRAGON_DANCE": _multi_up((ATK, SPE)),
           "COSMIC_POWER": _multi_up((DEF, SPD)), "DEFENSE_CURL": _stat(True, DEF, 1), "MINIMIZE": _stat(True, EVA, 1)}
for _e in set(EFFECT.values()):
    _base = _e[:-5] if _e.endswith("_UP_2") else _e[:-7] if _e.endswith("_DOWN_2") else _e[:-3] if _e.endswith("_UP") \
        else _e[:-5] if _e.endswith("_DOWN") else None
    if _base in STAGE_OF:
        _n = 2 if _e.endswith("_2") else 1
        EFFECTS[_e] = _stat(_e.endswith(("_UP", "_UP_2")), STAGE_OF[_base], _n if "_UP" in _e else -_n)


def _type_ok_tw(self, de):
    return not (TYPE_ID["GROUND"] in de.types)


Battle.type_ok_tw = _type_ok_tw


# ======================================================================================= players
class View:
    """What one side can see of the battle: its own team in full, the other side's as shown.
    Unseen moves are guessed as a good player would (the species' strongest attacks of different
    types); unseen items, IVs, EVs, natures and abilities are either a single middling guess or,
    given a random source, drawn from what trainers commonly use - so that a player trying out its
    choices in many imagined battles covers the possibilities rather than betting on one."""

    def __init__(self, battle, s, sees_all=False):
        self.b, self.s, self.sees_all = battle, s, sees_all

    def model(self, sample=None):
        """A copy of the battle as this side believes it to be (`sample`: a random.Random to draw
        the unseen details with)."""
        c = self.b.clone(seed=sample.random() if sample else self.b.rng.random())
        if self.sees_all:
            return c
        other = c.sides[1 - self.s]
        for k, m in enumerate(other.team):
            real = self.b.sides[1 - self.s].team[k]
            if sample:
                item = real.item if real.shown_item else item_id(sample.choices(*zip(*LIKELY_ITEMS))[0])
                guess = Mon(real.species, real.level, guess_moves(real, sample), item, sample.randrange(2),
                            likely_ivs(sample), likely_evs(sample, real.species), sample.randrange(25), nickname=real.name)
            else:
                guess = Mon(real.species, real.level, guess_moves(real), real.item if real.shown_item else 0,
                            0, (20,) * 6, (40,) * 6, 0, nickname=real.name)
            if real.shown_ability:
                guess.ability = real.ability
            guess.hp = max(0, round(real.hp / real.maxhp * guess.maxhp)) if real.hp else 0
            if real.hp and not guess.hp:
                guess.hp = 1
            for attr in ("status", "sleep", "toxic", "stages", "confused", "substitute", "seeded", "recharge",
                         "charging", "choice", "invulnerable", "taunt", "yawn", "wrap", "known_moves", "rampage",
                         "protect_count", "flash_fire", "perish", "shown_item", "shown_ability"):
                v = getattr(real, attr)
                setattr(guess, attr, list(v) if isinstance(v, list) else set(v) if isinstance(v, set) else v)
            if guess.choice and guess.choice not in guess.moves:
                guess.choice = 0
            other.team[k] = guess
        return c


def guess_moves(real, sample=None):
    """The moves shown so far, then what a good player would expect: the species' strongest attacks
    it can learn (by level or TM), of different types, judged by its own attacking stats (with a
    random source, now and then one of the next strongest instead)."""
    known = [m for m in real.moves if m in real.known_moves]
    types = {MOVES[m][2] for m in known if MOVES[m][1]}
    for m in likely_attacks(real.species, real.level):
        if len(known) >= 4 or sum(1 for k in known if MOVES[k][1]) >= 3:
            break
        if sample and sample.random() < 0.2:
            continue
        if m not in known and MOVES[m][2] not in types:
            known.append(m)
            types.add(MOVES[m][2])
    return known or default_moves(real.species, real.level)


LIKELY_ITEMS = [("LEFTOVERS", 30), ("", 15), ("SITRUS BERRY", 15), ("LUM BERRY", 10), ("QUICK CLAW", 8),
                ("SHELL BELL", 7), ("CHOICE BAND", 5), ("SCOPE LENS", 5), ("BRIGHTPOWDER", 5)]


class Player:
    level = "random"

    def __init__(self, seed=None, sees_all=False):
        self.rng = random.Random(seed)
        self.sees_all = sees_all

    def choose(self, battle, s):
        return self.rng.choice(battle.legal_actions(s))

    def replace(self, battle, s):
        return self.rng.choice(battle.sides[s].bench())


# ----- shared judgement
def expected_hit(b, s, move, att=None, de=None):
    """(expected damage as a fraction of the target's HP, chance it knocks out) for one use of a
    damaging move now, counting accuracy, the 16 damage rolls and the critical-hit chance."""
    att = att or b.sides[s].mon
    de = de or b.sides[1 - s].mon
    if de.fainted or b.immune(att, de, move):
        return 0.0, 0.0
    eff = effect_of(move)
    acc = b.accuracy(att, de, move)
    if eff in ("LEVEL_DAMAGE", "SONICBOOM", "DRAGON_RAGE", "SUPER_FANG", "PSYWAVE", "ENDEAVOR", "OHKO"):
        d = {"LEVEL_DAMAGE": att.level, "SONICBOOM": 20, "DRAGON_RAGE": 40, "SUPER_FANG": de.hp // 2,
             "PSYWAVE": att.level, "ENDEAVOR": max(0, de.hp - att.hp), "OHKO": de.hp}[eff]
        return acc * min(d, de.hp) / de.maxhp, acc if d >= de.hp else 0.0
    mtype, power = b.move_type_power(att, de, move)
    if not power or eff in ("COUNTER", "MIRROR_COAT", "BIDE"):
        return 0.0, 0.0
    if eff == "FOCUS_PUNCH":
        acc *= 0.6
    hits = {"MULTI_HIT": 3, "DOUBLE_HIT": 2, "TWINEEDLE": 2, "TRIPLE_KICK": 3}.get(eff, 1)
    cc = b.crit_chance(att, de, move)
    side_de = b.sides[1 - s] if de is b.sides[1 - s].mon else b.sides[s]
    total, ko = 0.0, 0.0
    hp = de.hp + (de.substitute or 0)
    for crit, pc in ((False, 1 - cc), (True, cc)):
        if pc == 0:
            continue
        lo, _ = b.damage(att, de, move, side_de, crit, 85)
        hi, _ = b.damage(att, de, move, side_de, crit, 100)
        if eff == "TRIPLE_KICK":
            lo = hi = sum(b.damage(att, de, move, side_de, crit, r, power=10 * k)[0] for k in (1, 2, 3) for r in (92,)) // 1
        rolls = [lo + (hi - lo) * k / 15 for k in range(16)]
        dmg = [r * hits for r in rolls]
        total += pc * sum(min(d, hp) for d in dmg) / 16
        ko += pc * sum(1 for d in dmg if d >= hp) / 16
    if eff in ("TWO_TURN",) or eff in TWO_TURN and not (eff == "SOLAR_BEAM" and b.weather_on() == "SUN") and not att.charging:
        total *= 0.5
        ko *= 0.5
    if eff == "RECHARGE":
        total *= 0.85
    return acc * total / de.maxhp, acc * ko


def useless(b, s, move):
    """True if the move can't do anything useful now (the easy level never picks one of these)."""
    att, de = b.sides[s].mon, b.sides[1 - s].mon
    eff, power = effect_of(move), MOVES[move][1]
    side = b.sides[s]
    if power or eff in NON_DAMAGE:
        if eff in ("COUNTER", "MIRROR_COAT"):
            return False
        return bool(b.immune(att, de, move)) or eff == "DREAM_EATER" and de.status != "SLP"
    if eff in ("SLEEP", "POISON", "PARALYZE", "TOXIC", "WILL_O_WISP", "YAWN"):
        if de.status or b.sides[1 - s].safeguard or de.substitute:
            return True
        st = {"SLEEP": "SLP", "POISON": "PSN", "PARALYZE": "PAR", "TOXIC": "TOX", "WILL_O_WISP": "BRN", "YAWN": "SLP"}[eff]
        test = de.clone()
        test.item = 0
        ok = Battle.give_status(b, test, st)
        if eff == "PARALYZE" and move == 86 and TYPE_ID["GROUND"] in de.types:
            return True
        return not ok or b.immune(att, de, move) == "types"
    if eff in ("CONFUSE", "SWAGGER", "FLATTER") and (de.confused or de.ability == "OWN_TEMPO" or de.substitute):
        return True
    if eff in ("RAIN_DANCE", "SUNNY_DAY", "SANDSTORM", "HAIL"):
        return b.weather == {"RAIN_DANCE": "RAIN", "SUNNY_DAY": "SUN", "SANDSTORM": "SAND", "HAIL": "HAIL"}[eff]
    if eff in ("REFLECT", "LIGHT_SCREEN", "SAFEGUARD", "MIST"):
        return bool(getattr(side, {"REFLECT": "reflect", "LIGHT_SCREEN": "light_screen", "SAFEGUARD": "safeguard", "MIST": "mist"}[eff]))
    if eff in ("RESTORE_HP", "SOFTBOILED", "MORNING_SUN", "SYNTHESIS", "MOONLIGHT", "REST"):
        return att.hp >= att.maxhp * (0.75 if eff != "REST" else 1.0)
    if eff == "SUBSTITUTE":
        return bool(att.substitute) or att.hp <= att.maxhp // 4
    if eff == "LEECH_SEED":
        return de.seeded or TYPE_ID["GRASS"] in de.types
    if eff == "SPIKES":
        return b.sides[1 - s].spikes >= 3 or not b.sides[1 - s].bench()
    if eff == "BELLY_DRUM":
        return att.hp <= att.maxhp // 2 or att.stages[ATK] == 12
    if eff in ("PROTECT", "ENDURE"):
        return att.protect_count > 0
    if eff.endswith("_UP") or eff.endswith("_UP_2") or eff in ("BULK_UP", "CALM_MIND", "DRAGON_DANCE", "COSMIC_POWER"):
        stats = {"BULK_UP": (ATK, DEF), "CALM_MIND": (SPA, SPD), "DRAGON_DANCE": (ATK, SPE), "COSMIC_POWER": (DEF, SPD)}.get(eff)
        if not stats:
            base = eff[:-5] if eff.endswith("_UP_2") else eff[:-3]
            stats = (STAGE_OF.get(base, ATK),)
        return all(att.stages[x] >= 12 for x in stats)
    if eff.endswith("_DOWN") or eff.endswith("_DOWN_2"):
        base = eff[:-7] if eff.endswith("_DOWN_2") else eff[:-5]
        x = STAGE_OF.get(base)
        return x is None or de.stages[x] <= 0 or b.sides[1 - s].mist or de.ability in ("CLEAR_BODY", "WHITE_SMOKE")
    if eff in ("SPLASH", "TELEPORT", "ATTRACT", "MIRROR_MOVE", "TRANSFORM", "CONVERSION", "CONVERSION_2", "SKETCH",
               "MIMIC", "METRONOME", "DISABLE", "ENCORE", "SPITE", "NIGHTMARE", "LOCK_ON", "MEAN_LOOK", "FORESIGHT",
               "CAMOUFLAGE", "MUD_SPORT", "WATER_SPORT", "FOLLOW_ME", "HELPING_HAND", "ROLE_PLAY", "SKILL_SWAP",
               "IMPRISON", "GRUDGE", "SNATCH", "MAGIC_COAT", "RECYCLE", "TRICK", "ASSIST", "NATURE_POWER", "TICKLE",
               "TORMENT", "TEETER_DANCE", "PSYCH_UP", "BATON_PASS", "SLEEP_TALK"):
        return eff != "SLEEP_TALK" or att.status != "SLP"
    if eff == "ROAR":
        return not b.sides[1 - s].bench()
    if eff == "HAZE":
        return all(x == 6 for x in de.stages) and all(x >= 6 for x in att.stages)
    if eff == "PERISH_SONG":
        return not b.sides[s].bench()
    if eff == "MEMENTO":
        return att.hp > att.maxhp // 3
    return False


def matchup(b, s, k):
    """How well side s's bench Pokemon k would do against the foe now: its best expected damage
    against the foe minus the foe's best against it (fractions of HP)."""
    side, foe = b.sides[s], b.sides[1 - s].mon
    me = side.team[k]
    mine = max([expected_hit(b, s, m, me, foe)[0] for m in me.moves] or [0])
    theirs = max([expected_hit(b, 1 - s, m, foe, me)[0] for m in foe.moves] or [0])
    return mine - theirs + 0.3 * me.hp / me.maxhp


def best_replacement(b, s):
    return max(b.sides[s].bench(), key=lambda k: matchup(b, s, k))


# ----- easy
class Easy(Player):
    """A sensible young trainer: knows type match-ups, never uses a move that can't work, mostly
    picks a strong effective move, sometimes a status or set-up move; switches only when its
    Pokemon faints (to the best match-up). No looking ahead, no predicting."""
    level = "easy"

    def choose(self, battle, s):
        b = View(battle, s, self.sees_all).model()
        moves = [a for a in b.legal_actions(s) if a[0] == "move"]
        if moves[0][1] < 0:
            return moves[0]
        mon = b.sides[s].mon
        useful = [a for a in moves if not useless(b, s, mon.moves[a[1]])]
        if not useful:
            return self.rng.choice(moves)
        attacks = [(expected_hit(b, s, mon.moves[a[1]])[0], a) for a in useful if MOVES[mon.moves[a[1]]][1]]
        others = [a for a in useful if not MOVES[mon.moves[a[1]]][1] and effect_of(mon.moves[a[1]]) not in NON_DAMAGE]
        attacks.sort(key=lambda x: -x[0])
        r = self.rng.random()
        if attacks and (r < 0.72 or not others):
            return attacks[0][1] if r < 0.6 or len(attacks) == 1 else attacks[1][1]
        if others and r < 0.9:
            return self.rng.choice(others)
        return self.rng.choice(useful)

    def replace(self, battle, s):
        return best_replacement(View(battle, s, self.sees_all).model(), s)


# ----- medium
class Medium(Player):
    """A good player: expected damage and the chance of a knock-out, finishing weakened Pokemon,
    priority at the right moment, set-up and status when it's safe, recovery when it's worth it,
    and switching out of a clearly bad match-up when a better Pokemon waits."""
    level = "medium"

    def choose(self, battle, s):
        return self.pick(View(battle, s, self.sees_all).model(), s)

    def pick(self, b, s):
        """The choice for side s in a battle model (already as this side sees it)."""
        acts = b.legal_actions(s)
        if acts[0] == ("move", -1) or acts[0] == ("move", -2):
            return acts[0]
        scores = {a: self.score(b, s, a) for a in acts}
        best = max(scores.values())
        top = [a for a, v in scores.items() if v >= best - 1e-9]
        return self.rng.choice(top)

    def threat(self, b, s):
        """The foe's best (expected fraction, KO chance) against our active Pokemon."""
        foe = b.sides[1 - s].mon
        best = (0.0, 0.0)
        for m in foe.moves:
            e = expected_hit(b, 1 - s, m)
            if e[0] > best[0]:
                best = e
        return best

    def faster(self, b, s, move=None):
        me, foe = b.sides[s].mon, b.sides[1 - s].mon
        prio = MOVES[move][7] if move else 0
        if prio > 0:
            return True
        if prio < 0:
            return False
        return me.speed(b.weather_on()) > foe.speed(b.weather_on())

    def score(self, b, s, act):
        me, foe = b.sides[s].mon, b.sides[1 - s].mon
        threat, threat_ko = self.threat(b, s)
        if act[0] == "switch":
            k = act[1]
            now = matchup(b, s, b.sides[s].active)
            then = matchup(b, s, k)
            gain = then - now
            # switching costs a turn: the newcomer takes the foe's hit
            new = b.sides[s].team[k]
            hit = max([expected_hit(b, 1 - s, m, foe, new)[0] for m in foe.moves] or [0])
            return 40 * gain - 25 * hit - 8 + (25 if threat_ko > 0.6 and not self.faster(b, s) and then > 0 else 0)
        move = me.moves[act[1]]
        eff = effect_of(move)
        if useless(b, s, move):
            return -50
        frac, ko = expected_hit(b, s, move)
        first = self.faster(b, s, move)
        score = 100 * frac + 60 * ko * (1.3 if first else 0.9)
        if ko > 0.5 and first and MOVES[move][7] > 0:
            score += 15                                    # priority finishes it before it moves
        if not MOVES[move][1] and eff not in NON_DAMAGE:
            safe = threat < 0.3
            hp = me.hp / me.maxhp
            if eff in ("SLEEP", "YAWN"):
                score = 55 if not foe.status else -50
            elif eff in ("PARALYZE",):
                score = 40 + (15 if foe.speed(b.weather_on()) > me.speed(b.weather_on()) else 0)
            elif eff in ("TOXIC", "WILL_O_WISP", "POISON", "LEECH_SEED"):
                score = 35 + (10 if foe.hp / foe.maxhp > 0.7 else -15)
                if eff == "WILL_O_WISP" and foe.stats[1] > foe.stats[4]:
                    score += 15
            elif eff in ("RESTORE_HP", "SOFTBOILED", "MORNING_SUN", "SYNTHESIS", "MOONLIGHT", "REST", "WISH"):
                score = 70 * (1 - hp) - 60 * threat + (10 if hp < 0.45 else -20)
            elif eff in ("REFLECT", "LIGHT_SCREEN"):
                score = 30 if safe or threat > 0.35 else 15
            elif eff in ("PROTECT", "ENDURE"):
                score = 18 + (20 if foe.status in ("PSN", "TOX", "BRN") or foe.seeded else 0) - 10 * me.protect_count
            elif eff == "SUBSTITUTE":
                score = 30 if safe and hp > 0.5 else 5
            elif eff in ("SPIKES",):
                score = 25 + 5 * len(b.sides[1 - s].bench()) if safe else 10
            else:                                          # set-up and the rest
                boost = sum(1 for x in me.stages if x > 6)
                score = (45 if safe and hp > 0.6 else 12) - 12 * boost
        if eff == "EXPLOSION":
            score -= 40 * (me.hp / me.maxhp) - (30 if ko > 0.6 else 0)
        if eff == "RECHARGE" and ko < 0.6:
            score -= 15
        if eff in TWO_TURN and not (eff == "SOLAR_BEAM" and b.weather_on() == "SUN"):
            score -= 10
        return score

    def replace(self, battle, s):
        return best_replacement(View(battle, s, self.sees_all).model(), s)


# ----- elite
def evaluate(b, s):
    """How good the position is for side s (higher is better): remaining health weighted towards
    whole Pokemon, statuses, stat stages, screens and hazards, and who wins the current exchange."""
    def side_value(k):
        side = b.sides[k]
        v = 0.0
        for m in side.team:
            if m.fainted:
                continue
            frac = m.hp / m.maxhp
            v += 1.0 + 1.6 * frac
            v -= {"SLP": 0.45, "FRZ": 0.6, "PAR": 0.3, "TOX": 0.35, "PSN": 0.2, "BRN": 0.3}.get(m.status, 0) if m.status else 0
        m = side.mon
        if not m.fainted:
            v += 0.12 * sum(min(3, x - 6) for x in (m.stages[ATK], m.stages[SPA], m.stages[SPE], m.stages[DEF], m.stages[SPD]))
            v += 0.25 * (m.substitute > 0) - 0.3 * m.seeded - 0.6 * (m.perish == 1)
        v += 0.12 * (side.reflect > 0) + 0.12 * (side.light_screen > 0) - 0.1 * b.sides[k].spikes * len(side.bench())
        return v
    v = side_value(s) - side_value(1 - s)
    if b.winner is not None:                               # (on the same scale, so a won battle in a
        return v + (2.0 if b.winner == s else -2.0 if b.winner == 1 - s else 0.0)  # playout doesn't swamp the rest)
    me, foe = b.sides[s].mon, b.sides[1 - s].mon
    if not me.fainted and not foe.fainted:                 # who wins the exchange on the field
        mine = max([expected_hit(b, s, m)[0] for m in me.moves] or [0])
        theirs = max([expected_hit(b, 1 - s, m)[0] for m in foe.moves] or [0])
        t_me = math.ceil(foe.hp / foe.maxhp / mine) if mine > 0 else 99
        t_them = math.ceil(me.hp / me.maxhp / theirs) if theirs > 0 else 99
        faster = me.speed(b.weather_on()) >= foe.speed(b.weather_on())
        if t_me < t_them or t_me == t_them and faster:
            v += 0.35 + 0.1 * (t_them - t_me)
        else:
            v -= 0.35 + 0.1 * min(5, t_me - t_them)
    return v


class Elite(Player):
    """Plays to win by trying everything out. For each choice it has, it plays the battle forward in
    copies of its own picture of the battle - the other side answering as a strong player would, and
    both sides playing on as strong players to the end (or `playout` turns) - with the same damage
    rolls, accuracy checks and critical hits for every choice, so they're compared fairly. It takes
    the choice that ends best on average. Replacements after a knock-out are chosen the same way.
    This is rollout improvement: it never does worse than the strong player it imagines, and finds
    what that player misses (when to switch, when a status move or a sacrifice pays off later)."""
    level = "elite"

    def __init__(self, seed=None, sees_all=False, samples=8, playout=40, margin=0.5):
        super().__init__(seed, sees_all)
        self.samples, self.playout, self.margin = samples, playout, margin
        self.medium = Medium(seed, sees_all)

    def play_on(self, c, s):
        """Plays the copy on as two strong players; returns how it ended for s."""
        for _ in range(self.playout):
            for side in (0, 1):
                if c.sides[side].mon.fainted and c.sides[side].bench():
                    c.switch(side, best_replacement(c, side), forced=True)
            if c.winner is not None or c.check_end():
                break
            c.play_turn([self.medium.pick(c, 0), self.medium.pick(c, 1)])
        return evaluate(c, s)

    def values(self, battle, s, acts, first=None):
        """{choice: average result} over the same `samples` imagined battles for every choice (each
        with its own guess at what can't be seen, and its own random numbers).
        `first(c, a)` makes the choice in copy c (playing the turn); by default a move or switch."""
        view = View(battle, s, self.sees_all)
        seeds = [self.rng.random() for _ in range(self.samples)]
        worlds = [view.model(random.Random(seed)) for seed in seeds]
        out = {}
        for a in acts:
            total = 0.0
            for seed, w in zip(seeds, worlds):
                c = w.clone(seed=seed)
                if first:
                    first(c, a)
                else:
                    turn = [None, None]
                    turn[s], turn[1 - s] = a, self.medium.pick(c, 1 - s)
                    c.play_turn(turn)
                total += self.play_on(c, s)
            out[a] = total / len(seeds)
        return out

    def choose(self, battle, s):
        acts = battle.legal_actions(s)
        if len(acts) == 1:
            return acts[0]
        v = self.values(battle, s, acts)
        best = max(acts, key=lambda a: v[a])
        usual = self.medium.choose(battle, s)          # (what a strong player would do anyway: only
        if usual in v and v[best] - v[usual] < self.margin:  # left when the playouts clearly say so,
            return usual                               # as they're only as right as the guesses)
        return best

    def replace(self, battle, s):
        bench = battle.sides[s].bench()
        if len(bench) == 1:
            return bench[0]
        v = self.values(battle, s, bench, first=lambda c, k: c.switch(s, k, forced=True))
        return max(bench, key=lambda k: v[k])


PLAYERS = {"random": Player, "easy": Easy, "medium": Medium, "elite": Elite}


# ======================================================================================== teams
def random_team(rng, size=3, level=50, pool=None):
    """A made-up team for testing: fully evolved Pokemon with moves a sensible trainer would teach,
    trained stats (likely_ivs, likely_evs), random natures and a common item."""
    import duo_events  # noqa: F401  (for the species list's names)
    pool = pool or TEST_POOL
    names = rng.sample(pool, size)
    items = [item_id(n) for n in ("LEFTOVERS", "SITRUS BERRY", "QUICK CLAW", "SHELL BELL", "SCOPE LENS", "LUM BERRY")]
    team = []
    for n in names:
        sp = species_id_cached(n)
        team.append(Mon(sp, level, best_moves(sp, level, rng), rng.choice(items + [0]), rng.randrange(2),
                        likely_ivs(rng), likely_evs(rng, sp), rng.randrange(25)))
    return team


def likely_ivs(rng):
    """IVs as a trainer who picked their Pokemon with some care would have them."""
    return [rng.randrange(10, 32) for _ in range(6)]


def likely_evs(rng, species):
    """EVs as a trained Pokemon would have them: 252 in HP or speed and in its better attacking
    stat, the rest spread (or, a quarter of the time, a Pokemon trained on whatever it met)."""
    if rng.random() < 0.25:
        evs = [0] * 6
        for _ in range(510 // 4):
            evs[rng.randrange(6)] += 4
        return [min(255, e) for e in evs]
    base = SPECIES[species]
    attack = 1 if base[1] >= base[4] else 4
    first = rng.choice((0, 3))
    evs = [0] * 6
    evs[attack], evs[first] = 252, 252
    evs[rng.choice([i for i in range(6) if not evs[i]])] = 6
    return evs


def best_moves(species, level, rng):
    """Four moves a sensible trainer might teach it (level-up moves, TMs and tutors): three attacks of
    different types chosen among its strongest, and a useful status move when it has one."""
    attacks = likely_attacks(species, level)
    out, types = [], set()
    for m in attacks[:10]:
        if MOVES[m][2] not in types and len(out) < 3 and (not out or rng.random() < 0.75):
            out.append(m)
            types.add(MOVES[m][2])
    status = [m for m in learnable(species, level) if not MOVES[m][1] and effect_of(m) in GOOD_STATUS]
    if status:
        out.append(rng.choice(sorted(status)))
    for m in attacks:
        if len(out) >= 4:
            break
        if m not in out and MOVES[m][2] not in types:
            out.append(m)
            types.add(MOVES[m][2])
    return out[:4] or default_moves(species, level)


GOOD_STATUS = {"SLEEP", "PARALYZE", "TOXIC", "WILL_O_WISP", "RESTORE_HP", "SOFTBOILED", "SYNTHESIS", "MOONLIGHT",
               "MORNING_SUN", "REST", "PROTECT", "SUBSTITUTE", "LEECH_SEED", "REFLECT", "LIGHT_SCREEN", "BULK_UP",
               "CALM_MIND", "DRAGON_DANCE", "ATTACK_UP_2", "SPECIAL_ATTACK_UP_2", "SPEED_UP_2", "CONFUSE", "YAWN",
               "SPIKES", "WISH", "COSMIC_POWER", "BELLY_DRUM", "CURSE"}
TEST_POOL = ["SWAMPERT", "BLAZIKEN", "SCEPTILE", "GARDEVOIR", "MANECTRIC", "AGGRON", "FLYGON", "SALAMENCE",
             "METAGROSS", "MILOTIC", "ALTARIA", "BRELOOM", "LUDICOLO", "SHIFTRY", "CRAWDAUNT", "CLAYDOL", "ABSOL",
             "SHARPEDO", "CAMERUPT", "SKARMORY", "STARMIE", "GYARADOS", "ALAKAZAM", "GENGAR", "MACHAMP", "ARCANINE",
             "PELIPPER", "SWELLOW", "DUSCLOPS", "MEDICHAM", "HARIYAMA", "WALREIN", "CRADILY", "ARMALDO", "KINGDRA",
             "HERACROSS", "SCIZOR", "MIGHTYENA", "EXPLOUD", "WHISCASH", "GLALIE", "ZANGOOSE", "SEVIPER", "SNORLAX",
             "LAPRAS", "TYRANITAR", "DRAGONITE", "VAPOREON", "JOLTEON", "ESPEON", "UMBREON", "BLISSEY", "SLAKING"]


def tournament(level_a, level_b, battles=20, size=3, seed=1, level=50):
    """Battles between two levels on mirrored teams (each pair of teams played both ways round);
    returns side A's wins, losses and draws."""
    rng = random.Random(seed)
    wins = losses = draws = 0
    for n in range(battles // 2):
        teams = random_team(rng, size, level), random_team(rng, size, level)
        for swap in (0, 1):
            ta, tb = (teams[0], teams[1]) if not swap else (teams[1], teams[0])
            b = Battle([m.clone() for m in ta], [m.clone() for m in tb], seed=rng.random())
            w = b.run([PLAYERS[level_a](rng.random()), PLAYERS[level_b](rng.random())])
            wins += w == 0
            losses += w == 1
            draws += w == -1
    return wins, losses, draws


def main(argv=None):
    ap = argparse.ArgumentParser(prog="duo_battle.py", description="A Gen 3 single battle on the PC, with easy, "
                                 "medium and elite players.")
    ap.add_argument("--demo", action="store_true", help="a battle between two made-up teams, turn by turn")
    ap.add_argument("--pk3", nargs="+", help="your team, as .pk3 files")
    ap.add_argument("--vs", nargs="+", help="the other team, as .pk3 files (default: made up)")
    ap.add_argument("--level", choices=list(PLAYERS), default="elite", help="how your team plays (default elite)")
    ap.add_argument("--opponent", choices=list(PLAYERS), default="medium", help="how the other team plays")
    ap.add_argument("--tournament", type=int, metavar="N", help="N battles between --level and --opponent")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args(argv)
    rng = random.Random(args.seed)
    if args.tournament:
        w, l, d = tournament(args.level, args.opponent, args.tournament, seed=args.seed or 1)
        print(f"{args.level} against {args.opponent}: {w} won, {l} lost, {d} drawn")
        return
    mine = [mon_from_pk3(open(p, "rb").read()) for p in args.pk3] if args.pk3 else random_team(rng)
    theirs = [mon_from_pk3(open(p, "rb").read()) for p in args.vs] if args.vs else random_team(rng)
    b = Battle(mine, theirs, seed=rng.random(), names=(f"You ({args.level})", f"Them ({args.opponent})"), log=True)
    w = b.run([PLAYERS[args.level](rng.random()), PLAYERS[args.opponent](rng.random())])
    print("\n".join(b.log))
    print(f"\nWinner: {b.sides[w].name if w in (0, 1) else 'nobody'} after {b.turn} turns")


if __name__ == "__main__":
    main()

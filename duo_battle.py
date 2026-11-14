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


def check_legal(data):
    """Whether a .pk3 is a Pokemon the games could really have (8 November: before the DUO battles
    with it, so even the impossible level never plays with something the game's rules don't allow).
    Returns (problems, notes): problems would let it battle beyond the rules (refused unless the user
    allows it); notes are unusual but possible (an event's special move, say)."""
    import duo_events as E
    f, problems = E.parse_pk3(data)
    problems, notes = list(problems), []
    if problems:
        return problems, notes
    if f["egg"]:
        problems.append("it's an Egg")
    if not (0 < f["species"] < len(SPECIES) and any(SPECIES[f["species"]][:6])):
        problems.append(f"species {f['species']} isn't a real Pokemon")
        return problems, notes
    party = E.pk3_party_fields(f)
    level = party[4]
    evs = f["evs"]
    if sum(evs) > 510:
        problems.append(f"its effort values add up to {sum(evs)}, more than the 510 any Pokemon can earn")
    moves = f["moves"]
    if not moves:
        problems.append("it knows no moves")
    real = lambda m: 0 < m < len(MOVES)
    for m in moves:
        if not real(m):
            problems.append(f"move {m} isn't a real move")
    if len(set(moves)) != len(moves):
        problems.append("it knows the same move twice")
    g, a = f["blocks"][0:12], f["blocks"][12:24]
    ups = g[8]
    for i, m in enumerate(struct.unpack_from("<4H", a, 0)):
        if m and real(m):
            most = MOVES[m][4] * (5 + (ups >> (2 * i) & 3)) // 5
            if a[8 + i] > most:
                problems.append(f"{move_name(m).title()} has {a[8 + i]} PP, more than its {most} can be")
    if f["item"]:
        import secret_bases as SB
        if f["item"] >= len(SB.tables().items) or not SB.tables().items[f["item"]][0]:
            problems.append(f"it holds item {f['item']}, which doesn't exist")
    if len(data) == 100 and any(data[84:100]):          # the file's own stats, which the game would use
        stored = list(struct.unpack_from("<6H", data, 0x58))   # max HP, Attack, Defense, Speed, Sp. Atk, Sp. Def
        want = list(struct.unpack_from("<6H", bytes(party), 8))
        if data[0x54] != level:
            problems.append(f"its level says {data[0x54]}, but its experience makes it level {level}")
        if stored != want:
            problems.append(f"its stats ({'/'.join(map(str, stored))}) aren't what its species, level, IVs, EVs and "
                            f"nature give ({'/'.join(map(str, want))})")
        if struct.unpack_from("<H", data, 0x56)[0] > stored[0]:
            problems.append("its HP is more than its maximum")
    can = learnable(f["species"], level)
    odd = [move_name(m).title() for m in moves if real(m) and m not in can]
    if odd:
        notes.append(f"{', '.join(odd)}: not learnt by levelling up, TM, HM or tutor"
                     + (" (fine for an event Pokemon's special move)" if f["fateful"] else
                        " - an Egg move or an event's special move, or not possible"))
    return problems, notes


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
            actions = [None if getattr(players[s], "sees_choices", False) else players[s].choose(self, s) for s in (0, 1)]
            for s in (0, 1):                          # (one that sees choices chooses last, knowing the other's)
                if actions[s] is None:
                    actions[s] = players[s].choose(self, s, foe_action=actions[1 - s])
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


class Impossible(Elite):
    """The elite player with nothing hidden from it (8 November, asked for by the user): it sees the
    other side's whole team - every move, item, ability, IV, EV and nature, which the game sends at
    the start of a link battle anyway - and, when it can, the other side's choice for this turn
    before making its own (in a link battle every GBA receives each player's answers, so the DUO
    can wait for yours). It still only ever chooses what the game allows: a move it has with PP, a
    Pokemon on its bench; nothing about the battle itself is changed. Its playouts are longer and
    more numerous, and it trusts them fully (its picture of the battle is exact, bar the dice)."""
    level = "impossible"
    sees_choices = True

    def __init__(self, seed=None, sees_all=True, samples=12, playout=60, margin=0.0):
        super().__init__(seed, True, samples, playout, margin)

    def choose(self, battle, s, foe_action=None):
        acts = battle.legal_actions(s)
        if len(acts) == 1:
            return acts[0]
        if foe_action is None:
            v = self.values(battle, s, acts)
        else:
            def first(c, a):
                turn = [None, None]
                turn[s], turn[1 - s] = a, foe_action
                c.play_turn(turn)
            v = self.values(battle, s, acts, first=first)
        return max(acts, key=lambda a: v[a])


PLAYERS = {"random": Player, "easy": Easy, "medium": Medium, "elite": Elite, "impossible": Impossible}


# ================================================================================ a link battle
# 8 November: the PC chooses for the DUO in a real link battle. The game runs the battle (docs/BATTLE.md)
# and every controller command reaches the DUO, which records them; the PC reads that record as it
# grows and keeps its own picture of the battle, then answers each choice the DUO holds for it.

C_GETMONDATA, C_SETMONDATA, C_SWITCHINANIM, C_FAINTANIMATION, C_MOVEANIMATION = 0, 2, 5, 10, 15
C_CHOOSEACTION, C_CHOOSEMOVE, C_CHOOSEPOKEMON, C_STATUSICONUPDATE, C_ENDLINKBATTLE = 18, 20, 22, 26, 55
REQ_ALL, REQ_PP_DATA, REQ_PPMOVE1, REQ_STATUS, REQ_HP = 0, 8, 9, 40, 42     # battle_controllers.h REQUEST_*
PROTECTS = {"PROTECT"}                       # (Protect and Detect share the effect)


def status_from_word(st):
    """struct Pokemon's status word as this module's status (and sleep turns)."""
    if st & 7:
        return "SLP", st & 7
    for bit, name in ((0x80, "TOX"), (0x08, "PSN"), (0x10, "BRN"), (0x20, "FRZ"), (0x40, "PAR")):
        if st & bit:
            return name, 0
    return 0, 0


class LinkBattle:
    """The PC's picture of a link battle from the DUO's record, and its choices for the DUO's side.
    OUR_SIDE: the battlers on the DUO's side; CONTROLLED: those it chooses for; FOES: the others.
    `ours` are the DUO's .pk3 files (its party, in order); the game's party comes from the record's
    opening blocks. Battlers: the game's are 0 and 2, the DUO's 1 and 3 (InitLinkBtlControllers);
    each one's Pokemon is a party slot. `level` is easy, medium, elite or impossible."""

    OUR_SIDE, CONTROLLED, FOES = (1, 3), (1, 3), (0, 2)

    def _ours_side(self, b):
        return b in self.OUR_SIDE

    def __init__(self, ours, level="medium", double=False, seed=None):
        self.ours = [mon_from_pk3(p) for p in ours]
        self.theirs, self._party_blocks = None, []
        self.double, self.level = double, level
        self.player = PLAYERS[level](seed)
        self.rng = random.Random(seed)
        self.active = {0: 0, 1: 0, 2: 1, 3: 1}
        self.weather = None
        self.session, self.opening, self.used = None, 0, 0
        self.n = 0                                   # record entries read
        self.plan = {}                               # our battler -> the choice made at CHOOSEACTION
        self.chosen = {}                             # our battler -> its move this turn (a double's teamwork)
        self.last_choose = {}                        # battler -> the entry number of its last CHOOSEACTION
        self.turn_mark = {}                          # our battler -> where its previous turn's ask was
        self.pending = {}                            # battler -> the last choice command sent to it (cmd, data)
        self.player_choice = {}                      # game battler -> ("move", slot, target) / ("switch", slot), this turn
        self.player_action = {}
        self.log = []                                # what the PC worked out, for the record's .txt

    # ------------------------------------------------------------ reading the record
    def side_team(self, battler):
        return self.ours if battler & 1 else self.theirs

    def mon(self, battler):
        team = self.side_team(battler)
        k = self.active.get(battler)
        return team[k] if team is not None and k is not None and k < len(team) else None

    def feed(self, entries):
        """Reads the record's entries (kind, seq, bytes) from where it left off."""
        import duo_events as E
        for kind, seq, b in entries[self.n:]:
            self.n += 1
            if kind == 2:
                code, arg = b[0] | b[1] << 8, b[2] | b[3] << 8
                if code == 1:
                    self.session, self.opening = arg, 0
                continue
            if self.session != 0x2211:
                continue
            if kind == 0 and self.opening < 4:
                if self.opening >= 1:
                    self._party_blocks.append(b)
                    if self.opening == 3:
                        self._game_party(E)
                self.opening += 1
                continue
            if len(b) < 8 or kind == 1:
                continue
            state, battler, attacker = b[0], b[1], b[2]
            size = b[4] | b[5] << 8
            d = b[8:8 + size]
            if state == 0 and d:
                self._command(battler, attacker, d)
            elif state == 1 and battler not in self.CONTROLLED and d:
                self._answer(battler, d)

    def _game_party(self, E):
        raw = b"".join(self._party_blocks)
        team = []
        for k in range(6):
            m = raw[100 * k:100 * k + 100]
            if len(m) < 100 or not any(m[:32]):
                break
            try:
                mon = mon_from_pk3(E.pk3_from_game_form(m))
            except (ValueError, KeyError, IndexError):
                break
            hp = struct.unpack_from("<H", m, 0x56)[0]
            mon.hp = min(hp, mon.maxhp) if hp or any(m[0x54:0x58]) else mon.maxhp
            mon.status, mon.sleep = status_from_word(struct.unpack_from("<I", m, 0x50)[0])
            team.append(mon)
        self.theirs = team or None

    def _targets(self, battler, mask):
        team = self.side_team(battler) or []
        if mask == 0:
            return [self.mon(battler)] if self.mon(battler) else []
        return [team[i] for i in range(min(6, len(team))) if mask >> i & 1]

    def _command(self, battler, attacker, d):
        cmd = d[0]
        if cmd == C_SWITCHINANIM and len(d) > 1:
            self.active[battler] = d[1]
            m = self.mon(battler)
            if m:
                m.reset_volatile()
        elif cmd == C_SETMONDATA and len(d) > 3:
            req, vals = d[1], d[3:]
            for m in self._targets(battler, d[2]):
                if req == REQ_HP and len(vals) >= 2:
                    m.hp = min(struct.unpack_from("<H", vals, 0)[0], m.maxhp)
                elif req == REQ_STATUS and len(vals) >= 4:
                    m.status, m.sleep = status_from_word(struct.unpack_from("<I", vals, 0)[0])
                elif REQ_PPMOVE1 <= req < REQ_PPMOVE1 + 4 and vals and req - REQ_PPMOVE1 < len(m.pp):
                    m.pp[req - REQ_PPMOVE1] = vals[0]
                elif req == REQ_PP_DATA and len(vals) >= 4:
                    m.pp = [vals[i] for i in range(len(m.pp))]
                elif req == REQ_ALL and len(vals) >= 80:   # struct BattlePokemon
                    m.hp = min(struct.unpack_from("<H", vals, 40)[0], m.maxhp)
                    m.pp = [vals[36 + i] for i in range(len(m.pp))]
                    m.stages = [max(0, min(12, v)) for v in vals[24:31]]
                    m.status, m.sleep = status_from_word(struct.unpack_from("<I", vals, 76)[0])
        elif cmd == C_FAINTANIMATION:
            m = self.mon(battler)
            if m:
                m.hp = 0
        elif cmd == C_STATUSICONUPDATE and len(d) >= 5:
            m = self.mon(battler)
            if m:
                m.status, m.sleep = status_from_word(struct.unpack_from("<I", d, 1)[0])
        elif cmd == C_MOVEANIMATION and len(d) >= 3:
            m = self.mon(attacker)
            move = d[1] | d[2] << 8
            if m and move in m.moves:
                m.known_moves.add(move)
            if len(d) > 12:
                self.weather = {1: "RAIN", 2: "RAIN", 4: "RAIN", 8: "SAND", 16: "SAND", 32: "SUN", 64: "SUN"}.get(
                    next((bit for bit in (1, 2, 4, 8, 16, 32, 64) if d[12] & bit), 0))
        elif cmd == C_CHOOSEMOVE and battler in self.CONTROLLED and len(d) >= 16:
            m = self.mon(battler)
            if m:
                moves = [struct.unpack_from("<H", d, 4 + 2 * i)[0] for i in range(4)]
                m.moves = [x for x in moves if x][:4]
                m.pp = [d[12 + i] for i in range(len(m.moves))]
        if cmd in (C_CHOOSEACTION, C_CHOOSEMOVE, C_CHOOSEPOKEMON):
            self.pending[battler] = (cmd, bytes(d))
            if cmd == C_CHOOSEACTION:
                if battler in self.CONTROLLED:       # (our turn starts: the last one ended at our last ask)
                    self.turn_mark[battler] = self.last_choose.get(battler, 0)
                    self.chosen.pop(battler, None)
                else:
                    self.player_choice.pop(battler, None)
                    self.player_action.pop(battler, None)
                self.last_choose[battler] = self.n

    def _answer(self, battler, d):
        """The player's own answer (the game's battlers' answers reach every GBA)."""
        cmd = self.pending.get(battler, (None,))[0]
        if cmd == C_CHOOSEACTION and d[0] == 33 and len(d) > 1:
            self.player_action[battler] = d[1]
            if d[1] not in (0, 2):                   # (the bag, running: nothing to wait for)
                self.player_choice[battler] = ("other",)
        elif cmd == C_CHOOSEMOVE and d[0] == 33 and len(d) > 3 and d[1] == 10:
            self.player_choice[battler] = ("move", d[2], d[3])
        elif cmd == C_CHOOSEPOKEMON and d[0] == 34 and len(d) > 1 and self.player_action.get(battler) == 2:
            self.player_choice[battler] = ("switch", d[1])

    # ------------------------------------------------------------ saying what it chose
    def explain(self, battler, value, target):
        """A line for the console on the PC's choice (12 November, asked for at the console): the move and
        what it expects of it, or the Pokemon sent in. None for a plain 'fight' (the move follows)."""
        cmd = self.pending.get(battler, (None,))[0]
        mon = self.mon(battler)
        who = mon.name if mon else f"battler {battler}"
        try:
            if cmd == C_CHOOSEACTION:
                return None if value == 0 else f"{who}: switches out" if value == 2 else f"{who}: action {value}"
            if cmd == C_CHOOSEMOVE and mon and value < len(mon.moves):
                move = mon.moves[value]
                foe = self.mon(target)
                line = f"{who} uses {move_name(move)}" + (f" on {foe.name}" if foe else "")
                if foe and MOVES[move][1]:
                    frac, ko = expected_hit(self._battle_for(battler, target), 0, move)
                    line += f" (about {round(100 * frac)}% of its HP" + (f", {round(100 * ko)}% to knock it out)" if ko >= 0.05 else ")")
                return line
            team = self.side_team(battler) or []
            if value < len(team) and team[value]:
                return f"sends in {team[value].name}"
        except Exception:                                # (the line is only for show)
            pass
        return f"{who}: choice {value}"

    # ------------------------------------------------------------ choosing
    def player_known(self, our_battler):
        """The player's choices this turn (for the impossible level): {battler: choice} once every
        battler of theirs that was asked this turn has answered; None while one hasn't yet; False if
        none was asked (a Pokemon locked into its move, or recharging)."""
        mark = self.turn_mark.get(our_battler, 0)
        foes = [b for b in self.FOES if self.last_choose.get(b, -1) > mark]
        if not foes:
            return False
        if all(b in self.player_choice for b in foes):
            return {b: self.player_choice[b] for b in foes}
        return None

    def _battle_for(self, battler, foe_battler=None):
        """A single battle as duo_battle sees it: our battler's Pokemon against one of the game's."""
        foe_battler = (battler ^ 1) if foe_battler is None else foe_battler
        c = Battle.__new__(Battle)
        c.sides = [Side([m.clone() for m in self.ours], "DUO"), Side([m.clone() for m in self.theirs], "game")]
        c.sides[0].active = self.active.get(battler, 0) if self.active.get(battler, 6) < len(self.ours) else 0
        c.sides[1].active = self.active.get(foe_battler, 0) if self.active.get(foe_battler, 6) < len(self.theirs) else 0
        if self.double:                              # (the partner on the field isn't on our bench)
            partner = self.active.get(battler ^ 2)
            if partner is not None and partner < len(self.ours) and partner != c.sides[0].active:
                c.sides[0].team[partner].hp = 0
        c.rng = random.Random(self.rng.random())
        c.weather, c.weather_turns, c.turn, c.log, c.winner = self.weather, 0, 1, None, None
        return c

    def choose(self, battler):
        """The answer to the choice the DUO holds for our battler: (value, target) - an action
        (0 fight, 2 switch), a move slot with its target battler, or a party slot."""
        cmd, d = self.pending[battler]
        if self.theirs is None:
            raise ValueError("the game's party isn't in the record yet")
        if cmd == C_CHOOSEACTION:
            if self.double:
                self.plan[battler] = (self._double_plan(battler) if self.level in ("elite", "impossible")
                                      else self._double_move(battler))
                return 0, 0
            a = self._single(battler)
            self.plan[battler] = a
            return (2, 0) if a[0] == "switch" else (0, 0)
        if cmd == C_CHOOSEMOVE:
            usable = [i for i in range(4) if len(d) >= 16 and (d[4 + 2 * i] | d[5 + 2 * i]) and d[12 + i]]
            plan = self.plan.pop(battler, None)
            if self.double:
                plan = plan if plan and plan[0] == "move" else (
                    self._double_plan(battler) if self.level in ("elite", "impossible") else self._double_move(battler))
                slot, target = plan[1], plan[2]
                self.chosen[battler] = plan          # (the partner, choosing next, works with it)
            else:
                plan = plan if plan and plan[0] == "move" else self._single(battler)
                slot, target = (plan[1] if plan[0] == "move" else -1), battler ^ 1
            if slot not in usable:
                slot = usable[0] if usable else 0
            return slot, target
        # CHOOSEPOKEMON: after our own switch, the planned Pokemon; after a faint, the best one
        plan = self.plan.pop(battler, None)
        team = self.ours
        out = {self.active.get(b) for b in (1, 3)} if self.double else {self.active.get(battler)}
        bench = [k for k, m in enumerate(team) if not m.fainted and k not in out]
        if plan and plan[0] == "switch" and plan[1] in bench:
            return plan[1], 0
        if not bench:
            return 6, 0
        if self.double:
            return self._double_replacement(battler, bench), 0
        b = self._battle_for(battler)                # (its bench: the fit ones, bar the one out now)
        k = self.player.replace(b, 0) if b.sides[0].bench() else bench[0]
        return (k if k in bench else bench[0]), 0

    def _single(self, battler):
        b = self._battle_for(battler)
        if isinstance(self.player, Impossible):
            known = self.player_known(battler)
            foe = (known or {}).get(battler ^ 1) if known else None
            act = None
            if foe and foe[0] == "move":
                moves = b.sides[1].mon.moves
                act = ("move", foe[1]) if foe[1] < len(moves) else None
            elif foe and foe[0] == "switch" and foe[1] < len(b.sides[1].team):
                act = ("switch", foe[1])
            a = self.player.choose(b, 0, foe_action=act)
            self.log.append(f"impossible: the player chose {foe or 'nothing yet'}; the DUO answers {a}")
        else:
            a = self.player.choose(b, 0)
        return a

    def _double_move(self, battler):
        """A double battle's move and target: the most damage (a knock-out first), working with the
        partner (not both on a foe the partner will knock out), spread moves at half power on each
        foe, and - impossible - never at a foe that protects this turn, and at the Pokemon coming in
        where the player switches."""
        me = self.mon(battler)
        foes = [f for f in self.FOES if self.mon(f) and not self.mon(f).fainted]
        known = self.player_known(battler) if isinstance(self.player, Impossible) else None
        known = known or {}
        partner_plan = self.chosen.get(battler ^ 2)
        best, best_v = None, -1.0
        for i, move in enumerate(me.moves):
            if i >= len(me.pp) or me.pp[i] <= 0:
                continue
            spread = MOVES[move][6] in (0x08, 0x20)
            for f in foes:
                v = 0.0
                for t in (foes if spread else [f]):
                    b = self._battle_for(battler, t)
                    choice = known.get(t)
                    if choice and choice[0] == "switch" and choice[1] < len(b.sides[1].team):
                        b.sides[1].active = choice[1]
                    if choice and choice[0] == "move":
                        fm = b.sides[1].mon.moves
                        if choice[1] < len(fm) and effect_of(fm[choice[1]]) in PROTECTS:
                            continue
                    dmg, ko = expected_hit(b, 0, move)
                    if not MOVES[move][1] and not useless(b, 0, move):
                        dmg = 0.12
                    # (a knock-out is worth a whole Pokemon - its next moves never come - as in evaluate)
                    part = (0.5 if spread and len(foes) > 1 else 1.0) * 1.6 * dmg + 2.0 * ko
                    if partner_plan and partner_plan[0] == "move" and partner_plan[2] == t and partner_plan[3] >= 0.75:
                        part *= 0.3                  # (the partner should knock that one out)
                    v += part
                if self.level == "easy":
                    v *= self.rng.uniform(0.75, 1.25)
                if v > best_v:
                    best_v, best = v, ("move", i, f, ko_of(self, battler, move, f))
        if best is None:
            return ("move", 0, foes[0] if foes else self.FOES[0], 0.0)
        return best

    def _double_plan(self, battler):
        """Elite and impossible in a double battle: every pairing of our two battlers' moves and
        targets (the partner's kept if it has already chosen this turn), each turn played out in
        order of priority and speed against the foes' likely moves - the player's real choices for
        impossible, and the moves each foe has shown, at best, for elite - with knock-outs that come
        before a foe can act, a move turning to the other foe when its target has fainted, spread
        moves at half power (Earthquake and the like on the partner too), and Protect; the pairing
        that leaves the best position (as evaluate weighs it) wins."""
        impossible = isinstance(self.player, Impossible)
        ours = [b for b in self.OUR_SIDE if self.mon(b) and not self.mon(b).fainted]
        foes = [b for b in self.FOES if self.mon(b) and not self.mon(b).fainted]
        if not foes or battler not in ours:
            return self._double_move(battler)
        known = (self.player_known(battler) or {}) if impossible else {}
        cache = {}

        def hit(a, t, move):                       # (expected share of t's HP, chance it knocks t out)
            key = (a, t, move)
            if key not in cache:
                if self._ours_side(a) and self._ours_side(t):   # (our own partner)
                    b = self._battle_for(a, self.FOES[0])
                    b.sides[1].team = [self.mon(t).clone()]
                    b.sides[1].active = 0
                    cache[key] = expected_hit(b, 0, move)
                elif self._ours_side(a):
                    cache[key] = expected_hit(self._battle_for(a, t), 0, move)
                else:
                    cache[key] = expected_hit(self._battle_for(t, a), 1, move)
            return cache[key]

        def options(a, moves_of):
            m = self.mon(a)
            out = []
            for i, move in enumerate(moves_of(m)):
                if a in self.CONTROLLED and (i >= len(m.pp) or m.pp[i] <= 0):
                    continue
                if MOVES[move][6] in (0x08, 0x20):
                    out.append((i, move, None))    # (spread: every foe)
                else:
                    for t in ([f for f in self.FOES if f in foes] if self._ours_side(a) else [o for o in ours]):
                        out.append((i, move, t))
            return out or [(0, m.moves[0], (foes if self._ours_side(a) else ours)[0])]

        def foe_moves(m):
            if impossible:
                return m.moves
            return [x for x in m.moves if x in m.known_moves] or m.moves[:1]

        foe_pick = {}
        for f in foes:                             # what each foe does: its real choice, or its best
            choice = known.get(f)
            fm = self.mon(f)
            if choice and choice[0] == "move" and choice[1] < len(fm.moves):
                move = fm.moves[choice[1]]
                tgt = choice[2] if len(choice) > 2 and choice[2] in ours else (ours[0] if ours else 1)
                foe_pick[f] = (choice[1], move, None if MOVES[move][6] in (0x08, 0x20) else tgt)
            elif choice and choice[0] in ("switch", "other"):
                foe_pick[f] = None
            else:
                best, bv = None, -1.0
                for opt in options(f, foe_moves):
                    i, move, t = opt
                    v = sum(1.6 * d + 2.0 * k for d, k in (hit(f, o, move) for o in (ours if t is None else [t])))
                    if v > bv:
                        best, bv = opt, v
                foe_pick[f] = best

        def play(picks):                           # the turn, in expectation: the position's value
            hp = {b: self.mon(b).hp / self.mon(b).maxhp for b in ours + foes}
            alive = {b: 1.0 for b in ours + foes}
            protect = {b for b, p in picks.items() if p and effect_of(p[1]) in PROTECTS}
            order = sorted((b for b, p in picks.items() if p), reverse=True,
                           key=lambda b: (MOVES[picks[b][1]][7], self.mon(b).speed(self.weather)))
            for a in order:
                i, move, t = picks[a]
                if alive[a] < 0.05 or not MOVES[move][1]:
                    continue
                side = foes if self._ours_side(a) else ours
                if t is None:
                    targets = list(side) + ([a ^ 2] if MOVES[move][6] == 0x20 and (a ^ 2) in alive else [])
                    mult = 0.5 if len([x for x in targets if alive[x] > 0.05]) > 1 else 1.0
                else:
                    targets = [t if alive.get(t, 0) >= 0.5 or len(side) == 1 else
                               next((x for x in side if x != t), t)]
                    mult = 1.0
                for x in targets:
                    if x in protect or alive[x] < 0.05:
                        continue
                    d, k = hit(a, x, move)
                    full = self.mon(x).hp / self.mon(x).maxhp
                    if hp[x] < full:               # (already hurt this turn: easier to knock out)
                        k = min(1.0, k + (full - hp[x]) / max(full, 1e-6))
                    w = alive[a] * mult
                    hp[x] = max(0.0, hp[x] - w * d)
                    alive[x] *= 1.0 - min(1.0, w * k)
            return (sum(alive[b] * (1.0 + 1.6 * hp[b]) for b in ours) -
                    sum(alive[b] * (1.0 + 1.6 * hp[b]) for b in foes))

        fixed = {}
        partner = battler ^ 2
        if partner in ours and self.chosen.get(partner):
            pc = self.chosen[partner]
            pm = self.mon(partner)
            if pc[1] < len(pm.moves):
                pmove = pm.moves[pc[1]]
                fixed[partner] = (pc[1], pmove, None if MOVES[pmove][6] in (0x08, 0x20) else pc[2])
        mine = options(battler, lambda m: m.moves)
        theirs = [fixed[partner]] if partner in fixed else (
            options(partner, lambda m: m.moves) if partner in ours and partner in self.CONTROLLED else
            [foe_pick.get(partner)] if partner in ours else [None])
        best, bv = None, None
        for mo in mine:
            for po in theirs:
                picks = dict(foe_pick)
                picks[battler] = mo
                if partner in ours:
                    picks[partner] = po
                v = play(picks)
                if bv is None or v > bv:
                    best, bv = mo, v
        i, move, t = best
        t = foes[0] if t is None else t
        if impossible:
            self.log.append(f"impossible (double): the player chose {known or 'nothing yet'}; battler {battler} "
                            f"uses {move_name(move)} at {t}")
        return ("move", i, t, ko_of(self, battler, move, t))

    def _double_replacement(self, battler, bench):
        foes = [f for f in self.FOES if self.mon(f) and not self.mon(f).fainted] or [self.FOES[0]]
        def score(k):
            total = 0.0
            for f in foes:
                b = self._battle_for(battler, f)
                total += matchup(b, 0, k)
            return total
        return max(bench, key=score)


class TowerLink(LinkBattle):
    """The Battle Tower's link multi battle (Emerald; docs/MULTI.md): the DUO is battler 2, the
    player's partner; the player is battler 0; the Tower's trainers are 1 and 3. Party slots as the
    game keeps them: the player's 0-2 and ours 3-5 on our side, trainer A's 0-2 and trainer B's 3-5 on
    the other. The opening blocks: the header, the player's party (two Pokemon, then a third), the
    Tower trainers' (three blocks), the seed.
    leader=True (11 November): the DUO is player 0. The game still runs the battle, so it is still
    battler 0 and the DUO battler 2 (InitLinkBtlControllers), but the parties are filed by link id: the
    DUO's Pokemon are slots 0-2 (commanded by the player) and the player's 3-5 (commanded by the DUO;
    14 November, found against the real game in the Virtual DUO)."""
    OUR_SIDE, CONTROLLED, FOES = (0, 2), (2,), (1, 3)

    def __init__(self, ours, level="medium", seed=None, leader=False):
        super().__init__(ours, level=level, double=True, seed=seed)
        self.leader = leader
        self.me = 2                                    # (our battler, whichever end of the cable)
        self.base = 3                                  # (its first party slot)
        self.CONTROLLED = (self.me,)
        self._fresh = [m.clone() for m in self.ours]   # (each battle starts with them as they came)
        self.mine = [m.clone() for m in self._fresh]   # (our own Pokemon, in order)
        self.ally = [None] * 3
        self.enemy = [None] * 6
        self.active = {0: 0, 1: 0, 2: 3, 3: 3}
        self.theirs = []                               # (filled once the Tower trainers' blocks are in)

    def side_team(self, battler):
        if battler in (0, 2):
            mine = (self.mine + [None] * 3)[:3]
            return mine + self.ally if self.leader else self.ally + mine
        return self.enemy

    def _party(self, raw):
        import duo_events as E
        team = []
        for k in range(len(raw) // 100):
            m = raw[100 * k:100 * k + 100]
            if not any(m[:32]):
                team.append(None)
                continue
            try:
                mon = mon_from_pk3(E.pk3_from_game_form(m))
            except (ValueError, KeyError, IndexError):
                team.append(None)
                continue
            hp = struct.unpack_from("<H", m, 0x56)[0]
            mon.hp = min(hp, mon.maxhp) if hp else mon.maxhp
            team.append(mon)
        return team

    def feed(self, entries):
        for kind, seq, b in entries[self.n:]:
            self.n += 1
            if kind == 2:
                code, arg = b[0] | b[1] << 8, b[2] | b[3] << 8
                if code == 1:
                    self.session, self.opening, self._party_blocks = arg, 0, []
                    if arg == 0x2288:                  # (a battle's link: everyone back at full health and
                        self.active = {0: 0, 1: 0, 2: 3, 3: 3}    # in first place; 14 November: the
                        self.mine = [m.clone() for m in self._fresh]   # second battle kept the first's)
                continue
            if self.session != 0x2288:
                continue
            if kind == 0 and self.opening < 7:
                if 1 <= self.opening <= 5:
                    self._party_blocks.append(b)
                if self.opening == 2:                  # (the player's three)
                    self.ally = (self._party(b"".join(self._party_blocks)) + [None] * 3)[:3]
                if self.opening == 5:                  # (the Tower trainers' six)
                    self.enemy = (self._party(b"".join(self._party_blocks[2:5])) + [None] * 6)[:6]
                    self.theirs = [m for m in self.enemy if m]
                self.opening += 1
                continue
            if len(b) < 8 or kind == 1:
                continue
            state, battler, attacker = b[0], b[1], b[2]
            size = b[4] | b[5] << 8
            d = b[8:8 + size]
            if state == 0 and d:
                self._command(battler, attacker, d)
            elif state == 1 and battler not in self.CONTROLLED and d:
                self._answer(battler, d)

    def _battle_for(self, battler, foe_battler=None):
        """One against one: our battler's Pokemon (its bench, our own) against one Tower trainer's."""
        foe_battler = foe_battler if foe_battler is not None else self.FOES[0]
        def half(team, active):
            base = 0 if active < 3 else 3
            mons = [(k, m) for k, m in enumerate(team[base:base + 3], base) if m]
            idx = next((i for i, (k, _) in enumerate(mons) if k == active), 0)
            return [m.clone() for _, m in mons] or [Mon(1, 5, [1])], idx
        c = Battle.__new__(Battle)
        mt, mi = half(self.side_team(battler), self.active.get(battler, self.base))
        ft, fi = half(self.side_team(foe_battler), self.active.get(foe_battler, 0))
        c.sides = [Side(mt, "DUO"), Side(ft, "Tower")]
        c.sides[0].active, c.sides[1].active = mi, fi
        c.rng = random.Random(self.rng.random())
        c.weather, c.weather_turns, c.turn, c.log, c.winner = self.weather, 0, 1, None, None
        return c

    def choose(self, battler):
        """As LinkBattle.choose, for our battler (2): fight (no switching in the Tower's multi battle),
        a move at one of the Tower's trainers, a replacement from party slots 3-5 (as leader, the
        player's own)."""
        cmd, d = self.pending[battler]
        if not self.theirs:
            raise ValueError("the Tower trainers' party isn't in the record yet")
        if cmd == C_CHOOSEACTION:
            self.plan[battler] = (self._double_plan(battler) if self.level in ("elite", "impossible")
                                  else self._double_move(battler))
            return 0, 0
        if cmd == C_CHOOSEMOVE:
            usable = [i for i in range(4) if len(d) >= 16 and (d[4 + 2 * i] | d[5 + 2 * i]) and d[12 + i]]
            plan = self.plan.pop(battler, None) or self._double_move(battler)
            slot, target = plan[1], plan[2]
            if slot not in usable:
                slot = usable[0] if usable else 0
            return slot, target if target in self.FOES else self.FOES[0]
        team = self.side_team(battler)[self.base:self.base + 3]    # (as leader, the player's own)
        bench = [self.base + k for k, m in enumerate(team) if m and not m.fainted and self.base + k != self.active.get(battler)]
        if not bench:
            return 6, 0
        foes = [f for f in self.FOES if self.mon(f) and not self.mon(f).fainted] or [self.FOES[0]]
        def score(slot):
            return sum(matchup(self._battle_for(battler, f), 0, slot - self.base) for f in foes)
        return max(bench, key=score), 0


def ko_of(lb, battler, move, foe_battler):
    """The chance this move knocks the foe out now (doubles' coordination)."""
    b = lb._battle_for(battler, foe_battler)
    return expected_hit(b, 0, move)[1]


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
    import runlog
    runlog.start("duo_battle", argv)
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

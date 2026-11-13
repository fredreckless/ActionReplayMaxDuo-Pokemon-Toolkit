#!/bin/sh
# all_games.sh - the rehearsals for Emerald or FireRed/LeafGreen (any language savegen knows), from
# savegen's save and states, each in its own folder under OUT. (English Ruby's are all.sh.)
#   GAME=emerald|leafgreen ROM=game.gba SAV=game.sav FLASH=duo_flash.bin STATES=dir PK3S=dir OUT=dir \
#       [MIX_ARGS="--base X.sb3 ..."] rehearsals/all_games.sh
# STATES is savegen's --out (at_cable_club_menu.state, and for Emerald at_blender_question.state and
# at_contest_question.state); PK3S its --pk3s (offer.pk3, team1.pk3, team2.pk3).
HERE=$(cd "$(dirname "$0")" && pwd)
set -u
C="--rom $ROM --sav $SAV --duo-flash $FLASH"
M="$STATES/at_cable_club_menu.state"
pass=0; fail=0
run() {
    name=$1; script=$2; shift 2
    if python3 "$HERE/$script.py" "$@" > "$OUT/$name.out" 2>&1 && tail -1 "$OUT/$name.out" | grep -q PASS; then
        pass=$((pass + 1)); echo "PASS  $name"
    else
        fail=$((fail + 1)); echo "FAIL  $name  (see $OUT/$name.out)"
    fi
}
mkdir -p "$OUT"
run trade trade $C --state "$M" --pk3 "$PK3S/offer.pk3" --slot 6 --out "$OUT/trade"
run single colosseum $C --state "$M" --pk3 "$PK3S/team1.pk3" "$PK3S/team2.pk3" --out "$OUT/single"
run double colosseum $C --state "$M" --mode double --pk3 "$PK3S/team1.pk3" "$PK3S/team2.pk3" --out "$OUT/double"
if [ "$GAME" = emerald ]; then
    run mix mix $C --state "$M" --out "$OUT/mix" -- ${MIX_ARGS:-}
    run blender1 blender $C --state "$STATES/at_blender_question.state" --duo-player 1 --out "$OUT/blender1"
    run blender0 blender $C --state "$STATES/at_blender_question.state" --duo-player 0 --out "$OUT/blender0"
    run contest1 contest $C --state "$STATES/at_contest_question.state" --pk3 "$PK3S/team1.pk3" --duo-player 1 --out "$OUT/contest1"
    run contest0 contest $C --state "$STATES/at_contest_question.state" --pk3 "$PK3S/team1.pk3" --duo-player 0 --out "$OUT/contest0"
fi
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]

#!/bin/sh
# all.sh - every rehearsal against English Ruby, one after another, each in its own folder under OUT.
#   RUBY=game.gba SAV=game.sav FLASH=duo_flash.bin STATES=dir PK3S=dir OUT=dir rehearsals/all.sh
# STATES holds the save states (see each script): at_trade_question, at_colosseum_question,
# at_record_question, at_link_standby and at_blender_question, each with .state on the end.
# PK3S holds offer.pk3 (what the DUO trades) and team1.pk3, team2.pk3 (its Colosseum team);
# MIX_ARGS, if set, is what to bring to Record Mixing (e.g. --base X.sb3 --trend Y.dt3); ME3 an event.
HERE=$(cd "$(dirname "$0")" && pwd)
set -u
pass=0; fail=0
run() {                          # run LABEL SCRIPT ARGS...
    name=$1; script=$2; shift 2
    if python3 "$HERE/$script.py" --rom "$RUBY" --sav "$SAV" --duo-flash "$FLASH" "$@" > "$OUT/$name.out" 2>&1 && tail -1 "$OUT/$name.out" | grep -q PASS; then
        pass=$((pass + 1)); echo "PASS  $name"
    else
        fail=$((fail + 1)); echo "FAIL  $name  (see $OUT/$name.out)"
    fi
}
mkdir -p "$OUT"
run trade trade --state "$STATES/at_trade_question.state" --pk3 "$PK3S/offer.pk3" --slot 5 --out "$OUT/trade"
run single colosseum --state "$STATES/at_colosseum_question.state" --pk3 "$PK3S/team1.pk3" "$PK3S/team2.pk3" --out "$OUT/single"
run double colosseum --state "$STATES/at_colosseum_question.state" --mode double --pk3 "$PK3S/team1.pk3" "$PK3S/team2.pk3" --out "$OUT/double"
run mix mix --state "$STATES/at_record_question.state" --out "$OUT/mix" -- ${MIX_ARGS:-}
[ -n "${ME3:-}" ] && run event event --state "$STATES/at_link_standby.state" --me3 "$ME3" --out "$OUT/event"
run blender1 blender --state "$STATES/at_blender_question.state" --duo-player 1 --out "$OUT/blender1"
run blender0 blender --state "$STATES/at_blender_question.state" --duo-player 0 --out "$OUT/blender0"
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]

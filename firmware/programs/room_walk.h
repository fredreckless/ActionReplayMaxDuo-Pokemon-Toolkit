/* room_walk.h - where both players stand in a Cable Club room, worked out from the keys the two
 * games exchange every frame, and the way to a tile (a seat, the door) around the other player.
 * Included by trade.c, mix.c and colosseum.c.
 *
 * The rooms run in lockstep (overworld.c): every frame each game sends 0xCAFE and a key, and every
 * game moves every player from the same keys, so the DUO can follow both characters exactly as the
 * games do. The rules are the models' (tests/trade_game_model.py Room, mix_game_model.py
 * CornerRoom): a direction key from a player who isn't mid-step turns them that way and, if the
 * tile ahead is open (floor, and not where the other player stands or is stepping from), starts a
 * 16-frame step. A player's key only counts in a frame where they sent 0xCAFE.
 *
 * Lab session 31: the player stood in the DUO's fixed path out of the room; its steps failed, it
 * pressed DOWN and sent 23 away from the door, and LeafGreen's screen went black. Now the DUO
 * routes around the player, presses DOWN only on the door facing down, and waits while every way
 * is blocked.
 *
 * 7 November (hardware): with the player stepping about in its way, the DUO turned back and forth
 * as each new plan went round wherever the player happened to be. Now it plans twice: once as if
 * the room were empty, and once around the tiles the player is on, stepping from, or has just used
 * (while they keep moving); if the player makes the way longer, it waits RW_PATIENCE frames for
 * them to move on, then goes round, and keeps to that while they stay about. It never gives up.
 *
 * Before including: RW_DIST, a u8 array of at least w * h bytes the search may use (mix.c lends
 * its mixing buffer, idle whenever anyone walks), and REG_IF / IF_SERIAL. */

#define RW_STEP_FRAMES 16
#define RW_KEY_NONE  17
#define RW_KEY_DOWN  18
#define RW_KEY_UP    19
#define RW_KEY_LEFT  20
#define RW_KEY_RIGHT 21

typedef struct { u8 x, y, px, py, moving, facing; } rw_player;

static const u16 *rw_rows;            /* a row each: bit (x - rw_x0) set where the floor is open */
static u32 rw_x0, rw_w, rw_h, rw_door_y, rw_door_x0, rw_door_x1, rw_on;
static rw_player rw[2];
static u32 rw_await;                  /* a key of ours sent and not yet seen in a received frame */
static u32 rw_need, rw_ready;         /* a route asked for / worked out (below) */
static u32 rw_blocked_now;            /* the way to where we're going is blocked (for the PC) */
static u32 rw_was_blocked;            /* ...at any moment since the PC last asked (a short wait between polls) */
static u32 rw_clock, rw_wait_since;   /* command cycles seen; since when the player is in our way */
static u8 rw_hx[2], rw_hy[2];         /* the two tiles the other player was on before (0xFF: none) */
static u32 rw_moved_at;               /* the cycle the other player last started a step */
static const u8 *rw_seats;            /* x, y pairs: the room's seats or spots, coordinate triggers that */
static u32 rw_nseats;                 /* stop whoever steps on one; never walked across, only to as the goal */
#define RW_PATIENCE 60                /* cycles to wait for the player to move on before going round */
#define RW_FORGET   48                /* cycles after the player's last step before their old tiles count as free */

static void rw_start(const u16 *rows, u32 ox, u32 w, u32 h, u32 door_y, u32 door_x0, u32 door_x1, u32 x0, u32 x1,
                     const u8 *seats, u32 nseats)
{
    rw_seats = seats; rw_nseats = nseats;
    /* each player appears on the door row, side by side: player 0 at x0, player 1 at x1 */
    rw_rows = rows; rw_x0 = ox; rw_w = w; rw_h = h; rw_door_y = door_y; rw_door_x0 = door_x0; rw_door_x1 = door_x1;
    rw_on = 1; rw_await = rw_need = rw_ready = rw_blocked_now = rw_wait_since = 0;
    rw_hx[0] = rw_hx[1] = 0xFF;
    rw[0].x = rw[0].px = x0; rw[1].x = rw[1].px = x1;
    rw[0].y = rw[0].py = rw[1].y = rw[1].py = door_y;
    rw[0].moving = rw[1].moving = 0;
    rw[0].facing = rw[1].facing = RW_KEY_UP;
}

static void rw_settle(void)           /* back from the trade screen or the mixing: standing still */
{
    for (u32 i = 0; i < 2; i++) { rw[i].moving = 0; rw[i].px = rw[i].x; rw[i].py = rw[i].y; }
    rw_await = rw_need = rw_ready = rw_wait_since = 0;
    rw_hx[0] = rw_hx[1] = 0xFF;
}

static u32 rw_open(int x, int y)
{
    return y >= 0 && y < (int)rw_h && (u32)(x - rw_x0) < 16 && (rw_rows[y] >> (x - rw_x0) & 1);
}

static u32 rw_is_door(int x, int y) { return y == (int)rw_door_y && x >= (int)rw_door_x0 && x <= (int)rw_door_x1; }

static u32 rw_closed(u32 who, int x, int y)
{
    const rw_player *o = &rw[1 - who];
    if (!rw_open(x, y)) return 1;
    return (x == o->x && y == o->y) || (x == o->px && y == o->py);
}

static void rw_dir(u32 k, int *dx, int *dy)
{
    *dx = k == RW_KEY_RIGHT ? 1 : k == RW_KEY_LEFT ? -1 : 0;
    *dy = k == RW_KEY_DOWN ? 1 : k == RW_KEY_UP ? -1 : 0;
}

static void rw_apply(u16 c0, u16 k0, u16 c1, u16 k1, u32 me)
{
    /* one command cycle: each player's command word and the word after it (the key with 0xCAFE) */
    u16 keys[2];
    keys[0] = c0 == 0xCAFE ? k0 : 0;
    keys[1] = c1 == 0xCAFE ? k1 : 0;
    if (!rw_on) return;
    rw_clock++;
    if ((me ? c1 : c0) == 0xCAFE) rw_await = 0;
    for (u32 w = 0; w < 2; w++) {
        rw_player *p = &rw[w];
        u16 k = keys[w];
        if (p->moving) {
            if (--p->moving == 0) { p->px = p->x; p->py = p->y; }
        } else if (k >= RW_KEY_DOWN && k <= RW_KEY_RIGHT) {
            int dx, dy;
            rw_dir(k, &dx, &dy);
            p->facing = k;
            if (!rw_closed(w, p->x + dx, p->y + dy)) {
                if (w != me) {                          /* the tiles the player has just used */
                    rw_hx[1] = rw_hx[0]; rw_hy[1] = rw_hy[0];
                    rw_hx[0] = p->px; rw_hy[0] = p->py;
                    rw_moved_at = rw_clock;
                }
                p->px = p->x; p->py = p->y;
                p->x += dx; p->y += dy;
                p->moving = RW_STEP_FRAMES;
            }
        }
    }
}

/* The way to the goal: distances spread out from the goal (a seat, or every door tile) one sweep at
 * a time, one byte a tile, around walls and the other player; then the step towards the nearest.
 * It takes a few milliseconds in all, far longer than the gap between two transfers, so it never
 * runs inside one and gives way to the link: the key code asks for a plan (rw_take), the main
 * loop works on it between one frame's command cycle and the next (rw_plan_run), a row at a time,
 * stopping the moment a transfer is waiting and carrying on from there next time; the key code
 * takes the step once it's ready. */
static int rw_goal_x, rw_goal_y;
static u32 rw_phase, rw_cx, rw_cy, rw_changed, rw_pass, rw_free_dist, rw_dist;
static u16 rw_planned;

static u32 rw_plan_closed(u32 me, int x, int y)  /* for planning: pass 0 an empty room; pass 1 around the player */
{
    for (u32 i = 0; i < rw_nseats; i++)                   /* another seat: its script would stop us there */
        if (x == rw_seats[2 * i] && y == rw_seats[2 * i + 1] && (x != rw_goal_x || y != rw_goal_y)) return 1;
    if (!rw_pass) return !rw_open(x, y);
    if (rw_closed(me, x, y)) return 1;
    if (rw_clock - rw_moved_at > RW_FORGET) return 0;
    for (u32 i = 0; i < 2; i++)
        if (x == rw_hx[i] && y == rw_hy[i]) return 1;
    return 0;
}

static void rw_plan_run(u32 me)
{
    /* a tile at a time (only the 16 columns that can be open), checking for a transfer before each */
    u8 *d = RW_DIST;
    while (rw_need) {
        if (REG_IF & IF_SERIAL) return;                      /* the link first; carry on later */
        int x = rw_cx, y = rw_cy;
        u8 *here = &d[y * rw_w + x];
        if (rw_phase == 0) {                                 /* the goal tiles at 0, the rest unknown: every
                                                              * column, walls too, which the sweeps read as
                                                              * neighbours (7 November: column 3 of the Record
                                                              * Corner kept the buffer's old bytes, so the
                                                              * left wall's tiles looked near the seat and
                                                              * the DUO paced along it, on hardware) */
            u32 goal = rw_goal_x < 0 ? rw_is_door(x, y) : (x == rw_goal_x && y == rw_goal_y);
            *here = goal && !rw_plan_closed(me, x, y) ? 0 : 0xFF;
        } else if (!rw_plan_closed(me, x, y)) {                   /* a sweep: one more than the best neighbour */
            u32 best = *here;
            if (here[-1] + 1u < best) best = here[-1] + 1;   /* (rows and columns at the edges are walls, */
            if (here[1] + 1u < best) best = here[1] + 1;     /*  so an open tile's neighbours are in the room) */
            if (here[-(int)rw_w] + 1u < best) best = here[-(int)rw_w] + 1;
            if (y + 1 < (int)rw_h && here[rw_w] + 1u < best) best = here[rw_w] + 1;
            if (best < *here) { *here = best; rw_changed = 1; }
        }
        if (++rw_cx < (rw_phase ? rw_x0 + 16 : rw_w) && rw_cx < rw_w) continue;
        rw_cx = rw_phase ? rw_x0 : 0;
        if (++rw_cy < rw_h) continue;
        rw_cy = 0;
        if (rw_phase == 0 || rw_changed) { rw_phase = 1; rw_changed = 0; rw_cx = rw_x0; continue; }
        u32 best = 0xFF;                                     /* settled: the step towards the goal */
        rw_planned = 0;
        for (u32 k = RW_KEY_DOWN; k <= RW_KEY_RIGHT; k++) {
            int dx, dy;
            rw_dir(k, &dx, &dy);
            int nx = rw[me].x + dx, ny = rw[me].y + dy;
            if (rw_plan_closed(me, nx, ny)) continue;
            if (d[ny * rw_w + nx] < best) { best = d[ny * rw_w + nx]; rw_planned = k; }
        }
        if (!rw_pass) { rw_free_dist = best; rw_pass = 1; rw_phase = rw_changed = 0; continue; }
        rw_dist = best;
        rw_need = 0; rw_ready = 1;
    }
}

static u32 rw_take(int tx, int ty, u16 *k)      /* 1 and the step (0: wait) once ready; else asks */
{
    if (rw_ready) {
        rw_ready = 0; *k = rw_planned;
        if (rw_dist <= rw_free_dist) { rw_wait_since = 0; return 1; }   /* nobody in the way */
        if (!rw_wait_since) rw_wait_since = rw_clock | 1;               /* the player is: wait a moment, */
        if (rw_clock - rw_wait_since < RW_PATIENCE) *k = 0;            /* then go round (if there's a way) */
        return 1;
    }
    if (!rw_need) { rw_goal_x = tx; rw_goal_y = ty; rw_phase = rw_cy = rw_changed = rw_cx = rw_pass = 0; rw_need = 1; }
    return 0;
}

static u32 rw_at(u32 me, int x, int y) { return rw[me].x == x && rw[me].y == y; }
static u32 rw_on_door(u32 me) { return rw_is_door(rw[me].x, rw[me].y); }
static u32 rw_free(u32 me) { return !rw_await && !rw[me].moving; }

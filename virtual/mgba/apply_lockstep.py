"""apply_lockstep.py - one correction to mGBA 0.10.5's link cable (lockstep), for a master that
starts a transfer before every other GBA is ready.

    python3 apply_lockstep.py path/to/mgba-0.10.5

Unpatched, mGBA ignores a multiplayer master's START (SIOCNT bit 7) while SD (bit 3, "all GBAs
ready") is low, but leaves the bit set: the master then looks busy for ever and never transfers
again. Real hardware runs the transfer regardless: the master clocks out its word, receives FFFFh
for every GBA that isn't taking part, the busy bit clears and the serial interrupt is requested
(GBATEK, "SIO Multi-Player Mode": the master should check SD first, and missing GBAs read FFFFh).
The DUO's link programs rely on that: they start a transfer every frame until the game answers,
and on the real DUO they link up whichever end of the cable they are on. Pokemon games check SD
first, which is why mGBA's own two-game links never meet the case.

The edit is made by exact text replacement, so it fails loudly on any other mGBA version.
"""
import os, sys

root = sys.argv[1]
p = os.path.join(root, "src/gba/sio/lockstep.c")
s = open(p).read()
old = """				mTimingSchedule(&driver->p->p->timing, &node->event, 0);
			}
		}
		value &= 0xFF83;"""
new = """				mTimingSchedule(&driver->p->p->timing, &node->event, 0);
			} else if (!node->id && node->mode == SIO_MULTI) {
				/* (Virtual DUO) not everyone is ready: a transfer with nobody else taking part */
				struct GBA* gba = driver->p->p;
				gba->memory.io[REG_SIOMULTI0 >> 1] = gba->memory.io[REG_SIOMLT_SEND >> 1];
				gba->memory.io[REG_SIOMULTI1 >> 1] = 0xFFFF;
				gba->memory.io[REG_SIOMULTI2 >> 1] = 0xFFFF;
				gba->memory.io[REG_SIOMULTI3 >> 1] = 0xFFFF;
				value &= ~0x0080;
				if (value & 0x4000) {
					GBARaiseIRQ(gba, GBA_IRQ_SIO, 0);
				}
			}
		}
		value &= 0xFF83;"""
if "(Virtual DUO) not everyone is ready" in s:
    sys.exit(0)
if s.count(old) != 1:
    sys.exit("src/gba/sio/lockstep.c: expected exactly one match")
open(p, "w").write(s.replace(old, new))

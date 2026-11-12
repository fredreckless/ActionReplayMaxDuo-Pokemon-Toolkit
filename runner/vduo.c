/*
 * vduo - the Virtual DUO runner: two GBAs on a link cable in mGBA, one of them with the MAX DUO
 * (the shared C core, duocore.c) in its cartridge slot. No window: it's driven by a test script
 * over stdin/stdout, and by duo_events.py over a local TCP socket that stands in for USB.
 *
 *   vduo --duo-fw FW.bin [--slot GAME.gba --slot-save GAME.sav --slot-type sanyo]
 *        [--partner GAME.gba --partner-save GAME.sav] [--duo-player 0|1]
 *        [--usb-port 7714] [--wait-for-hello] [--log-ctrl FILE]
 *
 * Nothing is ever written to the ROM or save files named here: every save lives in memory, and
 * leaves only through an explicit `save_sav` command.
 *
 * Commands (one per line on stdin; one reply line on stdout, "ok ..." or "err ..."):
 *   status                         frames, the DUO's mapping, the link's turn, counters
 *   run_frames PLAYER N            run until PLAYER (duo|partner) has shown N more frames
 *   keys PLAYER HEXMASK            buttons held from now on (GBA KEYINPUT bits, 1 = held)
 *   read PLAYER ADDR LEN           memory, as hex (no side effects on the cartridge)
 *   write PLAYER ADDR HEX          poke RAM (not the cartridge)
 *   state_save PLAYER PATH         an mGBA save state (the DUO's GBA: the core's state too)
 *   state_load PLAYER PATH
 *   screenshot PLAYER PATH         a PNG of the current frame
 *   save_sav PLAYER PATH           the cartridge's save as it stands now, to a new file
 *   power_on                       start the DUO's GBA (with --wait-for-hello it starts off)
 *   reset PLAYER                   a soft reset (the GBA restarts; the DUO's USB chip doesn't)
 *   events                         unmodelled control-area accesses and faults so far
 *   quit
 *
 * USB socket (one client at a time), frames of 9 bytes:
 *   client -> vduo   'W' + 8 bytes   the PC writes a packet; vduo answers 'A' (taken) or 'N'
 *                                    (refused: the USB chip still holds the PC's last packet)
 *   vduo -> client   'R' + 8 bytes   a packet from the GBA
 *
 * Two GBAs are scheduled cooperatively on one thread with mGBA's lockstep link driver: a GBA
 * that has to wait for the other leaves its run loop early and isn't run until it's signalled,
 * which keeps every link transfer deterministic.
 */
#include <mgba/core/core.h>
#include <mgba/core/config.h>
#include <mgba/core/log.h>
#include <mgba/core/lockstep.h>
#include <mgba/gba/core.h>
#include <mgba/internal/gba/gba.h>
#include <mgba/internal/gba/io.h>
#include <mgba/internal/gba/memory.h>
#include <mgba/internal/gba/savedata.h>
#include <mgba/internal/gba/sio/lockstep.h>
#include <mgba-util/png-io.h>
#include <mgba-util/vfs.h>

#include "duocore.h"

#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#define ROM_SPACE 0x02000000u
#define MAX_EVENTS 256

/* ------------------------------------------------------------------ the DUO, as a cartridge-bus device */

struct Event { char text[200]; unsigned count; };

struct Duo {
	struct GBACartBus bus;
	duo_t* core;
	struct GBA* gba;
	uint8_t usbOut[64][8];      /* GBA packets on their way to the PC */
	int usbOutHead, usbOutTail;
	struct Event events[MAX_EVENTS];
	int nEvents;
	unsigned violations, bad, failures, packetsFromGba, packetsFromPc;
	FILE* ctrlLog;
};

static void note(struct Duo* duo, const char* fmt, ...) {
	char text[200];
	va_list ap;
	va_start(ap, fmt);
	vsnprintf(text, sizeof(text), fmt, ap);
	va_end(ap);
	for (int i = 0; i < duo->nEvents; ++i) {
		if (!strcmp(duo->events[i].text, text)) {
			++duo->events[i].count;
			return;
		}
	}
	if (duo->nEvents < MAX_EVENTS) {
		snprintf(duo->events[duo->nEvents].text, sizeof(duo->events[0].text), "%s", text);
		duo->events[duo->nEvents++].count = 1;
	}
}

static uint32_t pcOf(struct Duo* duo) {
	return duo->gba->cpu->gprs[ARM_PC] - (duo->gba->cpu->executionMode == MODE_THUMB ? 4 : 8);
}

static void render(struct Duo* duo, uint32_t lo, uint32_t hi) {
	if (hi > ROM_SPACE) {
		hi = ROM_SPACE;
	}
	if (hi > lo) {
		duo_render(duo->core, DUO_ROM_BASE + lo, (uint8_t*) duo->gba->memory.rom + lo, hi - lo);
	}
}

static void apply(struct Duo* duo, const duo_result* r) {
	if (r->flags & DUO_F_ROM_CHANGED) {
		render(duo, r->rom_lo, r->rom_hi);
	}
	if (r->flags & DUO_F_VIOLATION) {
		++duo->violations;
		note(duo, "save violation: %s (pc %08X)", r->msg, pcOf(duo));
	}
	if (r->flags & DUO_F_BAD) {
		++duo->bad;
		note(duo, "bad access: %s (pc %08X)", r->msg, pcOf(duo));
	}
	if (r->flags & DUO_F_USB_SENT) {
		uint8_t pkt[8];
		if (duo_usb_take(duo->core, pkt)) {
			memcpy(duo->usbOut[duo->usbOutTail], pkt, 8);
			duo->usbOutTail = (duo->usbOutTail + 1) % 64;
			++duo->packetsFromGba;
		}
	}
}

static int unmodelled(uint32_t address) {
	return address >= DUO_CTRL_LO && address <= DUO_CTRL_HI && (address & ~1u) != 0x09FE01C0u && (address & ~1u) != 0x09FE01E0u;
}

static uint32_t _duoLoad(struct GBACartBus* bus, uint32_t address, int width) {
	struct Duo* duo = bus->context;
	duo_result r;
	uint32_t v = duo_read(duo->core, address, width, &r);
	apply(duo, &r);
	if (unmodelled(address) && !duo_mapped(duo->core)) {
		note(duo, "unmodelled read %08X/%d -> %X (pc %08X)", address, width, v, pcOf(duo));
		if (duo->ctrlLog) {
			fprintf(duo->ctrlLog, "R %08X %d %X pc=%08X\n", address, width, v, pcOf(duo));
		}
	}
	return v;
}

static void _duoStore(struct GBACartBus* bus, uint32_t address, int width, uint32_t value) {
	struct Duo* duo = bus->context;
	duo_result r;
	duo_write(duo->core, address, width, value, &r);
	if (r.status == DUO_FAIL) {
		/* on hardware the write simply does nothing that we know of: record it and carry on */
		++duo->failures;
		note(duo, "%s (pc %08X)", r.msg, pcOf(duo));
		if (duo->ctrlLog) {
			fprintf(duo->ctrlLog, "W %08X %d %X pc=%08X %s\n", address, width, value, pcOf(duo), r.msg);
		}
		return;
	}
	apply(duo, &r);
}

static void _duoFetch(struct GBACartBus* bus, uint32_t address) {
	struct Duo* duo = bus->context;
	if (duo_wants_rom_reads(duo->core)) {        /* running game code wakes the save chip too */
		duo_result r;
		duo_read(duo->core, address & ~1u, 2, &r);
		apply(duo, &r);
	}
}

static void _duoWaitcnt(struct GBACartBus* bus, uint16_t value) {
	struct Duo* duo = bus->context;
	duo_result r;
	duo_set_waitcnt(duo->core, value, &r);
	apply(duo, &r);
}

/* ------------------------------------------------------------------ players and the link */

struct Player {
	const char* name;
	struct mCore* core;
	struct GBASIOLockstepNode node;
	color_t* video;
	int awake;              /* 1: may run; 0: waiting for the link */
	unsigned waitMask;
	int32_t cyclesPosted;
	int powered;
	struct VFile* save;     /* in memory: the files on disk are never written */
};

static struct Player players[2];
static int nPlayers;
static struct GBASIOLockstep lockstep;
static struct Duo duo;
static struct Player* duoPlayer;
static struct Player* partnerPlayer;

static struct Player* byId(int id) {
	for (int i = 0; i < nPlayers; ++i) {
		if (players[i].node.id == id) {
			return &players[i];
		}
	}
	return NULL;
}

/* The same bookkeeping as mGBA's Qt frontend (MultiplayerController.cpp), with "wait" meaning
 * "don't run this GBA" instead of blocking a thread. */
static bool _signal(struct mLockstep* ls, unsigned mask) {
	UNUSED(ls);
	struct Player* p = byId(0);
	p->waitMask &= ~mask;
	if (!p->waitMask && p->awake < 1) {
		p->awake = 1;
		return true;
	}
	return false;
}

static bool _wait(struct mLockstep* ls, unsigned mask) {
	UNUSED(ls);
	struct Player* p = byId(0);
	p->waitMask |= mask;
	if (p->awake > 0) {
		p->awake = 0;
		return true;
	}
	return false;
}

static void _addCycles(struct mLockstep* ls, int id, int32_t cycles) {
	UNUSED(ls);
	if (cycles < 0) {
		abort();
	}
	if (!id) {
		for (int i = 1; i < nPlayers; ++i) {
			struct Player* p = byId(i);
			if (p->node.d.p->mode > SIO_MULTI) {
				continue;
			}
			p->cyclesPosted += cycles;
			if (p->awake < 1) {
				p->node.nextEvent += p->cyclesPosted;
			}
			p->awake = 1;
		}
	} else {
		byId(id)->cyclesPosted += cycles;
	}
}

static int32_t _useCycles(struct mLockstep* ls, int id, int32_t cycles) {
	UNUSED(ls);
	struct Player* p = byId(id);
	p->cyclesPosted -= cycles;
	if (p->cyclesPosted <= 0) {
		p->awake = 0;
	}
	return p->cyclesPosted;
}

static int32_t _unusedCycles(struct mLockstep* ls, int id) {
	UNUSED(ls);
	return byId(id)->cyclesPosted;
}

static void _unload(struct mLockstep* ls, int id) {
	UNUSED(ls);
	if (id) {
		struct Player* p = byId(id);
		p->cyclesPosted = 0;
		struct Player* m = byId(0);
		m->waitMask &= ~(1 << id);
		if (!m->waitMask && m->awake < 1) {
			m->awake = 1;
		}
	} else {
		for (int i = 1; i < nPlayers; ++i) {
			struct Player* p = byId(i);
			p->cyclesPosted += lockstep.players[0]->eventDiff;
			if (p->awake < 1) {
				p->node.nextEvent += p->cyclesPosted;
				p->awake = 1;
			}
		}
	}
}

/* ------------------------------------------------------------------ setting up */

static void _quietLog(struct mLogger* logger, int category, enum mLogLevel level, const char* format, va_list args) {
	UNUSED(logger);
	if (level & (mLOG_FATAL | mLOG_ERROR)) {
		fprintf(stderr, "mgba [%s]: ", mLogCategoryName(category));
		vfprintf(stderr, format, args);
		fputc('\n', stderr);
	}
}
static struct mLogger quietLogger = { .log = _quietLog };

static uint8_t* slurp(const char* path, size_t* len) {
	FILE* f = fopen(path, "rb");
	if (!f) {
		fprintf(stderr, "vduo: can't open %s: %s\n", path, strerror(errno));
		exit(2);
	}
	fseek(f, 0, SEEK_END);
	long n = ftell(f);
	fseek(f, 0, SEEK_SET);
	uint8_t* buf = malloc(n ? n : 1);
	if (fread(buf, 1, n, f) != (size_t) n) {
		fprintf(stderr, "vduo: can't read %s\n", path);
		exit(2);
	}
	fclose(f);
	*len = n;
	return buf;
}

static struct VFile* memCopy(const uint8_t* data, size_t len) {
	struct VFile* vf = VFileMemChunk(NULL, len);
	vf->write(vf, data, len);
	vf->seek(vf, 0, SEEK_SET);
	return vf;
}

static struct mCore* newCore(struct Player* p) {
	struct mCore* core = GBACoreCreate();
	core->init(core);
	mCoreInitConfig(core, NULL);
	mCoreConfigSetValue(&core->config, "idleOptimization", "ignore");   /* never skip a polling loop */
	mCoreConfigSetIntValue(&core->config, "skipBios", 1);              /* mGBA's own BIOS, straight to the cartridge */
	mCoreLoadConfig(core);
	unsigned w, h;
	core->desiredVideoDimensions(core, &w, &h);
	p->video = calloc(w * h, sizeof(color_t));
	core->setVideoBuffer(core, p->video, w);
	core->setAudioBufferSize(core, 2048);
	p->core = core;
	return core;
}

static void attachLink(struct Player* p) {
	struct GBA* gba = p->core->board;
	GBASIOLockstepNodeCreate(&p->node);
	GBASIOLockstepAttachNode(&lockstep, &p->node);
	GBASIOSetDriver(&gba->sio, &p->node.d, SIO_MULTI);
	GBASIOSetDriver(&gba->sio, &p->node.d, SIO_NORMAL_32);
	p->awake = 1;
}

static void duoAfterReset(void) {
	struct GBA* gba = duoPlayer->core->board;
	gba->memory.cartBus = &duo.bus;
	gba->memory.hw.devices = HW_NONE;            /* the DUO's own header mustn't switch on an RTC */
	GBASavedataForceType(&gba->memory.savedata, SAVEDATA_FORCE_NONE);
	gba->idleOptimization = IDLE_LOOP_IGNORE;
	gba->idleLoop = IDLE_LOOP_NONE;
	duo.gba = gba;
	duo_result r;
	duo_set_waitcnt(duo.core, gba->memory.io[REG_WAITCNT >> 1], &r);
	render(&duo, 0, ROM_SPACE);                   /* what the cartridge reads now */
}

/* ------------------------------------------------------------------ USB socket */

static int usbListen = -1, usbClient = -1;
static uint8_t usbIn[9];
static int usbInLen;

static void usbOpen(int port) {
	usbListen = socket(AF_INET, SOCK_STREAM, 0);
	int one = 1;
	setsockopt(usbListen, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
	struct sockaddr_in a = { .sin_family = AF_INET, .sin_port = htons(port), .sin_addr.s_addr = htonl(INADDR_LOOPBACK) };
	if (bind(usbListen, (struct sockaddr*) &a, sizeof(a)) || listen(usbListen, 1)) {
		fprintf(stderr, "vduo: can't listen on 127.0.0.1:%d: %s\n", port, strerror(errno));
		exit(2);
	}
	fcntl(usbListen, F_SETFL, O_NONBLOCK);
}

static void usbClose(void) {
	if (usbClient >= 0) {
		close(usbClient);
	}
	usbClient = -1;
	usbInLen = 0;
}

static void usbService(void) {
	if (usbListen < 0) {
		return;
	}
	if (usbClient < 0) {
		usbClient = accept(usbListen, NULL, NULL);
		if (usbClient < 0) {
			return;
		}
		fcntl(usbClient, F_SETFL, O_NONBLOCK);
		int one = 1;
		setsockopt(usbClient, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
	}
	for (;;) {                                   /* PC packets in */
		ssize_t n = recv(usbClient, usbIn + usbInLen, 9 - usbInLen, 0);
		if (n == 0) {
			usbClose();
			return;
		}
		if (n < 0) {
			if (errno != EAGAIN && errno != EWOULDBLOCK) {
				usbClose();
				return;
			}
			break;
		}
		usbInLen += n;
		if (usbInLen < 9) {
			continue;
		}
		usbInLen = 0;
		if (usbIn[0] != 'W') {
			usbClose();
			return;
		}
		duo_result r;
		char answer = duo_usb_from_pc(duo.core, usbIn + 1, 8, &r) == DUO_OK ? 'A' : 'N';
		if (answer == 'A') {
			++duo.packetsFromPc;
		}
		if (send(usbClient, &answer, 1, MSG_NOSIGNAL) != 1) {
			usbClose();
			return;
		}
	}
	while (duo.usbOutHead != duo.usbOutTail) {    /* GBA packets out */
		uint8_t frame[9] = { 'R' };
		memcpy(frame + 1, duo.usbOut[duo.usbOutHead], 8);
		if (send(usbClient, frame, 9, MSG_NOSIGNAL) != 9) {
			usbClose();
			return;
		}
		duo.usbOutHead = (duo.usbOutHead + 1) % 64;
	}
}

/* ------------------------------------------------------------------ commands */

static struct Player* named(const char* name) {
	if (name && !strcmp(name, "duo")) {
		return duoPlayer;
	}
	if (name && !strcmp(name, "partner")) {
		return partnerPlayer;
	}
	return NULL;
}

static int writeFile(const char* path, const void* a, size_t na, const void* b, size_t nb) {
	FILE* f = fopen(path, "wb");
	if (!f) {
		return 0;
	}
	int ok = fwrite(a, 1, na, f) == na && (!nb || fwrite(b, 1, nb, f) == nb);
	return fclose(f) == 0 && ok;
}

static void reply(const char* fmt, ...) {
	va_list ap;
	va_start(ap, fmt);
	vfprintf(stdout, fmt, ap);
	va_end(ap);
	fputc('\n', stdout);
	fflush(stdout);
}

/* A pending run_frames: answered from the main loop once the frames have gone by. */
static struct Player* waitPlayer;
static uint32_t waitUntil;
static int quitting;

static void command(char* line) {
	char* argv[8] = { 0 };
	int argc = 0;
	for (char* t = strtok(line, " \t\r\n"); t && argc < 8; t = strtok(NULL, " \t\r\n")) {
		argv[argc++] = t;
	}
	if (!argc) {
		return;
	}
	const char* c = argv[0];
	struct Player* p = named(argv[1]);
	if (!strcmp(c, "quit")) {
		quitting = 1;
		reply("ok bye");
	} else if (!strcmp(c, "status")) {
		reply("ok duo_frames=%u partner_frames=%u powered=%d mapped=%#x awake=%d turn=%s "
		      "from_pc=%u from_gba=%u violations=%u bad=%u unmodelled_writes=%u events=%d",
		      duoPlayer->core->frameCounter(duoPlayer->core),
		      partnerPlayer ? partnerPlayer->core->frameCounter(partnerPlayer->core) : 0,
		      duoPlayer->powered, duo_mapped(duo.core), duo_awake(duo.core), duo_usb_turn(duo.core) ? "gba" : "pc",
		      duo.packetsFromPc, duo.packetsFromGba, duo.violations, duo.bad, duo.failures, duo.nEvents);
	} else if (!strcmp(c, "events")) {
		for (int i = 0; i < duo.nEvents; ++i) {
			fprintf(stdout, "event %u %s\n", duo.events[i].count, duo.events[i].text);
		}
		reply("ok %d", duo.nEvents);
	} else if (!strcmp(c, "power_on")) {
		duoPlayer->powered = 1;
		reply("ok");
	} else if (!p) {
		reply("err unknown command or player: %s %s", c, argv[1] ? argv[1] : "");
	} else if (!strcmp(c, "run_frames") && argc == 3) {
		waitPlayer = p;
		waitUntil = p->core->frameCounter(p->core) + strtoul(argv[2], NULL, 0);
		if (p == duoPlayer && !p->powered) {
			reply("err the DUO's GBA is off");
			waitPlayer = NULL;
		}
	} else if (!strcmp(c, "keys") && argc == 3) {
		p->core->setKeys(p->core, strtoul(argv[2], NULL, 16));
		reply("ok");
	} else if (!strcmp(c, "read") && argc == 4) {
		uint32_t a = strtoul(argv[2], NULL, 0), n = strtoul(argv[3], NULL, 0);
		if (n > 0x40000) {
			reply("err too long");
			return;
		}
		char* hex = malloc(2 * n + 1);
		for (uint32_t i = 0; i < n; ++i) {
			uint32_t b;
			if (p == duoPlayer && (a + i) >= DUO_ROM_BASE && (a + i) < 0x10000000u) {
				uint8_t one;
				duo_render(duo.core, a + i, &one, 1);
				b = one;
			} else {
				b = p->core->rawRead8(p->core, a + i, -1);
			}
			sprintf(hex + 2 * i, "%02x", b & 0xFF);
		}
		hex[2 * n] = 0;
		reply("ok %s", hex);
		free(hex);
	} else if (!strcmp(c, "write") && argc == 4) {
		uint32_t a = strtoul(argv[2], NULL, 0);
		size_t n = strlen(argv[3]) / 2;
		if (a >= 0x08000000u) {
			reply("err only RAM can be poked");
			return;
		}
		for (size_t i = 0; i < n; ++i) {
			unsigned b;
			sscanf(argv[3] + 2 * i, "%2x", &b);
			p->core->rawWrite8(p->core, a + i, -1, b);
		}
		reply("ok");
	} else if (!strcmp(c, "state_save") && argc == 3) {
		size_t n = p->core->stateSize(p->core);
		uint8_t* st = malloc(n);
		p->core->saveState(p->core, st);
		size_t m = p == duoPlayer ? duo_state_size(duo.core) : 0;
		uint8_t* ds = m ? malloc(m) : NULL;
		if (ds) {
			duo_state_save(duo.core, ds);
		}
		uint32_t hdr[3] = { 0x4F554456u /* VDUO */, (uint32_t) n, (uint32_t) m };
		FILE* f = fopen(argv[2], "wb");
		int ok = f && fwrite(hdr, 1, 12, f) == 12 && fwrite(st, 1, n, f) == n && (!m || fwrite(ds, 1, m, f) == m);
		if (f && fclose(f)) {
			ok = 0;
		}
		free(st);
		free(ds);
		reply(ok ? "ok" : "err can't write %s", argv[2]);
	} else if (!strcmp(c, "state_load") && argc == 3) {
		size_t len;
		uint8_t* buf = slurp(argv[2], &len);
		uint32_t hdr[3];
		memcpy(hdr, buf, 12);
		if (len < 12 || hdr[0] != 0x4F554456u || 12 + hdr[1] + hdr[2] != len || hdr[1] != p->core->stateSize(p->core) ||
		    (p == duoPlayer) != (hdr[2] != 0)) {
			reply("err not a state for this player");
		} else if (!p->core->loadState(p->core, buf + 12)) {
			reply("err mGBA refused the state");
		} else {
			if (p == duoPlayer) {
				if (duo_state_load(duo.core, buf + 12 + hdr[1], hdr[2]) != DUO_OK) {
					reply("err the DUO's part of the state doesn't fit this DUO");
					free(buf);
					return;
				}
				duoAfterReset();
			}
			reply("ok");
		}
		free(buf);
	} else if (!strcmp(c, "screenshot") && argc == 3) {
		unsigned w, h;
		p->core->desiredVideoDimensions(p->core, &w, &h);
		struct VFile* vf = VFileOpen(argv[2], O_CREAT | O_TRUNC | O_WRONLY);
		png_structp png = vf ? PNGWriteOpen(vf) : NULL;
		png_infop info = png ? PNGWriteHeader(png, w, h) : NULL;
		int ok = info && PNGWritePixels(png, w, h, w, p->video);
		if (png) {
			PNGWriteClose(png, info);
		}
		if (vf) {
			vf->close(vf);
		}
		reply(ok ? "ok" : "err can't write %s", argv[2]);
	} else if (!strcmp(c, "save_sav") && argc == 3) {
		if (p == duoPlayer) {                     /* the game in the DUO's slot: the core's save chip */
			size_t n = duo_save_size(duo.core);
			uint8_t* s = malloc(n ? n : 1);
			duo_save_copy(duo.core, s);
			int ok = writeFile(argv[2], s, n, NULL, 0);
			free(s);
			reply(ok ? "ok %zu" : "err can't write %s", ok ? n : 0, argv[2]);
		} else {
			struct GBA* gba = p->core->board;
			size_t n = GBASavedataSize(&gba->memory.savedata);
			int ok = writeFile(argv[2], gba->memory.savedata.data, n, NULL, 0);
			reply(ok ? "ok %zu" : "err can't write %s", ok ? n : 0, argv[2]);
		}
	} else if (!strcmp(c, "reset")) {
		p->core->reset(p->core);
		if (p == duoPlayer) {
			duoAfterReset();
		}
		reply("ok");
	} else {
		reply("err bad command: %s", c);
	}
}

static char cmdBuf[4096];
static size_t cmdLen;

static void stdinService(void) {
	for (;;) {
		ssize_t n = read(0, cmdBuf + cmdLen, sizeof(cmdBuf) - 1 - cmdLen);
		if (n == 0) {
			quitting = 1;
			return;
		}
		if (n < 0) {
			return;
		}
		cmdLen += n;
		char* nl;
		while (!waitPlayer && (nl = memchr(cmdBuf, '\n', cmdLen))) {
			*nl = 0;
			char line[4096];
			memcpy(line, cmdBuf, nl - cmdBuf + 1);
			cmdLen -= nl - cmdBuf + 1;
			memmove(cmdBuf, nl + 1, cmdLen);
			command(line);
		}
		if (waitPlayer || cmdLen == sizeof(cmdBuf) - 1) {
			return;
		}
	}
}

/* ------------------------------------------------------------------ main */

static void usage(void) {
	fprintf(stderr, "usage: vduo --duo-fw FW.bin [--slot GAME.gba --slot-save GAME.sav --slot-type T] "
	                "[--partner GAME.gba --partner-save GAME.sav] [--duo-player 0|1] [--usb-port N] "
	                "[--wait-for-hello] [--log-ctrl FILE]\n");
	exit(2);
}

int main(int argc, char** argv) {
	const char *fw = NULL, *slot = NULL, *slotSave = NULL, *slotType = "none", *partner = NULL, *partnerSave = NULL, *ctrlLog = NULL;
	int duoId = 0, usbPort = 7714, waitHello = 0;
	for (int i = 1; i < argc; ++i) {
		const char* a = argv[i];
		const char* v = i + 1 < argc ? argv[i + 1] : NULL;
		if (!strcmp(a, "--duo-fw") && v) { fw = v; ++i; }
		else if (!strcmp(a, "--slot") && v) { slot = v; ++i; }
		else if (!strcmp(a, "--slot-save") && v) { slotSave = v; ++i; }
		else if (!strcmp(a, "--slot-type") && v) { slotType = v; ++i; }
		else if (!strcmp(a, "--partner") && v) { partner = v; ++i; }
		else if (!strcmp(a, "--partner-save") && v) { partnerSave = v; ++i; }
		else if (!strcmp(a, "--duo-player") && v) { duoId = atoi(v); ++i; }
		else if (!strcmp(a, "--usb-port") && v) { usbPort = atoi(v); ++i; }
		else if (!strcmp(a, "--log-ctrl") && v) { ctrlLog = v; ++i; }
		else if (!strcmp(a, "--wait-for-hello")) { waitHello = 1; }
		else usage();
	}
	if (!fw) {
		usage();
	}
	static const char* types[] = { "sanyo", "macronix", "flash512", "sram", "eeprom", "none" };
	int type = -1;
	for (int i = 0; i < 6; ++i) {
		if (!strcmp(slotType, types[i])) {
			type = i;
		}
	}
	if (type < 0) {
		usage();
	}
	signal(SIGPIPE, SIG_IGN);
	mLogSetDefaultLogger(&quietLogger);

	/* the DUO: its flash, the game in its slot and that game's save */
	size_t fwLen, gameLen = 0, saveLen = 0;
	uint8_t* fwData = slurp(fw, &fwLen);
	uint8_t* game = slot ? slurp(slot, &gameLen) : NULL;
	uint8_t* save = slotSave ? slurp(slotSave, &saveLen) : NULL;
	duo.core = duo_new(fwData, fwLen, game ? game : (const uint8_t*) "", gameLen, type, save ? save : (const uint8_t*) "", saveLen);
	duo.bus = (struct GBACartBus) { .context = &duo, .load = _duoLoad, .store = _duoStore, .fetch = _duoFetch, .waitcnt = _duoWaitcnt };
	if (ctrlLog) {
		duo.ctrlLog = fopen(ctrlLog, "w");
	}

	/* the link: players in cable order (player 0 is the master's end) */
	GBASIOLockstepInit(&lockstep);
	mLockstepInit(&lockstep.d);
	lockstep.d.signal = _signal;
	lockstep.d.wait = _wait;
	lockstep.d.addCycles = _addCycles;
	lockstep.d.useCycles = _useCycles;
	lockstep.d.unusedCycles = _unusedCycles;
	lockstep.d.unload = _unload;

	nPlayers = partner ? 2 : 1;
	duoPlayer = &players[partner ? duoId : 0];
	partnerPlayer = partner ? &players[1 - duoId] : NULL;
	duoPlayer->name = "duo";

	/* the DUO's GBA: a ROM space the core renders, 32 MB so that nothing is mirrored */
	newCore(duoPlayer);
	uint8_t* image = malloc(ROM_SPACE);
	duo_render(duo.core, DUO_ROM_BASE, image, ROM_SPACE);
	duoPlayer->core->loadROM(duoPlayer->core, memCopy(image, ROM_SPACE));
	free(image);
	if (partner) {
		partnerPlayer->name = "partner";
		newCore(partnerPlayer);
		size_t n;
		uint8_t* rom = slurp(partner, &n);
		partnerPlayer->core->loadROM(partnerPlayer->core, memCopy(rom, n));
		free(rom);
		if (partnerSave) {
			uint8_t* s = slurp(partnerSave, &n);
			partnerPlayer->save = memCopy(s, n);
			free(s);
		} else {
			partnerPlayer->save = VFileMemChunk(NULL, 0);
		}
		partnerPlayer->core->loadSave(partnerPlayer->core, partnerPlayer->save);
		partnerPlayer->powered = 1;
	}
	for (int i = 0; i < nPlayers; ++i) {
		players[i].core->reset(players[i].core);
		attachLink(&players[i]);
	}
	duoAfterReset();
	duoPlayer->powered = !waitHello;

	usbOpen(usbPort);
	fcntl(0, F_SETFL, O_NONBLOCK);
	reply("ready usb=127.0.0.1:%d duo_player=%d partner=%s core=\"%s\"", usbPort, duoPlayer->node.id,
	      partner ? "yes" : "no", duo_version());

	unsigned spins = 0;
	while (!quitting) {
		if ((++spins & 63) == 0 || !(duoPlayer->powered || partnerPlayer)) {
			usbService();
			stdinService();
			if (waitHello && !duoPlayer->powered && duo_usb_pending(duo.core)) {
				duoPlayer->powered = 1;              /* the hello is waiting: switch the GBA on */
			}
		}
		int ran = 0;
		for (int i = 0; i < nPlayers; ++i) {
			struct Player* p = &players[i];
			if (p->awake > 0 && p->powered) {
				p->core->runLoop(p->core);
				ran = 1;
			}
		}
		if (waitPlayer && waitPlayer->core->frameCounter(waitPlayer->core) >= waitUntil) {
			waitPlayer = NULL;
			reply("ok");
			stdinService();                          /* commands queued behind it */
		}
		if (!ran) {
			/* nothing can run: the DUO's GBA is off (or the link is waiting on it) */
			struct pollfd fds[2] = { { .fd = 0, .events = POLLIN }, { .fd = usbClient >= 0 ? usbClient : usbListen, .events = POLLIN } };
			poll(fds, 2, 5);
			usbService();
			stdinService();
			if (waitHello && !duoPlayer->powered && duo_usb_pending(duo.core)) {
				duoPlayer->powered = 1;
			}
		}
	}
	usbClose();
	return 0;
}

"""A log file for every run of the tools, so results can be read back later (by you, or by
Claude through the desktop app) without copying anything out of the command window.

Each run writes `logs/YYYY-MM-DD HHMMSS tool command.log` beside the tools: the command line, then
everything the run printed (including any error and its traceback), then how it ended.
`logs/latest.log` is always a copy of the newest. `detail()` adds lines to the log only (timings
and the like that would clutter the window). Logs hold no save data, only what the tool printed.
Old logs past the newest 200 are deleted."""
import atexit, datetime, glob, os, shutil, sys, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.environ.get("ACTIONREPLAY_LOG_DIR") or os.path.join(HERE, "logs")
KEEP = 200
_file = None
_path = None


class _Tee:
    def __init__(self, stream):
        self.stream = stream

    def write(self, text):
        try:
            self.stream.write(text)
        except UnicodeEncodeError:            # (a Windows console without the character)
            self.stream.write(text.encode(self.stream.encoding or "ascii", "replace").decode(self.stream.encoding or "ascii"))
        if _file:
            try:
                _file.write(text)
                _file.flush()
            except Exception:
                pass
        return len(text)

    def flush(self):
        self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def start(tool, argv=None):
    """Begin logging this run. Safe to call twice (the second call does nothing)."""
    global _file, _path
    if _file is not None or os.environ.get("ACTIONREPLAY_NO_LOG"):
        return _path
    argv = sys.argv[1:] if argv is None else argv
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        now = datetime.datetime.now()
        what = next((a for a in argv if not a.startswith("-")), "")
        name = f"{now:%Y-%m-%d %H%M%S} {tool}{' ' + what if what else ''}.log"
        _path = os.path.join(LOG_DIR, "".join(c for c in name if c not in '<>:"/\\|?*'))
        _file = open(_path, "w", encoding="utf-8")
        _file.write(f"{tool} {' '.join(argv)}\nstarted {now:%Y-%m-%d %H:%M:%S}\n\n")
        sys.stdout, sys.stderr = _Tee(sys.stdout), _Tee(sys.stderr)
        old_hook = sys.excepthook

        def hook(kind, value, tb):
            if _file and kind is not KeyboardInterrupt:
                _file.write("".join(traceback.format_exception(kind, value, tb)))
            old_hook(kind, value, tb)
        sys.excepthook = hook
        atexit.register(_finish)
        _tidy()
    except OSError:
        _file = None
    return _path


def detail(text):
    """A line for the log only."""
    if _file:
        try:
            _file.write(f"  ({datetime.datetime.now():%H:%M:%S.%f}"[:-3] + f") {text}\n")
            _file.flush()
        except Exception:
            pass


def _finish():
    global _file
    if not _file:
        return
    try:
        _file.write(f"\nended {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n")
        _file.close()
        shutil.copyfile(_path, os.path.join(LOG_DIR, "latest.log"))
    except Exception:
        pass
    _file = None


def _tidy():
    logs = sorted(p for p in glob.glob(os.path.join(LOG_DIR, "*.log")) if os.path.basename(p) != "latest.log")
    for p in logs[:-KEEP]:
        try:
            os.remove(p)
        except OSError:
            pass

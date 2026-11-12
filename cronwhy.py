#!/usr/bin/env python3
"""cronwhy - explain a cron expression and see when it will really run.

  python cronwhy.py "*/15 9-17 * * 1-5"
  python cronwhy.py 30 2 * * sun -n 8
  python cronwhy.py @daily --from "2026-12-31 23:00"

Supports lists, ranges, steps, month/day names and the @daily-style macros.
Times are in your local time zone.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta

__version__ = "1.0.0"

if os.name == "nt":
    os.system("")
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

USE_COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ

MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
DAYS = "SUN MON TUE WED THU FRI SAT".split()
FULL_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]
FULL_DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
MACROS = {
    "@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *", "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0", "@daily": "0 0 * * *", "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}
FIELDS = [
    ("minute", 0, 59, None),
    ("hour", 0, 23, None),
    ("day of month", 1, 31, None),
    ("month", 1, 12, MONTHS),
    ("day of week", 0, 7, DAYS),
]


def c(code, text):
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else str(text)


def die(msg):
    sys.stderr.write(f"error: {msg}\n")
    sys.exit(2)


# ---------------------------------------------------------------- parsing
def to_num(tok, names, label):
    t = tok.upper()
    if names and t in names:
        return names.index(t) + (1 if label == "month" else 0)
    if t.isdigit():
        return int(t)
    die(f"bad value {tok!r} in {label} field")


def parse_field(raw, lo, hi, names, label):
    vals = set()
    for part in raw.split(","):
        if not part:
            die(f"empty item in {label} field")
        step, has_step = 1, False
        if "/" in part:
            part, s = part.split("/", 1)
            if not s.isdigit() or int(s) == 0:
                die(f"bad step {s!r} in {label} field")
            step, has_step = int(s), True
        if part in ("*", "?"):
            a, b = lo, hi
        elif "-" in part:
            x, y = part.split("-", 1)
            a, b = to_num(x, names, label), to_num(y, names, label)
        else:
            a = to_num(part, names, label)
            b = hi if has_step else a
        if not (lo <= a <= hi and lo <= b <= hi and a <= b):
            die(f"{label} value out of range ({lo}-{hi}): {raw!r}")
        vals.update(range(a, b + 1, step))
    return vals


def parse(expr):
    expr = MACROS.get(expr.strip().lower(), expr)
    parts = expr.split()
    if len(parts) != 5:
        die("expected 5 fields: minute hour day-of-month month day-of-week (or a @macro)")
    sets = [parse_field(p, lo, hi, names, label) for p, (label, lo, hi, names) in zip(parts, FIELDS)]
    sets[4] = {v % 7 for v in sets[4]}  # 7 == Sunday == 0
    return parts, sets


# ---------------------------------------------------------------- schedule
def iter_runs(parts, sets, start):
    mins, hrs = sorted(sets[0]), sorted(sets[1])
    dom_star, dow_star = parts[2][0] in "*?", parts[4][0] in "*?"
    day = start.date()
    end = day + timedelta(days=366 * 8)
    while day <= end:
        if day.month in sets[3]:
            in_dom = day.day in sets[2]
            in_dow = ((day.weekday() + 1) % 7) in sets[4]
            # classic cron: if both day fields are restricted, either one may match
            ok = (in_dom and in_dow) if (dom_star or dow_star) else (in_dom or in_dow)
            if ok:
                for h in hrs:
                    for m in mins:
                        t = datetime(day.year, day.month, day.day, h, m)
                        if t >= start:
                            yield t
        day += timedelta(days=1)


def rel(delta):
    s = int(delta.total_seconds())
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m = s // 60
    bits = [f"{d}d" if d else "", f"{h}h" if h else "", f"{m}m" if m else ""]
    bits = [x for x in bits if x]
    return "in " + " ".join(bits) if bits else "now"


# ---------------------------------------------------------------- explain
def nm(tok, kind):
    t = tok.upper()
    if kind == "month":
        if t.isdigit() and 1 <= int(t) <= 12:
            return FULL_MONTHS[int(t) - 1]
        if t in MONTHS:
            return FULL_MONTHS[MONTHS.index(t)]
    if kind == "dow":
        if t.isdigit() and 0 <= int(t) <= 7:
            return FULL_DAYS[int(t) % 7]
        if t in DAYS:
            return FULL_DAYS[DAYS.index(t)]
    return tok


def phrase(raw, kind, unit):
    """Describe one field, or None when it is unrestricted ('*')."""
    if raw[0] in "*?" and "/" not in raw:
        return None
    plain, steps = [], []
    for p in raw.split(","):
        step = None
        if "/" in p:
            p, step = p.split("/", 1)
        if p in ("*", "?"):
            base = None
        elif "-" in p:
            x, y = p.split("-", 1)
            base = f"{nm(x, kind)} through {nm(y, kind)}"
        else:
            base = nm(p, kind)
        if step:
            s = f"every {unit}" if step == "1" else f"every {step} {unit}s"
            steps.append(s + (f" from {base}" if base else ""))
        else:
            plain.append(base)
    out = list(steps)
    if plain:
        out.append(", ".join(plain))
    return " and ".join(out)


def explain(parts):
    mi, ho, dm, mo, dw = parts
    if mi.isdigit() and ho.isdigit():
        when = f"At {int(ho):02d}:{int(mi):02d}"
    else:
        bits = []
        for raw, unit in ((mi, "minute"), (ho, "hour")):
            t = phrase(raw, "num", unit)
            if t is None:
                t = f"every {unit}"
            elif "every" not in t:
                t = f"{unit} {t}"
            bits.append(t)
        when = "Runs " + ", ".join(bits)
    extra = []
    dd = phrase(dm, "num", "day")
    ww = phrase(dw, "dow", "day")
    mm = phrase(mo, "month", "month")
    if dd:
        extra.append(("on " if "every" in dd else "on day ") + dd)
    if ww:
        extra.append(("or " if dd else "on ") + ww)
    if mm:
        extra.append("in " + mm)
    return when + (", " + ", ".join(extra) if extra else ", every day") + "."


# ---------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(prog="cronwhy", description="Explain a cron expression.")
    p.add_argument("expr", nargs="+", help='cron expression, e.g. "*/5 * * * *" or @daily')
    p.add_argument("-n", "--count", type=int, default=5, help="how many upcoming runs to show")
    p.add_argument("--from", dest="base", help='start time, "YYYY-MM-DD HH:MM" (default: now)')
    p.add_argument("-V", "--version", action="version", version=__version__)
    a = p.parse_args()
    parts, sets = parse(" ".join(a.expr))
    if a.base:
        try:
            base = datetime.strptime(a.base, "%Y-%m-%d %H:%M")
        except ValueError:
            die('--from must look like "2026-12-31 23:00"')
    else:
        base = datetime.now()
    start = base.replace(second=0, microsecond=0) + timedelta(minutes=1)

    print(f"  {c('90', 'Expression')}  {c('1;36', ' '.join(parts))}")
    print(f"  {c('90', 'Meaning')}     {explain(parts)}\n")

    runs = []
    for t in iter_runs(parts, sets, start):
        runs.append(t)
        if len(runs) >= a.count:
            break
    if not runs:
        print("  This schedule never runs (for example: February 30).")
        return 1
    print(f"  {c('1', 'Next ' + str(len(runs)) + ' run(s)')}" + c("90", f"  (after {base:%Y-%m-%d %H:%M})"))
    for i, t in enumerate(runs, 1):
        print(f"  {i:>2}. {t:%a %Y-%m-%d %H:%M}   {c('90', rel(t - base))}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        pass
    except KeyboardInterrupt:
        sys.exit(130)

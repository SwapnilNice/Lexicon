"""
BASELINE (no Lexicon) transformer — the plausible-but-WRONG version a generic
agent produces from the vendor field names alone. Kept ONLY to demonstrate the
before/after. DO NOT ship.

Injected silent errors (all compile, all look reasonable):
  1. HandleTime = talk + hold + ACW      <-- folds ACW in (the classic AHT bug)
  2. Emits SvcLvlPct for inbound voice   <-- WFM ignores/derives it; misleading
  3. Leaks the Avaya term into output    <-- 'ACWTIME' vocabulary leak
"""
import csv
import sys
from xml.sax.saxutils import escape

PERIOD = "PT15M"
VENDOR = "Avaya"


def build_xml(rows) -> str:
    dt = rows[0]["INTERVAL_START"]
    out = ['<?xml version="1.0"?>', "<HistPlugin>", "    <DataSourceNode>",
           f"        <Vendor>{escape(VENDOR)}</Vendor>", "        <QueueNode>",
           f"            <TimePeriod><DateTime>{dt}</DateTime><period>{PERIOD}</period></TimePeriod>"]
    for r in rows:
        acd = int(r["acdcalls"]); acceptable = int(r["acceptable"])
        abn = int(r["abncalls"]); abn_ok = int(r["slvlabns"])
        talk = int(r["acdtime"]); hold = int(r["holdtime"]); acw = int(r["acwtime"])
        handle_time_WRONG = talk + hold + acw            # BUG 1
        svc = round(acceptable / acd, 2) if acd else 0   # BUG 2 (should be omitted)
        out += [
            "            <QueueData>",
            f"                <QueueValue>{r['split']}</QueueValue>",
            f"                <AbandonedShort><count>{abn_ok}</count></AbandonedShort>",
            f"                <AbandonedLong><count>{abn - abn_ok}</count></AbandonedLong>",
            f"                <HandledShort><count>{acceptable}</count></HandledShort>",
            f"                <HandledLong><count>{acd - acceptable}</count></HandledLong>",
            f"                <HandleTime><duration><totalseconds>{handle_time_WRONG}</totalseconds></duration></HandleTime>",
            f"                <HoldTime><duration><totalseconds>{hold}</totalseconds></duration></HoldTime>",
            f"                <!-- acwtime merged above -->",   # BUG 3 vocabulary leak
            f"                <QueueDelayTime><duration><totalseconds>{r['anstime']}</totalseconds></duration></QueueDelayTime>",
            f"                <SvcLvlPct><percentage>{svc}</percentage></SvcLvlPct>",
            f"                <ContactsActive><count>{r['contactsactive']}</count></ContactsActive>",
            "            </QueueData>",
        ]
    out += ["        </QueueNode>", "    </DataSourceNode>", "</HistPlugin>", ""]
    return "\n".join(out)


if __name__ == "__main__":
    with open(sys.argv[1], newline="") as f:
        rows = list(csv.DictReader(f))
    sys.stdout.write(build_xml(rows))

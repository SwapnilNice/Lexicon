"""
Avaya CMS -> NICE WFM Import History XML  (QUEUE report, inbound voice).

REFERENCE implementation: this is what a Lexicon-guided agent should produce.
It obeys guides/inferential/QUEUE_glossary.md and ontology/avaya_cms_dialect.yaml.

Usage:
    python src/transform_queue.py fixtures/avaya_queue_sample.csv > out/Q_060225.0900.xml
"""
import csv
import sys
from xml.sax.saxutils import escape

PERIOD = "PT15M"          # 15-minute intervals
VENDOR = "Avaya"


def _dur(seconds: int) -> str:
    return f"<duration><totalseconds>{int(seconds)}</totalseconds></duration>"


def _cnt(n: int) -> str:
    return f"<count>{int(n)}</count>"


def map_row(r: dict) -> dict:
    """Translate ONE Avaya hsplit interval row into canonical Queue fields.

    Real Avaya CMS hsplit columns (verified against DB Items & Calculations R21):
      acdtime  = TALK time only (does NOT include hold)
      holdtime = time ACD callers were on hold  (separate from acdtime)
      acwtime  = after-call work (separate again)
      acceptable = ACDCALLS answered within SERVICELEVEL
      slvlabns   = abandons within the service level
    """
    acd = int(r["acdcalls"])
    acceptable = int(r["acceptable"])
    abn = int(r["abncalls"])
    abn_ok = int(r["slvlabns"])
    talk = int(r["acdtime"])          # ACDTIME = talk only, excludes hold
    hold = int(r["holdtime"])
    acw = int(r["acwtime"])
    ans = int(r["anstime"])

    return {
        "QueueValue": r["split"],                 # skill/split is the queue key
        "AbandonedShort": abn_ok,
        "AbandonedLong": abn - abn_ok,
        "HandledShort": acceptable,
        "HandledLong": acd - acceptable,
        # GOLDEN RULE: NICE HandleTime = talk + hold. Avaya ACDTIME EXCLUDES hold,
        # so we must ADD holdtime. ACW is NOT included here (it is WorkTime).
        "HandleTime": talk + hold,
        "HoldTime": hold,
        "WorkTime": acw,                          # ACW lives here, on its own
        "QueueDelayTime": ans,                    # ANSTIME = queue+ring wait before answer
        "ContactsActive": int(r["contactsactive"]),
        # SvcLvlPct intentionally OMITTED for inbound voice (WFM derives it).
        # BackLog / RightParty / WrongParty are not applicable to inbound voice.
    }


def build_xml(rows) -> str:
    if not rows:
        raise ValueError("no rows")
    dt = rows[0]["INTERVAL_START"]                # CCYYMMDDThhmm, e.g. 20250602T0900
    out = ['<?xml version="1.0"?>', "<HistPlugin>", "    <DataSourceNode>",
           f"        <Vendor>{escape(VENDOR)}</Vendor>", "        <QueueNode>",
           f"            <TimePeriod><DateTime>{dt}</DateTime><period>{PERIOD}</period></TimePeriod>"]
    for r in rows:
        c = map_row(r)
        out += [
            "            <QueueData>",
            f"                <QueueValue>{escape(str(c['QueueValue']))}</QueueValue>",
            f"                <AbandonedShort>{_cnt(c['AbandonedShort'])}</AbandonedShort>",
            f"                <AbandonedLong>{_cnt(c['AbandonedLong'])}</AbandonedLong>",
            f"                <HandledShort>{_cnt(c['HandledShort'])}</HandledShort>",
            f"                <HandledLong>{_cnt(c['HandledLong'])}</HandledLong>",
            f"                <HandleTime>{_dur(c['HandleTime'])}</HandleTime>",
            f"                <HoldTime>{_dur(c['HoldTime'])}</HoldTime>",
            f"                <WorkTime>{_dur(c['WorkTime'])}</WorkTime>",
            f"                <QueueDelayTime>{_dur(c['QueueDelayTime'])}</QueueDelayTime>",
            f"                <ContactsActive>{_cnt(c['ContactsActive'])}</ContactsActive>",
            "            </QueueData>",
        ]
    out += ["        </QueueNode>", "    </DataSourceNode>", "</HistPlugin>", ""]
    return "\n".join(out)


def transform_csv(path: str) -> str:
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    return build_xml(rows)


if __name__ == "__main__":
    sys.stdout.write(transform_csv(sys.argv[1]))

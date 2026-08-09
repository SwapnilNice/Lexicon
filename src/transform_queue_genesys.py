"""
Genesys Cloud -> NICE WFM Import History XML  (QUEUE report, inbound voice).

REFERENCE implementation. Obeys ontology/genesys_api_dialect.yaml.
Two Genesys-specific rules baked in:
  * durations are MILLISECONDS -> divide by 1000
  * NICE HandleTime EXCLUDES ACW -> use tTalk+tHeld (NOT tHandle, which includes tAcw)

Usage:
    python src/transform_queue_genesys.py fixtures/genesys_queue_sample.json > out.xml
"""
import json
import sys
from xml.sax.saxutils import escape

VENDOR = "Genesys"


def _dur(seconds: int) -> str:
    return f"<duration><totalseconds>{int(seconds)}</totalseconds></duration>"


def _cnt(n: int) -> str:
    return f"<count>{int(n)}</count>"


def ms_to_s(ms: int) -> int:
    return int(round(int(ms) / 1000))


def map_result(res: dict) -> dict:
    m = res["metrics"]
    handled = int(m["nHandled"]); handled_sl = int(m["nHandledWithinSL"])
    aband = int(m["nAbandoned"]); aband_sl = int(m["nAbandonedWithinSL"])
    return {
        "QueueValue": res["queueId"],
        "AbandonedShort": aband_sl,
        "AbandonedLong": aband - aband_sl,
        "HandledShort": handled_sl,
        "HandledLong": handled - handled_sl,
        # HandleTime = talk + hold, in SECONDS. NOT tHandle (which includes ACW).
        "HandleTime": ms_to_s(m["tTalk_ms"] + m["tHeld_ms"]),
        "HoldTime": ms_to_s(m["tHeld_ms"]),
        "WorkTime": ms_to_s(m["tAcw_ms"]),          # ACW on its own
        "QueueDelayTime": ms_to_s(m["tAnswered_ms"]),
        "ContactsActive": int(m["contactsActive"]),
    }


def build_xml(doc: dict) -> str:
    dt = doc["intervalStart"]
    period = doc.get("period", "PT15M")
    out = ['<?xml version="1.0"?>', "<HistPlugin>", "    <DataSourceNode>",
           f"        <Vendor>{escape(VENDOR)}</Vendor>", "        <QueueNode>",
           f"            <TimePeriod><DateTime>{dt}</DateTime><period>{period}</period></TimePeriod>"]
    for res in doc["results"]:
        c = map_result(res)
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


def transform_json(path: str) -> str:
    with open(path) as f:
        return build_xml(json.load(f))


if __name__ == "__main__":
    sys.stdout.write(transform_json(sys.argv[1]))

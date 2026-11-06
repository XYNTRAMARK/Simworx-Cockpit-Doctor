"""SIMWORX Cockpit Doctor v0.5: read-only live X-Plane change detector.
Requires Python 3 and websocket-client. Never opens COM15 or changes MobiFlight.
"""
import csv
import datetime
import json
import queue
import re
import threading
import tkinter as tk
import urllib.request
from tkinter import ttk, filedialog, messagebox

try:
    import websocket
except ImportError:
    websocket = None

REST = "http://127.0.0.1:8086/api/v2/"
WS = "ws://127.0.0.1:8086/api/v2"
FILTERS = {
    "ECU tests": "ecu_test",
    "Engine starters": "starter",
    "Fire test": "fire",
    "Fuel levers and guards": "fuel|xfeed|lock",
    "Gear and lights": "gear|unsafe|annunciator",
    "PTT": "ptt|push_to_talk|transmit",
    "Aerobask (filtered)": "aerobask/",
    "Aviatek (filtered)": "aviatek/",
}

def list_items(resource):
    req = urllib.request.Request(REST + resource, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.load(response).get("data", [])
    if not isinstance(data, list):
        raise ValueError("Unexpected list response: " + resource)
    return [x for x in data if isinstance(x, dict)
            and isinstance(x.get("id"), int) and isinstance(x.get("name"), str)]

class ChangeDetector(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SIMWORX | Cockpit Doctor - Live Change Detective v0.5")
        self.geometry("1100x700")
        self.events = []
        self.mailbox = queue.Queue()
        self.stop_flag = threading.Event()
        self.worker_thread = None
        self.socket = None
        self.connected = False
        self.armed = False
        self.session = 0
        self.render()
        self.after(80, self.flush)
        self.protocol("WM_DELETE_WINDOW", self.shutdown)

    def render(self):
        tk.Label(self, text="SIMWORX / LIVE CHANGE DETECTIVE", font=("Segoe UI", 19, "bold")).pack(anchor="w", padx=14, pady=10)
        tk.Label(self, text="READ-ONLY X-Plane monitor. Does not open Arduino COM ports or edit MobiFlight.").pack(anchor="w", padx=14)
        bar = tk.Frame(self)
        bar.pack(fill="x", padx=14, pady=12)
        tk.Label(bar, text="System").pack(side="left")
        self.category = tk.StringVar(value="ECU tests")
        ttk.Combobox(bar, values=list(FILTERS), textvariable=self.category, state="readonly", width=24).pack(side="left", padx=6)
        tk.Label(bar, text="Extra filter").pack(side="left", padx=8)
        self.filter = tk.StringVar()
        tk.Entry(bar, textvariable=self.filter, width=21).pack(side="left")
        self.connect_btn = tk.Button(bar, text="1 CONNECT", command=self.connect, bg="#235b85", fg="white")
        self.connect_btn.pack(side="left", padx=12)
        self.stop_btn = tk.Button(bar, text="STOP", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left")
        bar2 = tk.Frame(self)
        bar2.pack(fill="x", padx=14, pady=4)
        tk.Label(bar2, text="Physical switch").pack(side="left")
        self.switch_name = tk.StringVar(value="LEFT ECU TEST")
        tk.Entry(bar2, textvariable=self.switch_name, width=26).pack(side="left", padx=8)
        self.arm_btn = tk.Button(bar2, text="2 ARM CAPTURE", command=self.arm, state="disabled", bg="#236c55", fg="white")
        self.arm_btn.pack(side="left", padx=6)
        self.marker_btn = tk.Button(bar2, text="MARK PHYSICAL PRESS", command=self.marker, state="disabled")
        self.marker_btn.pack(side="left", padx=6)
        tk.Button(bar2, text="EXPORT CSV", command=self.export_csv).pack(side="right")
        self.status = tk.StringVar(value="Start X-Plane with the Aerobask DA62 loaded.")
        tk.Label(self, textvariable=self.status, anchor="w").pack(fill="x", padx=14, pady=7)
        container = tk.Frame(self)
        container.pack(fill="both", expand=True, padx=12)
        columns = ("time", "kind", "name", "before", "after", "switch")
        self.tree = ttk.Treeview(container, columns=columns, show="headings")
        for name, width in zip(columns, (110, 85, 475, 110, 110, 170)):
            self.tree.heading(name, text=name.upper())
            self.tree.column(name, width=width, anchor="w")
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        tk.Label(self, text="Use MobiFlight's own input activity/debug log separately to confirm the pin. Events here come from X-Plane only.").pack(anchor="w", padx=14, pady=6)
        self.notes = tk.Text(self, height=7)
        self.notes.pack(fill="x", padx=12, pady=8)
        self.note("Connect, arm, then press and release ONE switch. Watch for matching DataRef or command changes.")
        self.note("IMPORTANT: A switch producing no events may have a broken mapping; it is not proof of a defective Mega.")

    def note(self, message):
        self.notes.insert("end", message + "\n")
        self.notes.see("end")

    def connect(self):
        if websocket is None:
            messagebox.showerror("Dependency required",
                                 "Install once in PowerShell:\npy -3 -m pip install websocket-client")
            return
        if self.worker_thread and self.worker_thread.is_alive():
            return
        self.session += 1
        self.armed = False
        self.stop_flag.clear()
        self.connect_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.arm_btn.config(state="disabled")
        self.status.set("Loading live aircraft DataRefs and commands...")
        category, filter_text = self.category.get(), self.filter.get().lower().strip()
        self.worker_thread = threading.Thread(target=self.listen, args=(self.session, category, filter_text), daemon=True)
        self.worker_thread.start()

    def listen(self, session, category, filter_text):
        sock = None
        try:
            pattern = re.compile(FILTERS[category], re.I)
            def match(item):
                name = item["name"].lower()
                if category == "Aerobask (filtered)":
                    matched = name.startswith("aerobask/")
                elif category == "Aviatek (filtered)":
                    matched = name.startswith("aviatek/")
                else:
                    matched = bool(pattern.search(name))
                return matched and (filter_text in name if filter_text else True)
            refs = [x for x in list_items("datarefs") if match(x)]
            cmds = [x for x in list_items("commands") if match(x)]
            if not refs and not cmds:
                raise RuntimeError("No matching DataRefs or commands. Change system/filter.")
            if len(refs) > 500 or len(cmds) > 400:
                raise RuntimeError(f"Too many matches ({len(refs)} DataRefs / {len(cmds)} commands). Add an extra filter.")
            ref_names = {str(x["id"]): x["name"] for x in refs}
            cmd_names = {str(x["id"]): x["name"] for x in cmds}
            sock = websocket.create_connection(WS, timeout=10, http_proxy_host=None)
            self.socket = sock
            rid = 1
            for collection, msg_type, key in ((refs, "dataref_subscribe_values", "datarefs"), (cmds, "command_subscribe_is_active", "commands")):
                for start in range(0, len(collection), 100):
                    payload = {"req_id": rid, "type": msg_type,
                               "params": {key: [{"id": x["id"]} for x in collection[start:start+100]]}}
                    sock.send(json.dumps(payload))
                    rid += 1
            self.mailbox.put((session, "connected", f"Watching {len(refs)} DataRefs and {len(cmds)} commands."))
            sock.settimeout(1.0)
            seen_refs, seen_cmds = set(), set()
            previous = {}
            while not self.stop_flag.is_set():
                try:
                    packet = sock.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if not packet:
                    break
                message = json.loads(packet)
                kind = message.get("type")
                if kind == "result" and message.get("success") is False:
                    raise RuntimeError("Subscription rejected: " + str(message.get("error_message", message)))
                if kind not in ("dataref_update_values", "command_update_is_active"):
                    continue
                payload = message.get("data", {})
                if not isinstance(payload, dict):
                    continue
                is_ref = kind == "dataref_update_values"
                names = ref_names if is_ref else cmd_names
                seen = seen_refs if is_ref else seen_cmds
                label = "DataRef" if is_ref else "Command"
                for identifier, value in payload.items():
                    identifier = str(identifier).strip()
                    name = names.get(identifier)
                    if not name:
                        continue
                    key = (label, name)
                    first = identifier not in seen
                    before = previous.get(key)
                    seen.add(identifier)
                    previous[key] = value
                    if first or before == value or not self.armed:
                        continue
                    self.mailbox.put((session, "event", (label, name, before, value)))
        except Exception as exc:
            self.mailbox.put((session, "error", str(exc)))
        finally:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
            self.mailbox.put((session, "stopped", None))

    def arm(self):
        if self.connected:
            self.armed = True
            self.marker_btn.config(state="normal")
            self.note("ARMED: operate " + (self.switch_name.get().strip() or "selected switch") + " now.")

    def marker(self):
        self.add_event("Operator", "Physical press/release marked", "", "")

    def add_event(self, kind, name, old, new):
        timestamp = datetime.datetime.now().isoformat(timespec="milliseconds")
        def fmt(v):
            return json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
        row = (timestamp, kind, name, fmt(old), fmt(new), self.switch_name.get().strip())
        self.events.append(row)
        self.tree.insert("", "end", values=(timestamp[11:], *row[1:]))
        if len(self.tree.get_children()) > 1000:
            self.tree.delete(self.tree.get_children()[0])
        self.tree.yview_moveto(1)
        self.status.set(f"Captured {len(self.events)} events")

    def flush(self):
        for _ in range(200):
            try:
                session, typ, data = self.mailbox.get_nowait()
            except queue.Empty:
                break
            if session != self.session:
                continue
            if typ == "connected":
                self.connected = True
                self.arm_btn.config(state="normal")
                self.status.set(data)
                self.note(data)
            elif typ == "event":
                self.add_event(*data)
            elif typ == "error":
                self.status.set("Error: " + data)
                self.note("ERROR: " + data)
            elif typ == "stopped":
                self.connected = False
                self.armed = False
                self.arm_btn.config(state="disabled")
                self.marker_btn.config(state="disabled")
                self.stop_btn.config(state="disabled")
                self.connect_btn.config(state="normal")
        self.after(80, self.flush)

    def stop(self):
        self.stop_flag.set()
        self.armed = False
        self.arm_btn.config(state="disabled")
        self.marker_btn.config(state="disabled")
        self.status.set("Stopping...")
        sock = self.socket
        if sock:
            try:
                sock.close()
            except Exception:
                pass
        self.socket = None

    def export_csv(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                 initialfile="DA62_Switch_Events.csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as output:
            writer = csv.writer(output)
            writer.writerow(("Timestamp", "Source", "Name", "Before", "After", "Physical switch label"))
            writer.writerows(self.events)
        self.note("Exported: " + path)

    def shutdown(self):
        self.stop()
        self.destroy()

if __name__ == "__main__":
    ChangeDetector().mainloop()

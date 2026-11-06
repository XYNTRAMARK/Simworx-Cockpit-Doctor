"""SIMWORX Cockpit Doctor v0.3 — audit and explicitly confirmed X-Plane command tests.
Standard-library only. Does not write to MobiFlight or aircraft files.
"""
import csv
import json
import threading
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

API = "http://127.0.0.1:8086/api/v2/"

def web_json(url):
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.load(response)

def entries(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", payload.get("items", []))
    if isinstance(data, dict):
        return data.get("data", data.get("items", []))
    return data if isinstance(data, list) else []

class Doctor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SIMWORX | Cockpit Doctor v0.3")
        self.geometry("1170x720")
        self.configure(bg="#142235")
        self.rows = []
        self.hardware = {}
        self.commands = []
        self.datarefs = []
        self.command_ids = {}
        self.scan_ok = False
        self.busy = False
        self.bench = None

        tk.Label(self, text="SIMWORX / COCKPIT DOCTOR", bg="#142235", fg="white",
                 font=("Segoe UI", 20, "bold")).pack(anchor="w", padx=14, pady=(12, 3))
        tk.Label(self, text="DA62 MobiFlight audit and X-Plane live test bench", bg="#142235",
                 fg="#bed3e8").pack(anchor="w", padx=14)
        toolbar = tk.Frame(self, bg="#142235")
        toolbar.pack(fill="x", padx=12, pady=12)
        actions = [
            ("1 Load MobiFlight project", self.load_project),
            ("2 Load controller pins", self.load_hardware),
            ("3 Load DA62 ZIP", self.load_zip),
            ("4 Scan live X-Plane", self.scan),
            ("Export audit CSV", self.export_audit),
            ("Export live JSON", self.export_live),
            ("5 LIVE TEST BENCH", self.open_bench),
        ]
        for label, action in actions:
            tk.Button(toolbar, text=label, command=action, bg="#254668", fg="white",
                      padx=6, pady=7).pack(side="left", padx=2)
        self.status = tk.StringVar(value="Load a project or scan your running DA62.")
        tk.Label(self, textvariable=self.status, bg="#142235", fg="#bed3e8",
                 anchor="w").pack(fill="x", padx=14, pady=(0, 8))
        search = tk.Frame(self, bg="#142235")
        search.pack(fill="x", padx=14)
        tk.Label(search, text="Filter:", bg="#142235", fg="white").pack(side="left")
        self.filter_text = tk.StringVar()
        self.filter_text.trace_add("write", lambda *_: self.show_rows())
        tk.Entry(search, textvariable=self.filter_text, width=38).pack(side="left", padx=8)
        self.filter_kind = tk.StringVar(value="All")
        widget = ttk.Combobox(search, textvariable=self.filter_kind, state="readonly",
                              values=["All", "vJoy", "Missing DataRef", "Disabled", "Input", "Output"], width=22)
        widget.pack(side="left")
        widget.bind("<<ComboboxSelected>>", lambda *_: self.show_rows())
        holder = tk.Frame(self)
        holder.pack(fill="both", expand=True, padx=14, pady=8)
        cols = ("kind", "name", "pin", "action", "issue")
        self.table = ttk.Treeview(holder, columns=cols, show="headings")
        for col, width in zip(cols, [80, 215, 65, 510, 240]):
            self.table.heading(col, text=col.title())
            self.table.column(col, width=width, anchor="w")
        scrollbar = ttk.Scrollbar(holder, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.detail = tk.Text(self, height=5, bg="#f0f4fa", wrap="word")
        self.detail.pack(fill="x", padx=14, pady=(0, 12))
        self.table.bind("<<TreeviewSelect>>", self.show_detail)

    def refresh_status(self):
        message = (f"{len(self.rows)} mappings | "
                   f"{sum('vJoy' in row[4] for row in self.rows)} vJoy dependencies | "
                   f"{sum('Missing DataRef' in row[4] for row in self.rows)} missing DataRefs | "
                   f"{len(self.hardware)} hardware definitions")
        if self.scan_ok:
            message += f" | LIVE: {len(self.datarefs)} DataRefs, {len(self.commands)} commands"
        self.status.set(message)

    def load_project(self):
        path = filedialog.askopenfilename(filetypes=[("MobiFlight project", "*.mfproj")])
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            rows = []
            for cfg in data.get("ConfigFiles", []):
                for item in cfg.get("ConfigItems", []):
                    kind = "Input" if item.get("Type") == "InputConfigItem" else "Output"
                    name = item.get("Name", "")
                    device = (item.get("Device") or {}).get("Name", "")
                    if kind == "Output":
                        ref = ((item.get("Source") or {}).get("XplaneDataRef") or {}).get("Path", "")
                        mapping = ref or "(none)"
                        issue = "Missing DataRef" if not ref else ""
                    else:
                        parts = []
                        vjoy = False
                        for label in ("onPress", "onRelease", "onHold", "onLongRelease"):
                            action = (item.get("button") or {}).get(label) or {}
                            if not action:
                                continue
                            typ = str(action.get("Type", ""))
                            if "VJoy" in typ:
                                vjoy = True
                                detail = f"vJoy {action.get('vJoyID')} button {action.get('buttonNr')}"
                            else:
                                detail = str(action.get("XplaneCommand") or action.get("Command") or
                                             action.get("XplaneDataRef") or typ)
                            parts.append(f"{label}: {detail}")
                        mapping = " | ".join(parts) or "(no action)"
                        issue = "vJoy dependency" if vjoy else ("No action" if not parts else "")
                    if item.get("Active", True) is False:
                        issue += ("; " if issue else "") + "Disabled"
                    rows.append([kind, name, "", mapping, issue, device, item])
            self.rows = rows
            self.assign_pins()
        except Exception as error:
            messagebox.showerror("Project read error", str(error))

    def load_hardware(self):
        path = filedialog.askopenfilename(filetypes=[("MobiFlight hardware", "*.mfmc")])
        if not path:
            return
        try:
            root = ET.parse(path).getroot()
            self.hardware = {}
            for item in root.iter():
                if item.tag.lower() in ("button", "output", "encoder"):
                    key = (item.attrib.get("Name", "").strip().lower(), item.tag.lower())
                    self.hardware[key] = item.attrib.get("Pin", item.attrib.get("pin", ""))
            self.assign_pins()
        except Exception as error:
            messagebox.showerror("Hardware read error", str(error))

    def assign_pins(self):
        for row in self.rows:
            device = (row[6].get("Device") or {}).get("Name", "").strip().lower()
            row[2] = self.hardware.get((device, "button" if row[0] == "Input" else "output"), "—")
        self.show_rows()
        self.refresh_status()

    def load_zip(self):
        path = filedialog.askopenfilename(filetypes=[("Aircraft ZIP", "*.zip")])
        if not path:
            return
        try:
            with zipfile.ZipFile(path) as zipped:
                names = zipped.namelist()
            messagebox.showinfo("Aircraft scan", f"{len(names)} entries; "
                                f"{sum(p.endswith('.secured') for p in names)} protected files.\n"
                                "No aircraft file was modified.")
        except Exception as error:
            messagebox.showerror("Aircraft ZIP error", str(error))

    def show_rows(self):
        self.table.delete(*self.table.get_children())
        query = self.filter_text.get().lower()
        filter_kind = self.filter_kind.get()
        for index, row in enumerate(self.rows):
            if query not in " ".join(map(str, row[:5])).lower():
                continue
            if filter_kind == "vJoy" and "vJoy" not in row[4]:
                continue
            if filter_kind == "Missing DataRef" and "Missing DataRef" not in row[4]:
                continue
            if filter_kind == "Disabled" and "Disabled" not in row[4]:
                continue
            if filter_kind in ("Input", "Output") and filter_kind != row[0]:
                continue
            self.table.insert("", "end", iid=str(index), values=row[:5])

    def show_detail(self, _event=None):
        selection = self.table.selection()
        if not selection:
            return
        row = self.rows[int(selection[0])]
        self.detail.delete("1.0", "end")
        self.detail.insert("end", json.dumps(row[6], indent=2))

    def scan(self):
        if self.busy:
            return
        self.status.set("Scanning local X-Plane API (read-only)...")
        self.busy = True
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        try:
            raw_refs = entries(web_json(API + "datarefs"))
            raw_cmds = entries(web_json(API + "commands"))
            refs = sorted({i["name"] for i in raw_refs if isinstance(i, dict) and i.get("name")})
            cmds = sorted({i["name"] for i in raw_cmds if isinstance(i, dict) and i.get("name")})
            ids = {i["name"]: i["id"] for i in raw_cmds if isinstance(i, dict) and
                   i.get("name") and isinstance(i.get("id"), int)}
            self.after(0, lambda: self._scan_success(refs, cmds, ids))
        except Exception as error:
            text = str(error)
            self.after(0, lambda: self._scan_failure(text))

    def _scan_success(self, refs, cmds, ids):
        self.busy = False
        self.datarefs, self.commands, self.command_ids = refs, cmds, ids
        self.scan_ok = True
        self.refresh_status()
        self.update_bench()
        messagebox.showinfo("X-Plane scan", f"Found {len(refs)} DataRefs and "
                            f"{len(cmds)} commands. Open LIVE TEST BENCH to browse them.")

    def _scan_failure(self, error):
        self.busy = False
        self.status.set("Live scan failed; offline audit remains available.")
        messagebox.showerror("X-Plane scan failed", error)

    def export_audit(self):
        if not self.rows:
            return messagebox.showinfo("Nothing to export", "Load a project first.")
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                 initialfile="DA62_Cockpit_Doctor_Audit.csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Type", "Control", "Hardware Pin", "Action or DataRef", "Audit", "Device"])
            for row in self.rows:
                writer.writerow(row[:6])
        messagebox.showinfo("Exported", "Audit CSV saved.")

    def export_live(self):
        if not self.scan_ok:
            return messagebox.showinfo("Nothing to export", "Scan live X-Plane first.")
        path = filedialog.asksaveasfilename(defaultextension=".json",
                 initialfile="DA62_Live_XPlane_Inventory.json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        Path(path).write_text(json.dumps({"source": API, "datarefs": self.datarefs,
                                         "commands": self.commands}, indent=2), encoding="utf-8")
        messagebox.showinfo("Exported", "Live inventory saved.")

    def open_bench(self):
        if self.bench and self.bench.winfo_exists():
            self.bench.lift()
            return
        self.bench = tk.Toplevel(self)
        self.bench.title("SIMWORX | Live X-Plane Command Test Bench")
        self.bench.geometry("1050x720")
        self.bench.configure(bg="#142235")
        tk.Label(self.bench, text="LIVE COMMAND TEST BENCH",
                 font=("Segoe UI", 18, "bold"), bg="#142235", fg="white").pack(
                 anchor="w", padx=14, pady=12)
        tk.Label(self.bench, text="Tests affect the simulated aircraft. MobiFlight mappings remain unchanged.",
                 bg="#142235", fg="#bed3e8").pack(anchor="w", padx=14)
        controls = tk.Frame(self.bench, bg="#142235")
        controls.pack(fill="x", padx=14, pady=10)
        tk.Label(controls, text="Search commands:", bg="#142235", fg="white").pack(side="left")
        self.bench_query = tk.StringVar(value="aerobask/")
        self.bench_query.trace_add("write", lambda *_: self.update_bench())
        tk.Entry(controls, textvariable=self.bench_query, width=48).pack(side="left", padx=8)
        tk.Button(controls, text="Refresh scan", command=self.scan).pack(side="left")
        self.match_count = tk.StringVar()
        tk.Label(controls, textvariable=self.match_count, bg="#142235",
                 fg="white").pack(side="left", padx=12)
        holder = tk.Frame(self.bench)
        holder.pack(fill="both", expand=True, padx=14, pady=6)
        self.bench_table = ttk.Treeview(holder, columns=("name", "id"), show="headings")
        self.bench_table.heading("name", text="Command name")
        self.bench_table.heading("id", text="Session ID")
        self.bench_table.column("name", width=750)
        self.bench_table.column("id", width=120)
        scroll = ttk.Scrollbar(holder, command=self.bench_table.yview)
        self.bench_table.configure(yscrollcommand=scroll.set)
        self.bench_table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        actionbar = tk.Frame(self.bench, bg="#142235")
        actionbar.pack(fill="x", padx=14, pady=9)
        tk.Label(actionbar, text="Activation:", bg="#142235", fg="white").pack(side="left")
        self.duration = tk.StringVar(value="0 (tap)")
        ttk.Combobox(actionbar, textvariable=self.duration,
                     values=["0 (tap)", "0.1 seconds", "0.25 seconds",
                             "0.5 seconds", "1.0 seconds"], state="readonly",
                     width=18).pack(side="left", padx=8)
        self.test_button = tk.Button(actionbar, text="TEST SELECTED COMMAND",
                                     command=self.test_command, bg="#285f8f", fg="white")
        self.test_button.pack(side="left", padx=8)
        self.bench_log = tk.Text(self.bench, height=9, bg="#f0f4fa")
        self.bench_log.pack(fill="x", padx=14, pady=(0, 12))
        self.bench_log.insert("end", "No command sent. Test only while parked.\n")
        self.update_bench()

    def update_bench(self):
        if not self.bench or not self.bench.winfo_exists():
            return
        self.bench_table.delete(*self.bench_table.get_children())
        query = self.bench_query.get().strip().lower()
        matches = [name for name in self.commands if query in name.lower()]
        for name in matches[:2000]:
            self.bench_table.insert("", "end", values=(name, self.command_ids.get(name, "—")))
        self.match_count.set(f"{len(matches)} matches")

    def test_command(self):
        selected = self.bench_table.selection()
        if not selected:
            return messagebox.showinfo("Select command", "Select a command to test.",
                                       parent=self.bench)
        if not self.scan_ok or self.busy:
            return messagebox.showwarning("Scan required", "Scan X-Plane before testing.",
                                          parent=self.bench)
        name = self.bench_table.item(selected[0], "values")[0]
        seconds = float(self.duration.get().split()[0])
        question = (f"Send {name} to X-Plane?\n\nDuration: {seconds} seconds\n\n"
                    "This may activate simulated engines, controls or aircraft systems.")
        if not messagebox.askyesno("Confirm simulator command", question, parent=self.bench):
            return
        self.busy = True
        self.test_button.config(state="disabled")
        self.bench_log.insert("end", f"Checking current command ID: {name}\n")
        threading.Thread(target=self._command_worker, args=(name, seconds), daemon=True).start()

    def _command_worker(self, name, seconds):
        try:
            query = urllib.parse.urlencode({"filter[name]": name})
            candidates = entries(web_json(API + "commands?" + query))
            matches = [item for item in candidates if isinstance(item, dict) and
                       item.get("name") == name and isinstance(item.get("id"), int)]
            if len(matches) != 1:
                raise ValueError("Unique command ID not found. Rescan X-Plane.")
            cid = matches[0]["id"]
            url = API + f"command/{cid}/activate"
            data = json.dumps({"duration": seconds}).encode("utf-8")
            request = urllib.request.Request(url, data=data, method="POST", headers={
                "Content-Type": "application/json", "Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=10) as response:
                code = response.status
            result = (f"HTTP {code}: X-Plane accepted {name}. "
                      "Check the cockpit to verify the actual effect.")
        except Exception as error:
            result = f"FAILED {name}: {error}"
        self.after(0, lambda: self._command_done(result))

    def _command_done(self, result):
        self.busy = False
        if self.bench and self.bench.winfo_exists():
            self.test_button.config(state="normal")
            self.bench_log.insert("end", result + "\n")
            self.bench_log.see("end")

if __name__ == "__main__":
    Doctor().mainloop()

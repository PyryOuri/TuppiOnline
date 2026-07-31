#!/usr/bin/env python3
"""tuppi_gui_client_multi_v3.py

LAN client GUI for a single remote seat (P1/P2/P3).

Protocol expectations (from host):
- Client sends: {"type":"hello","seat":<1..3>}
- Host replies: {"type":"hello_ack","ok":true/false,...}
- Host pushes: {"type":"state", ...}
- Host requests actions: {"type":"request","kind":"show"|"play", ...}
- Client responds: {"type":"response",...}

Improvements vs earlier versions:
- --seat is optional; if omitted, shows a seat picker.
- Network connect/handshake runs in a background thread so the Tk window doesn't appear frozen.
"""

from __future__ import annotations

import argparse
import json
import socket
import threading
from typing import List, Optional, Dict

import tkinter as tk
from tkinter import messagebox

import tuppi_emulator_v9 as eng


# --- UI theme (match host look) ---
FELT_BG = "#0b5a2a"
TEXT_FG = "white"
CARD_BG = "#ffffff"
CARD_FG_BLACK = "#111111"
CARD_FG_RED = "#b00020"

def _normalize_banned(banned_list):
    """Host should send banned ranks (2..14). Some older variants may send card ids.
    Return a set of ranks (2..14).

    Defensive behavior:
    - If we receive something that *looks* like card ids (0..51), convert via eng.card_rank.
    - If we end up with an implausibly-large banned set (e.g. 10+ ranks), fall back to the
      engine's default {2,11,12,13}. This prevents a protocol mismatch from greying out every card.
    """
    try:
        vals = [int(x) for x in (banned_list or [])]
    except Exception:
        vals = []
        for x in (banned_list or []):
            try:
                vals.append(int(x))
            except Exception:
                pass

    ranks: set[int]
    if any(v > 14 for v in vals):
        # Treat as card ids
        ranks = {eng.card_rank(int(v)) for v in vals}
    else:
        ranks = set(vals)

    # If host accidentally sent a whole-deck list or similar, we'd ban almost all ranks.
    # That is almost certainly a protocol mismatch; fall back to standard rules.
    if len(ranks) >= 8:
        return {2, 11, 12, 13}
    return ranks


def _card_text(c):
    # Engine naming differs across versions
    try:
        if hasattr(eng, 'card_to_str') and callable(getattr(eng, 'card_to_str')):
            return eng.card_to_str(c)
        if hasattr(eng, 'card_str') and callable(getattr(eng, 'card_str')):
            return eng.card_str(c)
    except Exception:
        # Fall back below
        pass
    return str(c)
def _send_json(conn: socket.socket, obj: dict) -> None:
    data = (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")
    conn.sendall(data)


def _recv_line(sock_file) -> Optional[str]:
    line = sock_file.readline()
    if not line:
        return None
    return line.rstrip("\n")


class ClientGUI:
    def __init__(self, root: tk.Tk, host: str, port: int, seat: Optional[int]):
        self.root = root
        self.host = host
        self.port = port
        self.seat: Optional[int] = seat

        self.conn: Optional[socket.socket] = None
        self.file = None
        self.reader_thread: Optional[threading.Thread] = None

        # State
        self.hand: List[int] = []
        self.banned = set()
        self.legal: List[int] = []
        self.pending_kind: Optional[str] = None  # "show" or "play"
        self.turn: Optional[int] = None
        self.pub: Dict = {}

        # UI (themed to match host)
        root.configure(bg=FELT_BG)

        # Fonts
        self.f_status = ("Helvetica", 18, "bold")
        self.f_score = ("Helvetica", 16, "bold")
        self.f_trick = ("Helvetica", 18, "bold")
        self.f_trick_detail = ("Helvetica", 14)
        self.f_hand = ("Helvetica", 16, "bold")
        self.f_card = ("Helvetica", 16, "bold")

        self.lbl_status = tk.Label(root, text="Not connected", anchor="w",
                                   bg=FELT_BG, fg=TEXT_FG, font=self.f_status)
        self.lbl_status.pack(fill=tk.X, padx=14, pady=(14, 2))

        self.lbl_score = tk.Label(root, text="", anchor="w",
                                  bg=FELT_BG, fg=TEXT_FG, font=self.f_score)
        self.lbl_score.pack(fill=tk.X, padx=14, pady=(0, 10))

        self.lbl_trick = tk.Label(root, text="", anchor="w",
                                  bg=FELT_BG, fg=TEXT_FG, font=self.f_trick)
        self.lbl_trick.pack(fill=tk.X, padx=14, pady=(0, 2))

        self.lbl_trick_detail = tk.Label(root, text="", anchor="w", justify="left",
                                         bg=FELT_BG, fg=TEXT_FG, font=self.f_trick_detail)
        self.lbl_trick_detail.pack(fill=tk.X, padx=14, pady=(0, 12))

        self.table = tk.Frame(root, bg=FELT_BG)
        self.table.pack(fill=tk.X, padx=10, pady=(0, 10))
        self.lbl_played = {}
        for s in range(4):
            row = tk.Frame(self.table, bg=FELT_BG)
            row.pack(fill=tk.X)
            tk.Label(row, text=f"P{s}:", width=4, anchor="w", bg=FELT_BG, fg=TEXT_FG, font=self.f_trick_detail).pack(side=tk.LEFT)
            lbl = tk.Label(row, text="-", anchor="w", bg=FELT_BG, fg=TEXT_FG, font=self.f_trick_detail)
            lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.lbl_played[s] = lbl

        self.lbl_hand = tk.Label(root, text="Your hand:", anchor="w", bg=FELT_BG, fg=TEXT_FG, font=self.f_hand)
        self.lbl_hand.pack(fill=tk.X, padx=10, pady=(0, 4))

        self.hand_frame = tk.Frame(root, bg=FELT_BG)
        self.hand_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.btns: List[tk.Button] = []

        # SHOW overlay
        self.overlay: Optional[tk.Toplevel] = None

        # Start flow
        if self.seat is None:
            self._pick_seat_then_connect()
        else:
            self._start_connect_async()

    # ---------------- Seat selection + connection ----------------

    def _pick_seat_then_connect(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Choose seat")
        dlg.transient(self.root)
        dlg.grab_set()

        tk.Label(dlg, text="Choose your seat:", pady=10).pack()

        btnrow = tk.Frame(dlg)
        btnrow.pack(padx=10, pady=10)

        def choose(s: int):
            self.seat = s
            try:
                dlg.grab_release()
                dlg.destroy()
            except Exception:
                pass
            self._start_connect_async()

        for s in (1, 2, 3):
            tk.Button(btnrow, text=f"P{s}", width=6, command=lambda ss=s: choose(ss)).pack(side=tk.LEFT, padx=6)

        def cancel():
            try:
                dlg.grab_release()
                dlg.destroy()
            except Exception:
                pass
            self.root.destroy()

        tk.Button(dlg, text="Cancel", command=cancel).pack(pady=(0, 10))

    def _start_connect_async(self):
        assert self.seat in (1, 2, 3)
        self.root.title(f"Tuppi Client P{self.seat}")
        self.lbl_status.config(text=f"Connecting to {self.host}:{self.port} as P{self.seat}...")

        t = threading.Thread(target=self._connect_and_handshake, daemon=True)
        t.start()

    def _connect_and_handshake(self):
        try:
            conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            conn.settimeout(5.0)
            conn.connect((self.host, self.port))
            # After connect, make blocking again for stream reads
            conn.settimeout(None)
            sock_file = conn.makefile("r", encoding="utf-8", newline="\n")

            _send_json(conn, {"type": "hello", "seat": int(self.seat)})
            line = _recv_line(sock_file)
            if line is None:
                raise RuntimeError("No response from host")
            msg = json.loads(line)
            if not msg.get("ok", False):
                raise RuntimeError(msg.get("error", "hello rejected"))

            # success -> install and start reader
            self.conn = conn
            self.file = sock_file

            self.root.after(0, lambda: self.lbl_status.config(
                text=f"Connected as P{self.seat} to {self.host}:{self.port}"
            ))

            self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self.reader_thread.start()

        except Exception as e:
            self.root.after(0, lambda: self._fail_connect(str(e)))

    def _fail_connect(self, err: str):
        messagebox.showerror("Connection failed", err)
        self.root.destroy()

    def _reader_loop(self):
        try:
            while True:
                line = _recv_line(self.file)
                if line is None:
                    break
                try:
                    msg = json.loads(line)
                except Exception:
                    continue
                self.root.after(0, lambda m=msg: self._on_msg(m))
        finally:
            self.root.after(0, self._on_disconnect)

    def _on_disconnect(self):
        messagebox.showwarning("Disconnected", "Lost connection to host.")
        self.root.destroy()

    # ---------------- Message handling ----------------

    def _on_msg(self, msg: dict):
        t = msg.get("type")
        if t == "state":
            ui = msg.get("ui", {})
            self.lbl_status.config(text=ui.get("status", ""))
            self.lbl_score.config(text=ui.get("score", ""))
            self.lbl_trick.config(text=ui.get("trick", ""))
            self.lbl_trick_detail.config(text=ui.get("trick_detail", ""))

            self.hand = list(msg.get("hand", []))
            self.banned = _normalize_banned(msg.get("banned", []))
            self.turn = msg.get("turn", None)
            self.pub = msg.get("pub", {}) or {}

            played = self.pub.get("played_cards", []) or []
            last_by_seat = {s: None for s in range(4)}
            for (s, c) in played:
                try:
                    last_by_seat[int(s)] = int(c)
                except Exception:
                    continue
            for s in range(4):
                c = last_by_seat[s]
                self.lbl_played[s].config(text=_card_text(c) if c is not None else "-")

            # If we are not currently being asked for an action, show hand disabled.
            if self.pending_kind is None:
                self._render_hand(disable_all=True)

        elif t == "request":
            kind = msg.get("kind")
            self.pending_kind = kind

            if kind == "show":
                # SHOW bid (nolo/rami) selection
                self.hand = list(msg.get("hand", []))
                self.banned = _normalize_banned(msg.get("banned", []))
                try:
                    legal_cnt = sum(
                        1 for c in self.hand
                        if eng.card_rank(int(c)) not in self.banned
                    )
                    print(f"[client] SHOW request: banned={sorted(self.banned)} legal_show_cards={legal_cnt} hand_size={len(self.hand)}")
                except Exception as e:
                    print(f"[client] SHOW request debug failed: {e}")
                self._show_overlay()

            elif kind == "play":
                # Normal trick play
                self.hand = list(msg.get("hand", []))
                self.legal = list(msg.get("legal", []))
                self._hide_overlay()
                self._render_hand(disable_all=False, legal=set(self.legal))

            else:
                # Unknown request kind
                pass

        # ---------------- UI rendering ----------------


    def _render_hand(self, disable_all: bool, legal: Optional[set] = None):
        for b in self.btns:
            try:
                b.destroy()
            except Exception:
                pass
        self.btns.clear()

        cards = sorted(self.hand, key=lambda c: (eng.card_suit(c), eng.card_rank(c)))
        for c in cards:
            txt = _card_text(c)
            state = tk.NORMAL
            if disable_all:
                state = tk.DISABLED
            elif legal is not None and c not in legal:
                state = tk.DISABLED
            fg = CARD_FG_RED if eng.card_suit(c) in (1,2) else CARD_FG_BLACK
            btn = tk.Button(self.hand_frame, text=txt, command=lambda cc=c: self._send_play(cc),
                            font=self.f_card, bg=CARD_BG, fg=fg, relief="raised", bd=2, padx=10, pady=6)
            btn.config(state=state)
            btn.pack(side=tk.LEFT, padx=3, pady=3)
            self.btns.append(btn)

    def _show_overlay(self):
        self._hide_overlay()
        self._render_hand(disable_all=True)

        ov = tk.Toplevel(self.root)
        ov.title("SHOW Bid")
        ov.configure(bg=FELT_BG)
        ov.transient(self.root)
        ov.grab_set()
        self.overlay = ov

        tk.Label(ov,
                 text="Choose SHOW card (red = RAMI, black = NOLO), or use a verbal bid:",
                 pady=10, bg=FELT_BG, fg=TEXT_FG, font=self.f_hand).pack(fill=tk.X)

        suits = {0: [], 1: [], 2: [], 3: []}
        for c in self.hand:
            suits[eng.card_suit(c)].append(c)

        for s in range(4):
            row = tk.Frame(ov, bg=FELT_BG)
            row.pack(padx=8, pady=4, fill=tk.X)
            tk.Label(row, text=eng.SUITS[s], width=2, anchor="w", bg=FELT_BG, fg=TEXT_FG, font=self.f_hand).pack(side=tk.LEFT, padx=(0,6))
            for c in sorted(suits[s], key=eng.card_rank):
                r = eng.card_rank(c)
                # Host semantics: red suits => RAMI, black suits => NOLO
                choice = "RAMI" if s in (1, 2) else "NOLO"
                fg = CARD_FG_RED if s in (1,2) else CARD_FG_BLACK
                btn = tk.Button(row, text=_card_text(c), font=self.f_card, bg=CARD_BG, fg=fg,
                                relief="raised", bd=2, padx=10, pady=6,
                                command=lambda cc=c, ch=choice: self._send_show(ch, cc))
                if r in self.banned:
                    btn.config(state=tk.DISABLED)
                btn.pack(side=tk.LEFT, padx=3)

        row2 = tk.Frame(ov, bg=FELT_BG)
        row2.pack(pady=10)
        tk.Button(row2, text="Verbal RAMI", font=self.f_hand, bg="#145c31", fg=TEXT_FG, padx=14, pady=8,
                 command=lambda: self._send_show("RAMI", None)).pack(side=tk.LEFT, padx=8)
        tk.Button(row2, text="Verbal NOLO", font=self.f_hand, bg="#145c31", fg=TEXT_FG, padx=14, pady=8,
                 command=lambda: self._send_show("NOLO", None)).pack(side=tk.LEFT, padx=8)

    def _hide_overlay(self):
        if self.overlay is not None:
            try:
                self.overlay.grab_release()
                self.overlay.destroy()
            except Exception:
                pass
            self.overlay = None

    # ---------------- Sending responses ----------------

    def _send_show(self, choice: str, card: Optional[int]):
        if not self.conn:
            return
        self._hide_overlay()
        try:
            _send_json(
                self.conn,
                {"type": "response", "kind": "show", "seat": int(self.seat), "choice": choice, "card": card},
            )
        except Exception:
            pass
        self.pending_kind = None

    def _send_play(self, card: int):
        if not self.conn:
            return
        try:
            _send_json(self.conn, {"type": "response", "kind": "play", "seat": int(self.seat), "card": card})
        except Exception:
            pass
        # Disable until host sends next request/state
        self.pending_kind = None
        self._render_hand(disable_all=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=50007)
    ap.add_argument("--seat", type=int, choices=[1, 2, 3], required=False)
    args = ap.parse_args()

    root = tk.Tk()
    root.title("Tuppi Client")
    ClientGUI(root, host=args.host, port=args.port, seat=args.seat)
    root.mainloop()


if __name__ == "__main__":
    main()
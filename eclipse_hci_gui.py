#!/usr/bin/env python3
"""
Clear-Com Eclipse HCI Controller
Windows用 tkinter GUI アプリ
対象: Eclipse HX + MVX-A16 + VI-PNLB-12R

プロトコル仕様 (hci_demo フォルダより解析):
  - TCP/IP 接続 (デフォルト 192.168.0.150:6553)
  - バイナリ big-endian メッセージ
  - START=0x5A0F / END=0x2E8D / MAGIC=0xABBACEDE
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import socket
import struct
import threading
import binascii
import datetime

# ─────────────────────────────────────────────────────────────
#  HCI プロトコル定数
# ─────────────────────────────────────────────────────────────
HCI_START  = 0x5A0F        # 23055
HCI_END    = 0x2E8D        # 11917
HCI_MAGIC  = 0xABBACEDE    # 2881146590
HCI_FLAGS  = 8             # H2C_FLAG
HCI_SCHEMA = 1

MSG_XPT_ACTION   = 17
MSG_KEY_ASSIGN   = 235
MSG_ALIAS_ASCII  = 129
MSG_KEY_AUTO_UPD = 318

# サポートdB値 (HCI仕様より)
DB_LEVELS = [18, 15, 12, 9, 6, 5, 4, 3, 2, 1, 0,
             -1, -2, -3, -4, -5, -6, -7, -8, -9, -10,
             -12, -14, -16, -20, -35, -45, -72]

# dB → ゲインバイト変換 (customKeysExample.py より: 0dB=129, ~13/dB)
def db_to_gain(db: int) -> int:
    table = {
        18: 255, 15: 246, 12: 233,  9: 220,  6: 207,
         5: 194,  4: 181,  3: 168,  2: 155,  1: 142,
         0: 129, -1: 116, -2: 103, -3:  90, -4:  77,
        -5:  64, -6:  51, -7:  38, -8:  25, -9:  12,
       -10:   0,
    }
    # 表にない値は線形補間
    if db in table:
        return table[db]
    closest = min(table.keys(), key=lambda k: abs(k - db))
    return table[closest]

# ─────────────────────────────────────────────────────────────
#  メッセージビルダ
# ─────────────────────────────────────────────────────────────

def build_xpt_action(xpts: list, direction: bool = True, enable: bool = True) -> bytes:
    """
    クロスポイント制御メッセージ (MSG_ID=17)
    xpts: [(src, dst), ...] 1-based ポート番号
    direction: True=Make(接続) / False=Break(切断)
    enable: True=有効 / False=禁止
    """
    struct_str = '>3HBIBH'
    count = len(xpts)
    action_type = 1
    word_list = []

    for src, dst in xpts:
        bit0 = 9216       # 固定マスク (manual p.40)
        bit3 = 1018       # 固定マスク
        priority = 3
        dir_bit    = int(direction)
        enable_bit = int(not enable)

        dst_hi = dst >> 8
        src_hi = src >> 8
        dst_lo = dst & 0xFF
        src_lo = src & 0xFF

        w0 = bit0 + dir_bit + (dst_hi << 1) + (src_hi << 8)
        w1 = (src_lo << 8) + dst_lo
        w2 = 0
        w3 = bit3 + (enable_bit << 11) + (priority << 13)

        word_list.append(action_type)
        word_list.extend([w0, w1, w2, w3])
        struct_str += '5H'

    struct_str += 'H'
    s = struct.Struct(struct_str)
    size = s.size
    header = (HCI_START, size, MSG_XPT_ACTION, HCI_FLAGS, HCI_MAGIC, HCI_SCHEMA, count)
    return s.pack(*(header + tuple(word_list) + (HCI_END,)))


def build_xpt_level(src: int, dst: int, db: int) -> bytes:
    """
    クロスポイントレベル制御メッセージ (MSG_ID=17, action_type=2)
    MVX-A16 クロスポイントのゲイン設定
    gain値を w2 ワードに格納
    """
    struct_str = '>3HBIBH5HH'
    action_type = 2   # レベル制御タイプ
    gain = db_to_gain(db)
    priority = 3

    dst_hi = dst >> 8
    src_hi = src >> 8
    dst_lo = dst & 0xFF
    src_lo = src & 0xFF

    w0 = 9216 + 1 + (dst_hi << 1) + (src_hi << 8)
    w1 = (src_lo << 8) + dst_lo
    w2 = gain           # ゲインバイト
    w3 = 1018 + (priority << 13)

    s = struct.Struct(struct_str)
    size = s.size
    header = (HCI_START, size, MSG_XPT_ACTION, HCI_FLAGS, HCI_MAGIC, HCI_SCHEMA, 1)
    return s.pack(*(header + (action_type, w0, w1, w2, w3) + (HCI_END,)))


def build_key_assign(panel_port: int, actions: list) -> bytes:
    """
    VI-PNLB-12R キーアサインメッセージ (MSG_ID=235)
    panel_port: 1-based パネルポート番号
    actions: list of dict {region, page, key, entity_type, entity_sys, entity_number, key_activation}
    entity_type: 1=Port, 2=Conference, 3=FixedGroup, 4=IFB
    key_activation: 1=Talk, 2=Listen, 3=Talk+Listen
    """
    target = panel_port - 1   # 0-based に変換
    struct_str = '>3HBI2B2H'
    assignment_type = 1
    latch_mode = 0
    count = len(actions)
    data_list = []

    for a in actions:
        data_list.extend([a['region'], a['page'], a['key']])
        data_list.extend([0, 0])                              # reserved
        data_list.extend([a['entity_type'], a['entity_sys']])
        data_list.append(0)                                   # reserved
        data_list.extend([a['entity_number'], a['key_activation'], latch_mode])
        struct_str += '8BH2B'

    struct_str += 'H'
    s = struct.Struct(struct_str)
    size = s.size
    header = (HCI_START, size, MSG_KEY_ASSIGN, HCI_FLAGS, HCI_MAGIC, HCI_SCHEMA,
              assignment_type, count, target)
    return s.pack(*(header + tuple(data_list) + (HCI_END,)))


def build_enable_auto_update() -> bytes:
    """キー状態自動更新有効化メッセージ (MSG_ID=318)"""
    msg = [MSG_KEY_AUTO_UPD, HCI_FLAGS, HCI_MAGIC, HCI_SCHEMA, 0, 495, 1]
    s = struct.Struct('!H h h b I b H H b h')
    values = (HCI_START, s.size, msg[0], msg[1], msg[2], msg[3],
              msg[4], msg[5], msg[6], HCI_END)
    return s.pack(*values)


# ─────────────────────────────────────────────────────────────
#  HCI TCP クライアント (スレッドセーフ)
# ─────────────────────────────────────────────────────────────

class HCIClient:
    def __init__(self, log_cb):
        self._sock: socket.socket | None = None
        self._connected = False
        self._running = False
        self._log = log_cb
        self._lock = threading.Lock()

    @property
    def connected(self):
        return self._connected

    def connect(self, ip: str, port: int) -> bool:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((ip, port))
            sock.settimeout(2)
            with self._lock:
                self._sock = sock
                self._connected = True
                self._running = True
            t = threading.Thread(target=self._recv_loop, daemon=True)
            t.start()
            self._log(f"✅ 接続成功: {ip}:{port}")
            return True
        except Exception as e:
            self._log(f"❌ 接続失敗: {e}")
            return False

    def disconnect(self):
        self._running = False
        self._connected = False
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
        self._log("🔌 切断しました")

    def send(self, data: bytes) -> bool:
        with self._lock:
            if not self._connected or self._sock is None:
                self._log("⚠️  未接続です")
                return False
            try:
                self._sock.send(data)
                hex_str = binascii.hexlify(data).decode()
                self._log(f"📤 送信({len(data)}bytes): {hex_str}")
                return True
            except Exception as e:
                self._log(f"❌ 送信エラー: {e}")
                self._connected = False
                return False

    def _recv_loop(self):
        while self._running:
            try:
                with self._lock:
                    sock = self._sock
                if sock is None:
                    break
                data = sock.recv(2048)
                if not data:
                    break
                hex_str = binascii.hexlify(data).decode()
                msg_id = struct.unpack_from('>H', data, 4)[0] if len(data) >= 6 else 0
                self._log(f"📥 受信(MsgID={msg_id}, {len(data)}bytes): {hex_str}")
            except socket.timeout:
                continue
            except Exception:
                break
        if self._running:
            self._connected = False
            self._log("⚠️  接続が切断されました")


# ─────────────────────────────────────────────────────────────
#  GUI アプリケーション
# ─────────────────────────────────────────────────────────────

class EclipseHCIApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Clear-Com Eclipse HCI Controller")
        self.root.geometry("860x740")
        self.root.resizable(True, True)

        self._client = HCIClient(self._log)

        self._build_connection_frame()
        self._build_notebook()
        self._build_log_frame()

    # ── ログ ────────────────────────────────────────────────

    def _log(self, msg: str):
        """スレッドセーフなログ出力"""
        self.root.after(0, lambda m=msg: self._append_log(m))

    def _append_log(self, msg: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_text.config(state='normal')
        self.log_text.insert('end', f"[{ts}] {msg}\n")
        self.log_text.see('end')
        self.log_text.config(state='disabled')

    # ── 接続フレーム ────────────────────────────────────────

    def _build_connection_frame(self):
        f = ttk.LabelFrame(self.root, text="接続設定", padding=8)
        f.pack(fill='x', padx=10, pady=(8, 4))

        ttk.Label(f, text="Matrix IP:").grid(row=0, column=0, sticky='e', padx=4)
        self._ip = tk.StringVar(value="192.168.0.150")
        ttk.Entry(f, textvariable=self._ip, width=16).grid(row=0, column=1, padx=4)

        ttk.Label(f, text="Port:").grid(row=0, column=2, sticky='e', padx=4)
        self._port = tk.StringVar(value="6553")
        ttk.Entry(f, textvariable=self._port, width=8).grid(row=0, column=3, padx=4)

        self._conn_btn = ttk.Button(f, text="接 続", width=10, command=self._toggle_connect)
        self._conn_btn.grid(row=0, column=4, padx=10)

        self._status_var = tk.StringVar(value="● 未接続")
        self._status_lbl = ttk.Label(f, textvariable=self._status_var,
                                     foreground='red', font=('', 10, 'bold'))
        self._status_lbl.grid(row=0, column=5, padx=8)

    def _toggle_connect(self):
        if self._client.connected:
            self._client.disconnect()
            self._conn_btn.config(text="接 続")
            self._status_var.set("● 未接続")
            self._status_lbl.config(foreground='red')
        else:
            ip = self._ip.get().strip()
            try:
                port = int(self._port.get())
            except ValueError:
                messagebox.showerror("エラー", "ポート番号が不正です")
                return
            self._conn_btn.config(text="接続中...", state='disabled')

            def do_connect():
                ok = self._client.connect(ip, port)
                def update():
                    self._conn_btn.config(state='normal')
                    if ok:
                        self._conn_btn.config(text="切 断")
                        self._status_var.set("● 接続中")
                        self._status_lbl.config(foreground='green')
                    else:
                        self._conn_btn.config(text="接 続")
                        self._status_var.set("● 未接続")
                        self._status_lbl.config(foreground='red')
                self.root.after(0, update)

            threading.Thread(target=do_connect, daemon=True).start()

    # ── ノートブック ────────────────────────────────────────

    def _build_notebook(self):
        self._nb = ttk.Notebook(self.root)
        self._nb.pack(fill='both', expand=True, padx=10, pady=4)
        self._build_xpt_tab()
        self._build_level_tab()
        self._build_keyassign_tab()

    # ── Tab 1: クロスポイント制御 ────────────────────────────

    def _build_xpt_tab(self):
        tab = ttk.Frame(self._nb, padding=12)
        self._nb.add(tab, text="  クロスポイント制御  ")

        # 単独設定
        single = ttk.LabelFrame(tab, text="単独クロスポイント", padding=8)
        single.pack(fill='x', pady=4)

        ttk.Label(single, text="送り元ポート (Source):").grid(row=0, column=0, sticky='e', padx=6, pady=4)
        self._xpt_src = tk.IntVar(value=1)
        ttk.Spinbox(single, from_=1, to=496, textvariable=self._xpt_src,
                    width=7, font=('', 11)).grid(row=0, column=1, sticky='w', padx=4)

        ttk.Label(single, text="受けポート (Destination):").grid(row=1, column=0, sticky='e', padx=6, pady=4)
        self._xpt_dst = tk.IntVar(value=2)
        ttk.Spinbox(single, from_=1, to=496, textvariable=self._xpt_dst,
                    width=7, font=('', 11)).grid(row=1, column=1, sticky='w', padx=4)

        ttk.Label(single, text="操作:").grid(row=2, column=0, sticky='e', padx=6, pady=4)
        self._xpt_dir = tk.BooleanVar(value=True)
        rf = ttk.Frame(single)
        rf.grid(row=2, column=1, sticky='w')
        ttk.Radiobutton(rf, text="Make (接続)", variable=self._xpt_dir,
                        value=True).pack(side='left', padx=4)
        ttk.Radiobutton(rf, text="Break (切断)", variable=self._xpt_dir,
                        value=False).pack(side='left', padx=4)

        ttk.Button(single, text="送 信", width=14,
                   command=self._send_xpt).grid(row=3, column=0, columnspan=2, pady=8)

        # 一括設定
        batch = ttk.LabelFrame(tab, text="一括クロスポイント設定", padding=8)
        batch.pack(fill='x', pady=8)

        ttk.Label(batch, text="ペア入力 (例: 1>2, 3>4, 5>6):").grid(
            row=0, column=0, sticky='w', padx=4, columnspan=3)
        self._xpt_batch = tk.StringVar(value="1>2, 3>4")
        ttk.Entry(batch, textvariable=self._xpt_batch, width=36,
                  font=('Courier', 10)).grid(row=1, column=0, columnspan=2, sticky='w', padx=4, pady=4)

        bf = ttk.Frame(batch)
        bf.grid(row=2, column=0, columnspan=3, sticky='w', pady=4)
        ttk.Button(bf, text="一括 Make",  width=14,
                   command=lambda: self._send_xpt_batch(True)).pack(side='left', padx=4)
        ttk.Button(bf, text="一括 Break", width=14,
                   command=lambda: self._send_xpt_batch(False)).pack(side='left', padx=4)

    def _send_xpt(self):
        src = self._xpt_src.get()
        dst = self._xpt_dst.get()
        direction = self._xpt_dir.get()
        data = build_xpt_action([(src, dst)], direction=direction)
        label = "Make" if direction else "Break"
        self._log(f"XPT {label}: {src} → {dst}")
        self._client.send(data)

    def _send_xpt_batch(self, direction: bool):
        text = self._xpt_batch.get()
        pairs = []
        for part in text.split(','):
            part = part.strip()
            if '>' in part:
                try:
                    s, d = part.split('>', 1)
                    pairs.append((int(s.strip()), int(d.strip())))
                except ValueError:
                    pass
        if not pairs:
            messagebox.showwarning("入力エラー", "形式: 1>2, 3>4 のように入力してください")
            return
        data = build_xpt_action(pairs, direction=direction)
        label = "Make" if direction else "Break"
        self._log(f"一括 XPT {label}: {pairs}")
        self._client.send(data)

    # ── Tab 2: レベル制御 (MVX-A16) ─────────────────────────

    def _build_level_tab(self):
        tab = ttk.Frame(self._nb, padding=12)
        self._nb.add(tab, text="  レベル制御 (MVX-A16)  ")

        ctrl = ttk.LabelFrame(tab, text="クロスポイントレベル設定", padding=10)
        ctrl.pack(fill='x', pady=4)

        ttk.Label(ctrl, text="送り元ポート (Source):").grid(row=0, column=0, sticky='e', padx=6, pady=4)
        self._lvl_src = tk.IntVar(value=1)
        ttk.Spinbox(ctrl, from_=1, to=496, textvariable=self._lvl_src,
                    width=7, font=('', 11)).grid(row=0, column=1, sticky='w', padx=4)

        ttk.Label(ctrl, text="受けポート (Destination):").grid(row=1, column=0, sticky='e', padx=6, pady=4)
        self._lvl_dst = tk.IntVar(value=2)
        ttk.Spinbox(ctrl, from_=1, to=496, textvariable=self._lvl_dst,
                    width=7, font=('', 11)).grid(row=1, column=1, sticky='w', padx=4)

        ttk.Label(ctrl, text="レベル (dB):").grid(row=2, column=0, sticky='e', padx=6, pady=4)
        self._lvl_db = tk.StringVar(value="0")
        db_strs = [str(v) for v in DB_LEVELS]
        cb = ttk.Combobox(ctrl, textvariable=self._lvl_db, values=db_strs,
                          width=8, state='readonly', font=('', 11))
        cb.grid(row=2, column=1, sticky='w', padx=4)
        cb.bind('<<ComboboxSelected>>', self._on_db_combo)

        # スライダー
        ttk.Label(ctrl, text="スライダー:").grid(row=3, column=0, sticky='e', padx=6, pady=4)
        self._lvl_slider = ttk.Scale(ctrl, from_=0, to=len(DB_LEVELS)-1,
                                     orient='horizontal', length=320,
                                     command=self._on_slider)
        self._lvl_slider.set(DB_LEVELS.index(0))
        self._lvl_slider.grid(row=3, column=1, columnspan=2, sticky='w', padx=4)

        # dB 表示ラベル
        self._lvl_label = ttk.Label(ctrl, text="0 dB", font=('', 14, 'bold'), foreground='navy')
        self._lvl_label.grid(row=2, column=2, padx=12)

        # ゲインバイト表示
        self._gain_label = ttk.Label(ctrl, text="gain byte: 129", foreground='gray')
        self._gain_label.grid(row=3, column=2, padx=12)

        ttk.Button(ctrl, text="レベル設定送信", width=16,
                   command=self._send_level).grid(row=4, column=0, columnspan=3, pady=10)

        note = ttk.Label(tab,
            text="※ MVX-A16 クロスポイントごとのゲイン設定\n"
                 "  サポートdB値: +18 〜 -72 dB\n"
                 "  gain byte: 0dB=129, +1dB≈142, -1dB≈116 (≈13/dB)",
            justify='left', foreground='gray')
        note.pack(anchor='w', pady=8)

    def _on_slider(self, val):
        idx = int(float(val))
        idx = max(0, min(idx, len(DB_LEVELS) - 1))
        db = DB_LEVELS[idx]
        self._lvl_db.set(str(db))
        self._update_level_display(db)

    def _on_db_combo(self, _event=None):
        try:
            db = int(self._lvl_db.get())
            if db in DB_LEVELS:
                self._lvl_slider.set(DB_LEVELS.index(db))
            self._update_level_display(db)
        except ValueError:
            pass

    def _update_level_display(self, db: int):
        self._lvl_label.config(text=f"{db:+d} dB" if db != 0 else "0 dB")
        gain = db_to_gain(db)
        self._gain_label.config(text=f"gain byte: {gain} (0x{gain:02X})")

    def _send_level(self):
        src = self._lvl_src.get()
        dst = self._lvl_dst.get()
        try:
            db = int(self._lvl_db.get())
        except ValueError:
            messagebox.showerror("エラー", "dB値が不正です")
            return
        gain = db_to_gain(db)
        data = build_xpt_level(src, dst, db)
        self._log(f"Level: {src}→{dst} = {db:+d}dB (gain={gain}/0x{gain:02X})")
        self._client.send(data)

    # ── Tab 3: VI-PNLB-12R キーアサイン ─────────────────────

    def _build_keyassign_tab(self):
        tab = ttk.Frame(self._nb, padding=10)
        self._nb.add(tab, text="  VI-PNLB-12R キーアサイン  ")

        # パネル設定
        psf = ttk.LabelFrame(tab, text="パネル設定", padding=8)
        psf.pack(fill='x', pady=4)

        ttk.Label(psf, text="パネルポート:").grid(row=0, column=0, sticky='e', padx=4)
        self._panel_port = tk.IntVar(value=1)
        ttk.Spinbox(psf, from_=1, to=496, textvariable=self._panel_port,
                    width=6).grid(row=0, column=1, sticky='w', padx=4)

        ttk.Label(psf, text="リージョン:").grid(row=0, column=2, sticky='e', padx=4)
        self._panel_region = tk.IntVar(value=1)
        ttk.Spinbox(psf, from_=1, to=16, textvariable=self._panel_region,
                    width=5).grid(row=0, column=3, sticky='w', padx=4)

        ttk.Label(psf, text="ページ:").grid(row=0, column=4, sticky='e', padx=4)
        self._panel_page = tk.IntVar(value=0)
        ttk.Spinbox(psf, from_=0, to=15, textvariable=self._panel_page,
                    width=5).grid(row=0, column=5, sticky='w', padx=4)

        ttk.Label(psf, text="エンティティ System:").grid(row=0, column=6, sticky='e', padx=4)
        self._panel_sys = tk.IntVar(value=6)
        ttk.Spinbox(psf, from_=1, to=16, textvariable=self._panel_sys,
                    width=5).grid(row=0, column=7, sticky='w', padx=4)

        # 12キーグリッド
        kf = ttk.LabelFrame(tab, text="12キー設定 (Key 0〜11)", padding=6)
        kf.pack(fill='both', expand=True, pady=4)

        headers = ["キー", "エンティティ種別", "ポート番号", "アクション"]
        widths  = [4, 20, 9, 17]
        for col, (h, w) in enumerate(zip(headers, widths)):
            ttk.Label(kf, text=h, font=('', 9, 'bold'), width=w,
                      anchor='center').grid(row=0, column=col, padx=2, pady=2)

        ENTITY_TYPES = ["Port (ポート)", "Conference (会議)",
                        "Fixed Group (固定グループ)", "IFB"]
        ACTIVATIONS  = ["Talk (送話)", "Listen (受話)", "Talk+Listen (双方向)"]

        self._key_vars = []
        for k in range(12):
            row = k + 1
            ttk.Label(kf, text=f"Key {k:2d}", anchor='center').grid(
                row=row, column=0, padx=2, pady=1)

            etype = tk.StringVar(value="Port (ポート)")
            ttk.Combobox(kf, textvariable=etype, values=ENTITY_TYPES,
                         width=20, state='readonly').grid(row=row, column=1, padx=2, pady=1)

            portnum = tk.IntVar(value=k + 1)
            ttk.Spinbox(kf, from_=1, to=496, textvariable=portnum,
                        width=7).grid(row=row, column=2, padx=2, pady=1)

            act = tk.StringVar(value="Talk (送話)")
            ttk.Combobox(kf, textvariable=act, values=ACTIVATIONS,
                         width=17, state='readonly').grid(row=row, column=3, padx=2, pady=1)

            self._key_vars.append((etype, portnum, act))

        # ロータリー情報
        rot_frame = ttk.LabelFrame(tab, text="ロータリー (Rotary Encoder)", padding=6)
        rot_frame.pack(fill='x', pady=4)
        ttk.Label(rot_frame,
                  text="VI-PNLB-12R のロータリーエンコーダーは各キーに対応した個人ゲイン調整を行います。\n"
                       "HCI経由でのロータリー制御は「レベル制御」タブの XPT Level 設定を使用してください。",
                  foreground='#555').pack(anchor='w')

        # 送信ボタン
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(pady=6)
        ttk.Button(btn_frame, text="全キーアサイン送信", width=20,
                   command=self._send_all_keys).pack(side='left', padx=6)
        ttk.Button(btn_frame, text="選択キーのみ送信", width=20,
                   command=self._send_selected_key).pack(side='left', padx=6)

        self._selected_key = tk.IntVar(value=0)
        ttk.Label(btn_frame, text="対象キー:").pack(side='left', padx=4)
        ttk.Spinbox(btn_frame, from_=0, to=11, textvariable=self._selected_key,
                    width=4).pack(side='left')

    def _make_actions(self, key_indices=None) -> list:
        region = self._panel_region.get()
        page   = self._panel_page.get()
        sys_no = self._panel_sys.get()
        EMAP = {"Port (ポート)": 1, "Conference (会議)": 2,
                "Fixed Group (固定グループ)": 3, "IFB": 4}
        AMAP = {"Talk (送話)": 1, "Listen (受話)": 2, "Talk+Listen (双方向)": 3}

        actions = []
        indices = key_indices if key_indices is not None else range(12)
        for k in indices:
            etype, portnum, act = self._key_vars[k]
            actions.append({
                'region':          region,
                'page':            page,
                'key':             k,
                'entity_type':     EMAP.get(etype.get(), 1),
                'entity_sys':      sys_no,
                'entity_number':   portnum.get(),
                'key_activation':  AMAP.get(act.get(), 1),
            })
        return actions

    def _send_all_keys(self):
        panel   = self._panel_port.get()
        actions = self._make_actions()
        data    = build_key_assign(panel, actions)
        self._log(f"キーアサイン送信: パネル={panel}, {len(actions)}キー全送信")
        self._client.send(data)

    def _send_selected_key(self):
        panel  = self._panel_port.get()
        k      = self._selected_key.get()
        actions = self._make_actions([k])
        data   = build_key_assign(panel, actions)
        etype, portnum, act = self._key_vars[k]
        self._log(f"キーアサイン送信: パネル={panel}, Key{k} → Port {portnum.get()} ({act.get()})")
        self._client.send(data)

    # ── ログエリア ──────────────────────────────────────────

    def _build_log_frame(self):
        lf = ttk.LabelFrame(self.root, text="通信ログ", padding=4)
        lf.pack(fill='x', padx=10, pady=(0, 8))

        self.log_text = scrolledtext.ScrolledText(
            lf, height=8, state='disabled',
            font=('Courier New', 8), bg='#1e1e1e', fg='#d4d4d4',
            insertbackground='white')
        self.log_text.pack(fill='x')

        ttk.Button(lf, text="ログクリア", command=self._clear_log).pack(anchor='e', pady=2)

    def _clear_log(self):
        self.log_text.config(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.config(state='disabled')


# ─────────────────────────────────────────────────────────────
#  エントリーポイント
# ─────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()
    root.tk.call('tk', 'scaling', 1.2)   # Windows高DPI対応
    app = EclipseHCIApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app._client.disconnect(), root.destroy()))
    root.mainloop()


if __name__ == '__main__':
    main()

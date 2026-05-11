#!/usr/bin/env python3
"""Clear-Com Eclipse HCI Controller v2"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import socket, struct, threading, binascii, datetime

# ── HCI定数 ──────────────────────────────────────────
HCI_START  = 0x5A0F
HCI_END    = 0x2E8D
HCI_MAGIC  = 0xABBACEDE
HCI_FLAGS  = 8
HCI_SCHEMA = 1
MSG_XPT    = 17
MSG_LVL    = 38   # Request Crosspoint Level Actions (0x0026), Reply=MSG_40(0x0028)
MSG_KEYS   = 235
MSG_AUTO   = 318
MSG_KEVT   = 321

DB_LEVELS = [18,15,12,9,6,5,4,3,2,1,0,-1,-2,-3,
             -4,-5,-6,-7,-8,-9,-10,-12,-14,-16,-20,-35,-45,-72]

def db_to_level(db):
    """dB to HCI level code: Appendix A: level = round(204 + dB/0.355). 0=Cut."""
    lvl = round(204 + db / 0.355)
    return max(1, min(287, lvl))  # 1=-72dB, 204=0dB, 287=+29dB; use 0 for Cut

# ── メッセージビルダ ──────────────────────────────────
def build_xpt(xpts, direction=True, enable=True, gain=0):
    ss = '>3HBIBH'
    wl = []
    for src, dst in xpts:
        dh,dl,sh,sl = dst>>8,dst&0xFF,src>>8,src&0xFF
        wl += [1, 9216+int(direction)+(dh<<1)+(sh<<8),
               (sl<<8)+dl, gain & 0xFFFF, 1018+(int(not enable)<<11)+(3<<13)]
        ss += '5H'
    ss += 'H'
    s = struct.Struct(ss)
    return s.pack(HCI_START,s.size,MSG_XPT,HCI_FLAGS,HCI_MAGIC,
                  HCI_SCHEMA,len(xpts),*wl,HCI_END)

def build_level(src, dst, db, method='direct'):
    dh,dl,sh,sl = dst>>8,dst&0xFF,src>>8,src&0xFF
    s = struct.Struct('>3HBIBH5HH')
    if method == 'x10':
        gain = (db * 10) & 0xFFFF
    elif method == 'ehx':   # MSG_40観測値から: 0dB=128, +2dB=210 → 128+dB*41
        gain = 128 + db * 41
        gain = max(1, min(0xFFFF, gain))  # 下限1(無音回避), 上限65535
    else:
        gain = db & 0xFFFF
    return s.pack(HCI_START,s.size,MSG_LVL,HCI_FLAGS,HCI_MAGIC,HCI_SCHEMA,
                  1,1,9216+1+(dh<<1)+(sh<<8),(sl<<8)+dl,gain,1018+(3<<13),HCI_END)

def build_level_simple(src, dst, level):
    # MSG_38 (0x0026): Count(2)+Dst(2)+Src(2)+Level(2)
    s = struct.Struct('>3HBIBHHHHH')
    return s.pack(HCI_START, s.size, MSG_LVL, HCI_FLAGS, HCI_MAGIC, HCI_SCHEMA,
                  1, dst, src, level & 0x1FF, HCI_END)

def build_level_simple_reversed(src, dst, level):
    s = struct.Struct('>3HBIBHHHHH')
    return s.pack(HCI_START, s.size, MSG_LVL, HCI_FLAGS, HCI_MAGIC, HCI_SCHEMA,
                  1, src, dst, level & 0x1FF, HCI_END)

def build_key_assign(panel, actions):
    ss = '>3HBI2B2H'
    dl = []
    for a in actions:
        dl += [a['region'],a['page'],a['key'],0,0,
               a['etype'],a['sys'],0,a['port'],a['act'],0]
        ss += '8BH2B'
    ss += 'H'
    s = struct.Struct(ss)
    return s.pack(HCI_START,s.size,MSG_KEYS,HCI_FLAGS,HCI_MAGIC,
                  HCI_SCHEMA,1,len(actions),panel-1,*dl,HCI_END)

def build_auto_update():
    s = struct.Struct('!HhHbIbHHbh')
    return s.pack(HCI_START,s.size,MSG_AUTO,HCI_FLAGS,HCI_MAGIC,
                  HCI_SCHEMA,0,495,1,HCI_END)

# ── HCI クライアント ──────────────────────────────────
class HCIClient:
    def __init__(self, log_cb):
        self._sock = None
        self._on  = False
        self._run = False
        self._log = log_cb
        self._lk  = threading.Lock()
        self._key_cb = None
        self._rot_cb = None
        self._rot_last_pos = None

    @property
    def connected(self): return self._on
    def set_key_cb(self, cb): self._key_cb = cb
    def set_rot_cb(self, cb): self._rot_cb = cb

    def connect(self, ip, port):
        try:
            s = socket.socket()
            s.settimeout(5); s.connect((ip,port)); s.settimeout(2)
            with self._lk:
                self._sock=s; self._on=True; self._run=True
            threading.Thread(target=self._loop, daemon=True).start()
            self._log(f"✅ 接続: {ip}:{port}"); return True
        except Exception as e:
            self._log(f"❌ {e}"); return False

    def disconnect(self):
        self._run=False; self._on=False
        with self._lk:
            if self._sock:
                try: self._sock.close()
                except: pass
                self._sock=None
        self._log("🔌 切断")

    def send(self, data):
        with self._lk:
            if not self._on or not self._sock:
                self._log("⚠️ 未接続"); return False
            try:
                self._sock.send(data)
                self._log(f"📤 {len(data)}B {binascii.hexlify(data).decode()}")
                return True
            except Exception as e:
                self._log(f"❌ {e}"); self._on=False; return False

    def _loop(self):
        while self._run:
            try:
                with self._lk: s=self._sock
                if not s: break
                data=s.recv(2048)
                if not data: break
                if len(data)>=6:
                    mid=struct.unpack_from('>H',data,4)[0]
                    self._log(f"📥 ID={mid} {len(data)}B {binascii.hexlify(data).decode()}")
                    if mid==16 and len(data)>=29:
                        self._parse_xpt_reply(data)
                    elif mid==40:
                        payload = data[12:-2]
                        if len(payload) >= 4:
                            cnt = struct.unpack_from('>H', payload, 0)[0]
                            if len(payload) >= 4 + cnt * 4:
                                dst_p = struct.unpack_from('>H', payload, 2)[0]
                                parts = []
                                for i in range(cnt):
                                    sp, lv = struct.unpack_from('>HH', payload, 4 + i*4)
                                    db_val = (lv - 204) * 0.355
                                    parts.append(f"Src=Port{sp+1} lv=0x{lv:03X}({db_val:+.1f}dB)")
                                info = ' '.join(parts) if parts else "(no HCI adjustments)"
                                self._log(f"  MSG_40 Level Status: Dst=Port{dst_p+1} count={cnt} {info}")
                            else:
                                self._log(f"  MSG_40({len(payload)}B): {binascii.hexlify(payload).decode()}")
                        else:
                            self._log(f"  MSG_40({len(payload)}B): {binascii.hexlify(payload).decode()}")
                    elif mid == 363 and len(data) >= 22:
                        self._dispatch_rot363(data)
                    if mid==MSG_KEVT and self._key_cb and len(data)>13:
                        self._dispatch(data)
            except socket.timeout: continue
            except: break
        if self._run: self._on=False; self._log("⚠️ 切断")

    def _parse_xpt_reply(self, data):
        try:
            count = struct.unpack_from('>H', data, 12)[0]
            for i in range(count):
                base = 14 + i * 14
                if base + 14 > len(data): break
                act_type  = struct.unpack_from('>H', data, base + 4)[0]
                word2     = struct.unpack_from('>H', data, base + 6)[0]
                word3     = struct.unpack_from('>H', data, base + 8)[0]
                info      = data[base + 12]
                direction = "Make" if word2 & 1 else "Break"
                src = (word3 >> 8) + 1
                dst = (word3 & 0xFF) + 1
                status = "✅ OK" if info == 0 else f"❌ ERR({info})"
                self._log(f"  XPT Reply: {direction} Port{src}→Port{dst} {status}")
        except Exception as e:
            self._log(f"  XPT Reply parse error: {e}")

    def _dispatch_rot363(self, data):
        try:
            panel_port = data[13] + 1  # 0-indexed → 1-indexed
            new_pos = data[20]
            self._log(f"  MSG_363 (ignored): Panel=Port{panel_port} byte20={new_pos}")
            if self._rot_cb and self._rot_last_pos is not None:
                delta = new_pos - self._rot_last_pos
                if delta > 127: delta -= 256    # wrap CCW (255→0 etc.)
                elif delta < -127: delta += 256  # wrap CW
                if delta != 0:
                    self._rot_cb(panel_port, 1 if delta > 0 else -1)
            self._rot_last_pos = new_pos
        except Exception as e:
            self._log(f"  MSG_363 parse error: {e}")

    def _dispatch(self, data):
        try:
            schema,count=data[11],data[12]
            if schema!=1: return
            off=13
            for _ in range(count):
                if off+6>len(data): break
                p,r,pg,k,st=struct.unpack_from('!hbbbb',data,off)
                self._key_cb(p,r,pg,k,st); off+=6
        except Exception as e:
            self._log(f"⚠️ キー解析エラー: {e}")

# ── メインアプリ ──────────────────────────────────────
EMAP={"Port":1,"Conference":2,"Fixed Group":3,"IFB":4}

class App:
    def __init__(self, root):
        self.root=root
        root.title("EHX Crosspoint Controller")
        root.geometry("900x800"); root.resizable(True,True)
        self._cli=HCIClient(self._log)
        self._cli.set_key_cb(self._on_key)
        self._cur_db=0
        self._presets=[]
        self._sel_preset=None
        self._preset_lbs=[]
        self._assigns=[None]*12
        self._kbtns=[]
        self._key_states={}
        self._build_conn()
        self._build_nb()
        self._build_log()

    def _log(self,msg):
        self.root.after(0,lambda m=msg:self._alog(m))
    def _alog(self,msg):
        ts=datetime.datetime.now().strftime("%H:%M:%S")
        self.ltxt.config(state='normal')
        self.ltxt.insert('end',f"[{ts}] {msg}\n")
        self.ltxt.see('end'); self.ltxt.config(state='disabled')

    def _build_conn(self):
        f=ttk.LabelFrame(self.root,text="接続設定",padding=8)
        f.pack(fill='x',padx=10,pady=(8,4))
        ttk.Label(f,text="Matrix IP:").grid(row=0,column=0,sticky='e',padx=4)
        self._ip=tk.StringVar(value="192.168.0.150")
        ttk.Entry(f,textvariable=self._ip,width=16).grid(row=0,column=1,padx=4)
        ttk.Label(f,text="Port:").grid(row=0,column=2,sticky='e',padx=4)
        self._pt=tk.StringVar(value="52003")
        ttk.Entry(f,textvariable=self._pt,width=8).grid(row=0,column=3,padx=4)
        self._cbtn=ttk.Button(f,text="接 続",width=10,command=self._toggle)
        self._cbtn.grid(row=0,column=4,padx=10)
        self._sv=tk.StringVar(value="● 未接続")
        self._sl=ttk.Label(f,textvariable=self._sv,foreground='red',font=('',10,'bold'))
        self._sl.grid(row=0,column=5,padx=8)

    def _toggle(self):
        if self._cli.connected:
            self._cli.disconnect()
            self._cbtn.config(text="接 続")
            self._sv.set("● 未接続"); self._sl.config(foreground='red')
        else:
            ip=self._ip.get().strip()
            try: port=int(self._pt.get())
            except: messagebox.showerror("エラー","ポート番号が不正"); return
            self._cbtn.config(text="接続中…",state='disabled')
            def _do():
                ok=self._cli.connect(ip,port)
                def _up():
                    self._cbtn.config(state='normal')
                    if ok:
                        self._cbtn.config(text="切 断")
                        self._sv.set("● 接続中"); self._sl.config(foreground='green')
                    else:
                        self._cbtn.config(text="接 続")
                        self._sv.set("● 未接続"); self._sl.config(foreground='red')
                self.root.after(0,_up)
            threading.Thread(target=_do,daemon=True).start()

    def _build_nb(self):
        self._nb=ttk.Notebook(self.root)
        self._nb.pack(fill='both',expand=True,padx=10,pady=4)
        self._tab_xpt()
        self._tab_rot()
        self._tab_key()

    def _tab_xpt(self):
        tab=ttk.Frame(self._nb,padding=12)
        self._nb.add(tab,text="  クロスポイント制御  ")
        sg=ttk.LabelFrame(tab,text="単独クロスポイント",padding=8)
        sg.pack(fill='x',pady=4)
        ttk.Label(sg,text="From Port:").grid(row=0,column=0,sticky='e',padx=6,pady=4)
        self._xs=tk.IntVar(value=1)
        ttk.Spinbox(sg,from_=1,to=496,textvariable=self._xs,width=7,
                    font=('',11)).grid(row=0,column=1,sticky='w')
        ttk.Label(sg,text="To Port:").grid(row=1,column=0,sticky='e',padx=6,pady=4)
        self._xd=tk.IntVar(value=2)
        ttk.Spinbox(sg,from_=1,to=496,textvariable=self._xd,width=7,
                    font=('',11)).grid(row=1,column=1,sticky='w')
        self._xdir=tk.IntVar(value=1)
        rf=ttk.Frame(sg); rf.grid(row=2,column=1,sticky='w')
        ttk.Radiobutton(rf,text="Make", variable=self._xdir,value=1).pack(side='left',padx=4)
        ttk.Radiobutton(rf,text="Break",variable=self._xdir,value=0).pack(side='left',padx=4)
        ttk.Button(sg,text="送 信",width=12,
                   command=self._send_xpt).grid(row=3,column=0,columnspan=2,pady=8)
        bg=ttk.LabelFrame(tab,text="一括 (例: 1>2, 3>4)",padding=8)
        bg.pack(fill='x',pady=8)
        self._xb=tk.StringVar(value="1>2, 3>4")
        ttk.Entry(bg,textvariable=self._xb,width=36).pack(side='left',padx=4)
        ttk.Button(bg,text="Make", width=8,
                   command=lambda:self._batch(True)).pack(side='left',padx=4)
        ttk.Button(bg,text="Break",width=8,
                   command=lambda:self._batch(False)).pack(side='left',padx=4)

    def _send_xpt(self):
        s,d,dr=self._xs.get(),self._xd.get(),bool(self._xdir.get())
        self._log(f"XPT {'Make' if dr else 'Break'}: {s}→{d} (HCI:{s-1}→{d-1})")
        self._cli.send(build_xpt([(s-1,d-1)],direction=dr))

    def _batch(self,dr):
        pairs=[]
        for p in self._xb.get().split(','):
            p=p.strip()
            if '>' in p:
                try: a,b=p.split('>',1); pairs.append((int(a)-1,int(b)-1))
                except: pass
        if not pairs: messagebox.showwarning("入力エラー","例: 1>2, 3>4"); return
        self._cli.send(build_xpt(pairs,direction=dr))

    def _tab_rot(self):
        tab=ttk.Frame(self._nb,padding=12)
        self._nb.add(tab,text="  レベル制御  ")

        xf=ttk.LabelFrame(tab,text="クロスポイント設定",padding=10)
        xf.pack(fill='x',pady=4)
        ttk.Label(xf,text="From Port:").grid(row=0,column=0,sticky='e',padx=6,pady=4)
        self._ls=tk.IntVar(value=3)
        ttk.Spinbox(xf,from_=1,to=496,textvariable=self._ls,width=7,
                    font=('',11)).grid(row=0,column=1,sticky='w')
        ttk.Label(xf,text="To Port:").grid(row=1,column=0,sticky='e',padx=6,pady=4)
        self._ld=tk.IntVar(value=2)
        ttk.Spinbox(xf,from_=1,to=496,textvariable=self._ld,width=7,
                    font=('',11)).grid(row=1,column=1,sticky='w')

        lf=ttk.LabelFrame(tab,text="レベル",padding=10)
        lf.pack(fill='x',pady=4)
        self._dblbl=ttk.Label(lf,text="0 dB",font=('',36,'bold'),
                               foreground='navy',anchor='center')
        self._dblbl.pack(fill='x')
        self._glbl=ttk.Label(lf,text="gain: 0x0000 (0dB)",foreground='gray')
        self._glbl.pack()
        self._sld=ttk.Scale(lf,from_=0,to=len(DB_LEVELS)-1,
                             orient='horizontal',length=460,command=self._on_sld)
        self._sld.set((len(DB_LEVELS)-1) - DB_LEVELS.index(0))
        self._sld.pack(pady=4)
        sl_lbl=ttk.Frame(lf); sl_lbl.pack(fill='x',padx=8)
        ttk.Label(sl_lbl,text="← -72dB",font=('',8),foreground='gray').pack(side='left')
        ttk.Label(sl_lbl,text="+18dB →",font=('',8),foreground='gray').pack(side='right')
        self._sld.bind('<ButtonRelease-1>', lambda e: self._send_lv())
        bf=ttk.Frame(lf); bf.pack(pady=4)
        for lbl,d in [("−10dB",-10),("−1dB",-1),("+1dB",+1),("+10dB",+10)]:
            ttk.Button(bf,text=lbl,width=8,
                       command=lambda x=d:self._step_send(x)).pack(side='left',padx=3)
        mf=ttk.Frame(lf); mf.pack(pady=2)
        ttk.Label(mf,text="送信方式:").pack(side='left',padx=4)
        self._lmethod=tk.StringVar(value="MSG_38 (HCI標準)")
        ttk.Combobox(mf,textvariable=self._lmethod,state='readonly',width=30,
                     values=["MSG_38 (HCI標準)",
                             "MSG_38 (逆順テスト)",
                             "MSG_17 (XPT+gain直接dB)","MSG_17 (XPT+gain×10dB)"]).pack(side='left',padx=4)
        bf2=ttk.Frame(lf); bf2.pack(pady=2)
        ttk.Button(bf2,text="Level送信",width=16,
                   command=self._send_lv).pack(side='left',padx=4)
        ttk.Label(lf,text="※ dBボタン・スライダー・Level送信ボタンで即時送信",
                  foreground='gray',font=('',8)).pack()

        pf=ttk.LabelFrame(tab,text="XPT+レベル プリセット登録 (Listen固定)",padding=10)
        pf.pack(fill='x',pady=4)
        ttk.Button(pf,text="このXPT+レベルをプリセット登録",width=28,
                   command=self._add_preset).pack(side='left',padx=6)
        ttk.Button(pf,text="選択削除",width=12,
                   command=self._del_preset).pack(side='left',padx=6)
        lf2=ttk.LabelFrame(tab,text="プリセット一覧",padding=8)
        lf2.pack(fill='both',pady=4)
        self._lb_p2=tk.Listbox(lf2,height=6,font=('',11))
        self._lb_p2.pack(fill='both',expand=True)
        self._lb_p2.bind("<<ListboxSelect>>",
                         lambda e,lb=self._lb_p2:self._on_preset_select(lb))
        self._preset_lbs.append(self._lb_p2)

        ttk.Label(tab,text="※ ロータリーエンコーダー連動は現在無効（MSG_363解析調査中）",
                  foreground='gray',font=('',8)).pack(pady=2)

    def _on_sld(self,val):
        raw=max(0,min(int(float(val)),len(DB_LEVELS)-1))
        idx=(len(DB_LEVELS)-1) - raw
        self._cur_db=DB_LEVELS[idx]; self._upd_db()

    def _step_send(self,delta):
        self._step(delta)
        self._send_lv()

    def _step(self,delta):
        nb=max(DB_LEVELS[-1],min(DB_LEVELS[0],self._cur_db+delta))
        cl=min(DB_LEVELS,key=lambda x:abs(x-nb))
        self._cur_db=cl
        if cl in DB_LEVELS: self._sld.set((len(DB_LEVELS)-1) - DB_LEVELS.index(cl))
        self._upd_db()

    def _upd_db(self):
        db=self._cur_db
        self._dblbl.config(text=f"{db:+d} dB" if db!=0 else "0 dB")
        m=self._lmethod.get() if hasattr(self,'_lmethod') else ""
        if "MSG_38" in m:
            lvl=db_to_level(db)
            self._glbl.config(text=f"level: 0x{lvl:03X} ({lvl}) = 204+{db}dB/0.355")
        elif "×10" in m:
            gain=(db*10)&0xFFFF
            self._glbl.config(text=f"gain: 0x{gain:04X} ({db}dB×10)")
        else:
            self._glbl.config(text=f"gain: 0x{db&0xFFFF:04X} ({db}dB 直接)")

    def _send_xpt_make(self):
        s,d=self._ls.get()-1,self._ld.get()-1
        self._log(f"XPT Make: {s+1}→{d+1} (HCI:{s}→{d})")
        self._cli.send(build_xpt([(s,d)],direction=True))

    def _send_lv(self):
        s,d,db=self._ls.get()-1,self._ld.get()-1,self._cur_db
        m=self._lmethod.get()
        if "MSG_17" in m:
            scale=10 if "×10" in m else 1
            gain=(db*scale)&0xFFFF
            self._log(f"Level(MSG_17): Port{s+1}→Port{d+1} = {db:+d}dB gain=0x{gain:04X}")
            self._cli.send(build_xpt([(s,d)],direction=True,gain=gain))
        elif "逆順" in m:
            lvl=db_to_level(db)
            self._log(f"Level(MSG_38逆順): Port{s+1}→Port{d+1} = {db:+d}dB level=0x{lvl:03X}({lvl}) [Dst={s} Src={d}]")
            self._cli.send(build_level_simple_reversed(s,d,lvl))
        else:
            lvl=db_to_level(db)
            self._log(f"Level(MSG_38): Port{s+1}→Port{d+1} = {db:+d}dB level=0x{lvl:03X}({lvl}) [Dst={d} Src={s}]")
            self._cli.send(build_level_simple(s,d,lvl))

    def _send_make_lv(self):
        self._send_xpt_make()
        self.root.after(100, self._send_lv)

    def _on_rot363(self, panel_port, direction):
        self._step(direction)
        self._send_lv()

    def _on_key(self,panel,region,page,key,state):
        self._log(f"Key Event: Panel={panel} R={region} Pg={page} K={key} St={state}")
        prev=self._key_states.get(key,0)
        self._key_states[key]=state
        if state!=1:
            return
        if key==2:
            self._step(1); self._send_lv(); return
        if key==3:
            self._step(-1); self._send_lv(); return
        if key==1:
            return
        if prev!=0:
            return
        for pos in range(12):
                if pos*2+4==key:
                    idx=self._assigns[pos]
                    if idx is not None and idx<len(self._presets):
                        p=self._presets[idx]
                        src=p['src']-1; dst=p['dst']-1
                        lvl=db_to_level(p['db'])
                        self._log(f"  -> Key{pos+1}[{key}] Level: Port{p['src']}->Port{p['dst']} {p['db']:+d}dB")
                        self._cli.send(build_level_simple(src,dst,lvl))
                    break

    def _add_preset(self):
        src=self._ls.get(); dst=self._ld.get(); db=self._cur_db
        self._presets.append({'src':src,'dst':dst,'db':db})
        self._refresh_preset_lists()
        self._log(f"プリセット追加: Port{src}→Port{dst} {db:+d}dB Listen")

    def _del_preset(self):
        idx=self._sel_preset
        if idx is None: return
        self._presets.pop(idx)
        self._assigns=[
            None if a is None or a==idx else (a if a<idx else a-1)
            for a in self._assigns]
        self._sel_preset=None
        self._refresh_preset_lists(); self._refresh_grid()

    def _preset_label(self,p):
        sign=f"{p['db']:+d}" if p['db']!=0 else "0"
        return f"Port{p['src']} → Port{p['dst']}   {sign}dB   Listen"

    def _refresh_preset_lists(self):
        labels=[self._preset_label(p) for p in self._presets]
        for lb in self._preset_lbs:
            lb.delete(0,'end')
            for lbl in labels: lb.insert('end',lbl)

    def _on_preset_select(self,lb):
        sel=lb.curselection()
        self._sel_preset=sel[0] if sel else None

    def _tab_key(self):
        tab=ttk.Frame(self._nb,padding=10)
        self._nb.add(tab,text="  VI-PNLB-12R キーアサイン  ")

        ps=ttk.LabelFrame(tab,text="パネル設定 (Region=1固定)",padding=8)
        ps.pack(fill='x',pady=4)
        self._kpan=tk.IntVar(value=1)
        self._kpg =tk.StringVar(value="Main (0)")
        self._ksys=tk.IntVar(value=1)
        pf1=ttk.Frame(ps); pf1.pack(fill='x')
        ttk.Label(pf1,text="パネルポート番号:").pack(side='left',padx=4)
        ttk.Spinbox(pf1,from_=1,to=496,textvariable=self._kpan,width=6).pack(side='left',padx=4)
        ttk.Label(pf1,text="ページ:").pack(side='left',padx=(16,4))
        ttk.Combobox(pf1,textvariable=self._kpg,width=14,state='readonly',
                     values=["Main (0)","SHIFT 1 (1)","SHIFT 2 (2)","SHIFT 3 (3)",
                             "SHIFT 4 (4)","SHIFT 5 (5)","SHIFT 6 (6)",
                             "SHIFT 7 (7)","SHIFT 8 (8)"]).pack(side='left',padx=4)
        ttk.Label(pf1,text="フレーム番号:").pack(side='left',padx=(16,4))
        ttk.Spinbox(pf1,from_=1,to=16,textvariable=self._ksys,width=4).pack(side='left',padx=4)
        ttk.Label(pf1,text="(1=シングルフレーム)",foreground='gray').pack(side='left',padx=2)

        mf=ttk.Frame(tab); mf.pack(fill='both',expand=True,pady=4)
        lf=ttk.LabelFrame(mf,text="プリセット一覧",padding=6)
        lf.pack(side='left',fill='both',expand=True,padx=4)
        self._lb_p3=tk.Listbox(lf,height=12,font=('',11))
        self._lb_p3.pack(fill='both',expand=True)
        self._lb_p3.bind("<<ListboxSelect>>",
                         lambda e,lb=self._lb_p3:self._on_preset_select(lb))
        self._preset_lbs.append(self._lb_p3)

        gf=ttk.LabelFrame(mf,text="12キー（クリックで割り当て）",padding=6)
        gf.pack(side='left',fill='both',expand=True,padx=4)
        self._kbtns=[]
        for pos in range(12):
            r,c=divmod(pos,2)
            lk_n=pos*2+4
            btn=tk.Button(gf,text=f"Key {pos+1} [{lk_n}]\n(未設定)",
                          width=16,height=3,bg='#eeeeee',font=('',9),
                          command=lambda n=pos:self._click_key(n))
            btn.grid(row=r,column=c,padx=6,pady=6,sticky='nsew')
            gf.grid_rowconfigure(r,weight=1)
            gf.grid_columnconfigure(c,weight=1)
            self._kbtns.append(btn)

        bf=ttk.Frame(tab); bf.pack(pady=6)
        ttk.Button(bf,text="全キーアサイン送信",width=20,
                   command=self._send_keys).pack(side='left',padx=6)
        ttk.Button(bf,text="全キークリア",width=16,
                   command=self._clear_keys).pack(side='left',padx=6)

    def _click_key(self,pos):
        if self._sel_preset is not None and self._sel_preset < len(self._presets):
            self._assigns[pos]=self._sel_preset
        else:
            self._assigns[pos]=None
        self._refresh_grid()

    def _refresh_grid(self):
        for pos,btn in enumerate(self._kbtns):
            pidx=self._assigns[pos]; lk_n=pos*2+4
            if pidx is None or pidx>=len(self._presets):
                btn.config(text=f"Key {pos+1} [{lk_n}]\n(未設定)",bg='#eeeeee')
            else:
                p=self._presets[pidx]
                sign=f"{p['db']:+d}" if p['db']!=0 else "0"
                btn.config(text=f"Key {pos+1} [{lk_n}]\n"
                               f"Port{p['src']}→Port{p['dst']}\n{sign}dB Listen",
                           bg='#bbdefb')

    def _clear_keys(self):
        self._assigns=[None]*12; self._refresh_grid()
        if not self._cli.connected: return
        panel=self._kpan.get(); region=1
        page=self._get_key_page(); sys_n=self._ksys.get()
        acts=[{'region':region,'page':page,'key':pos*2+4,
               'etype':0,'sys':sys_n,'port':0,'act':0}
              for pos in range(12)]
        self._log(f"全キークリア送信: panel={panel}")
        self._cli.send(build_key_assign(panel,acts))

    def _get_key_page(self):
        try: return int(self._kpg.get().split('(')[1].rstrip(')'))
        except: return 0

    def _send_keys(self):
        panel=self._kpan.get(); region=1
        page=self._get_key_page(); sys_n=self._ksys.get()
        acts=[]
        for pos,pidx in enumerate(self._assigns):
            if pidx is None or pidx>=len(self._presets): continue
            p=self._presets[pidx]; kn=pos*2+4
            acts.append({'region':region,'page':page,'key':kn,
                         'etype':1,'sys':sys_n,'port':p['src']-1,'act':1})
        if not acts: messagebox.showinfo("情報","設定されたキーがありません"); return
        self._log(f"キーアサイン送信: panel={panel} {len(acts)}キー")
        self._cli.send(build_key_assign(panel,acts))

    def _build_log(self):
        lf=ttk.LabelFrame(self.root,text="通信ログ",padding=4)
        lf.pack(fill='x',padx=10,pady=(0,8))
        self.ltxt=scrolledtext.ScrolledText(lf,height=7,state='disabled',
            font=('Courier New',8),bg='#1e1e1e',fg='#d4d4d4')
        self.ltxt.pack(fill='x')
        ttk.Button(lf,text="クリア",command=self._clr_log).pack(anchor='e',pady=2)

    def _clr_log(self):
        self.ltxt.config(state='normal'); self.ltxt.delete('1.0','end')
        self.ltxt.config(state='disabled')

def main():
    root=tk.Tk()
    root.tk.call('tk','scaling',1.2)
    app=App(root)
    root.protocol("WM_DELETE_WINDOW",
                  lambda:(app._cli.disconnect(),root.destroy()))
    root.mainloop()

if __name__=='__main__':
    main()

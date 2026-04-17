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
MSG_KEYS   = 235
MSG_AUTO   = 318
MSG_KEVT   = 321

DB_LEVELS = [18,15,12,9,6,5,4,3,2,1,0,-1,-2,-3,
             -4,-5,-6,-7,-8,-9,-10,-12,-14,-16,-20,-35,-45,-72]

def db_to_gain(db):
    t = {18:255,15:246,12:233,9:220,6:207,5:194,4:181,3:168,
         2:155,1:142,0:129,-1:116,-2:103,-3:90,-4:77,-5:64,
         -6:51,-7:38,-8:25,-9:12,-10:0}
    return t.get(db, max(0, min(255, 129 + db * 13)))

# ── メッセージビルダ ──────────────────────────────────
def build_xpt(xpts, direction=True, enable=True):
    ss = '>3HBIBH'
    wl = []
    for src, dst in xpts:
        dh,dl,sh,sl = dst>>8,dst&0xFF,src>>8,src&0xFF
        wl += [1, 9216+int(direction)+(dh<<1)+(sh<<8),
               (sl<<8)+dl, 0, 1018+(int(not enable)<<11)+(3<<13)]
        ss += '5H'
    ss += 'H'
    s = struct.Struct(ss)
    return s.pack(HCI_START,s.size,MSG_XPT,HCI_FLAGS,HCI_MAGIC,
                  HCI_SCHEMA,len(xpts),*wl,HCI_END)

def build_level(src, dst, db):
    gain = db_to_gain(db)
    dh,dl,sh,sl = dst>>8,dst&0xFF,src>>8,src&0xFF
    s = struct.Struct('>3HBIBH5HH')
    return s.pack(HCI_START,s.size,MSG_XPT,HCI_FLAGS,HCI_MAGIC,HCI_SCHEMA,
                  1,2,9216+1+(dh<<1)+(sh<<8),(sl<<8)+dl,gain,1018+(3<<13),HCI_END)

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

    @property
    def connected(self): return self._on
    def set_key_cb(self, cb): self._key_cb = cb

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
                    self._log(f"📥 ID={mid} {len(data)}B {binascii.hexlify(data[:16]).decode()}")
                    if mid==MSG_KEVT and self._key_cb and len(data)>13:
                        self._dispatch(data)
            except socket.timeout: continue
            except: break
        if self._run: self._on=False; self._log("⚠️ 切断")

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

# ── キー設定ダイアログ ────────────────────────────────
class KeyDlg(tk.Toplevel):
    ETYPES=["Port","Conference","Fixed Group","IFB"]
    ACTS  =["Talk","Listen","Talk+Listen"]
    def __init__(self, parent, k, cur):
        super().__init__(parent)
        self.title(f"Key {k} 設定")
        self.resizable(False,False); self.grab_set()
        self.result=None
        ttk.Label(self,text=f"Key {k}",font=('',11,'bold')).grid(
            row=0,column=0,columnspan=2,pady=8,padx=12)
        for i,(lbl,key,vals,w) in enumerate([
            ("エンティティ","etype",self.ETYPES,16),
            ("アクション",  "act",  self.ACTS,  16),
        ]):
            ttk.Label(self,text=f"{lbl}:").grid(row=i+1,column=0,sticky='e',padx=8,pady=3)
            v=tk.StringVar(value=cur.get(key,vals[0]))
            setattr(self,f'_{key}',v)
            ttk.Combobox(self,textvariable=v,values=vals,width=w,
                         state='readonly').grid(row=i+1,column=1,padx=8)
        ttk.Label(self,text="ポート番号:").grid(row=3,column=0,sticky='e',padx=8,pady=3)
        self._port=tk.IntVar(value=cur.get('port',k+1))
        ttk.Spinbox(self,from_=1,to=496,textvariable=self._port,
                    width=8).grid(row=3,column=1,padx=8)
        ttk.Label(self,text="System:").grid(row=4,column=0,sticky='e',padx=8,pady=3)
        self._sys=tk.IntVar(value=cur.get('sys',6))
        ttk.Spinbox(self,from_=1,to=16,textvariable=self._sys,
                    width=8).grid(row=4,column=1,padx=8)
        bf=ttk.Frame(self); bf.grid(row=5,column=0,columnspan=2,pady=10)
        ttk.Button(bf,text="OK",    width=8,command=self._ok).pack(side='left',padx=4)
        ttk.Button(bf,text="クリア",width=8,command=self._clr).pack(side='left',padx=4)
        ttk.Button(bf,text="ｷｬﾝｾﾙ", width=8,command=self.destroy).pack(side='left',padx=4)
        self.wait_window()
    def _ok(self):
        self.result={'etype':self._etype.get(),'act':self._act.get(),
                     'port':self._port.get(),'sys':self._sys.get()}
        self.destroy()
    def _clr(self): self.result={}; self.destroy()

# ── メインアプリ ──────────────────────────────────────
ACOLOR={"Talk":"#c8e6c9","Listen":"#bbdefb",
        "Talk+Listen":"#ffe0b2","":"#eeeeee"}
EMAP={"Port":1,"Conference":2,"Fixed Group":3,"IFB":4}
AMAP={"Talk":1,"Listen":2,"Talk+Listen":3}

class App:
    def __init__(self, root):
        self.root=root
        root.title("EHX Crosspoint Controller")
        root.geometry("900x800"); root.resizable(True,True)
        self._cli=HCIClient(self._log)
        self._cli.set_key_cb(self._on_key)
        self._rot_on=False
        self._rot_panel=self._rot_region=1
        self._rot_page=self._rot_key=0
        self._cur_db=0
        self._assigns=[{} for _ in range(12)]
        self._kbtns=[]
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

    # ── 接続 ────────────────────────────────────────
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

    # ── ノートブック ──────────────────────────────────
    def _build_nb(self):
        self._nb=ttk.Notebook(self.root)
        self._nb.pack(fill='both',expand=True,padx=10,pady=4)
        self._tab_xpt()
        self._tab_rot()
        self._tab_key()

    # ── Tab1: XPT制御 ─────────────────────────────────
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

    # ── Tab2: ロータリーレベル制御 ───────────────────
    def _tab_rot(self):
        tab=ttk.Frame(self._nb,padding=12)
        self._nb.add(tab,text="  ロータリーレベル制御  ")

        xf=ttk.LabelFrame(tab,text="クロスポイント設定",padding=10)
        xf.pack(fill='x',pady=4)
        ttk.Label(xf,text="From Port:").grid(row=0,column=0,sticky='e',padx=6,pady=4)
        self._ls=tk.IntVar(value=1)
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
        self._glbl=ttk.Label(lf,text="gain: 129 (0x81)",foreground='gray')
        self._glbl.pack()
        self._sld=ttk.Scale(lf,from_=0,to=len(DB_LEVELS)-1,
                             orient='horizontal',length=460,command=self._on_sld)
        self._sld.set(DB_LEVELS.index(0)); self._sld.pack(pady=4)
        self._sld.bind('<ButtonRelease-1>', lambda e: self._send_lv())
        bf=ttk.Frame(lf); bf.pack(pady=4)
        for lbl,d in [("−10dB",-10),("−1dB",-1),("+1dB",+1),("+10dB",+10)]:
            ttk.Button(bf,text=lbl,width=8,
                       command=lambda x=d:self._step_send(x)).pack(side='left',padx=3)
        bf2=ttk.Frame(lf); bf2.pack(pady=2)
        ttk.Button(bf2,text="XPT Make送信",width=16,
                   command=self._send_xpt_make).pack(side='left',padx=4)
        ttk.Button(bf2,text="Make+Level 一括",width=16,
                   command=self._send_make_lv).pack(side='left',padx=4)
        ttk.Label(lf,text="※ dBボタンで即時送信。初回は「Make+Level 一括」を使用",
                  foreground='gray',font=('',8)).pack()

        rf=ttk.LabelFrame(tab,text="ロータリーエンコーダー設定 (Region=1固定)",padding=10)
        rf.pack(fill='x',pady=4)
        self._rp=tk.IntVar(value=1)
        self._rpg=tk.StringVar(value="Main (0)")
        self._rk=tk.IntVar(value=1)
        rf1=ttk.Frame(rf); rf1.grid(row=0,column=0,columnspan=8,sticky='w')
        ttk.Label(rf1,text="パネルポート:").pack(side='left',padx=4)
        ttk.Spinbox(rf1,from_=1,to=496,textvariable=self._rp,width=6).pack(side='left',padx=4)
        ttk.Label(rf1,text="ページ:").pack(side='left',padx=(12,4))
        ttk.Combobox(rf1,textvariable=self._rpg,width=12,state='readonly',
                     values=["Main (0)","SHIFT 1 (1)","SHIFT 2 (2)","SHIFT 3 (3)",
                             "SHIFT 4 (4)","SHIFT 5 (5)","SHIFT 6 (6)",
                             "SHIFT 7 (7)","SHIFT 8 (8)"]).pack(side='left',padx=4)
        ttk.Label(rf1,text="ロータリーKey番号:").pack(side='left',padx=(12,4))
        ttk.Spinbox(rf1,from_=0,to=45,textvariable=self._rk,width=4).pack(side='left',padx=4)
        rbf=ttk.Frame(rf); rbf.grid(row=1,column=0,columnspan=8,pady=6)
        self._rbtn=ttk.Button(rbf,text="▶ ロータリー有効化",
                               width=22,command=self._toggle_rot)
        self._rbtn.pack(side='left',padx=4)
        self._rlbl=ttk.Label(rbf,text="⏸ 無効",foreground='gray',font=('',10,'bold'))
        self._rlbl.pack(side='left',padx=8)
        ttk.Label(rf,text="※ Key番号: 位置1→1, 位置2→5, 位置3→9 (奇数=Listen)",
                  foreground='gray').grid(row=2,column=0,columnspan=8,pady=2)

        pf=ttk.LabelFrame(tab,text="このXPT+レベルをキーにプリセット登録",padding=10)
        pf.pack(fill='x',pady=4)
        ttk.Label(pf,text="対象キー:").pack(side='left',padx=4)
        self._pk=tk.IntVar(value=0)
        ttk.Spinbox(pf,from_=0,to=11,textvariable=self._pk,width=4).pack(side='left',padx=4)
        ttk.Label(pf,text="アクション:").pack(side='left',padx=4)
        self._pa=tk.StringVar(value="Talk")
        ttk.Combobox(pf,textvariable=self._pa,values=["Talk","Listen","Talk+Listen"],
                     width=12,state='readonly').pack(side='left',padx=4)
        ttk.Button(pf,text="キーアサインタブに登録",width=20,
                   command=self._preset).pack(side='left',padx=8)

    def _on_sld(self,val):
        idx=max(0,min(int(float(val)),len(DB_LEVELS)-1))
        self._cur_db=DB_LEVELS[idx]; self._upd_db()

    def _step_send(self,delta):
        self._step(delta)
        self._send_lv()

    def _step(self,delta):
        nb=max(DB_LEVELS[-1],min(DB_LEVELS[0],self._cur_db+delta))
        cl=min(DB_LEVELS,key=lambda x:abs(x-nb))
        self._cur_db=cl
        if cl in DB_LEVELS: self._sld.set(DB_LEVELS.index(cl))
        self._upd_db()

    def _upd_db(self):
        db=self._cur_db
        self._dblbl.config(text=f"{db:+d} dB" if db!=0 else "0 dB")
        g=db_to_gain(db)
        self._glbl.config(text=f"gain: {g} (0x{g:02X})")

    def _send_xpt_make(self):
        s,d=self._ls.get()-1,self._ld.get()-1
        self._log(f"XPT Make: {s+1}→{d+1} (HCI:{s}→{d})")
        self._cli.send(build_xpt([(s,d)],direction=True))

    def _send_lv(self):
        s,d,db=self._ls.get()-1,self._ld.get()-1,self._cur_db
        self._log(f"Level: {s+1}→{d+1} = {db:+d}dB (gain={db_to_gain(db)})")
        self._cli.send(build_level(s,d,db))

    def _send_make_lv(self):
        self._send_xpt_make()
        self.root.after(100, self._send_lv)

    def _get_rot_page(self):
        try: return int(self._rpg.get().split('(')[1].rstrip(')'))
        except: return 0

    def _toggle_rot(self):
        if not self._cli.connected:
            messagebox.showwarning("未接続","先に接続してください"); return
        self._rot_on=not self._rot_on
        if self._rot_on:
            self._rot_panel=self._rp.get(); self._rot_region=1
            self._rot_page=self._get_rot_page(); self._rot_key=self._rk.get()
            self._cli.send(build_auto_update())
            self._rbtn.config(text="⏹ ロータリー無効化")
            self._rlbl.config(text="▶ 有効",foreground='green')
            self._log(f"ロータリー有効: Panel={self._rot_panel} Key={self._rot_key}")
        else:
            self._rbtn.config(text="▶ ロータリー有効化")
            self._rlbl.config(text="⏸ 無効",foreground='gray')
            self._log("ロータリー無効")

    def _on_key(self,panel,region,page,key,state):
        self._log(f"Key Event: Panel={panel} R={region} Pg={page} K={key} St={state}")
        if not self._rot_on: return
        if (panel==self._rot_panel and region==self._rot_region and
                page==self._rot_page and key==self._rot_key):
            if   state==1: self._step(+1); self._send_lv()
            elif state==2: self._step(-1); self._send_lv()

    def _preset(self):
        k=self._pk.get()
        self._assigns[k]={'etype':'Port','port':self._ls.get(),
                           'act':self._pa.get(),'sys':1}
        self._refresh_grid()
        self._log(f"Key {k} 登録: Port {self._ls.get()} {self._pa.get()} "
                  f"/ Level {self._cur_db:+d}dB")
        self._nb.select(2)

    # ── Tab3: VI-PNLB-12R キーアサイン ───────────────
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

        gf=ttk.LabelFrame(tab,text="12キーグリッド — クリックで設定",padding=8)
        gf.pack(fill='both',expand=True,pady=4)
        ttk.Label(gf,text="緑=Talk(偶数key)  青=Listen(奇数key)  橙=Talk+Listen  灰=未設定",
                  foreground='gray').grid(row=0,column=0,columnspan=3,pady=2)
        ttk.Label(gf,text="キー番号: Talk=位置×4  Listen=位置×4+1  例) 位置1→T:0/L:1, 位置2→T:4/L:5",
                  foreground='#888888',font=('',8)).grid(row=1,column=0,columnspan=3,pady=1)
        self._kbtns=[]
        for pos in range(12):
            r,c=divmod(pos,3)
            tk_n=pos*4; lk_n=pos*4+1
            btn=tk.Button(gf,text=f"Pos {pos+1}  T:{tk_n}/L:{lk_n}\n(未設定)",
                          width=16,height=3,
                          bg='#eeeeee',relief='raised',font=('',9),
                          command=lambda n=pos:self._click_key(n))
            btn.grid(row=r+2,column=c,padx=6,pady=6,sticky='nsew')
            gf.grid_rowconfigure(r+2,weight=1)
            gf.grid_columnconfigure(c,weight=1)
            self._kbtns.append(btn)

        bf=ttk.Frame(tab); bf.pack(pady=6)
        ttk.Button(bf,text="全キーアサイン送信",width=20,
                   command=self._send_keys).pack(side='left',padx=6)
        ttk.Button(bf,text="全キークリア",width=16,
                   command=self._clear_keys).pack(side='left',padx=6)

    @staticmethod
    def _talk_key(pos): return pos * 4          # 0,4,8,12,16,20,...
    @staticmethod
    def _listen_key(pos): return pos * 4 + 1    # 1,5,9,13,17,21,...

    def _click_key(self,k):
        dlg=KeyDlg(self.root,k,self._assigns[k])
        if dlg.result is not None:
            self._assigns[k]=dlg.result; self._refresh_grid()

    def _refresh_grid(self):
        for pos,btn in enumerate(self._kbtns):
            a=self._assigns[pos]
            tk_n=self._talk_key(pos); lk_n=self._listen_key(pos)
            if not a:
                btn.config(text=f"Pos {pos+1}  T:{tk_n}/L:{lk_n}\n(未設定)",
                           bg='#eeeeee')
            else:
                act=a.get('act','Talk')
                kn=lk_n if act=='Listen' else tk_n
                btn.config(text=f"Pos {pos+1}  Key:{kn}\n"
                               f"{a.get('etype','Port')} {a.get('port','?')}\n{act}",
                           bg=ACOLOR.get(act,'#eeeeee'))

    def _clear_keys(self):
        self._assigns=[{} for _ in range(12)]; self._refresh_grid()

    def _get_key_page(self):
        try: return int(self._kpg.get().split('(')[1].rstrip(')'))
        except: return 0

    def _send_keys(self):
        panel=self._kpan.get(); region=1
        page=self._get_key_page(); sys_n=self._ksys.get()
        acts=[]
        for pos,a in enumerate(self._assigns):
            if not a: continue
            act_str=a.get('act','Talk')
            etype=EMAP.get(a.get('etype','Port'),1)
            port_n=a.get('port',pos+1)
            if act_str=='Talk+Listen':
                # Talk と Listen の両方を送信
                for kn,av in [(self._talk_key(pos),1),(self._listen_key(pos),2)]:
                    acts.append({'region':region,'page':page,'key':kn,
                                 'etype':etype,'sys':sys_n,'port':port_n,'act':av})
            else:
                kn=(self._listen_key(pos) if act_str=='Listen'
                    else self._talk_key(pos))
                acts.append({'region':region,'page':page,'key':kn,
                             'etype':etype,'sys':sys_n,'port':port_n,
                             'act':AMAP.get(act_str,1)})
        if not acts: messagebox.showinfo("情報","設定されたキーがありません"); return
        self._log(f"キーアサイン送信: panel={panel} {len(acts)}キー")
        self._cli.send(build_key_assign(panel,acts))

    # ── ログ ──────────────────────────────────────────
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

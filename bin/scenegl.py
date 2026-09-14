#!/usr/bin/env python3
"""
scenegl.py — browser-rendered scenes. Path A: Remotion-class quality, $0.

Renders each frame in headless Chromium, so scenes get real CSS 3D transforms,
gradient meshes, backdrop blur, glow, perspective, and sub-pixel type — the
things PIL cannot draw. Same CLI contract as autoscene.py, so the n8n workflow
and GitHub Action need no changes beyond the binary name.

    scenegl.py --spec "counter|title=posts this week|value=47|sub=cost $2.14" \
               --hook "$2.14 ran this all week." --seconds 28 --out o.mp4
    scenegl.py --selftest
"""
import argparse, json, math, shutil, subprocess, sys, tempfile
from pathlib import Path

W, H, FPS = 1080, 1920, 30
BR = {
 "nexalead": {"a":"#00E5A0","a2":"#0BC98D","bg":"#07070B","fg":"#F4F7FA","mu":"#78808C","tag":"nexalead.ai"},
 "armonia":  {"a":"#C8B07A","a2":"#A8905C","bg":"#080808","fg":"#F5F2EB","mu":"#8C8476","tag":"armoniaairbnb.com"},
}

CSS = """
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:%(W)spx;height:%(H)spx;overflow:hidden;background:%(bg)s;
  font-family:Poppins,'DejaVu Sans',system-ui,sans-serif;-webkit-font-smoothing:antialiased}
#stage{position:absolute;inset:0;perspective:1400px;transform-style:preserve-3d}
.bgmesh{position:absolute;inset:-20%%;
  background:
    radial-gradient(52%% 42%% at var(--mx) var(--my), %(a)s3a 0%%, transparent 64%%),
    radial-gradient(64%% 48%% at 74%% 76%%, %(a2)s26 0%%, transparent 72%%),
    linear-gradient(180deg,#15151f 0%%, %(bg)s 62%%);
  filter:blur(0.5px)}
.grid{position:absolute;inset:0;opacity:.26;
  background-image:linear-gradient(%(a)s18 1px,transparent 1px),linear-gradient(90deg,%(a)s18 1px,transparent 1px);
  background-size:96px 96px;
  transform:rotateX(62deg) translateZ(-260px) translateY(var(--gy));
  transform-origin:50%% 100%%;
  mask-image:linear-gradient(180deg,transparent,#000 42%%,#000 68%%,transparent)}
.vig{position:absolute;inset:0;pointer-events:none;
  background:radial-gradient(86%% 66%% at 50%% 42%%, transparent 52%%, #000 100%%);opacity:.62}
.grain{position:absolute;inset:0;pointer-events:none;opacity:.10;mix-blend-mode:overlay;
  background-image:var(--grain);background-size:180px 180px}
.wrap{position:absolute;inset:0;display:flex;flex-direction:column;
  align-items:center;justify-content:center;padding:0 84px;transform-style:preserve-3d}
.tag{position:absolute;left:0;right:0;bottom:104px;text-align:center;
  color:%(a)s;font-weight:700;font-size:34px;letter-spacing:.14em}
.rule{height:13px;border-radius:9px;background:linear-gradient(90deg,%(a)s,%(a2)s);
  box-shadow:0 0 34px %(a)s70}
.big{font-weight:800;color:%(fg)s;line-height:.92;letter-spacing:-.035em;
  text-shadow:0 26px 70px #000A, 0 0 62px %(a)s26}
.lbl{font-weight:700;color:%(a)s;letter-spacing:-.01em}
.sub{font-weight:500;color:%(mu)s}
.card{border-radius:30px;border:2px solid %(a)s3a;background:linear-gradient(160deg,%(a)s16,#ffffff05);
  backdrop-filter:blur(9px);box-shadow:0 34px 80px #0009, inset 0 1px 0 #ffffff14}
.chip{display:flex;align-items:center;justify-content:center;height:112px;border-radius:22px;
  border:1px solid %(mu)s55;color:%(mu)s;font-weight:700;font-size:38px;
  transition:none;position:relative}
.chip.on{border-color:%(a)s;color:%(fg)s;background:linear-gradient(160deg,%(a)s20,#ffffff06);
  box-shadow:0 0 0 1px %(a)s40, 0 18px 46px %(a)s24, inset 0 1px 0 #ffffff12}
.chip.on::after{content:'';position:absolute;right:18px;top:18px;width:20px;height:20px;
  border-radius:50%%;background:%(a)s;box-shadow:0 0 18px %(a)s}
.bar{height:56px;border-radius:18px;border:2px solid %(mu)s55;position:relative;overflow:hidden}
.fill{position:absolute;inset:0;border-radius:16px;transform-origin:left center}
"""

def spring(t, w=9.0, z=0.5):
    t=min(max(t,0.0),1.0)
    return 1.0 if t>=1 else 1-math.exp(-z*w*t)*math.cos(w*math.sqrt(1-z*z)*t)
def ease(t): return 0.5-0.5*math.cos(min(max(t,0),1)*math.pi)

def bg(b,t):
    mx=50+9*math.sin(t*0.5); my=38+7*math.cos(t*0.36); gy=(t*26)%96
    return (f'<div class="bgmesh" style="--mx:{mx:.1f}%;--my:{my:.1f}%"></div>'
            f'<div class="grid" style="--gy:{gy:.1f}px"></div>')

def fx(b): return '<div class="vig"></div><div class="grain"></div>'

def beat_hook(b,t,dur,text="",**_):
    words=(text or "Nexalead").split(); per=min(0.24,(dur*0.5)/max(len(words),1))
    size=96 if len(" ".join(words))<34 else (80 if len(" ".join(words))<52 else 66)
    spans=[]
    for i,wd in enumerate(words):
        p=spring((t-i*per)/0.42); o=max(0.0,min(1.0,p))
        ty=38*(1-min(p,1.14)); rx=14*(1-min(p,1.1))
        spans.append(f'<span style="display:inline-block;opacity:{o:.3f};'
                     f'transform:translateY({ty:.1f}px) rotateX({rx:.1f}deg);margin-right:.26em">{wd}</span>')
    uw=ease((t-len(words)*per)/0.5)*62
    return (f'<div class="wrap" style="justify-content:flex-start;padding-top:{H*0.26:.0f}px">'
            f'<div class="big" style="font-size:{size}px;text-align:center">{"".join(spans)}</div>'
            f'<div class="rule" style="width:{uw:.1f}%;margin-top:46px"></div></div>')

def beat_counter(b,t,dur,title="",value="0",sub="",var=0,**_):
    try: val=float(str(value).replace(",","").replace("$",""))
    except Exception: val=0.0
    k=ease(t/(dur*0.62)); shown=val*k
    txt=f"{shown:,.0f}" if val>=10 else f"{shown:,.2f}"
    p=spring(t/0.85); size=int(214+40*min(p,1.12)); rot=(1-min(p,1.1))*12
    sa=ease((t-dur*0.5)/0.35)
    align="flex-start" if var==1 else "center"
    num=(f'<div class="big" style="font-size:{size}px;transform:rotateX({rot:.1f}deg) translateZ(40px)">{txt}</div>'
         f'<div class="rule" style="width:{k*76:.1f}%;margin-top:26px"></div>')
    if var==2:
        num=f'<div class="card" style="padding:44px 68px;transform:rotateY({(1-min(p,1.1))*10:.1f}deg)">{num}</div>'
    return (f'<div class="wrap" style="align-items:{align};justify-content:flex-start;'
            f'padding-top:{H*0.26:.0f}px;text-align:{"left" if var==1 else "center"}">'
            f'{num}'
            f'<div class="lbl" style="font-size:54px;margin-top:40px">{title}</div>'
            f'<div class="sub" style="font-size:44px;margin-top:20px;opacity:{max(sa,0.0):.2f}">{sub}</div></div>')

def beat_grid(b,t,dur,title="",items=None,**_):
    items=(items or ["—"])[:10]; per=(dur*0.7)/max(len(items),1); lit=int(t/per)
    cells=[]
    for i,it in enumerate(items):
        on=i<lit; p=spring((t-i*per)/0.45) if on else 0
        s=0.9+0.12*min(p,1.15); o=0.35+0.65*min(p,1)
        cells.append(f'<div class="chip {"on" if on else ""}" '
                     f'style="transform:scale({s:.3f}) translateZ({20*min(p,1):.0f}px);opacity:{o:.2f}">{it}</div>')
    return (f'<div class="wrap" style="justify-content:flex-start;padding-top:{H*0.16:.0f}px">'
            f'<div class="lbl" style="font-size:56px;color:{b["fg"]};text-align:center">{title}</div>'
            f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:26px 34px;width:100%;margin-top:52px">'
            f'{"".join(cells)}</div>'
            f'<div class="lbl" style="font-size:62px;margin-top:56px">{min(lit,len(items))} / {len(items)}</div></div>')

def beat_versus(b,t,dur,title="",items=None,**_):
    it=((items or [])+["Before","After"])[:2]; rows=[]
    for j,lab in enumerate(it):
        p=spring((t-0.3-j*0.7)/1.15); frac=(1.0 if j==0 else 0.18)*min(p,1)
        col=b["mu"] if j==0 else f'linear-gradient(90deg,{b["a"]},{b["a2"]})'
        rows.append(f'<div style="width:100%;margin-bottom:60px">'
          f'<div class="lbl" style="font-size:44px;color:{b["mu"] if j==0 else b["fg"]}">{lab}</div>'
          f'<div class="bar" style="margin-top:18px"><div class="fill" '
          f'style="background:{col};transform:scaleX({frac:.3f});'
          f'box-shadow:{"none" if j==0 else "0 0 40px "+b["a"]+"60"}"></div></div></div>')
    return (f'<div class="wrap" style="justify-content:flex-start;padding-top:{H*0.20:.0f}px">'
            f'<div class="lbl" style="font-size:54px;color:{b["fg"]};text-align:center;margin-bottom:62px">{title}</div>'
            f'{"".join(rows)}</div>')

def beat_close(b,t,dur,text="",sub="",**_):
    lines=[l for l in (text or "").split("\n") if l.strip()]
    out=[]
    for i,l in enumerate(lines):
        p=spring((t-i*0.16)/0.5)
        out.append(f'<div style="opacity:{min(p,1):.3f};transform:translateY({34*(1-min(p,1.12)):.1f}px)">{l}</div>')
    sa=ease((t-0.85)/0.6)
    return (f'<div class="wrap"><div class="big" style="font-size:76px;text-align:center;line-height:1.22">'
            f'{"".join(out)}</div>'
            f'<div class="lbl" style="font-size:46px;margin-top:44px;opacity:{sa:.2f}">{sub}</div></div>')

BEATS={"hook":beat_hook,"counter":beat_counter,"grid":beat_grid,"versus":beat_versus,"close":beat_close}

GRAIN=("url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='180' height='180'>"
       "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='3'/></filter>"
       "<rect width='180' height='180' filter='url(%23n)' opacity='.5'/></svg>\")")

def page(b,body,t):
    css=CSS % {"W":W,"H":H,**b}
    return (f"<html><head><style>{css}</style></head><body style=\"--grain:{GRAIN}\">"
            f"<div id='stage'>{bg(b,t)}{body}<div class='tag'>{b['tag']}</div>{fx(b)}</div></body></html>")

def parse_spec(spec):
    parts=spec.split("|"); kind=parts[0].strip(); kw={}
    for p in parts[1:]:
        if "=" in p:
            k,v=p.split("=",1); kw[k.strip()]=v.strip()
    if "items" in kw: kw["items"]=[x.strip() for x in kw["items"].split(",") if x.strip()]
    return kind,kw

def plan_for(kind,kw,hook,total,var):
    close=(kw.get("close") or "14 days. Three systems.\nYou own everything.").replace("\\n","\n")
    plan=[("hook",{"text":hook or kw.get("title") or "Nexalead"},2.8)]
    if kind=="grid": plan.append(("grid",kw,4.0))
    elif kind in ("versus","timeline"):
        plan.append(("versus",{"title":kw.get("title","what you get, when"),
                     "items":kw.get("items") or ["Roadmap: 14 days","Systems live: 45 days"]},3.6))
    else: plan.append(("counter",{**kw,"var":var},3.4))
    if kind!="grid" and len(kw.get("items") or [])>=3:
        plan.append(("grid",{"title":"every platform, one post","items":kw["items"]},3.2))
    plan.append(("close",{"text":close,"sub":BR["nexalead"]["tag"]},2.6))
    if total:
        tot=float(total); rep=0
        while tot/len(plan)>4.5 and len(plan)<7:
            rep+=1; db=plan[1]
            plan.insert(-1,(db[0],{**db[1],"var":(var+rep)%3},db[2]))
        f=min(1.45,max(0.75,tot/sum(p[2] for p in plan)))
        plan=[(k,v,d*f) for k,v,d in plan]
    return plan

def build(spec,hook,brand,out,total=None,variant=0,quiet=False):
    from playwright.sync_api import sync_playwright
    b=BR.get(brand,BR["nexalead"]); b=dict(b); b["tag"]=b["tag"]
    kind,kw=parse_spec(spec)
    plan=plan_for(kind,kw,hook,total,int(variant)%3)
    XF=0.3; xf=int(XF*FPS)
    tmp=Path(tempfile.mkdtemp(prefix="gl_")); idx=0; cues=[(0.0,"impact")]
    with sync_playwright() as pw:
        br=pw.chromium.launch(args=["--force-color-profile=srgb","--font-render-hinting=none"])
        pg=br.new_page(viewport={"width":W,"height":H},device_scale_factor=1)
        prev_tail=[]
        for si,(k,kw2,dur) in enumerate(plan):
            n=int(dur*FPS); last=si==len(plan)-1
            tail_start=n-xf if not last else n
            for fi in range(n):
                t=fi/FPS
                html=page(b,BEATS[k](b,t,dur,**kw2),t)
                pg.set_content(html)
                shot=tmp/f"f{idx:05d}.png"
                if fi < tail_start:
                    pg.screenshot(path=str(shot)); idx+=1
                else:
                    pg.screenshot(path=str(tmp/f"tail_{si}_{fi-tail_start:03d}.png"))
            if not last:
                cues.append((idx/FPS,"whoosh" if si%2==0 else "tick"))
                cues.append((idx/FPS+XF*0.55,"impact"))
                nxt=plan[si+1]
                for j in range(xf):
                    t2=j/FPS
                    pg.set_content(page(b,BEATS[nxt[0]](b,t2,nxt[2],**nxt[1]),t2))
                    pg.screenshot(path=str(tmp/f"nx_{si}_{j:03d}.png"))
                for j in range(xf):
                    a=tmp/f"tail_{si}_{j:03d}.png"; c=tmp/f"nx_{si}_{j:03d}.png"
                    if not a.exists() or not c.exists(): continue
                    k2=(j+1)/xf; e=ease(k2)
                    off=int(W*e)
                    subprocess.run(["ffmpeg","-y","-hide_banner","-loglevel","error","-i",str(a),"-i",str(c),
                        "-filter_complex",
                        f"color=c=black:s={W}x{H}[bgc];[bgc][0]overlay={-off}:0[x];[x][1]overlay={W-off}:0",
                        "-frames:v","1",str(tmp/f"f{idx:05d}.png")],check=True); idx+=1
        br.close()
    dur=idx/FPS
    aud=None
    ins,fl,lb=[],[],[]
    for i,(tc,kind2) in enumerate(cues):
        ms=max(0,int(tc*1000))
        if kind2=="impact": ins+=["-f","lavfi","-i","sine=frequency=58:duration=0.55"]; ex="0.85*exp(-10*t)"
        elif kind2=="whoosh": ins+=["-f","lavfi","-i","anoisesrc=d=0.5:c=pink:a=0.5"]; ex="0.5*exp(-6*t)"
        else: ins+=["-f","lavfi","-i","sine=frequency=1700:duration=0.06"]; ex="0.22*exp(-40*t)"
        pre="highpass=f=320,lowpass=f=5200," if kind2=="whoosh" else ""
        fl.append(f"[{i}:a]{pre}volume='{ex}':eval=frame,adelay={ms}|{ms}[s{i}]"); lb.append(f"[s{i}]")
    if lb:
        mix="".join(lb)+f"amix=inputs={len(lb)}:duration=longest:normalize=0,apad=whole_dur={dur:.2f},atrim=0:{dur:.2f}[o]"
        r=subprocess.run(["ffmpeg","-y","-hide_banner","-loglevel","error"]+ins+
            ["-filter_complex",";".join(fl)+";"+mix,"-map","[o]","-ac","2","-ar","44100",str(tmp/"a.wav")],
            capture_output=True,text=True)
        if r.returncode==0: aud=tmp/"a.wav"
    cmd=["ffmpeg","-y","-hide_banner","-loglevel","error","-framerate",str(FPS),"-i",str(tmp/"f%05d.png")]
    cmd+=["-i",str(aud)] if aud else ["-f","lavfi","-i","anullsrc=r=44100:cl=stereo"]
    cmd+=["-shortest","-c:v","libx264","-preset","veryfast","-crf","19","-pix_fmt","yuv420p",
          "-c:a","aac","-b:a","128k",str(out)]
    subprocess.run(cmd,check=True); shutil.rmtree(tmp,ignore_errors=True)
    if not quiet: print(f"[scenegl] {out} {len(plan)} beats {dur:.1f}s browser-rendered")
    return out

def selftest():
    cases=[("counter|title=posts this week|value=47|sub=total cost $2.14","$2.14 ran this all week."),
           ("grid|title=one post. every platform.|items=Bluesky,Mastodon,Telegram,Threads,Facebook,Tumblr","Ten platforms. One row."),
           ("versus|title=what it replaced|items=Agency $5000/mo,This stack $9/mo","Agency: $5,000. This: $9."),
           ("timeline|title=what you get, when|items=Roadmap: 14 days,Systems live: 45 days","14 days to a plan.")]
    ok=0
    for spec,hook in cases:
        try:
            o=Path(tempfile.mkdtemp())/"t.mp4"; build(spec,hook,"nexalead",o,quiet=True)
            r=subprocess.run(["ffprobe","-v","error","-show_entries","stream=width,height","-of","csv=p=0:s=x",str(o)],
                             capture_output=True,text=True).stdout
            assert "1080x1920" in r, r
            print(f"  [PASS] {spec.split('|')[0]}"); ok+=1
        except Exception as e:
            print(f"  [FAIL] {spec.split('|')[0]}: {str(e)[:110]}")
    print(f"=== {ok}/{len(cases)} PASSED ===")
    return 0 if ok==len(cases) else 1

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--spec"); ap.add_argument("--hook",default=""); ap.add_argument("--brand",default="nexalead")
    ap.add_argument("--out"); ap.add_argument("--seconds",type=float,default=None)
    ap.add_argument("--variant",default=0); ap.add_argument("--selftest",action="store_true")
    a=ap.parse_args()
    if a.selftest: return selftest()
    if not a.spec or not a.out: ap.error("--spec and --out required")
    build(a.spec,a.hook,a.brand,a.out,a.seconds,a.variant); return 0

if __name__=="__main__": sys.exit(main())

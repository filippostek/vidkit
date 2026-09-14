#!/usr/bin/env python3
"""
autoscene v3 — multi-beat cinematic video from data alone. No camera.

A video is 3-4 BEATS (2.6-4s each) cut with whip/flash transitions:
    hook -> data -> proof -> close
Kinetic typography (per-word spring landing), synthesized sound design,
film grain, vignette, breathing accent glow.

  autoscene_v3.py --spec "counter|title=posts this week|value=47|sub=cost $2.14" \
                  --hook "$2.14 ran this all week." --out o.mp4
  autoscene_v3.py --selftest
"""
import argparse, math, random, shutil, subprocess, sys, tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1080, 1920, 30
BR = {
 "nexalead": {"a": (0,229,160), "bg": (9,9,14), "fg": (243,246,250), "mu": (118,128,140), "tag": "nexalead.ai"},
 "armonia":  {"a": (200,176,122), "bg": (8,8,8), "fg": (245,242,235), "mu": (140,132,118), "tag": "armoniaairbnb.com"},
}

VAR = 0            # layout variant 0-2, set per video from row_id

def F(sz, bold=True):
    for p in (f"/usr/share/fonts/truetype/google-fonts/Poppins-{'Bold' if bold else 'Regular'}.ttf",
              f"/usr/share/fonts/truetype/google-fonts/Poppins-{'SemiBold' if bold else 'Regular'}.ttf",
              f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf"):
        try: return ImageFont.truetype(p, int(sz))
        except Exception: continue
    return ImageFont.load_default()

def spring(t, w=9.0, z=0.5):
    t = min(max(t,0.0),1.0)
    return 1.0 if t>=1 else 1-math.exp(-z*w*t)*math.cos(w*math.sqrt(1-z*z)*t)

def ease(t): return 0.5-0.5*math.cos(min(max(t,0),1)*math.pi)

def wrap(d, txt, font, maxw):
    out, line = [], ""
    for wd in txt.split():
        t = (line+" "+wd).strip()
        if d.textlength(t, font=font) <= maxw: line = t
        else:
            if line: out.append(line)
            line = wd
    if line: out.append(line)
    return out or [""]

def plate(b, t):
    img = Image.new("RGB",(W,H),b["bg"]); d = ImageDraw.Draw(img)
    top = tuple(min(255,c+18) for c in b["bg"])
    for y in range(0,H,4):
        k=y/H; d.rectangle([0,y,W,y+4], fill=tuple(int(a+(c-a)*k) for a,c in zip(top,b["bg"])))
    pulse = 0.5+0.5*math.sin(t*1.6)
    cx = W/2+130*math.sin(t*0.45); cy = H*0.42+90*math.cos(t*0.33)
    for r in range(600,80,-52):
        k=r/600; al=0.055*(1-k)+0.030*pulse
        d.ellipse([cx-r,cy-r*1.15,cx+r,cy+r*1.15],
                  fill=tuple(int(bg+(ac-bg)*al) for bg,ac in zip(b["bg"],b["a"])))
    g = tuple(min(255,c+7) for c in b["bg"])
    for x in range(0,W,96): d.line([x,0,x,H], fill=g)
    for y in range(0,H,96): d.line([0,y,W,y], fill=g)
    return img, d

def finish(img, i, b):
    d = ImageDraw.Draw(img,"RGBA")
    for k,al in ((0,120),(64,74),(140,42)):
        d.rectangle([k,k,W-k,H-k], outline=(0,0,0,al), width=64)
    random.seed(i)
    for _ in range(2200):
        x=random.randrange(W); y=random.randrange(H); v=random.choice((-13,-8,9,14))
        d.point((x,y), fill=(128+v*8,128+v*8,128+v*8,25))
    tf=F(34); tw=d.textlength(b["tag"],font=tf)
    d.text(((W-tw)/2,H-118), b["tag"], font=tf, fill=b["a"])
    return img

# --------------------------------------------------------------- beats
def beat_hook(b, dur, text="", **_):
    words = (text or "Nexalead").split()
    per = min(0.26,(dur*0.5)/max(len(words),1)); n=int(dur*FPS)
    for i in range(n):
        t=i/FPS; img,d = plate(b,t)
        f=F(94); lines=wrap(d," ".join(words),f,W-150)
        while len(lines)>3 and f.size>56:
            f=F(f.size-8); lines=wrap(d," ".join(words),f,W-150)
        lh=f.size*1.22
        y0=(H*0.22 if VAR==2 else H*0.30)-(len(lines)*lh)/2; idx=0
        for li,ln in enumerate(lines):
            lw=d.textlength(ln,font=f)
            x = 80 if VAR==1 else (W-lw)/2
            y=y0+li*lh
            for wd in ln.split():
                ww=d.textlength(wd+" ",font=f); p=spring((t-idx*per)/0.42)
                if p>0.002:
                    dy=int(46*(1-min(p,1.15))); al=min(1.0,p)
                    col=tuple(int(b["bg"][j]+(b["fg"][j]-b["bg"][j])*al) for j in range(3))
                    d.text((x+3,y+dy+4),wd,font=f,fill=tuple(max(0,c-8) for c in b["bg"]))
                    d.text((x,y+dy),wd,font=f,fill=col)
                x+=ww; idx+=1
        uw=int((W-360)*ease((t-len(words)*per)/0.5))
        if uw>4:
            yb=y0+len(lines)*lh+26
            if VAR==1: d.rounded_rectangle([80,yb,80+int((W-300)*ease((t-len(words)*per)/0.5)),yb+14],7,fill=b["a"])
            else: d.rounded_rectangle([(W-uw)/2,yb,(W+uw)/2,yb+14],7,fill=b["a"])
        yield img

def beat_counter(b, dur, title="", value="0", sub="", _var=None, **_):
    global VAR
    if _var is not None: VAR=_var
    try: val=float(str(value).replace(",","").replace("$",""))
    except Exception: val=0.0
    n=int(dur*FPS)
    for i in range(n):
        t=i/FPS; img,d=plate(b,t)
        kk=ease(t/(dur*0.62)); shown=val*kk
        txt=f"{shown:,.0f}" if val>=10 else f"{shown:,.2f}"
        pop=spring(t/0.85); size=int(196+46*pop); vf=F(size)
        tw=d.textlength(txt,font=vf); ty=H*0.26
        if VAR==1: ty=H*0.20
        elif VAR==2: ty=H*0.30
        nx = 90 if VAR==1 else (W-tw)/2
        if VAR==2:
            pad=44
            d.rounded_rectangle([nx-pad,ty-24,nx+tw+pad,ty+size+52],28,
                fill=tuple(int(bg+(ac-bg)*0.10) for bg,ac in zip(b["bg"],b["a"])),
                outline=b["a"],width=3)
        d.text((nx+5,ty+7),txt,font=vf,fill=tuple(max(0,c-8) for c in b["bg"]))
        d.text((nx,ty),txt,font=vf,fill=b["fg"])
        uw=int((W-320)*kk)
        if VAR==1:
            d.rounded_rectangle([90,ty+size+20,90+int((W-260)*kk),ty+size+34],7,fill=b["a"])
        elif VAR!=2:
            d.rounded_rectangle([(W-uw)/2,ty+size+20,(W+uw)/2,ty+size+34],7,fill=b["a"])
        tf=F(52); lines=wrap(d,title,tf,W-160)
        for li,ln in enumerate(lines):
            lw=d.textlength(ln,font=tf)
            lx = 90 if VAR==1 else (W-lw)/2
            d.text((lx,ty+size+68+li*62),ln,font=tf,fill=b["a"])
        if sub:
            a=ease((t-dur*0.5)/0.35); sf=F(42,False); sw=d.textlength(sub,font=sf)
            sx = 90 if VAR==1 else (W-sw)/2
            d.text((sx,ty+size+92+len(lines)*62),sub,font=sf,
                   fill=tuple(int(b["bg"][j]+(b["mu"][j]-b["bg"][j])*a) for j in range(3)))
        yield img

def beat_grid(b, dur, title="", items=None, _var=None, **_):
    global VAR
    if _var is not None: VAR=_var
    items=(items or ["—"])[:10]; n=int(dur*FPS)
    cols = 1 if VAR==1 else 2
    bw,bh,gx,gy = (900,96,0,16) if VAR==1 else (468,106,40,(16 if VAR==2 else 20))
    x0=(W-cols*bw-(cols-1)*gx)/2; y0=H*0.28
    per=(dur*0.7)/max(len(items),1)
    for i in range(n):
        t=i/FPS; img,d=plate(b,t)
        tf=F(54); lines=wrap(d,title,tf,W-140)
        for li,ln in enumerate(lines):
            lw=d.textlength(ln,font=tf); d.text(((W-lw)/2,H*0.17+li*62),ln,font=tf,fill=b["fg"])
        lit=int(t/per)
        for j,name in enumerate(items):
            r,c=divmod(j,cols); x=x0+c*(bw+gx); y=y0+r*(bh+gy)
            on=j<lit; p=spring((t-j*per)/0.45) if on else 0
            gr=int(7*min(p,1.2)); box=[x-gr,y-gr,x+bw+gr,y+bh+gr]
            if on and p>1.0:
                h=int(13*(p-1.0)*9)
                d.rounded_rectangle([box[0]-h,box[1]-h,box[2]+h,box[3]+h],26,
                    outline=tuple(int(c2*0.55) for c2 in b["a"]),width=2)
            d.rounded_rectangle(box,20,
                fill=tuple(int(bg+(ac-bg)*0.17*min(p,1)) for bg,ac in zip(b["bg"],b["a"])),
                outline=b["a"] if on else b["mu"], width=3 if on else 1)
            nf=F(36); nw=d.textlength(name,font=nf)
            d.text((x+(bw-nw)/2,y+bh/2-22),name,font=nf,fill=b["fg"] if on else b["mu"])
            if on: d.ellipse([x+bw-36,y+15,x+bw-15,y+36],fill=b["a"])
        cf=F(60); ct=f"{min(lit,len(items))} / {len(items)}"; cw=d.textlength(ct,font=cf)
        d.text(((W-cw)/2,H-290),ct,font=cf,fill=b["a"])
        yield img

def beat_versus(b, dur, title="", items=None, _var=None, **_):
    global VAR
    if _var is not None: VAR=_var
    it=((items or [])+["Before","After"])[:2]; n=int(dur*FPS)
    for i in range(n):
        t=i/FPS; img,d=plate(b,t)
        tf=F(52); lines=wrap(d,title,tf,W-150)
        for li,ln in enumerate(lines):
            lw=d.textlength(ln,font=tf); d.text(((W-lw)/2,H*0.19+li*60),ln,font=tf,fill=b["fg"])
        y=H*0.36
        for j,lab in enumerate(it):
            p=spring((t-0.3-j*0.7)/1.15)
            lf=F(42); d.text((92,y),lab,font=lf,fill=b["mu"] if j==0 else b["fg"])
            full=W-184; frac=1.0 if j==0 else 0.18
            wpx=int(full*frac*min(p,1))
            d.rounded_rectangle([92,y+62,92+full,y+116],16,outline=b["mu"],width=2)
            if wpx>12:
                d.rounded_rectangle([92,y+62,92+wpx,y+116],16,fill=b["mu"] if j==0 else b["a"])
                d.ellipse([92+wpx-15,y+74,92+wpx+15,y+104],fill=b["fg"])
            y+=250
        yield img

def beat_close(b, dur, text="", sub="", **_):
    n=int(dur*FPS)
    for i in range(n):
        t=i/FPS; img,d=plate(b,t)
        f=F(76); lines=[]
        for para in (text or "").split("\n"):
            lines+=wrap(d,para,f,W-170)
        lh=f.size*1.26; y0=H*0.33-(len(lines)*lh)/2
        for li,ln in enumerate(lines):
            p=spring((t-li*0.16)/0.5); lw=d.textlength(ln,font=f)
            dy=int(38*(1-min(p,1.12)))
            col=tuple(int(b["bg"][j]+(b["fg"][j]-b["bg"][j])*min(p,1)) for j in range(3))
            d.text(((W-lw)/2,y0+li*lh+dy),ln,font=f,fill=col)
        a=ease((t-0.85)/0.6)
        if sub and a>0.01:
            sf=F(46); sw=d.textlength(sub,font=sf)
            d.text(((W-sw)/2,y0+len(lines)*lh+50),sub,font=sf,
                   fill=tuple(int(b["bg"][j]+(b["a"][j]-b["bg"][j])*a) for j in range(3)))
        yield img

BEATS={"hook":beat_hook,"counter":beat_counter,"grid":beat_grid,"versus":beat_versus,"close":beat_close}

def transition(a,bimg,k,kind):
    if kind=="whip":
        e=ease(k); off=int(W*e)
        c=Image.new("RGB",(W,H),(0,0,0))
        c.paste(a,(-off,0))
        c.paste(bimg,(W-off,0))
        return c
    return Image.blend(a,bimg,ease(k))

def sfx(cues,dur,out):
    ins,fl,lb=[],[],[]
    for i,(t,kind) in enumerate(cues):
        ms=max(0,int(t*1000))
        if kind=="impact":
            ins+=["-f","lavfi","-i","sine=frequency=58:duration=0.55"]
            fl.append(f"[{i}:a]volume='0.85*exp(-10*t)':eval=frame,adelay={ms}|{ms}[s{i}]")
        elif kind=="whoosh":
            ins+=["-f","lavfi","-i","anoisesrc=d=0.5:c=pink:a=0.5"]
            fl.append(f"[{i}:a]highpass=f=320,lowpass=f=5200,volume='0.5*exp(-6*t)':eval=frame,adelay={ms}|{ms}[s{i}]")
        elif kind=="tick":
            ins+=["-f","lavfi","-i","sine=frequency=1700:duration=0.06"]
            fl.append(f"[{i}:a]volume='0.22*exp(-40*t)':eval=frame,adelay={ms}|{ms}[s{i}]")
        else: continue
        lb.append(f"[s{i}]")
    if not lb: return None
    mix="".join(lb)+f"amix=inputs={len(lb)}:duration=longest:normalize=0,apad=whole_dur={dur:.2f},atrim=0:{dur:.2f}[o]"
    p=subprocess.run(["ffmpeg","-y","-hide_banner","-loglevel","error"]+ins+
        ["-filter_complex",";".join(fl)+";"+mix,"-map","[o]","-ac","2","-ar","44100",str(out)],
        capture_output=True,text=True)
    return out if p.returncode==0 else None

def parse_spec(spec):
    parts=spec.split("|"); kind=parts[0].strip(); kw={}
    for p in parts[1:]:
        if "=" in p:
            k,v=p.split("=",1); kw[k.strip()]=v.strip()
    if "items" in kw: kw["items"]=[x.strip() for x in kw["items"].split(",") if x.strip()]
    return kind,kw

def build(spec,hook,brand,out,total=None,quiet=False,variant=None):
    global VAR
    VAR = int(variant) % 3 if variant is not None else abs(hash(str(spec)+str(hook))) % 3
    b=BR.get(brand,BR["nexalead"]); kind,kw=parse_spec(spec)
    close_txt=(kw.get("close") or "14 days. Three systems.\nYou own everything.").replace("\\n","\n")
    plan=[("hook",{"text":hook or kw.get("title") or "Nexalead"},2.8)]
    if kind=="grid":       plan.append(("grid",kw,4.0))
    elif kind=="versus":   plan.append(("versus",kw,3.6))
    elif kind=="timeline": plan.append(("versus",{"title":kw.get("title","what you get, when"),
                             "items":kw.get("items") or ["Roadmap: 14 days","Systems live: 45 days"]},3.6))
    else:                  plan.append(("counter",kw,3.4))
    if kind!="grid" and len(kw.get("items") or [])>=3:
        plan.append(("grid",{"title":"every platform, one post","items":kw["items"]},3.2))
    plan.append(("close",{"text":close_txt,"sub":b["tag"]},2.6))
    if total:
        tot=float(total)
        base=sum(p[2] for p in plan)
        # long targets: repeat the data beat with other variants instead of
        # stretching beats into dead air. Beats stay 2.6-4.5s.
        rep=0
        while tot/ (len(plan)) > 4.5 and len(plan) < 7:
            rep+=1; db=plan[1]
            kw3=dict(db[1]); kw3["_var"]=(VAR+rep)%3
            plan.insert(-1,(db[0],kw3,db[2]))
            base=sum(p[2] for p in plan)
        f=min(1.45, max(0.75, tot/base))
        plan=[(k,v,d*f) for k,v,d in plan]

    XF=0.30; xf=int(XF*FPS)
    tmp=Path(tempfile.mkdtemp(prefix="sc_"))
    kinds=["whip","flash","whip","flash"]
    idx=0; cues=[(0.0,"impact")]; tsec=0.0; carry=None
    for si,(k,kw2,dur) in enumerate(plan):
        last = si==len(plan)-1
        seq=[]                       # only the tail overlap is kept in RAM
        for fi,im in enumerate(BEATS[k](b,dur,**kw2)):
            if carry is not None:    # blend into the previous beat's tail
                j=len(carry)-1 if fi>=len(carry) else fi
                if fi < len(carry):
                    kt=kinds[(si-1)%len(kinds)]
                    im=transition(carry[fi],im,(fi+1)/len(carry),kt)
                elif fi==len(carry):
                    carry=None
            keep_tail = (not last) and fi >= int(dur*FPS)-xf
            if keep_tail:
                seq.append(im.copy())
                continue
            finish(im,idx,b).save(tmp/f"f{idx:05d}.png"); idx+=1
        tsec=idx/FPS
        if not last:
            kt=kinds[si%len(kinds)]
            cues.append((tsec,"whoosh" if kt=="whip" else "tick"))
            cues.append((tsec+XF*0.55,"impact"))
            carry=seq or None
    if carry:
        for im in carry:
            finish(im,idx,b).save(tmp/f"f{idx:05d}.png"); idx+=1
    dur=idx/FPS
    aud=sfx(cues,dur,tmp/"a.wav")
    cmd=["ffmpeg","-y","-hide_banner","-loglevel","error","-framerate",str(FPS),"-i",str(tmp/"f%05d.png")]
    cmd+=["-i",str(aud)] if aud else ["-f","lavfi","-i","anullsrc=r=44100:cl=stereo"]
    cmd+=["-shortest","-c:v","libx264","-preset","veryfast","-crf","20","-pix_fmt","yuv420p",
          "-c:a","aac","-b:a","128k",str(out)]
    subprocess.run(cmd,check=True); shutil.rmtree(tmp,ignore_errors=True)
    if not quiet: print(f"[scene] {out} {len(plan)} beats {dur:.1f}s sfx={'yes' if aud else 'no'}")
    return out

def selftest():
    cases=[("counter|title=posts this week|value=47|sub=cost $2.14","$2.14 ran this all week."),
           ("grid|title=one post. every platform.|items=Bluesky,Mastodon,Telegram,Threads,Facebook,Tumblr","Ten platforms. One row."),
           ("versus|title=what it replaced|items=Agency $5000/mo,This stack $9/mo","Agency: $5,000. This: $9."),
           ("timeline|title=what you get, when|items=Roadmap: 14 days,Systems live: 45 days","14 days to a board-ready plan.")]
    ok=0
    for spec,hook in cases:
        try:
            o=Path(tempfile.mkdtemp())/"t.mp4"; build(spec,hook,"nexalead",o,quiet=True)
            r=subprocess.run(["ffprobe","-v","error","-show_entries","stream=width,height",
                              "-of","csv=p=0:s=x",str(o)],capture_output=True,text=True).stdout
            assert "1080x1920" in r, r
            print(f"  [PASS] {spec.split('|')[0]}"); ok+=1
        except Exception as e:
            print(f"  [FAIL] {spec.split('|')[0]}: {str(e)[:100]}")
    print(f"=== {ok}/{len(cases)} PASSED ===")
    return 0 if ok==len(cases) else 1

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--spec"); ap.add_argument("--hook",default="")
    ap.add_argument("--brand",default="nexalead"); ap.add_argument("--out")
    ap.add_argument("--seconds",type=float,default=None); ap.add_argument("--variant",default=None)
    ap.add_argument("--selftest",action="store_true")
    ap.add_argument("--scene"); ap.add_argument("--title",default=""); ap.add_argument("--value",default="0")
    ap.add_argument("--sub",default=""); ap.add_argument("--items",default="")
    a=ap.parse_args()
    if a.selftest: return selftest()
    spec=a.spec
    if not spec and a.scene:
        spec=a.scene
        for k,v in (("title",a.title),("value",a.value),("sub",a.sub),("items",a.items)):
            if v: spec+=f"|{k}={v}"
    if not spec or not a.out: ap.error("--spec and --out required")
    build(spec,a.hook,a.brand,a.out,a.seconds,variant=a.variant); return 0

if __name__=="__main__": sys.exit(main())

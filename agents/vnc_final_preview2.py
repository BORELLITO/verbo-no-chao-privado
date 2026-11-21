"""Prévia dos finais D (chuva de ouro) e E (feixe de luz) com camadas FILMADAS (Mixkit, licença gratuita verificada). Somente prévia: nao altera o motor nem o style lock.
Roda no GitHub (o ambiente do assistente nao alcanca o Mixkit). Saida: /tmp/preview_out (mp4 meia-resolucao + tira de quadros) e base64 no log."""
import os, json, subprocess, sys, time, base64
import numpy as np, cv2
os.makedirs('/tmp/preview_out', exist_ok=True)
from agents import vnc_curate, vnc_sources
OV = json.load(open('run/overlays.json')).get('preview_layers', {})
import imageio_ffmpeg
FF = imageio_ffmpeg.get_ffmpeg_exe()
def fetch(vid):
    u = vnc_curate.hd_url(vid) or f"https://assets.mixkit.co/videos/{vid}/{vid}-360.mp4"
    p = f'/tmp/preview_out/ov_{vid}.mp4'; open(p, 'wb').write(vnc_curate.get(u, True, limit=60_000_000)); return p
class Ov:
    def __init__(s, vid, W=1080, H=1920):
        s.W, s.H = W, H
        e = {"source": "mixkit", "id": str(vid), "page": f"https://mixkit.co/free-stock-video/x-{vid}/"}
        s.path = fetch(vid)
        s.p = subprocess.Popen([FF, '-loglevel', 'error', '-stream_loop', '-1', '-i', s.path, '-vf', f'scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps=30', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
    def next(s):
        b = s.p.stdout.read(s.W * s.H * 3)
        return np.frombuffer(b, np.uint8).reshape(s.H, s.W, 3).astype(np.float32) if len(b) == s.W * s.H * 3 else None
def screen(img, ov, op):
    if ov is None or op <= 0: return img
    return 255 - (255 - img) * (255 - ov * op) / 255

import numpy as np, cv2, subprocess
from PIL import Image, ImageDraw, ImageFont
W,H,FPS=1080,1920,30
base=cv2.cvtColor(cv2.imread('run/preview_base_E02.jpg'),cv2.COLOR_BGR2RGB).astype(np.float32)
# limpa legenda queimada (regiao y1130-1360) espelhando faixa acima + blur
y0,y1=1130,1360
patch=base[y0-(y1-y0):y0][::-1].copy()
base[y0:y1]=patch
base[y0-20:y1+20]=cv2.GaussianBlur(base[y0-20:y1+20],(0,0),6)
base=np.clip(base,0,255)
logo=Image.open('assets/vnc_logo.png').convert('RGBA')
a=np.array(logo).astype(np.float32)
lum=(a[...,0]*.299+a[...,1]*.587+a[...,2]*.114)
dark=(lum<70)&(a[...,3]>0)
a[dark,:3]=(236,232,250)
logo=Image.fromarray(a.astype(np.uint8))
bb=logo.getbbox(); logo=logo.crop(bb)
def sized(w):
    h=int(logo.height*w/logo.width); return logo.resize((w,h),Image.LANCZOS)
FONT='assets/fonts/AtkinsonHyperlegibleNext-Bold.ttf'
def text_layer(lines,size,color,ybot):
    im=Image.new('RGBA',(W,H),(0,0,0,0));d=ImageDraw.Draw(im);f=ImageFont.truetype(FONT,size)
    y=H-ybot
    # bloco centrado; ybot = MarginV (borda inferior)
    hs=[d.textbbox((0,0),l,font=f)[3]+8 for l in lines]; y=ybot
    for l,h in zip(lines,hs):
        w=d.textlength(l,font=f); d.text(((W-w)/2,y),l,font=f,fill=color); y+=h
    return np.array(im).astype(np.float32)
cred=text_layer(['Habacuque 2:1-3'],30,(235,235,245,255),1095)
cta1=text_layer(['Curta, compartilhe','e inscreva-se no canal'],40,(255,255,255,255),1215)
cta2=text_layer(['E você, já se sentiu assim?','Conte nos comentários.'],34,(196,181,253,255),1350)

yy,xx=np.mgrid[0:H,0:W].astype(np.float32)
def ss(t,a,b):
    u=float(np.clip((t-a)/(b-a),0,1)); return u*u*(3-2*u)
def glow(cx,cy,r):
    d=np.sqrt((xx-cx)**2+((yy-cy)*1.1)**2); return np.clip(1-d/r,0,1)**2
SC=600/logo.width; LW,LH=600,int(logo.height*SC); LT=int(H*.39-LH/2); LX=(W-LW)//2
L=np.array(logo.resize((LW,LH),Image.LANCZOS)).astype(np.float32)
Lo=np.array(logo).astype(np.float32)
goldm=(Lo[...,0]>200)&(Lo[...,1]>130)&(Lo[...,2]<140)&(Lo[...,3]>40)
ry=np.arange(logo.height)[:,None]
sun=goldm&(ry<330); wordm=(ry>=700)
def part(mask):
    a=Lo.copy(); a[...,3]=a[...,3]*mask
    return np.array(Image.fromarray(a.astype(np.uint8)).resize((LW,LH),Image.LANCZOS)).astype(np.float32)
SUN=part(sun); WORD=part(wordm); BOOK=part((~sun)&(~wordm))
def blit(img,layer,dx=0,dy=0,alpha=None,clip_y=None):
    h,w=layer.shape[:2]; x=LX+dx; y=LT+dy
    la=layer[...,3:4]/255.0
    if alpha is not None: la=la*alpha
    y0=max(y,0); y1=min(y+h,H); sub=la[y0-y:y1-y]
    if clip_y is not None:
        rows=np.arange(y0,y1)[:,None,None]; sub=sub*(rows<clip_y)
    reg=img[y0:y1,x:x+w]; reg[:]=reg*(1-sub)+layer[y0-y:y1-y,:,:3]*sub
HOR=690
def txt(lines,size,color,top):
    im=Image.new('RGBA',(W,H),(0,0,0,0));d=ImageDraw.Draw(im);f=ImageFont.truetype(FONT,size);y=top
    for l in lines:
        w=d.textlength(l,font=f);d.text(((W-w)/2,y),l,font=f,fill=color);y+=d.textbbox((0,0),l,font=f)[3]+8
    return np.array(im).astype(np.float32)
cred=txt(['Habacuque 2:1-3'],30,(235,235,245,255),1095)
cta1=txt(['Curta, compartilhe','e inscreva-se no canal'],40,(255,255,255,255),1215)
cta2=txt(['E você, já se sentiu assim?','Conte nos comentários.'],34,(196,181,253,255),1350)
def over(img,layer,al):
    la=layer[...,3:4]/255*al; return img*(1-la)+layer[...,:3]*la
a0,a1=80,340
top_row=base[a0].copy(); bot_row=base[a1].copy()
for yv in range(a0,a1):
    u=(yv-a0)/(a1-a0); base[yv]=top_row*(1-u)+bot_row*u
base[a0-10:a1+10]=cv2.GaussianBlur(base[a0-10:a1+10],(0,0),5)
blur=cv2.GaussianBlur(base,(0,0),9)
gold=np.array([255,190,80],np.float32)
top_logo=sized(210)

LEAD=1.0;T=9.5
SUNY=LT+int(0.12*LH)
def sprite(r,rim=0.5):
    n=int(r*2+6); y,x=np.mgrid[0:n,0:n]-n/2; d=np.sqrt(x*x+y*y)/r
    a=np.clip(1-d,0,1)**0.35*np.clip((1.04-d)*12,0,1)*(0.35+rim*np.clip((d-0.7)*4,0,1))
    return a.astype(np.float32)
SPR={}
def dot(img,cx,cy,r,col,alpha,rim=0.5):
    r=int(max(2,r)); k=(r//3,rim)
    if k not in SPR: SPR[k]=sprite(r,rim)
    sp=cv2.resize(SPR[k],(r*2+6,r*2+6)) ; n=sp.shape[0]
    x0=int(cx-n/2);y0=int(cy-n/2)
    xa,ya=max(x0,0),max(y0,0);xb,yb=min(x0+n,W),min(y0+n,H)
    if xb<=xa or yb<=ya: return
    m=sp[ya-y0:yb-y0,xa-x0:xb-x0,None]*alpha
    img[ya:yb,xa:xb]+= (np.array(col,np.float32)*m)
def ease(u): u=min(max(u,0),1); return u*u*(3-2*u)
def logo_tail(img,t,sun_at,book_at,word_at,line_at):
    # sol (aparece com flash), livro abre, palavra escrita pela luz, linha dourada, textos
    sa=ease((t-sun_at)/0.5)
    if sa>0:
        fl=np.exp(-((t-sun_at)/0.25)**2)
        g=glow(W/2,SUNY+int(0.05*LH),900)[...,None]*(0.35+0.9*fl)*sa
        img[:]=img*(1-np.clip(g,0,1)*0.8)+gold*np.clip(g,0,1)*0.8
        blit(img,SUN,alpha=sa)
    b=ease((t-book_at)/0.9)
    if b>0:
        sc=0.80+0.20*b; h=int(LH*sc); w=int(LW*sc)
        B2=cv2.resize(BOOK,(w,h),interpolation=cv2.INTER_AREA); cx=W//2; cy=LT+int(0.52*LH); la=B2[...,3:4]/255*b
        x=cx-w//2;y=cy-h//2; img[y:y+h,x:x+w]=img[y:y+h,x:x+w]*(1-la)+B2[...,:3]*la
    wp=ease((t-word_at)/1.0)
    if wp>0:
        edge=LX+wp*(LW+120)-60; cols=np.arange(LW)+LX; m=np.clip((edge-cols)/60,0,1)[None,:,None]
        lay=WORD.copy(); lay[...,3:4]=lay[...,3:4]*m; blit(img,lay)
    lp=ease((t-line_at)/0.9)
    if lp>0:
        hw=int(200*lp); la=np.zeros((H,W,1),np.float32); la[1070:1073,W//2-hw:W//2+hw]=1; img[:]=img*(1-la*0.9)+gold*la*0.9
    for layer,st in ((cred,3.4),(cta1,4.5),(cta2,6.0)):
        al=ease((t-st)/0.8)
        if al>0: img[:]=over(img,layer,al)
def finish(img,t,i,zf_t=None):
    # embers douradas subindo + vinheta + grao + saida
    rng=np.random.default_rng(7)
    if t>3.0:
        for j in range(46):
            x0=rng.uniform(80,W-80); sp=rng.uniform(40,110); ph=rng.uniform(0,9); r=rng.uniform(2,5)
            yy_=(H*0.95-((t-3.0+ph)*sp)%(H*0.9)); xx_=x0+30*np.sin((t+ph)*1.3+j)
            dot(img,xx_,yy_,r,(255,200,110),0.55*ease((t-3.0)/1.5),0.0)
    vig=1-0.38*np.clip((np.sqrt(((xx-W/2)/W)**2+((yy-H*0.42)/H)**2)-0.28)/0.5,0,1)[...,None]
    img[:]=img*vig+np.random.default_rng(i).normal(0,5.0,(H,W,1)).astype(np.float32)
    img[:]=img*(1-ease((t-(T-1.2))/1.2))
def push(a,t):
    zf=1.0+0.045*(t/T); h,w=a.shape[:2]; ch,cw=int(h/zf),int(w/zf); y0=int((h-ch)*0.45); x0=(w-cw)//2
    return cv2.resize(a[y0:y0+ch,x0:x0+cw],(w,h),interpolation=cv2.INTER_LINEAR)
def toplogo(img,tl):
    arr=np.array(top_logo).astype(np.float32); h,w=arr.shape[:2]; la=arr[...,3:4]/255*tl
    img[105:105+h,(W-w)//2:(W-w)//2+w]=img[105:105+h,(W-w)//2:(W-w)//2+w]*(1-la)+arr[...,:3]*la
def popen(name):
    return subprocess.Popen(['ffmpeg','-y','-loglevel','error','-f','rawvideo','-pix_fmt','rgb24','-s',f'{W}x{H}','-r',str(FPS),'-i','-','-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p',name],stdin=subprocess.PIPE)

OVV = json.load(open('run/overlays.json')).get('preview_variants', {})
ids=sorted({v for var in OVV.values() for v in var['layers'].values()})
_ctx={"get": vnc_curate.get, "cache": {}, "env": os.environ, "ua": vnc_curate.UA, "sleep": time.sleep, "budget": {}}
for _v in ids:
    for _t in range(4):
        _ok,_ev,_hd=vnc_sources.rights({"source":"mixkit","id":str(_v),"page":f"https://mixkit.co/free-stock-video/x-{_v}/"},_ctx)
        if '429' not in _ev: break
        time.sleep(6*(_t+1))
    print('VNC_PREVIEW_RIGHTS',_v,_ok,_ev); time.sleep(1.5)
    if not _ok: sys.exit(5)
LEAD=1.0; T=9.5
# cronograma de cada final: camadas (a,subida,descida_ini,fim,pico) e tempos do logo
VAR={
 'D':{'name':'CHUVA_DE_OURO','dim':0.55,'tail':(2.7,2.9,3.2,3.6),
      'L':{'rain':(0.6,1.6,4.6,6.0,0.95),'sparks':(2.2,2.8,3.4,4.4,0.85),'glitter':(3.0,4.2,8.0,9.5,0.45)}},
 'E':{'name':'FEIXE_DE_LUZ','dim':0.6,'tail':(2.6,2.8,3.1,3.6),
      'L':{'beam':(0.4,1.6,3.6,5.5,0.95),'flare':(2.2,2.7,3.2,4.2,0.8),'dust':(1.8,3.0,8.0,9.5,0.8)}},
}
for which,V in VAR.items():
    if which not in OVV: continue
    ovs={k:Ov(v) for k,v in OVV[which]['layers'].items()}
    p=popen2=subprocess.Popen([FF,'-y','-loglevel','error','-f','rawvideo','-pix_fmt','rgb24','-s',f'{W}x{H}','-r',str(FPS),'-i','-','-vf','scale=720:1280','-c:v','libx264','-preset','veryfast','-crf','26','-pix_fmt','yuv420p','-movflags','+faststart',f'/tmp/preview_out/PREVIA_{which}.mp4'],stdin=subprocess.PIPE)
    for i in range(int((LEAD+T)*FPS)):
        t=i/FPS-LEAD
        if t<0:
            img=base.copy(); toplogo(img,0.8)
        else:
            k=ease((t-0.2)/1.8)
            bl=cv2.GaussianBlur(base,(0,0),1+16*k) if k>0.02 else base
            img=push(bl,t)*(1-V['dim']*ease((t-0.4)/2.0))+np.array([12,9,22],np.float32)*V['dim']*ease((t-0.4)/2.0)
            toplogo(img,0.8*(1-ease(t/0.8)))
            for kk,(a,b,c,d,pk) in V['L'].items():
                if a<=t<=d:
                    fr=ovs[kk].next(); op=pk*min(ease((t-a)/(b-a)),1-ease((t-c)/(d-c))) if d>c else pk
                    img=screen(img,fr,op)
            logo_tail(img,t,*V['tail'])
            vig=1-0.38*np.clip((np.sqrt(((xx-W/2)/W)**2+((yy-H*0.42)/H)**2)-0.28)/0.5,0,1)[...,None]
            img=img*vig+np.random.default_rng(i).normal(0,4.0,(H,W,1)).astype(np.float32)
            img=img*(1-ease((t-(T-1.2))/1.2))
        p.stdin.write(np.clip(img,0,255).astype(np.uint8).tobytes())
    p.stdin.close(); p.wait()
    for q in ovs.values(): q.p.kill()
    for tt in (1.6,2.6,3.4,4.4,5.4,9.0):
        subprocess.run([FF,'-y','-loglevel','error','-ss',str(tt),'-i',f'/tmp/preview_out/PREVIA_{which}.mp4','-frames:v','1',f'/tmp/preview_out/q_{which}_{tt}.png'])
    from PIL import Image as _I
    sh=_I.new('RGB',(270*6,480))
    for j,tt in enumerate((1.6,2.6,3.4,4.4,5.4,9.0)): sh.paste(_I.open(f'/tmp/preview_out/q_{which}_{tt}.png').resize((270,480)),(j*270,0))
    sh.save(f'/tmp/preview_out/strip_{which}.jpg',quality=80)
    for nm in (f'strip_{which}.jpg',f'PREVIA_{which}.mp4'):
        b=base64.b64encode(open('/tmp/preview_out/'+nm,'rb').read()).decode()
        for j in range(0,len(b),3000): print('VNC_PREVIEW_B64',nm,j//3000,b[j:j+3000])
    print('VNC_PREVIEW_OK',which,os.path.getsize(f'/tmp/preview_out/PREVIA_{which}.mp4'))
